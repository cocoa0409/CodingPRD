"""Vendor pass-through costs (PRD 3.6)."""
from flask import Blueprint

import db
import response
import services
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("vendor_costs", __name__)


@bp.post("/vendor-costs")
@endpoint(["AccountManager"])
def create_vendor_cost():
    b = validate.body()
    campaign_id = validate.req_str(b, "campaign_id")
    vendor_name = validate.req_str(b, "vendor_name")
    vendor_type = validate.req_enum(b, "vendor_type", validate.VENDOR_TYPES)
    estimated = validate.req_int(b, "estimated_amount_cents", minimum=0)
    incurred_on = validate.req_datetime(b, "incurred_on")

    campaign = services.must("campaign", campaign_id)
    services.campaign_gate(campaign)

    obj = db.base_entity()
    obj.update(
        {
            "campaign_id": campaign_id,
            "vendor_name": vendor_name,
            "vendor_type": vendor_type,
            "incurred_on": b["incurred_on"],
            "estimated_amount_cents": estimated,
            "actual_amount_cents": None,
            "status": "SUBMITTED",
            "_incurred_on": incurred_on.date(),
        }
    )
    db.VENDOR_COSTS[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.post("/vendor-costs/<vid>/approve")
@endpoint(["AccountManager"])
def approve_vendor_cost(vid):
    b = validate.body()
    actual = validate.req_int(b, "actual_amount_cents", minimum=0)

    cost = services.must("vendor_cost", vid)
    if cost["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    campaign = services.must("campaign", cost["campaign_id"])
    services.campaign_gate(campaign)

    cost["actual_amount_cents"] = actual
    cost["status"] = "APPROVED"
    services.touch(cost)
    return response.ok(db.public(cost))
