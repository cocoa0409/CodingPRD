"""Meal plans and supervised-meal events (PRD §3.6)."""
from flask import Blueprint

import errors
from db import store
from errors import ApiError
from middleware import require_auth_and_roles
from response import success, list_response
from services import calc
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
    validate_bool,
    validate_enum,
    validate_int,
    validate_number,
)
from services.domain import recompute_patient_posture, set_patient_number

bp = Blueprint("meals", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]
MEAL_TYPES = {"BREAKFAST", "LUNCH", "DINNER", "SNACK"}


# --------------------------- meal plans ---------------------------
@bp.route("/edt/meal-plans", methods=["POST"])
@require_auth_and_roles(["Dietitian"])
def create_meal_plan():
    body = get_json_body()
    admission_id = require_field(body, "admission_id")
    facility_id = require_field(body, "facility_id")
    required_meals_per_day = validate_int(
        require_field(body, "required_meals_per_day"), "required_meals_per_day", 1, 6
    )
    supervision_level = validate_enum(
        require_field(body, "supervision_level"), "supervision_level", {"FULL", "PARTIAL"}
    )
    with store.lock:
        check_fk("admission_id", admission_id)
        check_fk("facility_id", facility_id)
        rec = base_record()
        rec.update({
            "admission_id": admission_id,
            "facility_id": facility_id,
            "required_meals_per_day": required_meals_per_day,
            "supervision_level": supervision_level,
            "meals_logged": 0,
            "completion_points": 0,
            "meal_compliance_rate": 0,
            "status": "ACTIVE",
        })
        store.meal_plans[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/meal-plans", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_meal_plans():
    page, limit, offset, total = list_collection(
        "meal_plans", filters={"admission_id": "admission_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/meal-plans/<mp_id>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_meal_plan(mp_id):
    rec = get_or_404("meal_plans", mp_id, errors.ERR_MEAL_PLAN_NOT_FOUND)
    return success(serialize(rec), status=200)


@bp.route("/edt/meal-plans/<mp_id>/close", methods=["POST"])
@require_auth_and_roles(["Dietitian"])
def close_meal_plan(mp_id):
    get_optional_json_body()
    with store.lock:
        mp = get_or_404("meal_plans", mp_id, errors.ERR_MEAL_PLAN_NOT_FOUND)
        # legal only from ACTIVE (PRD §3.6).
        if mp["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Meal plan is not ACTIVE.")
        mp["status"] = "CLOSED"
        touch(mp)
        # Reconcile patient risk: subtract credit = 40 * rate (round2), clamp [0,100].
        patient = store.patients[store.admissions[mp["admission_id"]]["patient_id"]]
        credit = calc.meal_close_credit(mp["meal_compliance_rate"])
        new_score = calc.Decimal(str(patient["nutritional_risk_score"])) - credit
        new_score = calc._clamp(new_score, calc.Decimal("0"), calc.Decimal("100"))
        set_patient_number(patient, "nutritional_risk_score", new_score)
        recompute_patient_posture(patient)
        touch(patient)
        return success(serialize(mp), status=200)


# --------------------------- meal events ---------------------------
@bp.route("/edt/meal-events", methods=["POST"])
@require_auth_and_roles(["Dietitian", "Clinician"])
def create_meal_event():
    body = get_json_body()
    meal_plan_id = require_field(body, "meal_plan_id")
    admission_id = require_field(body, "admission_id")
    meal_type = validate_enum(require_field(body, "meal_type"), "meal_type", MEAL_TYPES)
    completion_fraction = validate_number(
        require_field(body, "completion_fraction"), "completion_fraction", minimum=0, maximum=1
    )
    refused = body.get("refused", False)
    if refused is None:
        refused = False
    validate_bool(refused, "refused")
    with store.lock:
        mp = check_fk("meal_plan_id", meal_plan_id)
        check_fk("admission_id", admission_id)

        # Append-only log row: id + created_at only (no updated_at, no version).
        rec = base_record(with_version=False)
        rec.update({
            "meal_plan_id": meal_plan_id,
            "admission_id": admission_id,
            "meal_type": meal_type,
            "completion_fraction": completion_fraction,
            "refused": refused,
            "logged_at_iso": store.now_iso(),
        })
        store.meal_events[rec["id"]] = rec

        # Recompute the plan's aggregates (PRD §3.6).
        eff = calc.effective_fraction(completion_fraction, refused)
        mp["meals_logged"] += 1
        new_points = calc.Decimal(str(mp["completion_points"])) + eff
        mp["completion_points"] = calc._to_number(new_points)
        rate = calc.meal_compliance_rate(mp["completion_points"], mp["meals_logged"])
        mp["meal_compliance_rate"] = calc._to_number(rate)
        touch(mp)

        return success(serialize(rec), status=201)


@bp.route("/edt/meal-events", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_meal_events():
    page, limit, offset, total = list_collection(
        "meal_events", filters={"meal_plan_id": "meal_plan_id", "admission_id": "admission_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/meal-events/<me_id>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_meal_event(me_id):
    rec = get_or_404("meal_events", me_id, errors.ERR_MEAL_EVENT_NOT_FOUND)
    return success(serialize(rec), status=200)
