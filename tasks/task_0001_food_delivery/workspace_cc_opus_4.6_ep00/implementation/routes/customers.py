from flask import Blueprint, request
from store import store
from models import make_versioned, serialize
from middleware import check_role_permission
from response import success_response
from errors import raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_VALIDATION

bp = Blueprint("customers", __name__)


@bp.route("/api/customers", methods=["POST"])
def create_customer():
    check_role_permission({"PlatformAdmin", "CustomerService"})
    data = request.get_json(force=True, silent=True) or {}

    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise_error(ERR_VALIDATION, "name is required")

    phone = data.get("phone")
    if not phone or not isinstance(phone, str):
        raise_error(ERR_VALIDATION, "phone is required")

    for c in store.customers.values():
        if c["phone"] == phone:
            raise_error(ERR_VALIDATION, "phone must be unique across all customers")

    address = data.get("address")
    if not address or not isinstance(address, str):
        raise_error(ERR_VALIDATION, "address is required")

    lat = data.get("lat")
    lng = data.get("lng")
    if lat is None or lng is None:
        raise_error(ERR_VALIDATION, "lat and lng are required")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise_error(ERR_VALIDATION, "lat and lng must be numbers")

    customer = make_versioned({
        "name": name,
        "phone": phone,
        "address": address,
        "lat": lat,
        "lng": lng,
        "credit_balance_cents": 0,
        "trust_score": 1.0,
    })
    store.customers[customer["id"]] = customer
    return success_response(serialize(customer), 201)


@bp.route("/api/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    check_role_permission({"PlatformAdmin", "Customer", "CustomerService"})
    customer = store.customers.get(customer_id)
    if not customer:
        raise_error(ERR_NOT_FOUND, "Customer not found")

    if request.user_role == "Customer" and request.user_id != customer_id:
        raise_error(ERR_FORBIDDEN, "Cannot read another customer's profile")

    return success_response(serialize(customer))
