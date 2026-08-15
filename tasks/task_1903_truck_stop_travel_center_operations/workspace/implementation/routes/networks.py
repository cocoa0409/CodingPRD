"""Discount network programs and enrollments (PRD 3.4)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_DUPLICATE_NETWORK_ENROLLMENT, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_MEMBER_NOT_ACTIVE, ERR_NETWORK_CAP_REACHED,
    ERR_NETWORK_NOT_ACTIVE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_from, public
from services.core import FUEL_TYPES, new_record, touch
from validate import (
    get_body, query_filter, req_int, req_str, require_path_resource,
)

bp = Blueprint("networks", __name__)

ENROLLMENT_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED", "RETIRED", "CANCELLED"]


@bp.post("/discount-networks")
def create_network():
    authorized(["GeneralManager"])
    body = get_body()
    name = req_str(body, "name")
    discount = body.get("discount_per_gallon")
    if not isinstance(discount, (int, float)) or isinstance(discount, bool) or discount < 0:
        raise_error(ERR_INVALID_REQUEST, "discount_per_gallon must be a non-negative number")
    fuel_types = body.get("applicable_fuel_types")
    if not isinstance(fuel_types, list) or not fuel_types \
            or any(f not in FUEL_TYPES for f in fuel_types):
        raise_error(ERR_INVALID_REQUEST,
                    "applicable_fuel_types must be a non-empty subset of fuel types")
    cap = req_int(body, "program_cap", minimum=1)
    rec = new_record("networks", {
        "name": name,
        "discount_per_gallon": discount,
        "applicable_fuel_types": list(fuel_types),
        "program_cap": cap,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/discount-networks/<rid>")
def get_network(rid):
    authorized(["GeneralManager", "Cashier", "FuelDeskLead"])
    rec = require_path_resource("networks", rid)
    return success_object(public(rec))


@bp.get("/discount-networks/<rid>/enrollments")
def network_enrollments(rid):
    authorized(["GeneralManager", "Cashier"])
    network = require_path_resource("networks", rid)
    enrs = [e for e in db["enrollments"].values() if e["network_program_id"] == network["id"]]
    return list_from(enrs, {"status": query_filter("status", ENROLLMENT_STATUSES)})


@bp.post("/discount-networks/<rid>/activate")
def activate_network(rid):
    authorized(["GeneralManager"])
    network = require_path_resource("networks", rid)
    if network["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "network is not DRAFT")
    network["status"] = "ACTIVE"
    touch(network)
    return success_object(public(network))


@bp.post("/discount-networks/<rid>/retire")
def retire_network(rid):
    authorized(["GeneralManager"])
    network = require_path_resource("networks", rid)
    if network["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "network is not ACTIVE")
    network["status"] = "RETIRED"
    touch(network)
    for enr in db["enrollments"].values():
        if enr["network_program_id"] == network["id"] \
                and enr["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            enr["status"] = "RETIRED"
            touch(enr)
    return success_object(public(network))


def _active_enrollment_count(network_id):
    return len([e for e in db["enrollments"].values()
                if e["network_program_id"] == network_id and e["status"] == "ACTIVE"])


@bp.post("/discount-enrollments/<rid>/activate")
def activate_enrollment(rid):
    authorized(["Cashier", "GeneralManager"])
    enr = require_path_resource("enrollments", rid)
    if enr["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "enrollment is not PENDING")
    network = db["networks"].get(enr["network_program_id"])
    member = db["loyalty_members"].get(enr["loyalty_member_id"])
    # Gates in PRD 3.4 order: network ACTIVE, member ACTIVE, no duplicate, cap room
    if network is None or network["status"] != "ACTIVE":
        raise_error(ERR_NETWORK_NOT_ACTIVE, "network is not ACTIVE")
    if member is None or member["status"] != "ACTIVE":
        raise_error(ERR_MEMBER_NOT_ACTIVE, "loyalty member is not ACTIVE")
    for other in db["enrollments"].values():
        if other["id"] != enr["id"] \
                and other["loyalty_member_id"] == enr["loyalty_member_id"] \
                and other["network_program_id"] == enr["network_program_id"] \
                and other["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            raise_error(ERR_DUPLICATE_NETWORK_ENROLLMENT,
                        "member already enrolled in this network")
    if _active_enrollment_count(network["id"]) >= network["program_cap"]:
        raise_error(ERR_NETWORK_CAP_REACHED, "network has reached its program cap")
    enr["status"] = "ACTIVE"
    touch(enr)
    return success_object(public(enr))


@bp.post("/discount-enrollments/<rid>/suspend")
def suspend_enrollment(rid):
    authorized(["GeneralManager"])
    enr = require_path_resource("enrollments", rid)
    if enr["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "enrollment is not ACTIVE")
    enr["status"] = "SUSPENDED"
    touch(enr)
    return success_object(public(enr))


@bp.post("/discount-enrollments/<rid>/resume")
def resume_enrollment(rid):
    authorized(["GeneralManager"])
    enr = require_path_resource("enrollments", rid)
    if enr["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "enrollment is not SUSPENDED")
    network = db["networks"].get(enr["network_program_id"])
    if network is None or network["status"] != "ACTIVE":
        raise_error(ERR_NETWORK_NOT_ACTIVE, "network is not ACTIVE")
    if _active_enrollment_count(network["id"]) >= network["program_cap"]:
        raise_error(ERR_NETWORK_CAP_REACHED, "network has reached its program cap")
    enr["status"] = "ACTIVE"
    touch(enr)
    return success_object(public(enr))


@bp.post("/discount-enrollments/<rid>/cancel")
def cancel_enrollment(rid):
    caller = authorized(["LoyaltyMember", "GeneralManager"])
    enr = require_path_resource("enrollments", rid)
    if caller.role == "LoyaltyMember" and caller.user_id != enr["loyalty_member_id"]:
        from errors import ERR_FORBIDDEN
        raise_error(ERR_FORBIDDEN, "member may only cancel its own enrollments")
    if enr["status"] not in ("PENDING", "ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, "enrollment cannot be cancelled from its current state")
    enr["status"] = "CANCELLED"
    touch(enr)
    return success_object(public(enr))
