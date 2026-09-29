"""Reference registry: product models and retailers (PRD 3.1)."""

from flask import Blueprint

import auth
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("registry", __name__)

CATEGORIES = ("KITCHEN_APPLIANCE", "JUVENILE_PRODUCT", "POWER_TOOL",
              "SPORTING_GOODS", "HOME_ELECTRONICS")
CHANNEL_TYPES = ("BIG_BOX", "ONLINE_MARKETPLACE", "SPECIALTY", "DISTRIBUTOR")


@bp.route("/product-models/<model_id>", methods=["GET"])
def get_product_model(model_id):
    auth.authorize("ProgramAdmin", "IntakeSpecialist", "ComplianceOfficer",
                   "SafetyDirector", "FieldAuditor", "PenaltyCounsel")
    return responses.object_response(lookups.find("product_model", model_id))


@bp.route("/product-models", methods=["POST"])
def create_product_model():
    auth.authorize("ProgramAdmin")
    data = shapes.body()
    model_code = shapes.req_str(data, "model_code", 1, 40)
    brand = shapes.req_str(data, "brand", 1, 80)
    category = shapes.req_enum(data, "category", CATEGORIES)
    units_distributed = shapes.req_int(data, "units_distributed", minimum=1)
    units_registered = shapes.req_int(data, "units_registered", minimum=0)

    for existing in store.product_models.values():
        if existing["model_code"] == model_code:
            raise_error("ERR_MODEL_CODE_TAKEN")

    row = store.new_row(
        model_code=model_code,
        brand=brand,
        category=category,
        units_distributed=units_distributed,
        units_registered=units_registered,
        hazard_posture="MONITORED",
        open_escalation_count=0,
    )
    store.product_models[row["id"]] = row
    return responses.created(row)


@bp.route("/retailers/<retailer_id>", methods=["GET"])
def get_retailer(retailer_id):
    auth.authorize("ProgramAdmin", "ComplianceOfficer", "SafetyDirector",
                   "FieldAuditor", "RetailerRep")
    return responses.object_response(lookups.find("retailer", retailer_id))


@bp.route("/retailers", methods=["POST"])
def create_retailer():
    auth.authorize("ProgramAdmin")
    data = shapes.body()
    name = shapes.req_str(data, "name", 1, 120)
    channel_type = shapes.req_enum(data, "channel_type", CHANNEL_TYPES)
    store_count = shapes.req_int(data, "store_count", minimum=1)
    row = store.new_row(
        name=name,
        channel_type=channel_type,
        store_count=store_count,
        compliance_posture="CLEAR",
        open_stop_sale_count=0,
        verified_removal_count=0,
        delinquent_count=0,
    )
    store.retailers[row["id"]] = row
    return responses.created(row)
