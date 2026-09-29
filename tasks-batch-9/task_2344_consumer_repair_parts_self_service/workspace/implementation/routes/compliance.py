"""Regional profiles, compliance obligations, the sweep and the logical clock."""
from flask import Blueprint, g

import db
from db import base_row, setf, touch
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, PROGRAM_ADMIN, REPAIR_PROVIDER_TECH, \
    SAFETY_REVIEWER, SELF_REPAIR_CUSTOMER, endpoint
from response import collection, created, ok
from routes.helpers import filter_eq, get_model, get_obligation, obligation_for, find_profile
from serializers import obligation_json, profile_json
from services.compliance import apply_mandated_window, evaluate_obligation, \
    obligations_for_model, rollup_model_posture
from util import fmt_ts
from validation import F, int_range, read_body, str_len

bp = Blueprint("compliance", __name__)

MANDATE_TIERS = ("MANDATE_NONE", "MANDATE_BASIC", "MANDATE_FULL")

PROFILE_FIELDS = [
    F("region_code", "string", required=True),
    F("min_parts_availability_years", "int", required=True),
    F("min_documentation_years", "int", required=True),
    F("requires_public_manual", "bool", default=False),
    F("max_documentation_fee_cents", "int", required=True),
    F("allows_pairing_restriction", "bool", default=True),
    F("self_service_mandate_tier", "enum", required=True, enum=MANDATE_TIERS),
]


@bp.post("/compliance-profiles")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER])
def create_profile():
    body = read_body(PROFILE_FIELDS)
    str_len(body["region_code"], "region_code", 2, 8)
    int_range(body["min_parts_availability_years"], "min_parts_availability_years", 0, 15)
    int_range(body["min_documentation_years"], "min_documentation_years", 0, 15)
    int_range(body["max_documentation_fee_cents"], "max_documentation_fee_cents", 0, None)

    for existing in db.db.profiles.all():
        if existing["region_code"] == body["region_code"]:
            raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "region_code already registered.")

    row = base_row()
    row.update(body)
    db.db.profiles.add(row)
    return created(profile_json(row))


@bp.get("/compliance-profiles")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER, SAFETY_REVIEWER, SELF_REPAIR_CUSTOMER,
           REPAIR_PROVIDER_TECH])
def list_profiles():
    rows = db.db.profiles.all()
    rows = filter_eq(rows, "region_code")
    rows = filter_eq(rows, "self_service_mandate_tier")
    return collection(rows, profile_json)


@bp.post("/compliance-obligations")
@endpoint([COMPLIANCE_OFFICER, PROGRAM_ADMIN])
def create_obligation():
    body = read_body([
        F("model_id", "string", required=True),
        F("region_code", "string", required=True),
    ])
    if obligation_for(body["model_id"], body["region_code"]) is not None:
        raise ApiError("ERR_DUPLICATE_NATURAL_KEY",
                       "An obligation already exists for that model and region.")
    model = get_model(body["model_id"])
    profile = find_profile(body["region_code"])

    row = base_row()
    row.update({
        "model_id": model["id"],
        "region_code": profile["region_code"],
        "parts_available_until": None,
        "documentation_available_until": None,
        "deadline_basis": "PRODUCTION_ACTIVE",
        "status": "OPEN",
        "documentation_verified": False,
        "last_attested_at": None,
        "last_attested_by_user_id": None,
        "breach_count": 0,
    })
    db.db.obligations.add(row)

    apply_mandated_window(row, model, profile)
    evaluate_obligation(row, model)
    rollup_model_posture(model)
    touch(model)
    return created(obligation_json(row))


@bp.post("/compliance-obligations/<obligation_id>/attest")
@endpoint([COMPLIANCE_OFFICER])
def attest_obligation(obligation_id):
    body = read_body([
        F("attestation_note", "string"),
        F("documentation_verified", "bool", default=False),
    ])
    obligation = get_obligation(obligation_id)

    if obligation["status"] not in (
        "OPEN", "AT_RISK", "BREACHED_DOCUMENTATION", "BREACHED_PARTS"
    ):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    model = db.db.models.get(obligation["model_id"])
    if body["documentation_verified"] is not True:
        raise ApiError("ERR_ATTESTATION_UNSUPPORTED",
                       "documentation_verified must be true.")
    if model is None or model.get("documentation_posture") != "CURRENT":
        raise ApiError("ERR_ATTESTATION_UNSUPPORTED",
                       "The model's documentation posture is not CURRENT.")

    setf(obligation, "status", "ATTESTED")
    setf(obligation, "documentation_verified", True)
    setf(obligation, "last_attested_at", db.now())
    setf(obligation, "last_attested_by_user_id", g.user_id)
    rollup_model_posture(model)
    touch(model)
    return ok(obligation_json(obligation))


@bp.get("/compliance-obligations/<obligation_id>")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER, SAFETY_REVIEWER])
def read_obligation(obligation_id):
    return ok(obligation_json(get_obligation(obligation_id)))


@bp.get("/compliance-obligations")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER, SAFETY_REVIEWER])
def list_obligations():
    rows = db.db.obligations.all()
    for field in ("model_id", "region_code", "status", "deadline_basis"):
        rows = filter_eq(rows, field)
    return collection(rows, obligation_json)


@bp.post("/compliance-sweeps")
@endpoint([COMPLIANCE_OFFICER, PROGRAM_ADMIN], require_user_id=False)
def run_sweep():
    body = read_body([F("model_id", "string")])
    scope = db.ordered(db.db.obligations.all())
    if body["model_id"] is not None:
        get_model(body["model_id"])
        scope = [o for o in scope if o["model_id"] == body["model_id"]]

    breached = []
    touched_models = []
    for obligation in scope:
        model = db.db.models.get(obligation["model_id"])
        status = evaluate_obligation(obligation, model, force_touch=True)
        if status in ("BREACHED_PARTS", "BREACHED_DOCUMENTATION"):
            breached.append(obligation["id"])
        if model is not None and model not in touched_models:
            touched_models.append(model)

    at = db.now()
    expired = []
    for assessment in db.ordered(db.db.assessments.all()):
        if assessment["status"] != "VALID":
            continue
        if assessment.get("expires_at") is not None and assessment["expires_at"] < at:
            setf(assessment, "status", "EXPIRED")
            expired.append(assessment["id"])

    restricted = []
    for model in touched_models:
        if rollup_model_posture(model) == "ORDER_RESTRICTED":
            restricted.append(model["id"])
        touch(model)

    return ok({
        "swept_obligation_count": len(scope),
        "breached_obligation_ids": breached,
        "expired_assessment_ids": expired,
        "restricted_model_ids": restricted,
    })


@bp.post("/_clock/set_current_utc")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER], require_user_id=False)
def set_clock():
    body = read_body([F("to_iso8601", "datetime", required=True)])
    target = body["to_iso8601"]
    if target <= db.db.current_utc:
        raise ApiError("ERR_CLOCK_MONOTONICITY")
    db.db.current_utc = target
    return ok({"current_utc": fmt_ts(target)})
