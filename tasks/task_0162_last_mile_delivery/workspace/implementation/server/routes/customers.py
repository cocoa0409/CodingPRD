"""Customer + Address endpoints."""
from flask import Blueprint

from .. import store
from ..auth import authed
from ..envelope import success_object
from ..errors import raise_error
from ..serializers import serialize_customer, serialize_address
from ..services.rolling import recompute_customer_rolling
from ._helpers import (
    check_version,
    get_json_body,
    is_email,
    is_phone,
    is_postal,
    require,
)


bp = Blueprint("customers", __name__)


@bp.post("/customers")
@authed(["Dispatcher"])
def create_customer(user_id, user_role):
    body = get_json_body()
    email = require(body, "email")
    full_name = require(body, "full_name")
    phone = require(body, "phone")
    driver_release_authorized = bool(body.get("driver_release_authorized", False))

    if not is_email(email):
        raise_error("ERR_REFERENCE_NOT_FOUND", "email must be valid RFC 5322")
    if not isinstance(full_name, str) or not full_name.strip():
        raise_error("ERR_REFERENCE_NOT_FOUND", "full_name required")
    if not is_phone(phone):
        raise_error("ERR_REFERENCE_NOT_FOUND", "phone must be E.164")

    with store.lock:
        # Email uniqueness
        for existing in store.customers.values():
            if existing.get("email") == email:
                raise_error("ERR_REFERENCE_NOT_FOUND", "email already exists")

        customer = {
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "default_address_id": None,
            "driver_release_authorized": driver_release_authorized,
            "redelivery_attempts_used_30d": 0,
        }
        store.stamp_create(customer)
        store.customers[customer["id"]] = customer
        return success_object(serialize_customer(customer), status=201)


@bp.get("/customers/<cid>")
@authed(["Customer", "Dispatcher", "ComplianceOfficer"])
def read_customer(user_id, user_role, cid):
    with store.lock:
        customer = store.customers.get(cid)
        if not customer:
            raise_error("ERR_NOT_FOUND", "customer not found")
        if user_role == "Customer" and customer["id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        # PRD §3.1: 'recomputed on demand when the customer record is read'.
        recompute_customer_rolling(customer)
        return success_object(serialize_customer(customer))


@bp.patch("/customers/<cid>")
@authed(["Customer", "Dispatcher"])
def update_customer(user_id, user_role, cid):
    with store.lock:
        customer = store.customers.get(cid)
        if not customer:
            raise_error("ERR_NOT_FOUND", "customer not found")
        if user_role == "Customer" and customer["id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        body = get_json_body()
        check_version(body, customer)
        if "full_name" in body:
            if not isinstance(body["full_name"], str) or not body["full_name"].strip():
                raise_error("ERR_REFERENCE_NOT_FOUND", "invalid full_name")
            customer["full_name"] = body["full_name"]
        if "phone" in body:
            if not is_phone(body["phone"]):
                raise_error("ERR_REFERENCE_NOT_FOUND", "invalid phone")
            customer["phone"] = body["phone"]
        if "driver_release_authorized" in body:
            customer["driver_release_authorized"] = bool(body["driver_release_authorized"])
        if "default_address_id" in body:
            new_addr_id = body["default_address_id"]
            if new_addr_id is not None:
                addr = store.addresses.get(new_addr_id)
                if not addr or addr["customer_id"] != customer["id"]:
                    raise_error("ERR_REFERENCE_NOT_FOUND", "default_address_id invalid")
            customer["default_address_id"] = new_addr_id
        store.stamp_update(customer)
        return success_object(serialize_customer(customer))


@bp.post("/customers/<cid>/addresses")
@authed(["Customer", "Dispatcher"])
def create_address(user_id, user_role, cid):
    with store.lock:
        customer = store.customers.get(cid)
        if not customer:
            raise_error("ERR_NOT_FOUND", "customer not found")
        if user_role == "Customer" and customer["id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        body = get_json_body()
        line1 = require(body, "line1")
        city = require(body, "city")
        postal_code = require(body, "postal_code")
        latitude = require(body, "latitude")
        longitude = require(body, "longitude")
        residential = bool(body.get("residential", True))

        if not isinstance(line1, str) or not line1.strip():
            raise_error("ERR_REFERENCE_NOT_FOUND", "invalid line1")
        if not isinstance(city, str) or not city.strip():
            raise_error("ERR_REFERENCE_NOT_FOUND", "invalid city")
        if not is_postal(postal_code):
            raise_error("ERR_REFERENCE_NOT_FOUND", "postal_code must be 5 digits")
        try:
            lat = float(latitude)
            lon = float(longitude)
        except Exception:
            raise_error("ERR_REFERENCE_NOT_FOUND", "lat/lon must be numbers")
        if lat < -90.0 or lat > 90.0:
            raise_error("ERR_REFERENCE_NOT_FOUND", "latitude out of range")
        if lon < -180.0 or lon > 180.0:
            raise_error("ERR_REFERENCE_NOT_FOUND", "longitude out of range")

        addr = {
            "customer_id": customer["id"],
            "line1": line1,
            "city": city,
            "postal_code": postal_code,
            "latitude": lat,
            "longitude": lon,
            "residential": residential,
        }
        store.stamp_lightweight_create(addr)
        store.addresses[addr["id"]] = addr
        # Note: do NOT auto-assign as default; PRD says default_address_id "may be updated"
        # via the customer update path once the address exists.
        return success_object(serialize_address(addr), status=201)
