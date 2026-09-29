"""EquipmentModel endpoints (PRD Section 3.1)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from middleware import authorize
from response import ok, created, ok_list
from routes.helpers import find, filter_by, unique_code
from services import calc

bp = Blueprint("equipment_models", __name__)

POSTURES = ("UNLISTED", "PARTIAL", "LISTED", "SUSPENDED")

READ_ONE_ROLES = (
    "ComplianceEngineer", "ListingReviewer", "ApplicationEngineer", "EngineeringApprover",
    "ProductionPlanner", "ConnectedOpsEngineer", "ChannelManager", "ServicePartnerUser",
    "ChainAdmin", "WarrantyAdjudicator", "PlatformAdmin",
)
READ_LIST_ROLES = (
    "ComplianceEngineer", "ListingReviewer", "ApplicationEngineer", "EngineeringApprover",
    "ProductionPlanner", "ConnectedOpsEngineer", "ChannelManager", "PlatformAdmin",
)


@bp.post("/equipment-models")
def create_equipment_model():
    authorize("ComplianceEngineer", "PlatformAdmin")
    payload = validate.body()
    model_code = validate.string_field(payload, "model_code", min_len=1, max_len=32)
    name = validate.string_field(payload, "name", min_len=1)
    category = validate.enum_field(payload, "category", calc.CATEGORIES)
    energy_type = validate.enum_field(payload, "energy_type", calc.ENERGY_TYPES)
    base_price_cents = validate.int_field(payload, "base_price_cents", minimum=1)
    controls = validate.enum_array_field(payload, "supported_controls_packages",
                                         calc.CONTROLS_PACKAGES)
    rated = validate.number_field(payload, "rated_throughput_units_per_hour", gt=0)

    unique_code(db.equipment_models, model_code=model_code)

    model = insert(db.equipment_models, {
        "model_code": model_code,
        "name": name,
        "category": category,
        "energy_type": energy_type,
        "base_price_cents": base_price_cents,
        "supported_controls_packages": controls,
        "rated_throughput_units_per_hour": rated,
        "required_scopes": calc.required_scopes_for(energy_type),
        "covered_scopes": [],
        "certification_posture": "UNLISTED",
    })
    return created(model)


@bp.get("/equipment-models")
def list_equipment_models():
    authorize(*READ_LIST_ROLES)
    limit, offset = validate.pagination()
    category = validate.enum_arg("category", calc.CATEGORIES)
    energy_type = validate.enum_arg("energy_type", calc.ENERGY_TYPES)
    posture = validate.enum_arg("certification_posture", POSTURES)

    items = ordered(db.equipment_models)
    items = filter_by(items, "category", category)
    items = filter_by(items, "energy_type", energy_type)
    items = filter_by(items, "certification_posture", posture)
    return ok_list(items, limit, offset)


@bp.get("/equipment-models/<model_id>")
def get_equipment_model(model_id):
    authorize(*READ_ONE_ROLES)
    model = find(db.equipment_models, model_id, "ERR_EQUIPMENT_MODEL_NOT_FOUND")
    return ok(model)


@bp.patch("/equipment-models/<model_id>")
def patch_equipment_model(model_id):
    authorize("ComplianceEngineer", "PlatformAdmin")
    payload = validate.body()
    base_price_cents = validate.int_field(payload, "base_price_cents", required=False, minimum=1)
    controls = validate.enum_array_field(payload, "supported_controls_packages",
                                         calc.CONTROLS_PACKAGES, required=False)
    rated = validate.number_field(payload, "rated_throughput_units_per_hour",
                                  required=False, gt=0)

    model = find(db.equipment_models, model_id, "ERR_EQUIPMENT_MODEL_NOT_FOUND")
    if base_price_cents is not None:
        model["base_price_cents"] = base_price_cents
    if controls is not None:
        model["supported_controls_packages"] = controls
    if rated is not None:
        model["rated_throughput_units_per_hour"] = rated
    touch(model)
    return ok(model)
