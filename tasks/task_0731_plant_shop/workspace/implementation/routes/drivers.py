"""Delivery driver onboarding and read."""
from flask import Blueprint
from db import DB
from errors import not_found
from middleware import auth_context, require_role, require_json
from response import ok, created
from services.common import stamp_common
from services.validation import require_fields, require_string, require_int

bp = Blueprint("drivers", __name__)


@bp.post("/delivery-drivers")
def create_driver():
    role, _ = auth_context()
    require_role(role, {"Manager"})
    payload = require_json()
    require_fields(payload, ["name"])
    name = require_string(payload, "name")
    dcm = 240
    if "daily_capacity_minutes" in payload:
        dcm = require_int(payload, "daily_capacity_minutes", minimum=0)
    entity = {
        **stamp_common(full=True),
        "name": name,
        "daily_capacity_minutes": dcm,
    }
    DB.delivery_drivers[entity["id"]] = entity
    return created(entity)


@bp.get("/delivery-drivers/<did>")
def get_driver(did):
    role, user_id = auth_context()
    require_role(role, {"DeliveryDriver", "ShopStaff", "Manager"})
    entity = DB.delivery_drivers.get(did)
    if not entity:
        raise not_found("DeliveryDriver")
    if role == "DeliveryDriver" and user_id != did:
        from errors import unauthorized
        raise unauthorized("driver not owner")
    return ok(entity)
