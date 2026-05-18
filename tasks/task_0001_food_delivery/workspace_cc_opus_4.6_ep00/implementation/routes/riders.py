from flask import Blueprint, request
from store import store
from models import make_versioned, touch, serialize
from middleware import check_role_permission
from response import success_response
from errors import (
    raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_VALIDATION, ERR_SUSPEND_CRITERIA_NOT_MET,
)

bp = Blueprint("riders", __name__)


@bp.route("/api/riders", methods=["POST"])
def create_rider():
    check_role_permission({"PlatformAdmin"})
    data = request.get_json(force=True, silent=True) or {}

    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise_error(ERR_VALIDATION, "name is required")

    phone = data.get("phone")
    if not phone or not isinstance(phone, str):
        raise_error(ERR_VALIDATION, "phone is required")

    for r in store.riders.values():
        if r["phone"] == phone:
            raise_error(ERR_VALIDATION, "phone must be unique across all riders")

    rider = make_versioned({
        "name": name,
        "phone": phone,
        "status": "OFFLINE",
        "wallet_balance_cents": 0,
        "on_time_rate": 1.0,
        "acceptance_rate": 1.0,
        "rating": 5.0,
        "bonus_tier": "BRONZE",
    })
    store.riders[rider["id"]] = rider
    return success_response(serialize(rider), 201)


@bp.route("/api/riders/<rider_id>", methods=["GET"])
def get_rider(rider_id):
    check_role_permission({"PlatformAdmin", "Rider", "CustomerService"})
    rider = store.riders.get(rider_id)
    if not rider:
        raise_error(ERR_NOT_FOUND, "Rider not found")

    if request.user_role == "Rider" and request.user_id != rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot read another rider's profile")

    return success_response(serialize(rider))


@bp.route("/api/riders/<rider_id>/go-online", methods=["POST"])
def go_online(rider_id):
    check_role_permission({"Rider"})
    rider = store.riders.get(rider_id)
    if not rider:
        raise_error(ERR_NOT_FOUND, "Rider not found")
    if request.user_id != rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot go online for another rider")
    if rider["status"] != "OFFLINE":
        raise_error(ERR_INVALID_STATE, "Rider must be OFFLINE to go online")
    rider["status"] = "AVAILABLE"
    touch(rider)
    return success_response(serialize(rider))


@bp.route("/api/riders/<rider_id>/go-offline", methods=["POST"])
def go_offline(rider_id):
    check_role_permission({"Rider"})
    rider = store.riders.get(rider_id)
    if not rider:
        raise_error(ERR_NOT_FOUND, "Rider not found")
    if request.user_id != rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot go offline for another rider")
    if rider["status"] != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "Rider must be AVAILABLE to go offline")

    has_active = any(
        a["rider_id"] == rider_id and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
        for a in store.assignments.values()
    )
    if has_active:
        raise_error(ERR_INVALID_STATE, "Cannot go offline with active assignments")

    rider["status"] = "OFFLINE"
    touch(rider)
    return success_response(serialize(rider))


@bp.route("/api/riders/<rider_id>/suspend", methods=["POST"])
def suspend_rider(rider_id):
    check_role_permission({"PlatformAdmin"})
    rider = store.riders.get(rider_id)
    if not rider:
        raise_error(ERR_NOT_FOUND, "Rider not found")
    if rider["status"] != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "Rider must be AVAILABLE to suspend")
    if rider["on_time_rate"] >= 0.70 and rider["acceptance_rate"] >= 0.50:
        raise_error(ERR_SUSPEND_CRITERIA_NOT_MET, "Performance thresholds not breached")
    rider["status"] = "SUSPENDED"
    touch(rider)
    return success_response(serialize(rider))
