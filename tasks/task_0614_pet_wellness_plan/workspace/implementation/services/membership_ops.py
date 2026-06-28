"""Membership aggregate lifecycle operations (PRD §3.3, §3.6, §3.8, §3.9).

Each operation performs its state transition, cascades, ledger reconciliation,
and wallet adjustments as a single immediate-consistency unit (PRD §2.5).
"""
from db import db, clock_now, parse_iso, now_iso
from common import touch, touch_no_version
from errors import (
    err,
    ERR_MEMBERSHIP_NOT_PENDING, ERR_NO_ENROLLED_PET, ERR_PLAN_RETIRED,
    ERR_MEMBERSHIP_NOT_ENROLLED, ERR_MEMBERSHIP_NOT_SUSPENDED,
    ERR_TERM_EXPIRED, ERR_MEMBERSHIP_NOT_CANCELLABLE,
    ERR_MEMBERSHIP_NOT_CANCEL_PENDING,
)
from services.terms import (
    create_term, active_term_for_membership, term_credits,
)
from services.calculations import EARLY_TERMINATION_FEE_CENTS


def recompute_pet_count(membership):
    """pet_count = count of EnrolledPet rows under this membership whose status
    IN {ENROLLED, SUSPENDED} (PRD §3.2)."""
    count = 0
    for p in db.enrolled_pets.values():
        if p["membership_id"] == membership["id"] and p["status"] in (
                "ENROLLED", "SUSPENDED"):
            count += 1
    membership["pet_count"] = count


def _membership_pets(membership_id):
    return [p for p in db.enrolled_pets.values()
            if p["membership_id"] == membership_id]


def _membership_billing_cycles(membership_id):
    return [b for b in db.billing_cycles.values()
            if b["membership_id"] == membership_id]


