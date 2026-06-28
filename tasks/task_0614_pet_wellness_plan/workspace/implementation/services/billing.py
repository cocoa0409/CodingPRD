"""Billing epoch: monthly charges + annual renewal (PRD §3.9)."""
from datetime import timedelta

from db import db, clock_now, parse_iso, iso
from common import touch, stamp_new
from services.terms import (
    create_term, reconcile_term_balance, term_credits,
)
from services.membership_ops import _cycle_window
from services.calculations import RENEWAL_WINDOW_DAYS


def run_epoch():
    """Advance the monthly billing epoch and run renewals (PRD §3.9).

    Returns the list of BillingCycle records created this epoch.
    """
    now = clock_now()

    # --- Annual contract lifecycle first, so a fresh term/fee is in place ---
    _advance_terms(now)

    # --- Monthly billing ---
    created = _run_monthly_billing(now)
    return created


def _run_monthly_billing(now):
    day = now.day
    # Memberships due: billing_anchor_day == day-of-month(now), status IN
    # {ENROLLED, SUSPENDED}; processed in created_at ASC order (PRD §3.9).
    due = [m for m in db.memberships.values()
           if m["billing_anchor_day"] == day
           and m["status"] in ("ENROLLED", "SUSPENDED")]
    due.sort(key=lambda m: (m["created_at"], m["_seq"]))

    created = []
    for m in due:
        if m["status"] == "SUSPENDED":
            fee = 0
        else:  # ENROLLED
            fee = m["monthly_fee_cents"]
        p_start, p_end = _cycle_window(m)
        cycle = {
            "membership_id": m["id"],
            "period_start": iso(p_start),
            "period_end": iso(p_end),
            "fee_charged_cents": fee,
            "proration_credit_cents": 0,
            "status": "BILLED",
        }
        stamp_new(cycle)
        db.billing_cycles[cycle["id"]] = cycle
        # Debit wallet by fee.
        account = db.member_accounts[m["member_account_id"]]
        account["wallet_credit_cents"] -= fee
        touch(account)
        created.append(cycle)
    return created


def _advance_terms(now):
    """ACTIVE -> RENEWAL_PENDING (within renewal window, auto_renew) and
    RENEWAL_PENDING -> EXPIRED + successor (clock past ends_at)."""
    # ACTIVE -> RENEWAL_PENDING.
    for term in list(db.contract_terms.values()):
        if term["status"] != "ACTIVE":
            continue
        membership = db.memberships.get(term["membership_id"])
        if membership is None or not membership.get("auto_renew"):
            continue
        ends_at = parse_iso(term["ends_at"])
        window_open = ends_at - timedelta(days=RENEWAL_WINDOW_DAYS)
        if now >= window_open:
            term["status"] = "RENEWAL_PENDING"
            touch(term)

    # RENEWAL_PENDING -> EXPIRED + successor.
    for term in list(db.contract_terms.values()):
        if term["status"] != "RENEWAL_PENDING":
            continue
        ends_at = parse_iso(term["ends_at"])
        if now < ends_at:
            continue
        membership = db.memberships.get(term["membership_id"])
        term["status"] = "EXPIRED"
        # Forfeit every still-OPEN bucket (unused credits do not roll over).
        for c in term_credits(term["id"]):
            if c["status"] == "OPEN":
                c["status"] = "FORFEITED"
                touch(c)
        reconcile_term_balance(term)
        touch(term)
        # Successor term (term_index+1, starts_at=ends_at, +365d) + fresh grant.
        if membership is not None:
            successor = create_term(membership, membership["plan_id"],
                                    term["term_index"] + 1, ends_at)
            reconcile_term_balance(successor)
            touch(successor)
