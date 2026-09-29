"""Sponsors and area eligibility records (PRD sec 3.1, sec 3.4)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import cascades
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("sponsors", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN
ALL = mw.ALL_ROLES


@bp.post("/sfsp/sponsors")
@mw.endpoint([REVIEWER])
def create_sponsor():
    body = mw.json_body()
    legal_name = mw.field_str(body, "legal_name")
    sponsor_type = mw.field_enum(body, "sponsor_type", calc.SPONSOR_TYPES)
    experience_status = mw.field_enum(body, "experience_status", calc.EXPERIENCE_STATUSES)
    program_year = mw.field_int(body, "program_year", minimum=2020)
    advance_eligible = mw.field_bool(body, "advance_eligible", required=False, default=False)

    sponsor = db.new_row(
        {
            "legal_name": legal_name,
            "sponsor_type": sponsor_type,
            "experience_status": experience_status,
            "program_year": program_year,
            "advance_eligible": advance_eligible,
            "application_status": "DRAFT",
            "application_decision_reason": None,
            "approved_at": None,
        }
    )
    db.store.sponsors[sponsor["id"]] = sponsor
    return response.created_response(ser.sponsor(sponsor))


@bp.get("/sfsp/sponsors/<sponsor_id>")
@mw.endpoint(ALL)
def get_sponsor(sponsor_id):
    sponsor = lookup.require_sponsor(sponsor_id)
    return response.object_response(ser.sponsor(sponsor))


@bp.post("/sfsp/sponsors/<sponsor_id>/application-submit")
@mw.endpoint([SPONSOR_ADMIN])
def submit_application(sponsor_id):
    sponsor = lookup.require_sponsor(sponsor_id)
    require_owner(sponsor["id"])
    require_state(sponsor["application_status"] == "DRAFT", "ERR_SPONSOR_STATE_INVALID")

    sponsor["application_status"] = "SUBMITTED"
    db.touch(sponsor)
    return response.object_response(ser.sponsor(sponsor))


@bp.post("/sfsp/sponsors/<sponsor_id>/application-decision")
@mw.endpoint([REVIEWER])
def decide_application(sponsor_id):
    body = mw.json_body()
    decision = mw.field_enum(body, "decision", ("APPROVED", "DENIED", "TERMINATED"))
    reason = mw.field_str(body, "reason", required=False)
    if decision in ("DENIED", "TERMINATED") and reason is None:
        mw.bad_request("Field 'reason' is required for a %s decision." % decision)

    sponsor = lookup.require_sponsor(sponsor_id)
    if decision in ("APPROVED", "DENIED"):
        require_state(
            sponsor["application_status"] == "SUBMITTED", "ERR_SPONSOR_STATE_INVALID"
        )
    else:
        require_state(
            sponsor["application_status"] == "APPROVED", "ERR_SPONSOR_STATE_INVALID"
        )

    if decision == "APPROVED":
        sponsor["application_status"] = "APPROVED"
        sponsor["approved_at"] = db.clock.now_iso()
    elif decision == "DENIED":
        sponsor["application_status"] = "DENIED"
        sponsor["application_decision_reason"] = reason
    else:
        sponsor["application_status"] = "TERMINATED"
        sponsor["application_decision_reason"] = reason
    db.touch(sponsor)

    if decision == "TERMINATED":
        cascades.terminate_sponsor_cascade(sponsor)

    return response.object_response(ser.sponsor(sponsor))


# --------------------------------------------------------------------------
# Area eligibility records
# --------------------------------------------------------------------------
@bp.post("/sfsp/area-eligibility-records")
@mw.endpoint([REVIEWER])
def create_area_record():
    body = mw.json_body()
    area_code = mw.field_str(body, "area_code")
    data_source = mw.field_enum(body, "data_source", calc.DATA_SOURCES)
    free_reduced_pct = mw.field_decimal(
        body, "free_reduced_pct", minimum=0, maximum=100, places=2
    )
    determination_date = mw.field_date(body, "determination_date")
    valid_through_date = mw.field_date(body, "valid_through_date")

    for existing in db.store.area_records.values():
        if existing["area_code"] == area_code and existing["data_source"] == data_source:
            raise ApiError("ERR_DUPLICATE_AREA_RECORD")

    record = db.new_row(
        {
            "area_code": area_code,
            "data_source": data_source,
            "free_reduced_pct": free_reduced_pct,
            "determination_date": db.date_iso(determination_date),
            "valid_through_date": db.date_iso(valid_through_date),
        },
        versioned=False,
    )
    db.store.area_records[record["id"]] = record
    return response.created_response(ser.area_record(record))


@bp.get("/sfsp/area-eligibility-records/<record_id>")
@mw.endpoint([REVIEWER, SPONSOR_ADMIN])
def get_area_record(record_id):
    record = lookup.require_area_record(record_id)
    return response.object_response(ser.area_record(record))
