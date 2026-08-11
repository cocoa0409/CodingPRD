"""Mistint inventory: listings with decaying prices, sale, write-off."""
from flask import Blueprint, request

import db
import services as svc
from authz import require_roles
from calc import mistint_initial_list_price
from envelope import ok_object, ok_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_VALIDATION,
)
from serializers import ser_mistint, sorted_rows
from validate import body_json, req_int, pagination_params, query_enum_filter

bp = Blueprint("mistint", __name__)

READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "Contractor"]
LISTING_STATUS = {"LISTED", "SOLD", "WRITTEN_OFF"}


def _get_listing(listing_id):
    m = db.mistint_listings.get(listing_id)
    if m is None:
        raise_err(ERR_NOT_FOUND, "mistint listing %s not found" % listing_id)
    return m


@bp.post("/mistint-listings")
def create_listing():
    require_roles(["StoreAssociate"])
    data = body_json()
    product_id = data.get("product_id")
    formula_id = data.get("formula_id")
    if isinstance(product_id, str) and product_id not in db.products:
        raise_err(ERR_REFERENCE_NOT_FOUND, "product_id %s not found" % product_id)
    if formula_id is not None and isinstance(formula_id, str) and formula_id not in db.tint_formulas:
        raise_err(ERR_REFERENCE_NOT_FOUND, "formula_id %s not found" % formula_id)
    if not isinstance(product_id, str):
        raise_err(ERR_VALIDATION, "field 'product_id' is required and must be a string")
    if formula_id is not None and not isinstance(formula_id, str):
        raise_err(ERR_VALIDATION, "field 'formula_id' must be a string or null")
    quantity = req_int(data, "quantity", minimum=1)
    cost_basis = req_int(data, "cost_basis_cents", minimum=0)
    m = svc.stamp_new({
        "product_id": product_id,
        "formula_id": formula_id,
        "quantity": quantity,
        "cost_basis_cents": cost_basis,
        "list_price_cents": mistint_initial_list_price(cost_basis),
        "status": "LISTED",
        "sold_price_cents": None,
        "sold_to_contractor_account_id": None,
    })
    db.mistint_listings[m["id"]] = m
    return ok_object(ser_mistint(m), 201)


@bp.get("/mistint-listings")
def list_listings():
    require_roles(READERS)
    limit, offset = pagination_params()
    status_filter = query_enum_filter("status", LISTING_STATUS)
    product_filter = request.args.get("product_id")
    formula_filter = request.args.get("formula_id")
    sold_to_filter = request.args.get("sold_to_contractor_account_id")
    rows = list(db.mistint_listings.values())
    if status_filter is not None:
        rows = [m for m in rows if m["status"] == status_filter]
    if product_filter is not None:
        rows = [m for m in rows if m["product_id"] == product_filter]
    if formula_filter is not None:
        rows = [m for m in rows if m["formula_id"] == formula_filter]
    if sold_to_filter is not None:
        rows = [m for m in rows if m["sold_to_contractor_account_id"] == sold_to_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_mistint(m) for m in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/mistint-listings/<listing_id>")
def get_listing(listing_id):
    require_roles(READERS)
    return ok_object(ser_mistint(_get_listing(listing_id)))


@bp.post("/mistint-listings/<listing_id>/mark-sold")
def mark_sold(listing_id):
    require_roles(["StoreAssociate"])
    m = _get_listing(listing_id)
    data = body_json()
    sold_to = data.get("sold_to_contractor_account_id")
    if sold_to is not None:
        if not isinstance(sold_to, str):
            raise_err(ERR_REFERENCE_NOT_FOUND,
                      "sold_to_contractor_account_id must be a string or null")
        if sold_to not in db.contractor_accounts:
            raise_err(ERR_REFERENCE_NOT_FOUND,
                      "sold_to_contractor_account_id %s not found" % sold_to)
    if m["status"] != "LISTED":
        raise_err(ERR_INVALID_STATE, "listing is not LISTED")
    m["sold_price_cents"] = svc.mistint_price_now(m)
    m["sold_to_contractor_account_id"] = sold_to
    m["status"] = "SOLD"
    svc.bump(m)
    return ok_object(ser_mistint(m))


@bp.post("/mistint-listings/<listing_id>/write-off")
def write_off(listing_id):
    require_roles(["StoreManager"])
    m = _get_listing(listing_id)
    if m["status"] != "LISTED":
        raise_err(ERR_INVALID_STATE, "listing is not LISTED")
    m["status"] = "WRITTEN_OFF"
    svc.bump(m)
    return ok_object(ser_mistint(m))
