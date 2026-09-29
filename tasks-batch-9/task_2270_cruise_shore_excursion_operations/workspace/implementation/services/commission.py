"""Commission accrual and the nine-step statement waterfall (PRD 3.9)."""

from db import db
from util import apply_bps

NO_SHOW_COMMISSION_CAP_BPS = 500
PORT_FEE_BPS = 250
OPERATIONAL_PENALTY_BPS = 2000
REBATE_HIGH_THRESHOLD_CENTS = 500000
REBATE_LOW_THRESHOLD_CENTS = 200000
REBATE_HIGH_BPS = 150
REBATE_LOW_BPS = 75
ADVERSE_CLAIM_STATUSES = ("ADJUDICATED_UPHELD", "SETTLED")


def provisional_line_cents(booking, commission_rate_bps):
    return apply_bps(booking["quoted_total_cents"], commission_rate_bps)


def final_line_cents(booking, commission_rate_bps):
    basis = max(0, booking["quoted_total_cents"] - booking["refunded_cents"])
    rate = commission_rate_bps
    if booking["fulfillment_status"] == "NO_SHOW":
        rate = min(commission_rate_bps, NO_SHOW_COMMISSION_CAP_BPS)
    return apply_bps(basis, rate)


def net_basis_line_cents(booking, commission_rate_bps):
    """Re-accrual after a refund or retention event, on the surviving net basis."""
    basis = max(0, booking["quoted_total_cents"] - booking["refunded_cents"])
    return apply_bps(basis, commission_rate_bps)


def operator_of_departure(departure):
    excursion = db.excursions.get(departure["excursion_id"])
    if excursion is None:
        return None
    return excursion["operator_id"]


def scope_departures(operator_id, port_call_id):
    rows = [d for d in db.departures.values()
            if d["port_call_id"] == port_call_id and operator_of_departure(d) == operator_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def scope_bookings(operator_id, port_call_id):
    departure_ids = set(d["id"] for d in scope_departures(operator_id, port_call_id))
    rows = [b for b in db.bookings.values() if b["departure_id"] in departure_ids]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def compute_statement(statement):
    """Run the nine waterfall steps onto the statement row."""
    operator = db.operators.get(statement["operator_id"])
    rate = operator["commission_rate_bps"] if operator else 0
    bookings = scope_bookings(statement["operator_id"], statement["port_call_id"])

    # step 1 - gross and line count
    if statement["basis"] == "PROVISIONAL":
        lines = [b for b in bookings if b["financial_status"] in ("CHARGED", "PARTIALLY_REFUNDED")]
        gross = sum(b["quoted_total_cents"] for b in lines)
        commission = sum(provisional_line_cents(b, rate) for b in lines)
    else:
        lines = [b for b in bookings if b["fulfillment_status"] in ("COMPLETED", "NO_SHOW")]
        gross = sum(max(0, b["quoted_total_cents"] - b["refunded_cents"]) for b in lines)
        commission = sum(final_line_cents(b, rate) for b in lines)

    line_ids = set(b["id"] for b in lines)
    refunds = sum(e["amount_cents"] for e in db.ledger.values()
                  if e["booking_id"] in line_ids and e["entry_kind"] == "REFUND")

    # step 2 - port infrastructure fee, charged on gross
    port_fee = apply_bps(gross, PORT_FEE_BPS)

    # step 4 - adverse claim offsets
    claim_offset = sum(c["operator_charge_cents"] for c in db.claims.values()
                       if c["operator_id"] == statement["operator_id"]
                       and c["port_call_id"] == statement["port_call_id"]
                       and c["status"] in ADVERSE_CLAIM_STATUSES)

    # step 5 - operational cancellation penalty
    penalty = 0
    for departure in scope_departures(statement["operator_id"], statement["port_call_id"]):
        if departure["status"] == "CANCELLED_OPERATIONAL":
            penalty += apply_bps(departure.get("forgone_gross_ticket_cents", 0), OPERATIONAL_PENALTY_BPS)

    # step 6 - pre-rebate payable
    pre_rebate = max(0, gross - port_fee - commission - claim_offset - penalty)

    # step 7/8 - volume rebate selected once from the pre-rebate figure
    if pre_rebate >= REBATE_HIGH_THRESHOLD_CENTS:
        rebate_bps = REBATE_HIGH_BPS
    elif pre_rebate >= REBATE_LOW_THRESHOLD_CENTS:
        rebate_bps = REBATE_LOW_BPS
    else:
        rebate_bps = 0
    rebate_cents = -apply_bps(pre_rebate, rebate_bps)

    statement["gross_ticket_cents"] = gross
    statement["booking_line_count"] = len(lines)
    statement["refunds_cents"] = refunds
    statement["port_fee_cents"] = port_fee
    statement["line_commission_cents"] = commission
    statement["claim_offset_cents"] = claim_offset
    statement["operational_penalty_cents"] = penalty
    statement["payable_pre_rebate_cents"] = pre_rebate
    statement["rebate_bps"] = rebate_bps
    statement["rebate_cents"] = rebate_cents
    # step 9
    statement["operator_payable_cents"] = pre_rebate + rebate_cents + statement.get("adjustment_cents", 0)
    return statement


def recompute_step_nine(statement):
    statement["operator_payable_cents"] = (statement["payable_pre_rebate_cents"]
                                           + statement["rebate_cents"]
                                           + statement["adjustment_cents"])
    return statement


def recompute_draft_statements(operator_id, port_call_id):
    for statement in db.statements.values():
        if (statement["operator_id"] == operator_id
                and statement["port_call_id"] == port_call_id
                and statement["status"] == "DRAFT"):
            compute_statement(statement)
            db.touch(statement)
