"""FulfillmentCenter endpoints."""
from flask import Blueprint, request

import response
import serialize
import validate
from db import db, mark_created, new_row, set_field
from middleware import require_fc_scope, require_roles
from routes.common import finish, get_fc

bp = Blueprint("centers", __name__)

PREP_PROFILES = ("POLYBAG_REQUIRED", "LABEL_ONLY", "CASE_PACK_STRICT")
RECEIVING_STATUSES = ("OPEN", "THROTTLED", "SUSPENDED")


@bp.post("/fulfillment/fulfillment-centers")
@require_roles("MarketplaceAdmin")
def create_center():
    data = validate.body()
    fc_code = validate.req_str(data, "fc_code")
    region_code = validate.req_str(data, "region_code")
    prep_profile = validate.req_enum(data, "prep_profile", PREP_PROFILES)
    case_pack_min = validate.req_int(data, "case_pack_min_units", minimum=1)
    capacity = validate.req_int(data, "receiving_capacity_units_per_window", minimum=1)
    monthly_rate = validate.req_int(data, "monthly_storage_rate_cents_per_cubic_foot", minimum=0)
    ltsf_rate = validate.req_int(data, "ltsf_rate_cents_per_cubic_foot", minimum=0)

    for existing in db.fcs.values():
        if existing["fc_code"] == fc_code:
            validate.bad("fc_code must be unique across fulfillment centers.")

    row = new_row()
    row.update({
        "fc_code": fc_code,
        "region_code": region_code,
        "prep_profile": prep_profile,
        "case_pack_min_units": case_pack_min,
        "receiving_capacity_units_per_window": capacity,
        "monthly_storage_rate_cents_per_cubic_foot": monthly_rate,
        "ltsf_rate_cents_per_cubic_foot": ltsf_rate,
        "receiving_status": "OPEN",
        "committed_receiving_units": 0,
    })
    db.fcs[row["id"]] = row
    mark_created(row)
    return finish(lambda: serialize.fulfillment_center(row), 201)


@bp.get("/fulfillment/fulfillment-centers/<fc_id>")
@require_roles("MarketplaceAdmin", "FcOperator", "SellerOperator")
def read_center(fc_id):
    fc = get_fc(fc_id)
    return response.object_response(serialize.fulfillment_center(fc), 200)


@bp.patch("/fulfillment/fulfillment-centers/<fc_id>")
@require_roles("FcOperator", "MarketplaceAdmin")
def update_center(fc_id):
    data = validate.body()
    receiving_status = validate.req_enum(data, "receiving_status", RECEIVING_STATUSES, required=False)
    capacity = validate.req_int(data, "receiving_capacity_units_per_window",
                                required=False, minimum=1)
    fc = get_fc(fc_id)
    require_fc_scope(fc["id"])

    if receiving_status is not None:
        set_field(fc, "receiving_status", receiving_status)
    if capacity is not None:
        set_field(fc, "receiving_capacity_units_per_window", capacity)
    return finish(lambda: serialize.fulfillment_center(fc), 200)
