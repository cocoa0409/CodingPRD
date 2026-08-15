"""Vaccine products and lots (PRD §3.2, §3.4)."""

from flask import Blueprint, request

import db
from errors import invalid_request, ApiError, ERR_UNIT_SITE_MISMATCH
from middleware import get_auth, ALL_ROLES, ROLE_COMPLIANCE_AUDITOR, ROLE_VACCINE_MANAGER
from response import success_object, paginate
from services.validate import (
    require_body, require_string, require_int, require_bool, require_enum,
    require_date, get_or_404,
    ENUM_PRESENTATION, ENUM_STORAGE_REQUIREMENT, ENUM_STOCK_TYPE,
)

bp = Blueprint("products_lots", __name__)


# ------------------------------ Products -----------------------------------

def serialize_product(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "ndc_code": p["ndc_code"],
        "display_name": p["display_name"],
        "presentation": p["presentation"],
        "doses_per_container": p["doses_per_container"],
        "vfc_program_eligible": p["vfc_program_eligible"],
        "storage_requirement": p["storage_requirement"],
    }


@bp.route("/vaccine-products", methods=["POST"])
def create_product():
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    body = require_body(request.get_json(silent=True))
    ndc_code = require_string(body, "ndc_code")
    display_name = require_string(body, "display_name")
    presentation = require_enum(body, "presentation", ENUM_PRESENTATION)
    doses_per_container = require_int(body, "doses_per_container", minimum=1)
    vfc_program_eligible = require_bool(body, "vfc_program_eligible")
    storage_requirement = require_enum(body, "storage_requirement", ENUM_STORAGE_REQUIREMENT)

    now = db.now_ts()
    product = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "ndc_code": ndc_code,
        "display_name": display_name,
        "presentation": presentation,
        "doses_per_container": doses_per_container,
        "vfc_program_eligible": vfc_program_eligible,
        "storage_requirement": storage_requirement,
    }
    db.vaccine_products[product["id"]] = product
    return success_object(serialize_product(product), 201)


def _parse_bool_query(raw):
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


@bp.route("/vaccine-products", methods=["GET"])
def list_products():
    get_auth(ALL_ROLES)
    items = list(db.vaccine_products.values())
    eligible = _parse_bool_query(request.args.get("vfc_program_eligible"))
    if eligible is not None:
        items = [p for p in items if p["vfc_program_eligible"] == eligible]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return paginate([serialize_product(p) for p in items], request.args)


@bp.route("/vaccine-products/<product_id>", methods=["GET"])
def get_product(product_id):
    get_auth(ALL_ROLES)
    product = get_or_404(db.vaccine_products, product_id, "vaccine product")
    return success_object(serialize_product(product))


# -------------------------------- Lots -------------------------------------

def serialize_lot(lot):
    return {
        "id": lot["id"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
        "provider_site_id": lot["provider_site_id"],
        "storage_unit_id": lot["storage_unit_id"],
        "vaccine_product_id": lot["vaccine_product_id"],
        "lot_number": lot["lot_number"],
        "stock_type": lot["stock_type"],
        "quantity_on_hand": lot["quantity_on_hand"],
        "quantity_borrowed_in": lot["quantity_borrowed_in"],
        "expires_on": lot["expires_on"],
        "status": lot["status"],
        "received_via_order_id": lot["received_via_order_id"],
    }


@bp.route("/provider-sites/<site_id>/lots", methods=["POST"])
def create_lot(site_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    storage_unit_id = require_string(body, "storage_unit_id")
    vaccine_product_id = require_string(body, "vaccine_product_id")
    lot_number = require_string(body, "lot_number")
    stock_type = require_enum(body, "stock_type", ENUM_STOCK_TYPE)
    quantity_on_hand = require_int(body, "quantity_on_hand", minimum=0)
    expires_on_raw, expires_on_date = require_date(body, "expires_on")

    # Existence of referenced body ids
    unit = get_or_404(db.storage_units, storage_unit_id, "storage unit")
    product = get_or_404(db.vaccine_products, vaccine_product_id, "vaccine product")

    # Referential: unit must belong to this site
    if unit["provider_site_id"] != site["id"]:
        raise ApiError(ERR_UNIT_SITE_MISMATCH,
                       "Storage unit does not belong to the referenced provider site", 422)

    # Manual registration accepts only PRIVATE stock
    if stock_type != "PRIVATE":
        raise invalid_request("Manual lot creation only accepts stock_type=PRIVATE")

    now = db.now_ts()
    lot = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "storage_unit_id": unit["id"],
        "vaccine_product_id": product["id"],
        "lot_number": lot_number,
        "stock_type": stock_type,
        "quantity_on_hand": quantity_on_hand,
        "quantity_borrowed_in": 0,
        "expires_on": expires_on_raw,
        "_expires_on_date": expires_on_date,
        "status": "AVAILABLE",
        "received_via_order_id": None,
        "expired_written_off_doses": 0,
    }
    db.lots[lot["id"]] = lot
    return success_object(serialize_lot(lot), 201)


def _filter_lots(items, args):
    f_site = args.get("provider_site_id")
    f_unit = args.get("storage_unit_id")
    f_product = args.get("vaccine_product_id")
    f_order = args.get("received_via_order_id")
    f_stock = args.get("stock_type")
    f_status = args.get("status")
    if f_site is not None:
        items = [l for l in items if l["provider_site_id"] == f_site]
    if f_unit is not None:
        items = [l for l in items if l["storage_unit_id"] == f_unit]
    if f_product is not None:
        items = [l for l in items if l["vaccine_product_id"] == f_product]
    if f_order is not None:
        items = [l for l in items if l["received_via_order_id"] == f_order]
    if f_stock is not None:
        items = [l for l in items if l["stock_type"] == f_stock]
    if f_status is not None:
        items = [l for l in items if l["status"] == f_status]
    return items


@bp.route("/provider-sites/<site_id>/lots", methods=["GET"])
def list_lots(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [l for l in db.lots.values() if l["provider_site_id"] == site["id"]]
    items = _filter_lots(items, request.args)
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return paginate([serialize_lot(l) for l in items], request.args)


@bp.route("/lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    get_auth(ALL_ROLES)
    lot = get_or_404(db.lots, lot_id, "lot")
    return success_object(serialize_lot(lot))


@bp.route("/lots", methods=["GET"])
def list_lots_global():
    get_auth(ALL_ROLES)
    items = list(db.lots.values())
    items = _filter_lots(items, request.args)
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return paginate([serialize_lot(l) for l in items], request.args)
