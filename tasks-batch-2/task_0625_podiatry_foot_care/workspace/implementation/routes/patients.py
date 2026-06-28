"""Patient intake and diabetic-foot risk stratification (PRD §3.2)."""

from flask import Blueprint, request

import calculations as calc
import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("patients", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}

RISK_BOOLS = [
    "has_diabetes_mellitus",
    "has_loss_protective_sensation",
    "has_peripheral_arterial_disease",
    "has_foot_deformity",
    "has_prior_ulcer_or_amputation",
]


@bp.route("/podiatry/patients", methods=["POST"])
def create_patient():
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    body = mw.get_body()
    with db.lock():
        practice_id = v.as_str(body, "practice_id", required=True)
        if practice_id not in db.practices:
            raise errors.fk_not_found("practice_id references a non-existent practice.")
        full_name = v.as_str(body, "full_name", required=True)
        date_of_birth = v.as_date(body, "date_of_birth", required=True)
        entity = {
            "practice_id": practice_id,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
        }
        for f in RISK_BOOLS:
            entity[f] = v.as_bool(body, f, default=False)
        entity["diabetic_foot_risk_category"] = calc.diabetic_foot_risk_category(entity)
        entity["last_covered_routine_care_date"] = None
        db.stamp_common(entity)
        db.patients[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/patients", methods=["GET"])
def list_patients():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    practice_id = request.args.get("practice_id")
    items = [p for p in db.patients.values()
             if practice_id is None or p["practice_id"] == practice_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.patients.get(patient_id)
    if entity is None:
        raise errors.not_found("Patient not found.")
    return resp.success(entity, 200)


@bp.route("/podiatry/patients/<patient_id>/risk-factors", methods=["PATCH"])
def update_risk_factors(patient_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    with db.lock():
        entity = db.patients.get(patient_id)
        if entity is None:
            raise errors.not_found("Patient not found.")
        body = mw.get_body()
        # Any subset of the five booleans may be supplied (PRD §3.2).
        for f in RISK_BOOLS:
            if f in body and body[f] is not None:
                if not isinstance(body[f], bool):
                    raise errors.invalid_request(f"Field {f} must be a boolean")
                entity[f] = body[f]
        entity["diabetic_foot_risk_category"] = calc.diabetic_foot_risk_category(entity)
        db.touch(entity)
        return resp.success(entity, 200)
