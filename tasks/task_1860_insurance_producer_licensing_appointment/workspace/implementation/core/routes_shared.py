"""Shared write helpers used by more than one route module."""

from . import calc
from .store import new_row


def create_commission_entry(app, producer):
    """The provisional CommissionEntry created at application submission
    (PRD 3.5/3.6): PROVISIONAL amount priced off the YTD total at submission;
    ELIGIBLE business starts PAYABLE, APPOINTMENT_GAP starts HELD with
    APPOINTMENT_PENDING, LICENSE_GAP starts HELD with UNLICENSED_AT_SALE."""
    snapshot = app["eligibility_snapshot"]
    ytd = calc.producer_ytd_live(producer["id"])
    amount = calc.commission_amount_cents(app, producer, ytd)
    if snapshot == "ELIGIBLE":
        status, hold_reason = "PAYABLE", None
    elif snapshot == "APPOINTMENT_GAP":
        status, hold_reason = "HELD", "APPOINTMENT_PENDING"
    else:
        status, hold_reason = "HELD", "UNLICENSED_AT_SALE"
    entry = new_row("commission_entries", {
        "application_id": app["id"],
        "producer_id": app["producer_id"],
        "amount_cents": amount,
        "amount_variant": "PROVISIONAL",
        "status": status,
        "hold_reason": hold_reason,
    })
    if status == "HELD":
        calc.recompute_producer_held(app["producer_id"])
    return entry
