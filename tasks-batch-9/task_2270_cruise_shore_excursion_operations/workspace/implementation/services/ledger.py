"""Refund ledger writes and the money settlement branches (PRD 3.7)."""

from db import db
from util import apply_bps, minutes_between

GUEST_TIER_FULL_MINUTES = 4320
GUEST_TIER_THREE_QUARTER_MINUTES = 1440
GUEST_TIER_HALF_MINUTES = 180
GOODWILL_BPS = 1000
REPATRIATION_ALLOWANCE_CENTS = 25000


def entries_for(booking_id):
    rows = [e for e in db.ledger.values() if e["booking_id"] == booking_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def add_entry(booking, entry_kind, amount_cents, refund_pct_bps, basis, reason_code=None):
    row = {
        "booking_id": booking["id"],
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "refund_pct_bps": refund_pct_bps,
        "basis": basis,
        "reason_code": reason_code if reason_code is not None else basis,
    }
    db.insert("ledger", row, versioned=False)
    if entry_kind == "REFUND":
        booking["refunded_cents"] = booking["refunded_cents"] + amount_cents
    elif entry_kind in ("GOODWILL_CREDIT", "REPATRIATION_ALLOWANCE"):
        booking["goodwill_credit_cents"] = booking["goodwill_credit_cents"] + amount_cents
    return row


def derive_financial_status(booking):
    """financial_status and retained_cents follow from the refund arithmetic."""
    refunded = booking["refunded_cents"]
    charge_total = booking["charge_total_cents"]
    if refunded == 0:
        status = "RETAINED"
    elif refunded >= charge_total:
        status = "REFUNDED"
    else:
        status = "PARTIALLY_REFUNDED"
    booking["financial_status"] = status
    booking["retained_cents"] = charge_total - refunded
    return status


def guest_refund_pct_bps(departure):
    minutes = minutes_between(db.now(), departure["meeting_time_utc"])
    if minutes >= GUEST_TIER_FULL_MINUTES:
        return 10000
    if minutes >= GUEST_TIER_THREE_QUARTER_MINUTES:
        return 7500
    if minutes >= GUEST_TIER_HALF_MINUTES:
        return 5000
    return 0


def void_authorization(booking, basis, reason_code=None):
    add_entry(booking, "AUTH_VOID", 0, 0, basis, reason_code)
    booking["financial_status"] = "VOIDED"
    booking["retained_cents"] = 0


def guest_cancellation_settlement(booking, departure, reason_code=None):
    pct = guest_refund_pct_bps(departure)
    if pct == 10000:
        refund_cents = booking["charge_total_cents"]
    else:
        refund_cents = apply_bps(booking["quoted_total_cents"], pct)
    if refund_cents > 0:
        add_entry(booking, "REFUND", refund_cents, pct, "GUEST_INITIATED", reason_code)
    else:
        add_entry(booking, "RETENTION", booking["charge_total_cents"], 0, "GUEST_INITIATED", reason_code)
    derive_financial_status(booking)


def line_cancellation_settlement(booking, basis, goodwill):
    """Refund whatever remains of the charge; operational cause adds goodwill."""
    refund_cents = booking["charge_total_cents"] - booking["refunded_cents"]
    add_entry(booking, "REFUND", refund_cents, 10000, basis)
    if goodwill:
        goodwill_cents = apply_bps(booking["quoted_total_cents"], GOODWILL_BPS)
        add_entry(booking, "GOODWILL_CREDIT", goodwill_cents, GOODWILL_BPS, basis)
    derive_financial_status(booking)


def no_show_retention(booking):
    add_entry(booking, "RETENTION", booking["charge_total_cents"], 0, "NO_SHOW")
    booking["financial_status"] = "RETAINED"
    booking["retained_cents"] = booking["charge_total_cents"]


def return_guarantee_settlement(booking):
    """Ticket value is refunded, the service fee is retained, status is REFUNDED."""
    add_entry(booking, "REFUND", booking["quoted_total_cents"], 10000, "RETURN_GUARANTEE_BREACH")
    add_entry(booking, "REPATRIATION_ALLOWANCE", REPATRIATION_ALLOWANCE_CENTS, 0,
              "RETURN_GUARANTEE_BREACH")
    booking["financial_status"] = "REFUNDED"
    booking["retained_cents"] = booking["charge_total_cents"] - booking["refunded_cents"]
