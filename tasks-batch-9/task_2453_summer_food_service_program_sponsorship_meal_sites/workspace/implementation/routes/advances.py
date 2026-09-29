"""Advance payments (PRD sec 3.3)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("advances", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN

ADVANCE_STATUSES = (
    "REQUESTED",
    "APPROVED",
    "DENIED",
    "DISBURSED",
    "PARTIALLY_RECOVERED",
    "RECOVERED",
    "DEMAND_ISSUED",
)


@bp.post("/sfsp/advance-payments")
@mw.endpoint([SPONSOR_ADMIN])
def create_advance():
    body = mw.json_body()
    sponsor_id = mw.field_str(body, "sponsor_id")
    request_month = mw.field_month(body, "request_month", months=calc.PROGRAM_MONTHS)
    requested_cents = mw.field_int(body, "requested_amount_cents", minimum=1)
    expected_version = mw.field_int(body, "expected_sponsor_version", minimum=0)

    sponsor = lookup.require_sponsor(sponsor_id)
    require_owner(sponsor["id"])
    require_state(
        sponsor["application_status"] == "APPROVED", "ERR_SPONSOR_NOT_APPROVED"
    )
    if expected_version != sponsor["version"]:
        raise ApiError("ERR_STALE_SPONSOR_VERSION")

    advance = db.new_row(
        {
            "sponsor_id": sponsor["id"],
            "request_month": request_month,
            "requested_amount_cents": requested_cents,
            "approved_amount_cents": None,
            "recovered_amount_cents": 0,
            "status": "REQUESTED",
            "disbursed_at": None,
            "demand_issued_at": None,
            "decision_reason": None,
            "_reached_disbursed": False,
        }
    )
    db.store.advances[advance["id"]] = advance
    db.touch(sponsor)
    return response.created_response(ser.advance(advance))


@bp.get("/sfsp/advance-payments/<advance_id>")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def get_advance(advance_id):
    advance = lookup.require_advance(advance_id)
    return response.object_response(ser.advance(advance))


@bp.get("/sfsp/advance-payments")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def list_advances():
    limit, offset = mw.pagination()
    sponsor_id = mw.query_value("sponsor_id")
    status = mw.query_enum("status", ADVANCE_STATUSES)
    request_month = mw.query_month("request_month")

    rows = []
    for advance in db.store.advances.values():
        if sponsor_id is not None and advance["sponsor_id"] != sponsor_id:
            continue
        if status is not None and advance["status"] != status:
            continue
        if request_month is not None and advance["request_month"] != request_month:
            continue
        rows.append(advance)
    return response.paginate(rows, limit, offset, ser.advance)


@bp.post("/sfsp/advance-payments/<advance_id>/decision")
@mw.endpoint([REVIEWER])
def decide_advance(advance_id):
    body = mw.json_body()
    decision = mw.field_enum(body, "decision", ("APPROVED", "DENIED"))
    reason = mw.field_str(body, "reason", required=False)
    approved_cents = mw.field_int(body, "approved_amount_cents", required=False, minimum=0)
    if decision == "APPROVED":
        if approved_cents is None:
            mw.bad_request(
                "Field 'approved_amount_cents' is required for an APPROVED decision."
            )
    elif reason is None:
        mw.bad_request("Field 'reason' is required for a DENIED decision.")

    advance = lookup.require_advance(advance_id)
    require_state(advance["status"] == "REQUESTED", "ERR_ADVANCE_STATE_INVALID")
    sponsor = lookup.require_sponsor(advance["sponsor_id"])

    if decision == "APPROVED":
        budget = lookup.approved_budget_for(sponsor)
        if budget is None:
            raise ApiError("ERR_BUDGET_NOT_APPROVED")
        if approved_cents > advance["requested_amount_cents"]:
            raise ApiError("ERR_APPROVED_EXCEEDS_REQUESTED")
        cap = calc.advance_cap_cents(
            budget["approved_operating_cost_cents"], budget["approved_admin_cost_cents"]
        )
        if approved_cents > cap:
            raise ApiError("ERR_ADVANCE_EXCEEDS_CAP")
        if not sponsor["advance_eligible"] or sponsor["experience_status"] != "EXPERIENCED":
            raise ApiError("ERR_SPONSOR_NOT_ADVANCE_ELIGIBLE")

        advance["approved_amount_cents"] = approved_cents
        advance["status"] = "APPROVED"
    else:
        advance["decision_reason"] = reason
        advance["status"] = "DENIED"
    db.touch(advance)
    return response.object_response(ser.advance(advance))


@bp.post("/sfsp/advance-payments/<advance_id>/disburse")
@mw.endpoint([REVIEWER])
def disburse_advance(advance_id):
    advance = lookup.require_advance(advance_id)
    require_state(advance["status"] == "APPROVED", "ERR_ADVANCE_STATE_INVALID")
    sponsor = lookup.require_sponsor(advance["sponsor_id"])

    has_approved_site = any(
        site["approval_status"] == "APPROVED"
        for site in lookup.sponsor_sites(sponsor["id"])
    )
    if not has_approved_site:
        raise ApiError("ERR_NO_APPROVED_SITE")

    advance["status"] = "DISBURSED"
    advance["disbursed_at"] = db.clock.now_iso()
    advance["_reached_disbursed"] = True
    db.touch(advance)
    db.touch(sponsor)
    return response.object_response(ser.advance(advance))


@bp.post("/sfsp/advance-payments/<advance_id>/demand")
@mw.endpoint([REVIEWER])
def demand_advance(advance_id):
    body = mw.json_body()
    reason = mw.field_str(body, "reason")

    advance = lookup.require_advance(advance_id)
    require_state(
        advance["status"] in ("DISBURSED", "PARTIALLY_RECOVERED"),
        "ERR_ADVANCE_STATE_INVALID",
    )

    year, month = db.parse_year_month(advance["request_month"])
    next_year, next_month = db.add_months(year, month, 1)
    threshold = db.last_day_of_month(next_year, next_month)
    if ser.advance_outstanding(advance) <= 0 or db.clock.today() <= threshold:
        raise ApiError("ERR_DEMAND_TOO_EARLY")

    advance["decision_reason"] = reason
    advance["demand_issued_at"] = db.clock.now_iso()
    advance["status"] = "DEMAND_ISSUED"
    db.touch(advance)
    return response.object_response(ser.advance(advance))
