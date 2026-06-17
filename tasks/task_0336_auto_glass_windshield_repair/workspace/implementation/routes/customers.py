"""Customer + Vehicle CRUD and reverse-lookup endpoints (PRD 3.1)."""
from flask import Blueprint, g

import db
import errors
import response
import validation as V
from errors import ApiError
from middleware import require_roles
from services import helpers as H

bp = Blueprint("customers", __name__)

US_STATE_RE_LEN = 2


def _validate_state(code):
    if not isinstance(code, str) or len(code) != 2 or not code.isalpha() or code != code.upper():
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "service_address_state must be a 2-letter uppercase US state code.")
    return code


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
@require_roles("ServiceAdvisor", "ShopManager")
def create_customer():
    body = V.get_json()
    full_name = V.require_str(body, "full_name")
    email = V.require_str(body, "email")
    phone = V.opt_str(body, "phone")
    state_raw = V.require_str(body, "service_address_state")
    _validate_state(state_raw)

    # email uniqueness (ERR_DUPLICATE, business constraint priority 17)
    for c in db.customers.values():
        if c["email"] == email:
            raise ApiError(errors.ERR_DUPLICATE, 409, "Customer email already exists.")

    cust = db.stamp_new({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "service_address_state": state_raw,
    })
    db.customers[cust["id"]] = cust
    return response.success(H.view(cust), 201)


@bp.route("/customers/<cid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def get_customer(cid):
    cust = H.get_customer(cid)
    H.enforce_customer_owns(cust["id"])
    return response.success(H.view(cust))


@bp.route("/customers/<cid>/vehicles", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def list_customer_vehicles(cid):
    cust = H.get_customer(cid)
    H.enforce_customer_owns(cust["id"])
    limit, offset = V.parse_pagination()
    items = [v for v in db.vehicles.values() if v["customer_id"] == cid]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


@bp.route("/customers/<cid>/work-orders", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def list_customer_work_orders(cid):
    cust = H.get_customer(cid)
    H.enforce_customer_owns(cust["id"])
    limit, offset = V.parse_pagination()
    items = [w for w in db.work_orders.values() if w["customer_id"] == cid]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
@bp.route("/vehicles", methods=["POST"])
@require_roles("ServiceAdvisor", "ShopManager")
def create_vehicle():
    body = V.get_json()
    # Existence of FK before field validation (PRD 2.5): customer_id must exist.
    customer_id = V.require_str(body, "customer_id")
    H.get_customer(customer_id)

    vin = V.require_str(body, "vin")
    make = V.require_str(body, "make")
    model = V.require_str(body, "model")
    model_year = V.require_int(body, "model_year")
    glass_part_number = V.require_str(body, "glass_part_number")
    adas_equipped = V.opt_bool(body, "adas_equipped", False)

    if len(vin) != 17:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "vin must be exactly 17 characters.")
    if model_year < 1980 or model_year > 2027:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "model_year must be between 1980 and 2027.")

    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise ApiError(errors.ERR_DUPLICATE, 409, "Vehicle VIN already exists.")

    veh = db.stamp_new({
        "customer_id": customer_id,
        "vin": vin,
        "make": make,
        "model": model,
        "model_year": model_year,
        "adas_equipped": adas_equipped,
        "glass_part_number": glass_part_number,
    })
    db.vehicles[veh["id"]] = veh
    return response.success(H.view(veh), 201)


@bp.route("/vehicles/<vid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def get_vehicle(vid):
    veh = H.get_vehicle(vid)
    H.enforce_customer_owns(veh["customer_id"])
    return response.success(H.view(veh))


@bp.route("/vehicles/<vid>/work-orders", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def list_vehicle_work_orders(vid):
    veh = H.get_vehicle(vid)
    H.enforce_customer_owns(veh["customer_id"])
    limit, offset = V.parse_pagination()
    items = [w for w in db.work_orders.values() if w["vehicle_id"] == vid]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)
