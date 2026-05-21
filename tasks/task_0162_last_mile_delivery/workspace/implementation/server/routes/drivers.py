"""Driver endpoints."""
from flask import Blueprint

from .. import store
from ..auth import authed
from ..envelope import success_object
from ..errors import raise_error
from ..serializers import serialize_driver
from ._helpers import get_json_body, require


bp = Blueprint("drivers", __name__)


@bp.post("/drivers")
@authed(["Dispatcher"])
def create_driver(user_id, user_role):
    body = get_json_body()
    badge_id = require(body, "badge_id")
    home_center_id = require(body, "home_center_id")
    hazmat_endorsement = bool(body.get("hazmat_endorsement", False))

    if not isinstance(badge_id, str) or not badge_id.strip():
        raise_error("ERR_REFERENCE_NOT_FOUND", "invalid badge_id")
    with store.lock:
        for existing in store.drivers.values():
            if existing.get("badge_id") == badge_id:
                raise_error("ERR_REFERENCE_NOT_FOUND", "badge_id already exists")
        if home_center_id not in store.transit_centers:
            raise_error("ERR_REFERENCE_NOT_FOUND", "home_center_id not found")

        d = {
            "badge_id": badge_id,
            "home_center_id": home_center_id,
            "hazmat_endorsement": hazmat_endorsement,
            "status": "OFF_DUTY",
        }
        store.stamp_create(d)
        store.drivers[d["id"]] = d
        return success_object(serialize_driver(d), status=201)


@bp.post("/drivers/<did>/check-in")
@authed(["Driver", "Dispatcher"])
def check_in(user_id, user_role, did):
    with store.lock:
        driver = store.drivers.get(did)
        if not driver:
            raise_error("ERR_NOT_FOUND", "driver not found")
        if user_role == "Driver" and driver["id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        if driver["status"] != "OFF_DUTY":
            raise_error("ERR_INVALID_STATE", "driver must be OFF_DUTY to check in")
        driver["status"] = "ON_DUTY"
        store.stamp_update(driver)
        return success_object(serialize_driver(driver))


@bp.post("/drivers/<did>/check-out")
@authed(["Driver", "Dispatcher"])
def check_out(user_id, user_role, did):
    with store.lock:
        driver = store.drivers.get(did)
        if not driver:
            raise_error("ERR_NOT_FOUND", "driver not found")
        if user_role == "Driver" and driver["id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        if driver["status"] != "RETURNED":
            raise_error("ERR_INVALID_STATE", "driver must be RETURNED to check out")
        driver["status"] = "OFF_DUTY"
        store.stamp_update(driver)
        return success_object(serialize_driver(driver))
