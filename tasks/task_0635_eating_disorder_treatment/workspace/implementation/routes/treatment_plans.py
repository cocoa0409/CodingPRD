"""Treatment plans: fork/join sign-off, activate, revise, goals (PRD §3.7)."""
from flask import Blueprint, g

import errors
from db import store
from errors import ApiError
from middleware import require_auth_and_roles
from response import success, list_response
from services.common import (
    base_record,
    check_fk,
    get_json_body,
    get_optional_json_body,
    get_or_404,
    list_collection,
    require_field,
    serialize,
    touch,
    validate_enum,
    validate_int,
)

bp = Blueprint("treatment_plans", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]
DISCIPLINES = {"THERAPY", "DIETITIAN", "MEDICAL"}
DISCIPLINE_FLAG = {"THERAPY": "therapy_signed", "DIETITIAN": "dietitian_signed", "MEDICAL": "medical_signed"}


@bp.route("/edt/treatment-plans", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def create_treatment_plan():
    body = get_json_body()
    admission_id = require_field(body, "admission_id")
    facility_id = require_field(body, "facility_id")
    goals_total = validate_int(require_field(body, "goals_total"), "goals_total", minimum=1)
    with store.lock:
        check_fk("admission_id", admission_id)
        check_fk("facility_id", facility_id)
        rec = base_record()
        rec.update({
            "admission_id": admission_id,
            "facility_id": facility_id,
            "therapy_signed": False,
            "dietitian_signed": False,
            "medical_signed": False,
            "goals_total": goals_total,
            "goals_met": 0,
            "status": "DRAFT",
        })
        store.treatment_plans[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/treatment-plans", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_treatment_plans():
    page, limit, offset, total = list_collection(
        "treatment_plans", filters={"admission_id": "admission_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/treatment-plans/<tp_id>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_treatment_plan(tp_id):
    rec = get_or_404("treatment_plans", tp_id, errors.ERR_TREATMENT_PLAN_NOT_FOUND)
    return success(serialize(rec), status=200)


@bp.route("/edt/treatment-plans/<tp_id>/sign", methods=["POST"])
@require_auth_and_roles(["Clinician", "Dietitian"])
def sign_discipline(tp_id):
    body = get_json_body()
    discipline = validate_enum(require_field(body, "discipline"), "discipline", DISCIPLINES)
    with store.lock:
        tp = get_or_404("treatment_plans", tp_id, errors.ERR_TREATMENT_PLAN_NOT_FOUND)
        # legal while DRAFT or REVISION (PRD §3.7).
        if tp["status"] not in ("DRAFT", "REVISION"):
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Treatment plan is not DRAFT/REVISION.")
        # THERAPY/MEDICAL by Clinician; DIETITIAN by Dietitian (PRD §3.7).
        role = g.user_role
        if discipline in ("THERAPY", "MEDICAL") and role != "Clinician":
            raise ApiError(errors.ERR_UNAUTHORIZED, 403, "THERAPY/MEDICAL require Clinician.")
        if discipline == "DIETITIAN" and role != "Dietitian":
            raise ApiError(errors.ERR_UNAUTHORIZED, 403, "DIETITIAN requires Dietitian.")
        flag = DISCIPLINE_FLAG[discipline]
        if tp[flag]:
            raise ApiError(errors.ERR_DISCIPLINE_ALREADY_SIGNED, 409, "Discipline already signed.")
        tp[flag] = True
        touch(tp)
        return success(serialize(tp), status=200)


@bp.route("/edt/treatment-plans/<tp_id>/goals/met", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def goals_met(tp_id):
    get_optional_json_body()
    with store.lock:
        tp = get_or_404("treatment_plans", tp_id, errors.ERR_TREATMENT_PLAN_NOT_FOUND)
        # goals_met += 1, capped at goals_total (PRD §3.7).
        if tp["goals_met"] < tp["goals_total"]:
            tp["goals_met"] += 1
        touch(tp)
        return success(serialize(tp), status=200)


@bp.route("/edt/treatment-plans/<tp_id>/activate", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def activate(tp_id):
    get_optional_json_body()
    with store.lock:
        tp = get_or_404("treatment_plans", tp_id, errors.ERR_TREATMENT_PLAN_NOT_FOUND)
        # legal from DRAFT or REVISION; same join condition both paths (PRD §3.7).
        if tp["status"] not in ("DRAFT", "REVISION"):
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Treatment plan is not DRAFT/REVISION.")
        if not (tp["therapy_signed"] and tp["dietitian_signed"] and tp["medical_signed"]):
            raise ApiError(errors.ERR_DISCIPLINES_INCOMPLETE, 409, "All three disciplines must be signed.")
        tp["status"] = "ACTIVE"
        touch(tp)
        return success(serialize(tp), status=200)


@bp.route("/edt/treatment-plans/<tp_id>/revise", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def revise(tp_id):
    body = get_json_body()
    expected_admission_version = require_field(body, "expected_admission_version")
    with store.lock:
        tp = get_or_404("treatment_plans", tp_id, errors.ERR_TREATMENT_PLAN_NOT_FOUND)
        admission = store.admissions[tp["admission_id"]]
        # Priority 5: OCC on Admission.version before state/business logic (PRD §2.5/§2.6).
        if not isinstance(expected_admission_version, int) or isinstance(expected_admission_version, bool):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_admission_version must be an integer.")
        if expected_admission_version != admission["version"]:
            raise ApiError(errors.ERR_STALE_VERSION, 412, "Stale admission version.")
        # legal only from ACTIVE (PRD §3.7).
        if tp["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Treatment plan is not ACTIVE.")
        tp["status"] = "REVISION"
        tp["therapy_signed"] = False
        tp["dietitian_signed"] = False
        tp["medical_signed"] = False
        touch(tp)
        # increments Admission.version by 1.
        touch(admission)
        return success(serialize(tp), status=200)
