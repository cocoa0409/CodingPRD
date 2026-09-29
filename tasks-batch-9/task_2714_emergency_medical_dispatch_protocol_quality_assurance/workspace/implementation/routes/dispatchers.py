"""The dispatcher roster, certification and the call feed (PRD 3.1, 3.3)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
import helpers
import validate
from auth import ALL_OPERATORS, require
from cascades import set_fields
from envelope import ok, public
from errors import fail
from store import base_row, clock, db, order_rows

bp = Blueprint("dispatchers", __name__)

CALL_TYPES = (
    "CARDIAC_ARREST",
    "CHEST_PAIN",
    "BREATHING_PROBLEM",
    "TRAUMA",
    "UNCONSCIOUS",
)


@bp.post("/dispatchers")
@require("ProgramAdmin")
def enroll_dispatcher():
    payload = validate.body()
    program_id = validate.get_str(payload, "program_id")
    employee_code = validate.get_str(payload, "employee_code")
    full_name = validate.get_str(payload, "full_name")
    hire_date = validate.get_instant(payload, "hire_date", required=False)

    program = helpers.program(program_id)

    for other in db.dispatchers.values():
        if (
            other["program_id"] == program["id"]
            and other["employee_code"] == employee_code
        ):
            fail(
                "ERR_DUPLICATE_EMPLOYEE_CODE",
                "employee_code is already used in this programme.",
            )

    dispatcher = base_row()
    dispatcher.update(
        {
            "program_id": program["id"],
            "employee_code": employee_code,
            "full_name": full_name,
            "hire_date": hire_date,
            "certified_protocol_version_id": None,
            "certification_status": "PROVISIONAL",
            "certified_at": None,
            "reviewed_case_count": 0,
            "compliance_points_total": calc.q1(Decimal("0")),
            "compliance_pct": None,
            "compliance_posture": "UNRATED",
            "remediation_hours_owed": calc.q2(Decimal("0")),
            "sentinel_event_count": 0,
            "dispatch_privilege": "FULL",
        }
    )
    db.dispatchers[dispatcher["id"]] = dispatcher
    return ok(public(dispatcher), 201)


@bp.get("/dispatchers/<dispatcher_id>")
@require(*(ALL_OPERATORS + ("Dispatcher",)))
def read_dispatcher(dispatcher_id):
    return ok(public(helpers.dispatcher(dispatcher_id)))


@bp.get("/dispatchers")
@require(*ALL_OPERATORS)
def list_dispatchers():
    limit, offset = validate.pagination()
    filters = {
        "program_id": request.args.get("program_id"),
        "certified_protocol_version_id": request.args.get(
            "certified_protocol_version_id"
        ),
        "compliance_posture": request.args.get("compliance_posture"),
        "dispatch_privilege": request.args.get("dispatch_privilege"),
        "certification_status": request.args.get("certification_status"),
    }
    rows = [d for d in db.dispatchers.values() if helpers.matches(d, filters)]
    return helpers.respond_list(rows, limit, offset)


@bp.post("/dispatchers/<dispatcher_id>/certify")
@require("ProgramAdmin")
def certify_dispatcher(dispatcher_id):
    payload = validate.body()
    version_id = validate.get_str(payload, "protocol_version_id")
    certified_at = validate.get_instant(payload, "certified_at", required=False)

    dispatcher = helpers.dispatcher(dispatcher_id)
    version = helpers.protocol_version(version_id)

    if version["program_id"] != dispatcher["program_id"]:
        fail(
            "ERR_PROGRAM_SCOPE_MISMATCH",
            "The protocol version belongs to another programme.",
        )
    if version["status"] not in ("APPROVED", "ACTIVE"):
        fail(
            "ERR_VERSION_NOT_CERTIFIABLE",
            "Only an APPROVED or ACTIVE version may certify a dispatcher.",
        )

    previous_version_id = dispatcher["certified_protocol_version_id"]
    set_fields(
        dispatcher,
        {
            "certification_status": "CERTIFIED",
            "certified_protocol_version_id": version["id"],
            "certified_at": certified_at or clock(),
        },
    )

    # Re-certification reopens whatever the lapse suspended (PRD 3.3).
    for plan in order_rows(cascades.plans_of_dispatcher(dispatcher["id"])):
        if plan["status"] != "SUSPENDED":
            continue
        reopened = "IN_PROGRESS" if plan["credited_hours"] > Decimal("0") else "ASSIGNED"
        set_fields(plan, {"status": reopened})

    cascades.recompute_rollouts_for_version(version["id"])
    if previous_version_id and previous_version_id != version["id"]:
        cascades.recompute_rollouts_for_version(previous_version_id)

    cascades.recompute_hours_and_privilege(dispatcher)
    return ok(public(dispatcher))


@bp.post("/dispatchers/<dispatcher_id>/call-records")
@require("ProgramAdmin")
def ingest_call(dispatcher_id):
    payload = validate.body()
    call_reference = validate.get_str(payload, "call_reference")
    call_type = validate.get_enum(payload, "call_type", CALL_TYPES)
    received_at = validate.get_instant(payload, "received_at")
    code = validate.get_str(payload, "dispatched_determinant_code")
    arrest_confirmed = validate.get_bool(
        payload, "cardiac_arrest_confirmed", required=False, default=False
    )
    bystander = validate.get_bool(
        payload, "bystander_cpr_in_progress", required=False, default=False
    )

    if not calc.valid_determinant_code(code):
        fail(
            "ERR_INVALID_DETERMINANT_CODE",
            "dispatched_determinant_code is not a valid determinant code.",
        )

    dispatcher = helpers.dispatcher(dispatcher_id)

    if received_at > clock():
        fail(
            "ERR_CALL_RECEIVED_IN_FUTURE",
            "received_at may not be after the logical clock.",
        )

    for other in db.call_records.values():
        if other["call_reference"] == call_reference:
            fail(
                "ERR_DUPLICATE_CALL_REFERENCE",
                "call_reference must be globally unique.",
            )

    decoded = calc.decode_determinant(code)
    call = base_row()
    call.update(
        {
            "dispatcher_id": dispatcher["id"],
            "call_reference": call_reference,
            "call_type": call_type,
            "received_at": received_at,
            "dispatched_determinant_code": code,
            "dispatched_priority_rank": decoded["priority_rank"],
            "response_mode_assigned": decoded["response_mode"],
            "resource_assigned": decoded["resource"],
            "cardiac_arrest_confirmed": arrest_confirmed,
            "bystander_cpr_in_progress": bystander,
            "status": "INGESTED",
        }
    )
    db.call_records[call["id"]] = call
    return ok(public(call), 201)


@bp.get("/dispatchers/<dispatcher_id>/call-records")
@require("ProgramAdmin", "QaSupervisor", "QaReviewer", "MedicalDirector")
def list_calls(dispatcher_id):
    limit, offset = validate.pagination()
    dispatcher = helpers.dispatcher(dispatcher_id)
    filters = {
        "call_type": request.args.get("call_type"),
        "status": request.args.get("status"),
    }
    rows = [
        c
        for c in db.call_records.values()
        if c["dispatcher_id"] == dispatcher["id"] and helpers.matches(c, filters)
    ]
    return helpers.respond_list(rows, limit, offset)
