"""Project rollups, ledger, lazy time-driven expiry, and cross-dimension
advances (PRD 2.6, 3.6, 3.7, 3.10).

The rolled-up Project fields are computed from children rather than written
directly, and recomputed whenever a relevant child changes.
"""

from clock import clock
from common import parse_iso8601, public
from db import db


# --------------------------------------------------------------------------
# Ledger (PRD 3.7) — replay SETTLED payments in created_at ASC order, ties
# broken by the internal monotonic _seq captured at create, NOT by id.
# --------------------------------------------------------------------------
def _settled_payments_for(project_id):
    rows = [
        p
        for p in db.payments.values()
        if p["project_id"] == project_id and p["status"] == "SETTLED"
    ]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return rows


def compute_ledger(project, include_pending=False):
    """Compute deposit/balance/refund totals and signed/floored outstanding.

    Settled-only by default; forward-projected (include_pending) additionally
    folds in PENDING payment rows as projected.
    """
    pid = project["id"]
    rows = [p for p in db.payments.values() if p["project_id"] == pid]
    if include_pending:
        rows = [p for p in rows if p["status"] in ("SETTLED", "PENDING")]
    else:
        rows = [p for p in rows if p["status"] == "SETTLED"]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))

    deposit = sum(p["amount_cents"] for p in rows if p["kind"] == "DEPOSIT")
    balance = sum(p["amount_cents"] for p in rows if p["kind"] == "BALANCE")
    refund = sum(p["amount_cents"] for p in rows if p["kind"] == "REFUND")

    contract_total = project.get("contract_total_cents", 0)
    signed = contract_total - deposit - balance + refund
    outstanding = max(signed, 0)
    return {
        "deposit_paid_cents": deposit,
        "balance_paid_cents": balance,
        "amount_refunded_cents": refund,
        "signed_outstanding_cents": signed,
        "outstanding_balance_cents": outstanding,
    }


# --------------------------------------------------------------------------
# Rollups (PRD 2.6) — recompute computed fields from children. These are pure
# (no version bump); callers wrap a logical mutation in touch().
# --------------------------------------------------------------------------
def recompute_rollups(project):
    pid = project["id"]
    ledger = compute_ledger(project, include_pending=False)
    project["deposit_paid_cents"] = ledger["deposit_paid_cents"]
    project["balance_paid_cents"] = ledger["balance_paid_cents"]
    project["amount_refunded_cents"] = ledger["amount_refunded_cents"]
    project["outstanding_balance_cents"] = ledger["outstanding_balance_cents"]

    open_count = sum(
        1
        for c in db.callbacks.values()
        if c["project_id"] == pid and c["status"] in ("OPEN", "IN_PROGRESS")
    )
    project["open_callback_count"] = open_count


def accepted_design(project_id):
    for d in db.design_layouts.values():
        if d["project_id"] == project_id and d["status"] == "ACCEPTED":
            return d
    return None


def accepted_quote(project_id):
    for q in db.quotes.values():
        if q["project_id"] == project_id and q["status"] == "ACCEPTED":
            return q
    return None


# --------------------------------------------------------------------------
# Lazy time-driven expiry (PRD 3.6, 3.10, 3.13) — applied on read of affected
# rows. Advancing the clock causes SENT quotes and ACTIVE warranties to expire
# on the next read.
# --------------------------------------------------------------------------
def expire_quote_if_due(quote):
    from common import touch
    from services.calculations import QUOTE_TTL_DAYS
    from datetime import timedelta

    if quote["status"] != "SENT":
        return
    # The quote's "creation time" for TTL purposes is the logical-clock instant
    # captured when the quote was created (PRD 3.13: time in this system is the
    # logical clock and never falls back to wall-clock). created_at is a
    # wall-clock audit stamp and is NOT the TTL anchor.
    created = parse_iso8601(quote.get("_logical_created_at"))
    if created is None:
        return
    if clock.now() >= created + timedelta(days=QUOTE_TTL_DAYS):
        quote["status"] = "EXPIRED"
        touch(quote)


def expire_warranty_if_due(plan):
    from common import touch

    if plan["status"] != "ACTIVE":
        return
    expires = parse_iso8601(plan.get("expires_at"))
    if expires is None:
        return
    if clock.now() >= expires:
        plan["status"] = "EXPIRED"
        touch(plan)


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
def serialize_project(project):
    """Public view of a project, with rollups recomputed at read time."""
    recompute_rollups(project)
    return public(project)
