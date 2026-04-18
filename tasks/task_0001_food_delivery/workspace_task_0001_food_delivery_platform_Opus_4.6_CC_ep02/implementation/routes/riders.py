from flask import Blueprint, request
from auth import require_roles, check_ownership
from errors import APIError
from models import riders, assignments, versioned_resource_base, touch
from response_envelope import success_response
from calculations import recompute_rider_bonus

bp = Blueprint("riders", __name__)


def rider_dict(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "phone": r["phone"],
        "status": r["status"],
        "on_time_rate": r["on_time_rate"],
        "acceptance_rate": r["acceptance_rate"],
        "rating": r["rating"],
        "wallet_balance_cents": r["wallet_balance_cents"],
        "bonus_tier": r["bonus_tier"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/api/riders", methods=["POST"])
@require_roles("PlatformAdmin")
def create_rider():
    data = request.get_json(force=True, silent=True) or {}

    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise APIError("ERR_VALIDATION", "name is required")

    phone = data.get("phone")
    if not phone or not isinstance(phone, str):
        raise APIError("ERR_VALIDATION", "phone is required")

    for r in riders.values():
        if r["phone"] == phone:
            raise APIError("ERR_VALIDATION", "phone must be unique across all riders")

    r = versioned_resource_base()
    r.update({
        "name": name,
        "phone": phone,
        "status": "OFFLINE",
        "on_time_rate": 1.0,
        "acceptance_rate": 1.0,
        "rating": 5.0,
        "wallet_balance_cents": 0,
        "bonus_tier": "BRONZE",
    })

    riders[r["id"]] = r
    return success_response(rider_dict(r), 201)


@bp.route("/api/riders/<rider_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Rider", "CustomerService")
def get_rider(rider_id):
    r = riders.get(rider_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Rider not found")

    check_ownership(rider_id, request.user_id, request.user_role, ["Rider"])

    return success_response(rider_dict(r))


@bp.route("/api/riders/<rider_id>/go-online", methods=["POST"])
@require_roles("Rider")
def go_online(rider_id):
    r = riders.get(rider_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Rider not found")

    check_ownership(rider_id, request.user_id, request.user_role, ["Rider"])

    if r["status"] != "OFFLINE":
        raise APIError("ERR_INVALID_STATE", "Rider must be OFFLINE to go online")

    r["status"] = "AVAILABLE"
    touch(r)
    return success_response(rider_dict(r))


@bp.route("/api/riders/<rider_id>/go-offline", methods=["POST"])
@require_roles("Rider")
def go_offline(rider_id):
    r = riders.get(rider_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Rider not found")

    check_ownership(rider_id, request.user_id, request.user_role, ["Rider"])

    if r["status"] != "AVAILABLE":
        raise APIError("ERR_INVALID_STATE", "Rider must be AVAILABLE to go offline")

    active_statuses = {"OFFERED", "ACCEPTED", "PICKED_UP"}
    for a in assignments.values():
        if a["rider_id"] == rider_id and a["status"] in active_statuses:
            raise APIError("ERR_INVALID_STATE", "Cannot go offline with active assignments")

    r["status"] = "OFFLINE"
    touch(r)
    return success_response(rider_dict(r))


@bp.route("/api/riders/<rider_id>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_rider(rider_id):
    r = riders.get(rider_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Rider not found")

    if r["status"] != "AVAILABLE":
        raise APIError("ERR_INVALID_STATE", "Rider must be AVAILABLE to suspend")

    if r["on_time_rate"] >= 0.70 and r["acceptance_rate"] >= 0.50:
        raise APIError("ERR_SUSPEND_CRITERIA_NOT_MET",
                        "Rider metrics do not meet suspension thresholds")

    r["status"] = "SUSPENDED"
    touch(r)
    return success_response(rider_dict(r))
