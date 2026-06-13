"""Customer + MeasurementProfile endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err, ERR_INVALID_REQUEST, ERR_FORBIDDEN
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers
from services.calculations import recommended_size

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    require_role(role, {"StoreClerk", "Customer"})
    body = helpers.get_json_body()

    full_name = helpers.as_str(body, "full_name")
    email = helpers.as_str(body, "email")
    # email must be unique across all customers (well-formedness, priority 4).
    for c in db.customers.values():
        if c["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email already in use")

    customer = {
        "full_name": full_name,
        "email": email,
    }
    db.stamp_create(customer)
    db.customers[customer["id"]] = customer
    return success(views.customer_view(customer), status=201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    customer = helpers.find("Customer", cid)
    # A Customer may only act on their own customer resource (ownership).
    if role == "Customer" and user_id != customer["id"]:
        raise err(ERR_FORBIDDEN, "Customer may only access their own account")
    return success(views.customer_view(customer))


@bp.route("/customers/<cid>/measurement-profiles", methods=["POST"])
def create_measurement_profile(cid):
    user_id, role = authenticate()
    require_role(role, {"StoreClerk", "Customer"})
    customer = helpers.find("Customer", cid)
    if role == "Customer" and user_id != customer["id"]:
        raise err(ERR_FORBIDDEN, "Customer may only create profiles for themselves")
    body = helpers.get_json_body()

    chest_cm = helpers.as_int_min(body, "chest_cm", 1)
    waist_cm = helpers.as_int_min(body, "waist_cm", 1)
    inseam_cm = helpers.as_int_min(body, "inseam_cm", 1)

    profile = {
        "customer_id": cid,
        "chest_cm": chest_cm,
        "waist_cm": waist_cm,
        "inseam_cm": inseam_cm,
        "recommended_size_code": recommended_size(chest_cm),
    }
    db.stamp_create(profile)
    db.measurement_profiles[profile["id"]] = profile
    return success(views.measurement_profile_view(profile), status=201)


@bp.route("/customers/<cid>/measurement-profiles", methods=["GET"])
def list_measurement_profiles(cid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    customer = helpers.find("Customer", cid)
    if role == "Customer" and user_id != customer["id"]:
        raise err(ERR_FORBIDDEN, "Customer may only list their own profiles")
    limit, offset = helpers.parse_pagination()
    records = [m for m in db.measurement_profiles.values() if m["customer_id"] == cid]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success(
        [views.measurement_profile_view(m) for m in page], limit, offset, total
    )


@bp.route("/measurement-profiles/<mid>", methods=["GET"])
def get_measurement_profile(mid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    profile = helpers.find("MeasurementProfile", mid)
    if role == "Customer" and user_id != profile["customer_id"]:
        raise err(ERR_FORBIDDEN, "Customer may only access their own profiles")
    return success(views.measurement_profile_view(profile))
