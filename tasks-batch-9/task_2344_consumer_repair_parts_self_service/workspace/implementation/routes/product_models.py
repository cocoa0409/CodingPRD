"""Product models and the support lifecycle (PRD 3.1)."""
from flask import Blueprint

import db
from db import base_row, setf
from errors import ApiError
from middleware import ALL_ROLES, COMPLIANCE_OFFICER, DOCUMENTATION_ENGINEER, \
    PROGRAM_ADMIN, REPAIR_PROVIDER_TECH, SAFETY_REVIEWER, SELF_REPAIR_CUSTOMER, endpoint
from response import collection, created, ok
from routes.helpers import filter_as_of_date, filter_bool, filter_eq, get_model, \
    profile_or_none
from serializers import compat_json, model_json, obligation_json
from services.compliance import apply_mandated_window, compat_rows, evaluate_obligation, \
    obligations_for_model, rollup_model_posture
from validation import F, read_body, str_len

bp = Blueprint("product_models", __name__)

REPAIRABILITY_TIERS = (
    "TIER_A_SELF_SERVICE", "TIER_B_GUIDED", "TIER_C_AUTHORIZED_ONLY",
    "TIER_D_NON_SERVICEABLE",
)

CREATE_FIELDS = [
    F("model_code", "string", required=True),
    F("product_family", "string", required=True),
    F("market_release_date", "datetime", required=True),
    F("end_of_production_date", "datetime"),
    F("last_hardware_change_date", "datetime"),
    F("repairability_tier", "enum", required=True, enum=REPAIRABILITY_TIERS),
]


@bp.post("/product-models")
@endpoint([PROGRAM_ADMIN])
def create_model():
    body = read_body(CREATE_FIELDS)
    str_len(body["model_code"], "model_code", 3, 32)

    eop = body["end_of_production_date"]
    if eop is not None and eop < body["market_release_date"]:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "end_of_production_date precedes market_release_date.")

    for existing in db.db.models.all():
        if existing["model_code"] == body["model_code"]:
            raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "model_code already registered.")

    row = base_row()
    row.update({
        "model_code": body["model_code"],
        "product_family": body["product_family"],
        "market_release_date": body["market_release_date"],
        "end_of_production_date": eop,
        "last_hardware_change_date": body["last_hardware_change_date"],
        "repairability_tier": body["repairability_tier"],
        "support_state": "LEGACY_SUPPORT" if eop is not None else "ACTIVE_PRODUCTION",
        "support_end_date": None,
        "documentation_posture": "MISSING",
        "published_disassembly_revision_number": None,
        "published_safety_sheet_revision_number": None,
        "compliance_posture": "OPEN",
        "open_obligation_count": 0,
    })
    db.db.models.add(row)
    return created(model_json(row))


@bp.get("/product-models/<model_id>")
@endpoint(ALL_ROLES)
def read_model(model_id):
    return ok(model_json(get_model(model_id)))


@bp.get("/product-models")
@endpoint(ALL_ROLES)
def list_models():
    rows = db.db.models.all()
    for field in ("product_family", "support_state", "repairability_tier",
                  "compliance_posture", "documentation_posture"):
        rows = filter_eq(rows, field)
    return collection(rows, model_json)


@bp.post("/product-models/<model_id>/end-production")
@endpoint([PROGRAM_ADMIN])
def end_production(model_id):
    body = read_body([F("end_of_production_date", "datetime", required=True)])
    model = get_model(model_id)
    eop = body["end_of_production_date"]

    if eop < model["market_release_date"]:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "end_of_production_date precedes market_release_date.")
    if model["support_state"] != "ACTIVE_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    setf(model, "end_of_production_date", eop)
    setf(model, "support_state", "LEGACY_SUPPORT")

    for obligation in obligations_for_model(model["id"]):
        profile = profile_or_none(obligation["region_code"])
        if profile is not None:
            apply_mandated_window(obligation, model, profile)
    for obligation in obligations_for_model(model["id"]):
        evaluate_obligation(obligation, model, force_touch=True)
    rollup_model_posture(model)
    db.touch(model)
    return ok(model_json(model))


@bp.post("/product-models/<model_id>/end-support")
@endpoint([PROGRAM_ADMIN])
def end_support(model_id):
    body = read_body([F("support_end_date", "datetime", required=True)])
    model = get_model(model_id)
    support_end = body["support_end_date"]

    eop = model.get("end_of_production_date")
    if eop is not None and support_end < eop:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "support_end_date precedes end_of_production_date.")
    if model["support_state"] != "LEGACY_SUPPORT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    for obligation in obligations_for_model(model["id"]):
        if obligation["status"] not in ("CLOSED", "ATTESTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "An obligation is neither CLOSED nor ATTESTED.")

    setf(model, "support_end_date", support_end)
    setf(model, "support_state", "SUPPORT_ENDED")

    at = db.now()
    for obligation in obligations_for_model(model["id"]):
        if obligation["status"] in ("OPEN", "AT_RISK", "ATTESTED"):
            deadline = obligation.get("parts_available_until")
            if deadline is not None and at > deadline:
                setf(obligation, "status", "CLOSED")
    for assessment in db.ordered(db.db.assessments.all()):
        if assessment["model_id"] == model["id"] and assessment["status"] == "VALID":
            setf(assessment, "status", "EXPIRED")
    rollup_model_posture(model)
    db.touch(model)
    return ok(model_json(model))


@bp.get("/product-models/<model_id>/compliance-obligations")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER, SAFETY_REVIEWER])
def list_model_obligations(model_id):
    get_model(model_id)
    rows = [o for o in db.db.obligations.all() if o["model_id"] == model_id]
    for field in ("region_code", "status", "deadline_basis"):
        rows = filter_eq(rows, field)
    return collection(rows, obligation_json)


@bp.get("/product-models/<model_id>/part-compatibilities")
@endpoint([PROGRAM_ADMIN, SAFETY_REVIEWER, DOCUMENTATION_ENGINEER, SELF_REPAIR_CUSTOMER,
           REPAIR_PROVIDER_TECH])
def list_model_compats(model_id):
    get_model(model_id)
    rows = compat_rows(model_id=model_id)
    rows = filter_eq(rows, "part_id")
    rows = filter_eq(rows, "required_tool_part_id")
    rows = filter_bool(rows, "self_service_eligible")
    rows = filter_as_of_date(rows)
    return collection(rows, compat_json)
