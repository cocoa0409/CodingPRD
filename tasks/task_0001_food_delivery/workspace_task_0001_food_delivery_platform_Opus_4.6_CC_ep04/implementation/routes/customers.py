from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from models.customer import Customer
from response import success_response
from errors import raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_VALIDATION

bp = Blueprint("customers", __name__)


@bp.route("/api/customers", methods=["POST"])
@require_roles("PlatformAdmin", "CustomerService")
def create_customer():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    phone = data.get("phone")
    address = data.get("address")
    lat = data.get("lat")
    lng = data.get("lng")

    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise_error(ERR_VALIDATION, "Name is required.")
    if not phone or not isinstance(phone, str) or len(phone.strip()) == 0:
        raise_error(ERR_VALIDATION, "Phone is required.")
    if address is None:
        raise_error(ERR_VALIDATION, "Address is required.")
    if lat is None or lng is None:
        raise_error(ERR_VALIDATION, "lat and lng are required.")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise_error(ERR_VALIDATION, "lat and lng must be numbers.")

    for c in db.customers.values():
        if c.phone == phone:
            raise_error(ERR_VALIDATION, "Phone must be unique across all customers.")

    customer = Customer(name, phone, address, float(lat), float(lng))
    db.customers[customer.id] = customer
    return success_response(customer.to_dict(), 201)


@bp.route("/api/customers/<customer_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "CustomerService")
def get_customer(customer_id):
    c = db.customers.get(customer_id)
    if not c:
        raise_error(ERR_NOT_FOUND, "Customer not found.")
    if request.user_role == "Customer" and request.user_id != c.id:
        raise_error(ERR_FORBIDDEN, "Cannot view another customer's profile.")
    return success_response(c.to_dict())