def _cycle_window(membership):
    """The monthly billing window enclosing the current clock instant for this
    membership, anchored on billing_anchor_day (PRD §3.6). period_start counts
    the start day; period_end is the next anchor (exclusive)."""
    from datetime import datetime, timezone
    now = clock_now()
    anchor = membership["billing_anchor_day"]
    # Find the most recent anchor date <= now.
    y, m = now.year, now.month
    start = datetime(y, m, anchor, 0, 0, 0, tzinfo=timezone.utc)
    if start > now:
        # Step back one month.
        if m == 1:
            y, m = y - 1, 12
        else:
            m = m - 1
        start = datetime(y, m, anchor, 0, 0, 0, tzinfo=timezone.utc)
    # period_end = next month's anchor.
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = datetime(ny, nm, anchor, 0, 0, 0, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# Activation: PENDING_PAYMENT -> ENROLLED
# ---------------------------------------------------------------------------
def activate(membership):
    if membership["status"] != "PENDING_PAYMENT":
        raise err(ERR_MEMBERSHIP_NOT_PENDING, "Membership is not PENDING_PAYMENT")
    pets = _membership_pets(membership["id"])
    if not any(p["status"] == "ENROLLED" for p in pets):
        raise err(ERR_NO_ENROLLED_PET, "No ENROLLED pet under membership")
    plan = db.plans.get(membership["plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_RETIRED, "Plan is RETIRED")

    # Transition.
    membership["status"] = "ENROLLED"
    # Confirm monthly fee snapshot from the plan.
    membership["monthly_fee_cents"] = plan["monthly_fee_cents"]

    # First ContractTerm (term_index=1, starts_at=now, ends_at=+365d) + grant.
    starts_at = clock_now()
    term = create_term(membership, membership["plan_id"], 1, starts_at)

    # Charge wallet: enrollment_fee + first monthly_fee (debit, may go negative).
    account = db.member_accounts[membership["member_account_id"]]
    debit = plan["enrollment_fee_cents"] + plan["monthly_fee_cents"]
    account["wallet_credit_cents"] -= debit
    touch(account)

    # First BillingCycle (status=BILLED, fee_charged_cents=monthly_fee).
    p_start, p_end = _cycle_window(membership)
    _create_billing_cycle(membership, p_start, p_end,
                          plan["monthly_fee_cents"], 0)

    touch(membership)
    return membership


def _create_billing_cycle(membership, period_start, period_end, fee, proration):
    from common import stamp_new
    from db import iso
    cycle = {
        "membership_id": membership["id"],
        "period_start": iso(period_start),
        "period_end": iso(period_end),
        "fee_charged_cents": fee,
        "proration_credit_cents": proration,
        "status": "BILLED",
    }
    stamp_new(cycle)
    db.billing_cycles[cycle["id"]] = cycle
    return cycle


# ---------------------------------------------------------------------------
# Suspend / Resume
# ---------------------------------------------------------------------------
def suspend(membership):
    if membership["status"] != "ENROLLED":
        raise err(ERR_MEMBERSHIP_NOT_ENROLLED, "Membership is not ENROLLED")
    membership["status"] = "SUSPENDED"
    # Cascade pets ENROLLED -> SUSPENDED; record which pets we suspended so
    # resume reverses exactly those (PRD §3.6).
    for p in _membership_pets(membership["id"]):
        if p["status"] == "ENROLLED":
            p["status"] = "SUSPENDED"
            p["_suspended_by_membership"] = True
            touch(p)
    touch(membership)
    return membership


def resume(membership):
    if membership["status"] != "SUSPENDED":
        raise err(ERR_MEMBERSHIP_NOT_SUSPENDED, "Membership is not SUSPENDED")
    term = active_term_for_membership(membership["id"])
    if term is None or clock_now() >= parse_iso(term["ends_at"]):
        raise err(ERR_TERM_EXPIRED, "Contract term window has closed")
    membership["status"] = "ENROLLED"
    # Cascade back to ENROLLED exactly those pets suspended by the suspend.
    for p in _membership_pets(membership["id"]):
        if p["status"] == "SUSPENDED" and p.get("_suspended_by_membership"):
            p["status"] = "ENROLLED"
            p["_suspended_by_membership"] = False
            touch(p)
    touch(membership)
    return membership


# ---------------------------------------------------------------------------
# Cancel / Finalize
# ---------------------------------------------------------------------------
def cancel(membership):
    if membership["status"] not in ("ENROLLED", "SUSPENDED"):
        raise err(ERR_MEMBERSHIP_NOT_CANCELLABLE,
                  "Membership is not ENROLLED or SUSPENDED")
    term = active_term_for_membership(membership["id"])

    # compute_early_termination_settlement (gross basis, PRD §3.8).
    consumed_value = term["entitlement_consumed_cents"] if term else 0
    plan = db.plans.get(membership["plan_id"])
    enrollment_fee = plan["enrollment_fee_cents"] if plan else 0
    fees_paid = sum(c["fee_charged_cents"]
                    for c in _membership_billing_cycles(membership["id"]))
    fees_paid += enrollment_fee
    unused_value = max(0, fees_paid - consumed_value)
    etf_cents = min(EARLY_TERMINATION_FEE_CENTS, unused_value)
    settlement_credit = max(0, unused_value - etf_cents)

    # Apply settlement credit to wallet.
    account = db.member_accounts[membership["member_account_id"]]
    if settlement_credit:
        account["wallet_credit_cents"] += settlement_credit
    touch(account)

    # State transitions.
    membership["status"] = "CANCEL_PENDING"
    membership["auto_renew"] = False
    if term is not None:
        term["status"] = "TERMINATED"
        # Forfeit every still-OPEN credit bucket on the term.
        for c in term_credits(term["id"]):
            if c["status"] == "OPEN":
                c["status"] = "FORFEITED"
                touch(c)
        touch(term)
    touch(membership)
    return membership


def finalize_cancel(membership):
    if membership["status"] != "CANCEL_PENDING":
        raise err(ERR_MEMBERSHIP_NOT_CANCEL_PENDING,
                  "Membership is not CANCEL_PENDING")
    membership["status"] = "CANCELLED"
    # Cascade every remaining pet -> REMOVED. This cascade does NOT fire the
    # per-pet version rule (PRD §3.6) — refresh updated_at only on the pets.
    for p in _membership_pets(membership["id"]):
        if p["status"] != "REMOVED":
            p["status"] = "REMOVED"
            touch_no_version(p)
    recompute_pet_count(membership)
    touch(membership)
    return membership
