"""Catalog and resource config endpoints: customers, packages, vehicle-size-rates,
addons, service-bays, mobile-units (PRD §3.1)."""
from flask import Blueprint, request

import auth
import db
from errors import err
from recordutil import base_versioned, base_catalog, sorted_by_creation
from response import object_response, array_response
from serialize import serialize, serialize_list
from validation import (
    get_body, require_str, require_enum, require_int, optional_bool, optional_int,
    parse_pagination, paginate, VEHICLE_SIZES, TIERS, ADDON_CODES,
)

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------- Customers
@bp.route("/detailing/customers", methods=["POST"])
def create_customer():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    body = get_body()
    email = require_str(body, "email")
    if "@" not in email:
        raise err("ERR_INVALID_REQUEST", "email must contain '@'")
    full_name = require_str(body, "full_name")
    if any(c["email"] == email for c in db.customers.values()):
        raise err("ERR_INVALID_REQUEST", "email must be unique")
    rec = base_versioned()
    rec.update({
        "email": email,
        "full_name": full_name,
        "membership_id": None,
        "loyalty_tier": "BRONZE",
        "chronological_lifetime_spend_cents": 0,
        "projected_lifetime_spend_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    rec = db.customers.get(cid)
    if not rec:
        raise err("ERR_NOT_FOUND", "customer not found")
    # A Customer may only read its own customer record.
    auth.require_owner(role, _uid(), cid)
    return object_response(serialize(rec))


@bp.route("/detailing/customers", methods=["GET"])
def list_customers():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    limit, offset = parse_pagination()
    rows = sorted_by_creation(list(db.customers.values()))
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


@bp.route("/detailing/customers/<cid>/appointments", methods=["GET"])
def list_customer_appointments(cid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    if cid not in db.customers:
        raise err("ERR_NOT_FOUND", "customer not found")
    auth.require_owner(role, _uid(), cid)
    limit, offset = parse_pagination()
    rows = sorted_by_creation([a for a in db.appointments.values()
                               if a["customer_id"] == cid])
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


@bp.route("/detailing/customers/<cid>/memberships", methods=["GET"])
def list_customer_memberships(cid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager"})
    if cid not in db.customers:
        raise err("ERR_NOT_FOUND", "customer not found")
    auth.require_owner(role, _uid(), cid)
    limit, offset = parse_pagination()
    rows = sorted_by_creation([m for m in db.memberships.values()
                               if m["customer_id"] == cid])
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


# ---------------------------------------------------------------- Packages
@bp.route("/detailing/packages", methods=["POST"])
def create_package():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    body = get_body()
    tier = require_enum(body, "tier", TIERS)
    base_price = require_int(body, "base_price_cents", gt=0)
    prep = require_int(body, "prep_minutes", minimum=0)
    service = require_int(body, "service_minutes", gt=0)
    cure = require_int(body, "cure_minutes", minimum=0)
    guarantee = require_int(body, "guarantee_days", minimum=0)
    if any(p["tier"] == tier for p in db.packages.values()):
        raise err("ERR_INVALID_REQUEST", "tier must be unique")
    rec = base_catalog()
    rec.update({
        "tier": tier,
        "base_price_cents": base_price,
        "prep_minutes": prep,
        "service_minutes": service,
        "cure_minutes": cure,
        "guarantee_days": guarantee,
    })
    db.packages[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/packages", methods=["GET"])
def list_packages():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    limit, offset = parse_pagination()
    rows = sorted_by_creation(list(db.packages.values()))
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


# ---------------------------------------------------------------- Vehicle size rates
@bp.route("/detailing/vehicle-size-rates", methods=["POST"])
def create_rate():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    body = get_body()
    size = require_enum(body, "vehicle_size", VEHICLE_SIZES)
    mult = require_int(body, "size_multiplier_bps", minimum=10000)
    if any(r["vehicle_size"] == size for r in db.vehicle_size_rates.values()):
        raise err("ERR_INVALID_REQUEST", "vehicle_size must be unique")
    rec = base_catalog()
    rec.update({"vehicle_size": size, "size_multiplier_bps": mult})
    db.vehicle_size_rates[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/vehicle-size-rates", methods=["GET"])
def list_rates():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    limit, offset = parse_pagination()
    rows = sorted_by_creation(list(db.vehicle_size_rates.values()))
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


# ---------------------------------------------------------------- Add-ons
@bp.route("/detailing/addons", methods=["POST"])
def create_addon():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    body = get_body()
    code = require_enum(body, "addon_code", ADDON_CODES)
    price = require_int(body, "price_cents", gt=0)
    extra = require_int(body, "extra_minutes", minimum=0)
    if any(a["addon_code"] == code for a in db.addons.values()):
        raise err("ERR_INVALID_REQUEST", "addon_code must be unique")
    rec = base_catalog()
    rec.update({"addon_code": code, "price_cents": price, "extra_minutes": extra})
    db.addons[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/addons", methods=["GET"])
def list_addons():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    limit, offset = parse_pagination()
    rows = sorted_by_creation(list(db.addons.values()))
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


# ---------------------------------------------------------------- Service bays
@bp.route("/detailing/service-bays", methods=["POST"])
def create_bay():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    body = get_body()
    bay_code = require_str(body, "bay_code")
    supports = optional_bool(body, "supports_ceramic", default=False)
    if any(b["bay_code"] == bay_code for b in db.service_bays.values()):
        raise err("ERR_INVALID_REQUEST", "bay_code must be unique")
    rec = base_versioned()
    rec.update({"bay_code": bay_code, "status": "AVAILABLE", "supports_ceramic": supports})
    db.service_bays[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/service-bays/<bid>", methods=["GET"])
def get_bay(bid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    rec = db.service_bays.get(bid)
    if not rec:
        raise err("ERR_NOT_FOUND", "service bay not found")
    return object_response(serialize(rec))


@bp.route("/detailing/service-bays", methods=["GET"])
def list_bays():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    limit, offset = parse_pagination()
    rows = sorted_by_creation(list(db.service_bays.values()))
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


@bp.route("/detailing/service-bays/<bid>/set-status", methods=["POST"])
def set_bay_status(bid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    rec = db.service_bays.get(bid)
    if not rec:
        raise err("ERR_NOT_FOUND", "service bay not found")
    body = get_body()
    status = require_enum(body, "status", {"AVAILABLE", "MAINTENANCE"})
    rec["status"] = status
    from domain import touch
    touch(rec)
    return object_response(serialize(rec))


# ---------------------------------------------------------------- Mobile units
@bp.route("/detailing/mobile-units", methods=["POST"])
def create_unit():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    body = get_body()
    unit_code = require_str(body, "unit_code")
    buffer = optional_int(body, "travel_buffer_minutes", default=30, minimum=0)
    if any(u["unit_code"] == unit_code for u in db.mobile_units.values()):
        raise err("ERR_INVALID_REQUEST", "unit_code must be unique")
    rec = base_versioned()
    rec.update({"unit_code": unit_code, "status": "AVAILABLE",
                "travel_buffer_minutes": buffer})
    db.mobile_units[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/mobile-units/<uid>", methods=["GET"])
def get_unit(uid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    rec = db.mobile_units.get(uid)
    if not rec:
        raise err("ERR_NOT_FOUND", "mobile unit not found")
    return object_response(serialize(rec))


@bp.route("/detailing/mobile-units", methods=["GET"])
def list_units():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    limit, offset = parse_pagination()
    rows = sorted_by_creation(list(db.mobile_units.values()))
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


def _uid():
    return request.headers.get("X-User-ID")
