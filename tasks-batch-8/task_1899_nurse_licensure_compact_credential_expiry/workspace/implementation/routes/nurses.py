from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_RESOURCE,
    ERR_HIRE_REQUIREMENTS_UNMET,
    ERR_INVALID_NURSE_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from services.derived import (
    FACILITY_STATE,
    derive_privilege,
    recompute_posture,
    unit_decrement,
)
from util import parse_time_loose

bp = Blueprint("nurses", __name__)

ALL_ROLES = None  # sentinel: GET endpoints accept every declared role

EMPLOYMENT_TYPES = ["STAFF", "TRAVEL", "PER_DIEM"]

CREATE_SCHEMA = {
    "full_name": ("string", True, None),
    "email": ("string", True, None),
    "primary_state_of_residence": ("string", True, None),
    "employment_type": ("string", True, EMPLOYMENT_TYPES),
    "hire_date": ("date", True, None),
}

PATCH_SCHEMA = {
    "full_name": ("string", False, None),
    "email": ("string", False, None),
    "primary_state_of_residence": ("string", False, None),
    "employment_type": ("string", False, EMPLOYMENT_TYPES),
    "expected_nurse_version": ("int", True, None),
}


@bp.route("/credentialing/nurses", methods=["POST"])
def create_nurse():
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    body = validate_body(get_body(), CREATE_SCHEMA)
    if any(n["email"] == body["email"] for n in all_entities("nurses")):
        raise ApiError(ERR_DUPLICATE_RESOURCE, "A nurse with this email already exists", 409)
    nurse = create_entity("nurses", {
        "full_name": body["full_name"],
        "email": body["email"],
        "primary_state_of_residence": body["primary_state_of_residence"],
        "employment_type": body["employment_type"],
        "hire_date": body["hire_date"].isoformat(),
        "status": "ONBOARDING",
        "credential_posture": "SCHEDULING_SUSPENDED",
        "multistate_privilege_status": "NONE",
        "practice_scope": [],
        "open_encumbrance_count": 0,
    })
    # Initial privilege derivation (no PrivilegeEvaluation row appended on create).
    derive_privilege(nurse, reason=None)
    return success_object(serialize("nurses", nurse), 201)


@bp.route("/credentialing/nurses", methods=["GET"])
def list_nurses():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("nurses")
    for param in ("status", "credential_posture", "employment_type"):
        value = request.args.get(param)
        if value is not None:
            rows = [n for n in rows if n[param] == value]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize("nurses", n) for n in page], limit, offset, total)


@bp.route("/credentialing/nurses/<nurseId>", methods=["GET"])
def get_nurse(nurseId):
    auth_context()
    nurse = get_or_404("nurses", nurseId, ERR_NOT_FOUND, "Nurse not found")
    return success_object(serialize("nurses", nurse))


@bp.route("/credentialing/nurses/<nurseId>", methods=["PATCH"])
def patch_nurse(nurseId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    nurse = get_or_404("nurses", nurseId, ERR_NOT_FOUND, "Nurse not found")
    body = validate_body(get_body(allow_empty=False), PATCH_SCHEMA)
    # OCC (stage 6)
    if body["expected_nurse_version"] != nurse["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_nurse_version does not match the nurse's current version", 412)
    # Uniqueness (stage 9)
    if "email" in body and body["email"] != nurse["email"]:
        if any(n["email"] == body["email"] and n["id"] != nurse["id"] for n in all_entities("nurses")):
            raise ApiError(ERR_DUPLICATE_RESOURCE, "A nurse with this email already exists", 409)
    psor_changed = (
        "primary_state_of_residence" in body
        and body["primary_state_of_residence"] != nurse["primary_state_of_residence"]
    )
    for field in ("full_name", "email", "primary_state_of_residence", "employment_type"):
        if field in body:
            nurse[field] = body[field]
    if psor_changed:
        derive_privilege(nurse, reason="PSOR_CHANGE")
    # Posture recompute (also covers employment_type changes); nurse touched once.
    recompute_posture(nurse, touch_nurse=False)
    touch(nurse)  # PATCH increments the nurse version by exactly 1
    return success_object(serialize("nurses", nurse))


@bp.route("/credentialing/nurses/<nurseId>/activate", methods=["POST"])
def activate_nurse(nurseId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    nurse = get_or_404("nurses", nurseId, ERR_NOT_FOUND, "Nurse not found")
    if nurse["status"] != "ONBOARDING":
        raise ApiError(ERR_INVALID_NURSE_STATE, "Only an ONBOARDING nurse can be activated", 409)
    has_active_license = any(
        lic for lic in all_entities("licenses")
        if lic["nurse_id"] == nurse["id"] and lic["status"] == "ACTIVE"
    )
    if not has_active_license or FACILITY_STATE not in nurse["practice_scope"]:
        raise ApiError(
            ERR_HIRE_REQUIREMENTS_UNMET,
            "Activation requires at least one ACTIVE license and the facility state in derived practice scope",
            409,
        )
    nurse["status"] = "ACTIVE"
    touch(nurse)
    recompute_posture(nurse)
    return success_object(serialize("nurses", nurse))


@bp.route("/credentialing/nurses/<nurseId>/terminate", methods=["POST"])
def terminate_nurse(nurseId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    nurse = get_or_404("nurses", nurseId, ERR_NOT_FOUND, "Nurse not found")
    if nurse["status"] == "TERMINATED":
        raise ApiError(ERR_INVALID_NURSE_STATE, "Nurse is already TERMINATED", 409)
    now = db.logical_now()
    # Future SCHEDULED shifts -> AUTO_CANCELLED (NURSE_TERMINATED); unit counters released.
    for shift in all_entities("shifts"):
        if (shift["nurse_id"] == nurse["id"] and shift["status"] == "SCHEDULED"
                and parse_time_loose(shift["starts_at"]) > now):
            shift["status"] = "AUTO_CANCELLED"
            shift["cancel_reason"] = "NURSE_TERMINATED"
            touch(shift)
            unit_decrement(db.STORES["units"].get(shift["unit_id"]), shift["hours"])
    # Non-terminal packets -> VOIDED.
    for packet in all_entities("packets"):
        if packet["nurse_id"] == nurse["id"] and packet["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            packet["status"] = "VOIDED"
            touch(packet)
    nurse["status"] = "TERMINATED"
    nurse["credential_posture"] = "SCHEDULING_SUSPENDED"  # forced terminal snapshot
    touch(nurse)
    return success_object(serialize("nurses", nurse))
