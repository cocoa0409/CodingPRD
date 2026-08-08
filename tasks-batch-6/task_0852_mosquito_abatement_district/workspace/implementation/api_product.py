"""Pesticide stock ledger and the applicator roster."""
from flask import Blueprint

import calc
import store
import views
from common import (
    ALL_DISTRICT_READERS, ApiError, D, auth, created, get_body, ok,
    opt_bool, parse_date, q2, req_decimal, req_enum, req_int, req_present,
    req_string,
)

bp = Blueprint("product", __name__)

ACTIVE_INGREDIENTS = ("BTI", "METHOPRENE", "PERMETHRIN", "MALATHION", "NALED")
APPLICATION_METHODS = ("LARVICIDE", "ADULTICIDE", "AERIAL")
LICENSE_CATEGORIES = ("LARVICIDE_ONLY", "ADULTICIDE", "AERIAL")
APPLICATOR_STATUSES = ("ACTIVE", "SUSPENDED")


@bp.post("/pesticide-products")
def create_product():
    auth(("DistrictAdmin",))
    body = get_body()
    name = req_string(body, "name", 1, 120)
    epa_reg_no = req_string(body, "epa_reg_no", 1, 32)
    active_ingredient = req_enum(body, "active_ingredient", ACTIVE_INGREDIENTS)
    application_method = req_enum(body, "application_method", APPLICATION_METHODS)
    label_rate = req_decimal(body, "label_rate_ml_per_acre", minimum=0, exclusive_min=True)
    reentry_interval_hours = req_int(body, "reentry_interval_hours", minimum=0)
    cost_cents_per_liter = req_int(body, "cost_cents_per_liter", minimum=0)
    received_total_ml = req_decimal(body, "received_total_ml", minimum=0, exclusive_min=True)
    restricted_use = opt_bool(body, "restricted_use", default=False)

    for existing in store.PESTICIDE_PRODUCTS.values():
        if existing["epa_reg_no"] == epa_reg_no:
            raise ApiError("ERR_DUPLICATE_RESOURCE", 409,
                           "EPA registration number '%s' is already in use." % epa_reg_no)

    received_total_ml = q2(received_total_ml)
    record = store.new_record()
    record.update({
        "name": name,
        "epa_reg_no": epa_reg_no,
        "active_ingredient": active_ingredient,
        "application_method": application_method,
        "label_rate_ml_per_acre": label_rate,
        "reentry_interval_hours": reentry_interval_hours,
        "cost_cents_per_liter": cost_cents_per_liter,
        "restricted_use": restricted_use,
        "received_total_ml": received_total_ml,
        "on_hand_ml": received_total_ml,
        "committed_ml": q2(0),
        "applied_ml": q2(0),
    })
    store.PESTICIDE_PRODUCTS[record["id"]] = record
    return created(views.product_view(record))


@bp.get("/pesticide-products/<product_id>")
def get_product(product_id):
    auth(ALL_DISTRICT_READERS)
    product = store.fetch("PesticideProduct", product_id)
    return ok(views.product_view(product))


@bp.post("/pesticide-products/<product_id>/adjustments")
def adjust_product(product_id):
    auth(("DistrictAdmin",))
    product = store.fetch("PesticideProduct", product_id)
    body = get_body()
    delta_ml = req_decimal(body, "delta_ml")
    req_string(body, "reason", 1, 500)
    expected_version = req_int(body, "expected_product_version")

    if expected_version != product["version"]:
        raise ApiError("ERR_STALE_PRODUCT_VERSION", 412,
                       "expected_product_version does not match.")

    delta_ml = q2(delta_ml)
    new_on_hand = q2(D(product["on_hand_ml"]) + delta_ml)
    new_received = q2(D(product["received_total_ml"]) + delta_ml)
    if new_on_hand < D("0.00") or new_received <= D("0.00"):
        raise ApiError("ERR_INVENTORY_NEGATIVE", 422,
                       "The adjustment would break the inventory partition.")

    product["on_hand_ml"] = new_on_hand
    product["received_total_ml"] = new_received
    store.touch(product)
    return ok(views.product_view(product))


@bp.post("/applicators")
def create_applicator():
    auth(("DistrictAdmin",))
    body = get_body()
    full_name = req_string(body, "full_name", 1, 120)
    license_no = req_string(body, "license_no", 1, 32)
    license_category = req_enum(body, "license_category", LICENSE_CATEGORIES)
    license_expires_on = parse_date(req_present(body, "license_expires_on"),
                                    "license_expires_on")

    for existing in store.APPLICATORS.values():
        if existing["license_no"] == license_no:
            raise ApiError("ERR_DUPLICATE_RESOURCE", 409,
                           "Licence number '%s' is already in use." % license_no)

    record = store.new_record()
    record.update({
        "full_name": full_name,
        "license_no": license_no,
        "license_category": license_category,
        "license_expires_on": license_expires_on,
        "status": "ACTIVE",
        "assigned_route_count": 0,
    })
    store.APPLICATORS[record["id"]] = record
    return created(views.applicator_view(record))


@bp.get("/applicators/<applicator_id>")
def get_applicator(applicator_id):
    auth(ALL_DISTRICT_READERS)
    applicator = store.fetch("Applicator", applicator_id)
    return ok(views.applicator_view(applicator))


@bp.post("/applicators/<applicator_id>/status")
def set_applicator_status(applicator_id):
    auth(("DistrictAdmin",))
    applicator = store.fetch("Applicator", applicator_id)
    body = get_body()
    status = req_enum(body, "status", APPLICATOR_STATUSES)
    applicator["status"] = status
    store.touch(applicator)
    return ok(views.applicator_view(applicator))
