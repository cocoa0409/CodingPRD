"""Rider intake, activation, withdrawal and medical clearance (PRD §3.1)."""

from flask import Blueprint, request

from core.constants import (
    DEMOGRAPHIC_GROUPS,
    FUNDING_MODES,
    INCOME_BANDS,
    PROGRAM_CODES,
    RIDER_MAX_WEIGHT_LB,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, endpoint, pagination, paginate, query_enum, validate_body,
)
from core.lookups import resource_or_404, rider_or_404
from core.store import all_rows, db, new_row, touch
from domain import derive, gates, serialize

bp = Blueprint("riders", __name__)

RIDER_STATUSES = ["INTAKE", "ACTIVE", "MEDICAL_HOLD", "WITHDRAWN"]
ASSESSMENT_STATUSES = ["NEVER_ASSESSED", "CURRENT", "DUE", "OVERDUE"]


@bp.post("/riders")
@endpoint(["IntakeCoordinator", "ProgramAdmin"])
def create_rider():
    payload = validate_body([
        Field("full_name", "string", required=True),
        Field("date_of_birth", "date", required=True),
        Field("weight_lb", "number", required=True,
              exclusive_min=0, maximum=RIDER_MAX_WEIGHT_LB),
        Field("household_income_band", "enum", required=True, members=INCOME_BANDS),
        Field("demographic_group", "enum", required=True, members=DEMOGRAPHIC_GROUPS),
        Field("program_code", "enum", required=True, members=PROGRAM_CODES),
        Field("condition_codes", "string_array", required=True),
        Field("funding_mode", "enum", members=FUNDING_MODES),
        Field("payer_rate_cents", "int", minimum=0),
    ])
    row = new_row("riders")
    row.update({
        "full_name": payload["full_name"],
        "date_of_birth": payload["date_of_birth"],
        "weight_lb": payload["weight_lb"],
        "household_income_band": payload["household_income_band"],
        "demographic_group": payload["demographic_group"],
        "program_code": payload["program_code"],
        "condition_codes": list(payload["condition_codes"]),
        "funding_mode": payload.get("funding_mode") or "PRIVATE_PAY_ALLOWED",
        "payer_rate_cents": payload.get("payer_rate_cents")
        if payload.get("payer_rate_cents") is not None else 0,
        "status": "INTAKE",
        "medical_hold_incident_id": None,
        "withdraw_reason": None,
        "independence_level": None,
        "required_sidewalker_count": None,
        "requires_leader": None,
        "sidewalker_hold_type": None,
        "backriding_required": False,
        "assessment_next_due_at": None,
    })
    return object_response(serialize.rider(row), 201)


@bp.get("/riders/<rider_id>")
@endpoint(["IntakeCoordinator", "ProgramAdmin", "Instructor", "BillingClerk"])
def read_rider(rider_id):
    row = rider_or_404(rider_id)
    return object_response(serialize.rider(row))


@bp.get("/riders")
@endpoint(["IntakeCoordinator", "ProgramAdmin", "Instructor"])
def list_riders():
    limit, offset = pagination()
    status = query_enum("status", RIDER_STATUSES)
    program_code = query_enum("program_code", PROGRAM_CODES)
    assessment_status = query_enum("assessment_status", ASSESSMENT_STATUSES)
    incident_id = request.args.get("medical_hold_incident_id")
    release_id = request.args.get("active_release_id")

    rows = all_rows("riders")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if program_code is not None:
        rows = [r for r in rows if r["program_code"] == program_code]
    if assessment_status is not None:
        rows = [r for r in rows if derive.assessment_status(r) == assessment_status]
    if incident_id is not None:
        rows = [r for r in rows if r["medical_hold_incident_id"] == incident_id]
    if release_id is not None:
        rows = [r for r in rows
                if (derive.active_release(r["id"]) or {}).get("id") == release_id]
    page = paginate(rows, limit, offset)
    return list_response([serialize.rider(r) for r in page], limit, offset, len(rows))


@bp.patch("/riders/<rider_id>")
@endpoint(["IntakeCoordinator", "ProgramAdmin"])
def update_rider(rider_id):
    payload = validate_body([
        Field("weight_lb", "number", exclusive_min=0, maximum=RIDER_MAX_WEIGHT_LB),
        Field("household_income_band", "enum", members=INCOME_BANDS),
        Field("condition_codes", "string_array"),
        Field("funding_mode", "enum", members=FUNDING_MODES),
        Field("payer_rate_cents", "int", minimum=0),
    ])
    row = rider_or_404(rider_id)
    for key in ("weight_lb", "household_income_band", "funding_mode",
                "payer_rate_cents"):
        if payload.get(key) is not None:
            row[key] = payload[key]
    if payload.get("condition_codes") is not None:
        row["condition_codes"] = list(payload["condition_codes"])
    touch(row)
    return object_response(serialize.rider(row))


@bp.post("/riders/<rider_id>/activate")
@endpoint(["IntakeCoordinator", "ProgramAdmin"])
def activate_rider(rider_id):
    row = rider_or_404(rider_id)
    gates.gate_medical_release(row)                       # rung 18
    if row["status"] != "INTAKE":                         # rung 19
        fail("ERR_INVALID_STATE", "Only a rider in INTAKE may be activated.")
    if derive.recorded_assessment(rider_id) is None:
        fail("ERR_INVALID_STATE", "The rider has no RECORDED assessment.")
    if derive.active_release(rider_id) is None:
        fail("ERR_INVALID_STATE", "The rider has no active release.")
    row["status"] = "ACTIVE"
    touch(row)
    return object_response(serialize.rider(row))


@bp.post("/riders/<rider_id>/withdraw")
@endpoint(["IntakeCoordinator", "ProgramAdmin"])
def withdraw_rider(rider_id):
    payload = validate_body([Field("reason", "string", required=True)])
    row = rider_or_404(rider_id)
    if row["status"] not in ("INTAKE", "ACTIVE", "MEDICAL_HOLD"):
        fail("ERR_INVALID_STATE", "A withdrawn rider cannot be withdrawn again.")
    live = [s for s in db["sessions"].values()
            if s["rider_id"] == rider_id
            and s["schedule_status"] in ("CREW_PENDING", "CONFIRMED")]
    if live:
        fail("ERR_INVALID_STATE",
             "The rider still holds CREW_PENDING or CONFIRMED sessions.")
    row["status"] = "WITHDRAWN"
    row["withdraw_reason"] = payload["reason"]
    touch(row)
    return object_response(serialize.rider(row))


@bp.post("/riders/<rider_id>/medical-clearance")
@endpoint(["ProgramAdmin"])
def medical_clearance(rider_id):
    payload = validate_body([
        Field("medical_release_id", "string", required=True),
        Field("note", "string", required=True),
    ])
    row = rider_or_404(rider_id)
    release = resource_or_404("medical_releases", payload["medical_release_id"])
    if row["status"] != "MEDICAL_HOLD":
        fail("ERR_INVALID_STATE", "Only a rider in MEDICAL_HOLD may be cleared.")
    if row["medical_hold_incident_id"] is not None:
        fail("ERR_INVALID_STATE", "The incident hold has not been released yet.")
    if release["rider_id"] != rider_id:
        fail("ERR_INVALID_STATE", "That release belongs to another rider.")
    if derive.release_status(release) != "ACTIVE":
        fail("ERR_INVALID_STATE", "The named release is not ACTIVE.")
    row["status"] = "ACTIVE"
    touch(row)
    return object_response(serialize.rider(row))
