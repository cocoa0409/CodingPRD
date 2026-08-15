"""Driver registration and status transitions."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized, ANY_ROLE
from response import success_object
from services import core
from validate import json_body, v_str, v_num, v_enum, v_date

bp = Blueprint("drivers", __name__)

LICENSE_TYPES = {"RENTAL", "OWNER"}
DRIVER_STATUSES = {"PENDING", "ACTIVE", "SUSPENDED"}

# Driver state machine: PENDING -> ACTIVE, ACTIVE -> SUSPENDED, SUSPENDED -> ACTIVE
_DRIVER_TRANSITIONS = {
    ("PENDING", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
}


@bp.post("/drivers")
def create_driver():
    authorized(["LeagueAdmin", "Driver"])
    body = json_body()
    full_name = v_str(body, "full_name")
    dob_raw, _dob = v_date(body, "date_of_birth")
    weight = v_num(body, "body_weight_kg", gt=0)
    license_type = v_enum(body, "license_type", LICENSE_TYPES)
    driver = core.create_record("drivers", {
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "body_weight_kg": weight,
        "license_type": license_type,
        "status": "PENDING",
    })
    return success_object(core.serialize_driver(driver), 201)


@bp.get("/drivers/<driver_id>")
def get_driver(driver_id):
    authorized(ANY_ROLE)
    driver = core.must_find("drivers", driver_id, "driver not found")
    return success_object(core.serialize_driver(driver))


@bp.patch("/drivers/<driver_id>")
def patch_driver(driver_id):
    authorized(["LeagueAdmin"])
    body = json_body()
    target = v_enum(body, "status", DRIVER_STATUSES)
    driver = core.must_find("drivers", driver_id, "driver not found")
    if (driver["status"], target) not in _DRIVER_TRANSITIONS:
        raise_error(
            ERR_INVALID_STATE,
            f"driver status transition {driver['status']} -> {target} is not permitted",
        )
    driver["status"] = target
    core.touch(driver)
    return success_object(core.serialize_driver(driver))
