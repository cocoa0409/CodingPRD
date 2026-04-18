from flask import Blueprint, request
from auth import require_roles, check_ownership
from errors import APIError
from models import customers, versioned_resource_base
from response_envelope import success_response

bp = Blueprint("customers", __name__)


def customer_dict(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "phone": c["phone"],
        "address": c["address"],
        "lat": c["lat"],
        "lng": c["lng"],
        "credit_balance_cents": c["credit_balance_cents"],
        "trust_score": c["trust_score"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/api/customers", methods=["POST"])
@require_roles("PlatformAdmin", "CustomerService")
def create_customer():
    data = request.get_json(force=True, silent=True) or {}

    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise APIError("ERR_VALIDATION", "name is required")

    phone = data.get("phone")
    if not phone or not isinstance(phone, str):
        raise APIError("ERR_VALIDATION", "phone is required")

    for c in customers.values():
        if c["phone"] == phone:
            raise APIError("ERR_VALIDATION", "phone must be unique across all customers")

    address = data.get("address")
    if not address or not isinstance(address, str):
        raise APIError("ERR_VALIDATION", "address is required")

    lat = data.get("lat")
    lng = data.get("lng")
    if lat is None or lng is None:
        raise APIError("ERR_VALIDATION", "lat and lng are required")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise APIError("ERR_VALIDATION", "lat and lng must be numbers")

    c = versioned_resource_base()
    c.update({
        "name": name,
        "phone": phone,
        "address": address,
        "lat": float(lat),
        "lng": float(lng),
        "credit_balance_cents": 0,
        "trust_score": 1.0,
    })

    customers[c["id"]] = c
    return success_response(customer_dict(c), 201)


@bp.route("/api/customers/<customer_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "CustomerService")
def get_customer(customer_id):
    c = customers.get(customer_id)
    if not c:
        raise APIError("ERR_NOT_FOUND", "Customer not found")

    check_ownership(customer_id, request.user_id, request.user_role, ["Customer"])

    return success_response(customer_dict(c))
