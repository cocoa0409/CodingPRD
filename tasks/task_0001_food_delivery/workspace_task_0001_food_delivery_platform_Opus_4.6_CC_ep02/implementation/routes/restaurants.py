from flask import Blueprint, request
from auth import require_roles, check_ownership
from errors import APIError
from models import restaurants, orders, new_id, versioned_resource_base, touch, check_version
from response_envelope import success_response
from pagination import parse_pagination_params, paginate
import clock

bp = Blueprint("restaurants", __name__)


def restaurant_dict(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "address": r["address"],
        "lat": r["lat"],
        "lng": r["lng"],
        "status": r["status"],
        "commission_rate_override": r["commission_rate_override"],
        "pending_settlement_cents": r["pending_settlement_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/api/restaurants", methods=["POST"])
@require_roles("PlatformAdmin")
def create_restaurant():
    data = request.get_json(force=True, silent=True) or {}

    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise APIError("ERR_VALIDATION", "name is required and must be non-empty")
    name = name.strip()
    if len(name) > 120:
        raise APIError("ERR_VALIDATION", "name must be at most 120 characters")

    for r in restaurants.values():
        if r["name"] == name and r["status"] != "CLOSED":
            raise APIError("ERR_VALIDATION", "Restaurant name must be unique among active restaurants")

    address = data.get("address")
    if not address or not isinstance(address, str):
        raise APIError("ERR_VALIDATION", "address is required")

    lat = data.get("lat")
    lng = data.get("lng")
    if lat is None or lng is None:
        raise APIError("ERR_VALIDATION", "lat and lng are required")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise APIError("ERR_VALIDATION", "lat and lng must be numbers")

    commission_rate_override = data.get("commission_rate_override")
    if commission_rate_override is not None:
        if not isinstance(commission_rate_override, (int, float)):
            raise APIError("ERR_VALIDATION", "commission_rate_override must be a number")
        if commission_rate_override < 0.05 or commission_rate_override > 0.35:
            raise APIError("ERR_VALIDATION", "commission_rate_override must be in [0.05, 0.35]")

    r = versioned_resource_base()
    r.update({
        "name": name,
        "address": address,
        "lat": float(lat),
        "lng": float(lng),
        "status": "PENDING_APPROVAL",
        "commission_rate_override": commission_rate_override,
        "pending_settlement_cents": 0,
    })

    restaurants[r["id"]] = r
    return success_response(restaurant_dict(r), 201)


@bp.route("/api/restaurants", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_restaurants():
    limit, offset = parse_pagination_params(request.args)
    status_filter = request.args.get("status")

    items = sorted(restaurants.values(), key=lambda x: x["created_at"])
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]

    page, pagination = paginate(items, limit, offset)
    return success_response([restaurant_dict(r) for r in page], 200, "array", pagination)


@bp.route("/api/restaurants/<restaurant_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def get_restaurant(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")
    return success_response(restaurant_dict(r))


@bp.route("/api/restaurants/<restaurant_id>", methods=["PATCH"])
@require_roles("PlatformAdmin", "Restaurant")
def update_restaurant(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")

    check_ownership(restaurant_id, request.user_id, request.user_role, ["Restaurant"])

    data = request.get_json(force=True, silent=True) or {}
    check_version(r, data.get("version"))

    if "address" in data:
        if not data["address"] or not isinstance(data["address"], str):
            raise APIError("ERR_VALIDATION", "address must be a non-empty string")
        r["address"] = data["address"]

    if "lat" in data:
        if not isinstance(data["lat"], (int, float)):
            raise APIError("ERR_VALIDATION", "lat must be a number")
        r["lat"] = float(data["lat"])

    if "lng" in data:
        if not isinstance(data["lng"], (int, float)):
            raise APIError("ERR_VALIDATION", "lng must be a number")
        r["lng"] = float(data["lng"])

    if "commission_rate_override" in data:
        cro = data["commission_rate_override"]
        if cro is not None:
            if not isinstance(cro, (int, float)):
                raise APIError("ERR_VALIDATION", "commission_rate_override must be a number")
            if cro < 0.05 or cro > 0.35:
                raise APIError("ERR_VALIDATION", "commission_rate_override must be in [0.05, 0.35]")
        r["commission_rate_override"] = cro

    touch(r)
    return success_response(restaurant_dict(r))


@bp.route("/api/restaurants/<restaurant_id>/approve", methods=["POST"])
@require_roles("PlatformAdmin")
def approve_restaurant(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")
    if r["status"] != "PENDING_APPROVAL":
        raise APIError("ERR_INVALID_STATE", "Restaurant must be in PENDING_APPROVAL to approve")
    r["status"] = "ACTIVE"
    touch(r)
    return success_response(restaurant_dict(r))


@bp.route("/api/restaurants/<restaurant_id>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_restaurant(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")
    if r["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", "Restaurant must be ACTIVE to suspend")

    r["status"] = "SUSPENDED"
    touch(r)

    for o in orders.values():
        if o["restaurant_id"] == restaurant_id and o["status"] == "PLACED":
            o["status"] = "CANCELLED"
            if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
                o["payment_status"] = "VOIDED"
            touch(o)

    return success_response(restaurant_dict(r))


@bp.route("/api/restaurants/<restaurant_id>/reinstate", methods=["POST"])
@require_roles("PlatformAdmin")
def reinstate_restaurant(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")
    if r["status"] != "SUSPENDED":
        raise APIError("ERR_INVALID_STATE", "Restaurant must be SUSPENDED to reinstate")
    r["status"] = "ACTIVE"
    touch(r)
    return success_response(restaurant_dict(r))


@bp.route("/api/restaurants/<restaurant_id>/settle", methods=["POST"])
@require_roles("PlatformAdmin")
def settle_restaurant(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")
    r["pending_settlement_cents"] = 0
    touch(r)
    return success_response(restaurant_dict(r))
