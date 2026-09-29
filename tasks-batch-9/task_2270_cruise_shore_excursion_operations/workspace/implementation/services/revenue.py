"""Per-port revenue report (PRD 3.9)."""

from db import db
from util import ratio_bps

REVENUE_FINANCIAL_STATUSES = ("CHARGED", "PARTIALLY_REFUNDED", "REFUNDED", "RETAINED")
STATEMENT_STATUSES = ("ISSUED", "DISPUTED", "ADJUSTED", "SETTLED")
GOODWILL_KINDS = ("GOODWILL_CREDIT", "REPATRIATION_ALLOWANCE")


def build_report(port, voyage_code=None):
    calls = [c for c in db.port_calls.values() if c["port_id"] == port["id"]]
    if voyage_code is not None:
        calls = [c for c in calls if c["voyage_code"] == voyage_code]
    call_ids = set(c["id"] for c in calls)

    departure_ids = set(d["id"] for d in db.departures.values() if d["port_call_id"] in call_ids)
    bookings = [b for b in db.bookings.values() if b["departure_id"] in departure_ids]

    money_lines = [b for b in bookings if b["financial_status"] in REVENUE_FINANCIAL_STATUSES]
    money_ids = set(b["id"] for b in money_lines)

    gross = sum(b["quoted_total_cents"] for b in money_lines)
    service_fee = sum(b["service_fee_cents"] for b in money_lines)

    refunds = 0
    goodwill = 0
    for entry in db.ledger.values():
        if entry["booking_id"] not in money_ids:
            continue
        if entry["entry_kind"] == "REFUND":
            refunds += entry["amount_cents"]
        elif entry["entry_kind"] in GOODWILL_KINDS:
            goodwill += entry["amount_cents"]

    line_commission = 0
    operator_payable = 0
    for statement in db.statements.values():
        if statement["port_call_id"] in call_ids and statement["status"] in STATEMENT_STATUSES:
            line_commission += statement["line_commission_cents"]
            operator_payable += statement["operator_payable_cents"]

    booking_count = len(bookings)
    cancelled = len([b for b in bookings
                     if b["fulfillment_status"] in ("CANCELLED_BY_GUEST", "CANCELLED_BY_LINE")])
    completed = len([b for b in bookings if b["fulfillment_status"] == "COMPLETED"])
    no_show = len([b for b in bookings if b["fulfillment_status"] == "NO_SHOW"])

    return {
        "port_id": port["id"],
        "voyage_code": voyage_code,
        "port_call_count": len(calls),
        "booking_count": booking_count,
        "completed_booking_count": completed,
        "cancelled_booking_count": cancelled,
        "no_show_booking_count": no_show,
        "gross_ticket_cents": gross,
        "service_fee_cents": service_fee,
        "refunds_cents": refunds,
        "goodwill_cents": goodwill,
        "line_commission_cents": line_commission,
        "operator_payable_cents": operator_payable,
        "net_line_revenue_cents": gross + service_fee - refunds - goodwill - operator_payable,
        "cancellation_rate_bps": ratio_bps(cancelled, booking_count),
        "no_show_rate_bps": ratio_bps(no_show, booking_count),
    }
