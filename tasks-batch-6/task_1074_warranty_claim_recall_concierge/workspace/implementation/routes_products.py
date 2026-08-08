"""Products: register, archive, reads."""
from flask import Blueprint, request

import store
import serializers as S
from calc import recompute_active_claim_count, ACTIVE_CLAIM_STATES
from store import touch
from common import (
    bad_request, get_body, new_common, ok, ok_list, paginate, require_auth,
    require_int, require_str, require_household_member, resolve_or_404,
)
from errors import ApiError
from util import parse_dt

bp_products = Blueprint("products", __name__)

PROD_READ_ROLES = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "ManufacturerAgent", "PlatformAdmin"]


@bp_products.route("/products", methods=["POST"])
def create_product():
    role, uid = require_auth(["HouseholdOwner", "HouseholdMember"])
    body = get_body()

    household_id = body.get("household_id")
    manufacturer_id = body.get("manufacturer_id")

    # existence + membership (membership precedes non-household existence)
    if household_id is not None:
        if household_id not in store.households:
            raise ApiError("ERR_NOT_FOUND")
        require_household_member(uid, household_id)
    if manufacturer_id is not None and manufacturer_id not in store.manufacturers:
        raise ApiError("ERR_NOT_FOUND")

    # well-formedness
    if not isinstance(household_id, str) or household_id == "":
        raise bad_request("household_id is required.")
    if not isinstance(manufacturer_id, str) or manufacturer_id == "":
        raise bad_request("manufacturer_id is required.")
    model_number = require_str(body, "model_number")
    serial_number = require_int(body, "serial_number")
    purchase_date = body.get("purchase_date")
    if not isinstance(purchase_date, str):
        raise bad_request("purchase_date is required.")
    try:
        parse_dt(purchase_date)
    except (ValueError, TypeError):
        raise bad_request("purchase_date must be a valid ISO 8601 timestamp.")
    purchase_price_cents = require_int(body, "purchase_price_cents")
    warranty_months = require_int(body, "warranty_months")

    rec = new_common()
    rec.update({
        "household_id": household_id,
        "manufacturer_id": manufacturer_id,
        "model_number": model_number,
        "serial_number": serial_number,
        "purchase_date": purchase_date,
        "purchase_price_cents": purchase_price_cents,
        "warranty_months": warranty_months,
        "registration_status": "REGISTERED",
        "recall_status": "NONE",
    })
    store.products[rec["id"]] = rec
    return ok(S.product(rec), 201)


@bp_products.route("/products/<pid>/archive", methods=["POST"])
def archive_product(pid):
    role, uid = require_auth(["HouseholdOwner"])
    product = resolve_or_404(store.products, pid)
    require_household_member(uid, product["household_id"], require_owner=True)

    if product["registration_status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE")
    for c in store.claims.values():
        if c["product_id"] == pid and c["status"] in ACTIVE_CLAIM_STATES:
            raise ApiError("ERR_PRODUCT_HAS_ACTIVE_CLAIM")

    product["registration_status"] = "ARCHIVED"
    touch(product)
    return ok(S.product(product))


@bp_products.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    require_auth(PROD_READ_ROLES)
    rec = resolve_or_404(store.products, pid)
    return ok(S.product(rec))


@bp_products.route("/products", methods=["GET"])
def list_products():
    require_auth(PROD_READ_ROLES)
    hid = request.args.get("household_id")
    mid = request.args.get("manufacturer_id")
    records = list(store.products.values())
    if hid is not None:
        records = [p for p in records if p["household_id"] == hid]
    if mid is not None:
        records = [p for p in records if p["manufacturer_id"] == mid]
    items, pagination = paginate(records, S.product)
    return ok_list(items, pagination)
