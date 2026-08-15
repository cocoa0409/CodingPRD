"""Photographer endpoints."""

from flask import Blueprint, request

from db import store
from errors import invalid_request, not_found, ApiError
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from serializers import photographer_json, booking_json
from services.domain import touch, sweep_clock, OPEN_COMMITTED_STATES
from timeutil import new_id, iso_now_ms
import errors

bp = Blueprint("photographers", __name__)

VALID_PACKAGES = {"STANDARD", "PREMIUM", "LUXURY"}


def _validate_photographer_payload(data, partial=False):
    if not partial:
        for f in ("market_id", "full_name", "email", "equipment_packages"):
            if f not in data:
                raise invalid_request(f"Missing required field: {f}")
    if "equipment_packages" in data:
        v = data["equipment_packages"]
        if not isinstance(v, list) or not v:
            raise invalid_request("equipment_packages must be a non-empty array")
        for pkg in v:
            if pkg not in VALID_PACKAGES:
                raise invalid_request("equipment_packages must be subset of {STANDARD, PREMIUM, LUXURY}")
    if "max_shoot_minutes_per_day" in data:
        v = data["max_shoot_minutes_per_day"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 60 or v > 720:
            raise invalid_request("max_shoot_minutes_per_day must be 60..720")
    if "drone_certified" in data and not isinstance(data["drone_certified"], bool):
        raise invalid_request("drone_certified must be a boolean")
    if "status" in data:
        if data["status"] not in ("ACTIVE", "INACTIVE"):
            raise invalid_request("status must be ACTIVE or INACTIVE")


@bp.route("/photographers", methods=["POST"])
def create_photographer():
    require_roles("OpsAdmin")
    data = request.get_json(silent=True) or {}
    _validate_photographer_payload(data, partial=False)
    if data["market_id"] not in store.markets:
        raise not_found("Market not found")
    for p in store.photographers.values():
        if p["email"] == data["email"]:
            raise invalid_request("email must be unique across Photographers")
    now = iso_now_ms()
    p = {
        "id": new_id(),
        "market_id": data["market_id"],
        "full_name": data["full_name"],
        "email": data["email"],
        "equipment_packages": list(data["equipment_packages"]),
        "drone_certified": data.get("drone_certified", False),
        "max_shoot_minutes_per_day": data.get("max_shoot_minutes_per_day", 480),
        "committed_minutes_by_day": {},
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.photographers[p["id"]] = p
    return success_object(photographer_json(p), http_status=201)


@bp.route("/photographers", methods=["GET"])
def list_photographers():
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.photographers.values(), key=lambda p: p["created_at"])
    market_id = request.args.get("market_id")
    status = request.args.get("status")
    if market_id is not None:
        items = [p for p in items if p["market_id"] == market_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([photographer_json(p) for p in page], limit, offset, total)


@bp.route("/photographers/<photographerId>", methods=["GET"])
def get_photographer(photographerId):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    p = store.photographers.get(photographerId)
    if not p:
        raise not_found("Photographer not found")
    return success_object(photographer_json(p))


@bp.route("/photographers/<photographerId>", methods=["PATCH"])
def patch_photographer(photographerId):
    require_roles("OpsAdmin")
    p = store.photographers.get(photographerId)
    if not p:
        raise not_found("Photographer not found")
    data = request.get_json(silent=True) or {}
    _validate_photographer_payload(data, partial=True)
    # INACTIVE gate: no open commitments
    if data.get("status") == "INACTIVE" and p["status"] != "INACTIVE":
        for b in store.bookings.values():
            if b.get("assigned_photographer_id") == p["id"] and b["state"] in OPEN_COMMITTED_STATES:
                raise ApiError(errors.ERR_PHOTOGRAPHER_HAS_OPEN_COMMITMENTS, 409,
                               "Photographer has open commitments")
    for f in ("equipment_packages", "drone_certified", "max_shoot_minutes_per_day", "status"):
        if f in data:
            p[f] = data[f]
    touch(p)
    return success_object(photographer_json(p))


@bp.route("/photographers/<photographerId>/shoot-bookings", methods=["GET"])
def photographer_bookings(photographerId):
    require_roles("Coordinator", "OpsAdmin", "Photographer")
    sweep_clock()
    p = store.photographers.get(photographerId)
    if not p:
        raise not_found("Photographer not found")
    limit, offset = parse_pagination(request.args)
    items = [b for b in store.bookings.values() if b.get("assigned_photographer_id") == photographerId]
    state = request.args.get("state")
    if state is not None:
        items = [b for b in items if b["state"] == state]
    items = sorted(items, key=lambda b: b["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([booking_json(b) for b in page], limit, offset, total)
