"""Expenditures: charges checked against the authority basis then the cash basis."""

from flask import Blueprint

import auth
import clock
import db
import response
from errors import fail
from services import constants as C
from services import core
from validators import (
    bad_amount,
    body_json,
    listing,
    peek_fk,
    query_enum,
    query_int,
    read_id,
    read_int,
    read_str,
)

bp = Blueprint("expenditures", __name__)


@bp.post("/fiscal/expenditures")
def post_expenditure():
    actor = auth.authenticate((auth.AGENCY_BUDGET_OFFICER,))
    body = body_json()

    appropriation = peek_fk(body, "appropriation_id", core.get_appropriation)
    if appropriation is not None:
        auth.require_agency_scope(actor, appropriation["agency_id"])

    read_id(body, "appropriation_id")
    quarter = read_int(body, "quarter")
    amount_cents = read_int(body, "amount_cents")
    object_code = read_str(body, "object_code", min_len=1, max_len=16)
    vendor_reference = read_str(body, "vendor_reference", min_len=1, max_len=64)
    if quarter < 1 or quarter > 4:
        bad_amount("quarter must be between 1 and 4.")
    if amount_cents <= 0:
        bad_amount("amount_cents must be greater than zero.")

    cycle = core.get_cycle(appropriation["budget_cycle_id"])
    core.require_not_closed(cycle)

    if appropriation["authority_status"] != "ENACTED":
        fail("ERR_APPROPRIATION_NOT_ENACTED", "The appropriation is not ENACTED.")
    if appropriation["cash_status"] == "FROZEN":
        fail("ERR_CASH_FROZEN", "Cash is frozen on this appropriation.")
    core.check_quarter(cycle, quarter, exact=True)

    if amount_cents > appropriation["available_authority_cents"]:
        fail(
            "ERR_APPROPRIATION_OVERSPEND",
            "Charge %d exceeds the available authority of %d."
            % (amount_cents, appropriation["available_authority_cents"]),
        )
    if amount_cents > appropriation["available_cash_cents"]:
        fail(
            "ERR_INSUFFICIENT_CASH_RELEASED",
            "Charge %d exceeds the available released cash of %d."
            % (amount_cents, appropriation["available_cash_cents"]),
        )

    row = db.new_row()
    row.update(
        {
            "appropriation_id": appropriation["id"],
            "quarter": quarter,
            "amount_cents": amount_cents,
            "object_code": object_code,
            "vendor_reference": vendor_reference,
            "status": "POSTED",
            "posted_at": clock.fmt(clock.get_now()),
            "void_reason": None,
        }
    )
    db.expenditures[row["id"]] = row

    core.sync(cycle, touch_cycle=False, force_appr=(appropriation["id"],))
    core.refresh_moe_spend(appropriation["agency_id"], cycle["id"])
    return response.created(db.serialize(row))


@bp.post("/fiscal/expenditures/<expenditure_id>/void")
def void_expenditure(expenditure_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    row = core.get_expenditure(expenditure_id)
    body = body_json()
    reason = read_str(body, "reason", min_len=1, max_len=500)

    appropriation = core.get_appropriation(row["appropriation_id"])
    cycle = core.get_cycle(appropriation["budget_cycle_id"])
    core.require_phase(cycle, ("EXECUTION",))
    if row["status"] != "POSTED":
        fail("ERR_INVALID_STATE", "Only a POSTED expenditure may be voided.")

    db.apply_changes(row, {"status": "VOIDED", "void_reason": reason})
    core.sync(cycle, touch_cycle=False, force_appr=(appropriation["id"],))
    core.refresh_moe_spend(appropriation["agency_id"], cycle["id"])
    return response.ok(db.serialize(row))


@bp.get("/fiscal/appropriations/<appropriation_id>/expenditures")
def list_expenditures(appropriation_id):
    auth.authenticate(auth.ANY_ROLE)
    appropriation = core.get_appropriation(appropriation_id)
    status = query_enum("status", C.EXPENDITURE_STATUSES)
    quarter = query_int("quarter", minimum=1, maximum=4)
    rows = []
    for row in db.expenditures.values():
        if row["appropriation_id"] != appropriation["id"]:
            continue
        if status is not None and row["status"] != status:
            continue
        if quarter is not None and row["quarter"] != quarter:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)
