"""Logical clock + BPO vendor registration."""
from flask import Blueprint

import constants as K
import validation as V
from auth import require
from db import db
from envelope import created, success
from serializers import vendor_out
from timeutil import to_iso

bp = Blueprint("platform", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require(K.ROLE_PLATFORM_ADMIN)
    data = V.body()
    instant = V.req_datetime(data, "to_iso8601")
    db.set_clock(instant)
    return success({"current_utc": to_iso(instant)}, 200)


@bp.post("/short-sale/bpo-vendors")
def create_vendor():
    require(K.ROLE_PLATFORM_ADMIN)
    data = V.body()
    vendor = {
        "id": db.new_id(),
        "vendor_name": V.req_string(data, "vendor_name"),
        "license_state": V.req_string(data, "license_state"),
        "daily_inspection_capacity": V.req_int(data, "daily_inspection_capacity", minimum=1),
    }
    db.insert("vendors", vendor, common_fields=False)
    return created(vendor_out(vendor))
