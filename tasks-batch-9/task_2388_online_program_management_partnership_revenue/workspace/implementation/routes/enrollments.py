"""Enrollment reads, academic actions (Cascade B) and the bursar cash ledger."""

from flask import Blueprint, request

import constants as C
import db
import serializers
from db import store, touch
from errors import ApiError, bad_request
from middleware import PARTNER, authenticate, body, check_action_role, check_scope
from response import object_response
from routes.common import get_enrollment, get_partnership, get_program, listing
from services.cascades import withdraw_enrollment
from services.derive import (recompute_enrollment_cash, recompute_partnership,
                             recompute_program)
from services.money import parse_iso_date
from validation import Field, enum_filter, pagination_args, validate_body

bp = Blueprint("enrollments", __name__)

READ_ROLES = ("PlatformAdmin", "UniversityProvost", "UniversityBursar",
              "ComplianceAuditor", "PartnerAccountLead")

ACADEMIC_SPEC = {
    "action": Field("enum", required=True, enum=tuple(C.ACADEMIC_ACTION_ROLES)),
    "credits_completed": Field("integer", minimum=0),
    "withdrawal_date": Field("date"),
    "withdrawal_reason": Field("string"),
}

PAYMENT_SPEC = {
    "entry_type": Field("enum", required=True, enum=C.TUITION_ENTRY_TYPES),
    "amount_cents": Field("integer", required=True),
    "posted_date": Field("date", required=True),
    "reference_note": Field("string"),
}


def _partnership_id_of(enrollment):
    program = store.programs.get(enrollment["program_id"])
    return program["partnership_id"] if program else None


@bp.get("/enrollments/<enrollment_id>")
def read(enrollment_id):
    uid, role = authenticate(READ_ROLES)
    enrollment = get_enrollment(enrollment_id)
    check_scope(role, uid, _partnership_id_of(enrollment))
    return object_response(serializers.enrollment(enrollment))


@bp.get("/enrollments")
def index():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_args(request.args)
    status = enum_filter(request.args, "status", C.ENROLLMENT_STATUSES)
    program_id = request.args.get("program_id")
    lead_id = request.args.get("lead_id")

    if role == PARTNER and program_id is not None:
        program = store.programs.get(program_id)
        if program is not None and program["partnership_id"] != uid:
            raise ApiError("ERR_PARTNERSHIP_SCOPE_VIOLATION")

    items = db.sort_created(list(store.enrollments.values()))
    if program_id is not None:
        items = [e for e in items if e["program_id"] == program_id]
    if lead_id is not None:
        items = [e for e in items if e["lead_id"] == lead_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if role == PARTNER:
        items = [e for e in items if _partnership_id_of(e) == uid]
    return listing(items, serializers.enrollment, limit, offset)


@bp.post("/enrollments/<enrollment_id>/academic-actions")
def academic_action(enrollment_id):
    uid, role = authenticate(("UniversityBursar", "UniversityProvost"))
    values = validate_body(body(), ACADEMIC_SPEC)
    action = values["action"]
    check_action_role(role, action, C.ACADEMIC_ACTION_ROLES)

    if action == "RECORD_PROGRESS" and "credits_completed" not in values:
        raise bad_request("credits_completed is required on RECORD_PROGRESS.")
    if action == "WITHDRAW" and "withdrawal_date" not in values:
        raise bad_request("withdrawal_date is required on WITHDRAW.")

    enrollment = get_enrollment(enrollment_id)

    if action == "WITHDRAW":
        if enrollment["status"] not in ("ENROLLED", "ACTIVE"):
            raise ApiError("ERR_ENROLLMENT_INVALID_STATE")
    elif enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE")

    program = get_program(enrollment["program_id"])
    partnership = get_partnership(program["partnership_id"])

    if action == "RECORD_PROGRESS":
        if values["credits_completed"] > enrollment["credits_enrolled"]:
            raise bad_request("credits_completed may not exceed credits_enrolled.")
        enrollment["credits_completed"] = values["credits_completed"]
        touch(enrollment)
    elif action == "COMPLETE":
        if enrollment["credits_completed"] != enrollment["credits_enrolled"]:
            raise ApiError("ERR_ENROLLMENT_INVALID_STATE")
        enrollment["status"] = "COMPLETED"
        touch(enrollment)
        recompute_program(program)
        recompute_partnership(partnership)
    else:
        if parse_iso_date(values["withdrawal_date"]) < parse_iso_date(
                enrollment["term_start_date"]):
            raise bad_request("withdrawal_date may not precede term_start_date.")
        withdraw_enrollment(enrollment, values["withdrawal_date"], program, partnership)

    return object_response(serializers.enrollment(enrollment))


@bp.post("/enrollments/<enrollment_id>/tuition-payments")
def post_payment(enrollment_id):
    uid, role = authenticate(("UniversityBursar",))
    values = validate_body(body(), PAYMENT_SPEC)
    enrollment = get_enrollment(enrollment_id)

    if enrollment["status"] not in ("ENROLLED", "ACTIVE"):
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE")

    if values["entry_type"] == "REFUND":
        available = enrollment["collected_cents"] - enrollment["refunded_cents"]
        if values["amount_cents"] > available:
            raise ApiError("ERR_REFUND_EXCEEDS_COLLECTED")

    entry = db.base_entity(full=False)
    entry.update({
        "enrollment_id": enrollment["id"],
        "entry_type": values["entry_type"],
        "amount_cents": values["amount_cents"],
        "posted_date": values["posted_date"],
        "reference_note": values.get("reference_note"),
        "generated_by": "BURSAR_POST",
    })
    store.tuition_payments[entry["id"]] = entry

    recompute_enrollment_cash(enrollment)
    if enrollment["status"] == "ENROLLED" and enrollment["collected_cents"] > 0:
        enrollment["status"] = "ACTIVE"
        touch(enrollment)

    program = get_program(enrollment["program_id"])
    partnership = get_partnership(program["partnership_id"])
    recompute_program(program)
    recompute_partnership(partnership)
    return object_response(serializers.tuition_payment(entry), 201)


@bp.get("/enrollments/<enrollment_id>/tuition-payments")
def list_payments(enrollment_id):
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_args(request.args)
    enrollment = get_enrollment(enrollment_id)
    check_scope(role, uid, _partnership_id_of(enrollment))
    return listing(db.payments_of(enrollment["id"]), serializers.tuition_payment,
                   limit, offset)
