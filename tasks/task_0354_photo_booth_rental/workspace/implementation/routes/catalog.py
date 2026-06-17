"""Catalog & inventory: booth models, packages, booths, attendants, add-ons
(PRD §3.1)."""
from flask import Blueprint

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
import helpers
from services.serialize import plain_out, package_out, addon_out

bp = Blueprint("catalog", __name__)

BOOTH_TYPES = {"OPEN_AIR", "ENCLOSED", "MIRROR", "ROAMING_360"}
BOOTH_STATUSES = {"AVAILABLE", "MAINTENANCE", "RETIRED"}
ATTENDANT_STATUSES = {"AVAILABLE", "ON_LEAVE", "INACTIVE"}
ADDON_CODES = {"PROPS", "BACKDROP", "ATTENDANT", "ALBUM"}


# ---------------- Booth Models ----------------
@bp.route("/booth-models", methods=["POST"])
def create_booth_model():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = helpers.get_json()
    name = helpers.require_string(body, "name")
    booth_type = helpers.require_enum(body, "booth_type", BOOTH_TYPES)
    footprint = helpers.require_int(body, "footprint_sqft", minimum=1)
    max_prints = helpers.require_int(body, "max_prints_per_hour", minimum=0)
    active = helpers.require_bool(body, "active", True)

    rec = db.common_create()
    rec.update({
        "name": name,
        "booth_type": booth_type,
        "footprint_sqft": footprint,
        "max_prints_per_hour": max_prints,
        "active": active,
    })
    db.booth_models[rec["id"]] = rec
    return success(plain_out(rec), 201)


@bp.route("/booth-models/<bm_id>", methods=["GET"])
def get_booth_model(bm_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "OperationsManager", "Customer"})
    rec = db.booth_models.get(bm_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Booth model not found.")
    return success(plain_out(rec), 200)


# ---------------- Packages ----------------
@bp.route("/packages", methods=["POST"])
def create_package():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = helpers.get_json()
    booth_model_id = helpers.require_string(body, "booth_model_id")
    name = helpers.require_string(body, "name")
    # Existence (priority 10) before deeper well-formedness of numbers is fine;
    # but PRD §2.9 puts existence before well-formedness. Validate FK now.
    if booth_model_id not in db.booth_models:
        raise err(errors.ERR_NOT_FOUND, "Booth model not found.")
    base_price = helpers.require_money(body, "base_price", minimum=0)
    included_hours = helpers.require_int(body, "included_hours", minimum=1)
    included_prints = helpers.require_int(body, "included_prints", minimum=0)
    overtime = helpers.require_money(body, "overtime_rate_per_hour", minimum=0)
    idle = helpers.require_money(body, "idle_rate_per_hour", minimum=0)
    overage = helpers.require_money(body, "overage_print_rate", minimum=0)
    active = helpers.require_bool(body, "active", True)

    rec = db.common_create()
    rec.update({
        "booth_model_id": booth_model_id,
        "name": name,
        "base_price": base_price,
        "included_hours": included_hours,
        "included_prints": included_prints,
        "overtime_rate_per_hour": overtime,
        "idle_rate_per_hour": idle,
        "overage_print_rate": overage,
        "active": active,
    })
    db.packages[rec["id"]] = rec
    return success(package_out(rec), 201)


@bp.route("/packages/<pkg_id>", methods=["GET"])
def get_package(pkg_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "OperationsManager", "Customer"})
    rec = db.packages.get(pkg_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Package not found.")
    return success(package_out(rec), 200)


@bp.route("/packages", methods=["GET"])
def list_packages():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "OperationsManager", "Customer"})
    limit, offset = helpers.pagination_params()
    from flask import request
    model_filter = request.args.get("booth_model_id")
    recs = list(db.packages.values())
    if model_filter is not None:
        recs = [r for r in recs if r["booth_model_id"] == model_filter]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([package_out(r) for r in window], limit, offset, total)


# ---------------- Booths ----------------
@bp.route("/booths", methods=["POST"])
def create_booth():
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    body = helpers.get_json()
    booth_model_id = helpers.require_string(body, "booth_model_id")
    asset_tag = helpers.require_string(body, "asset_tag")
    status = helpers.optional_enum(body, "status", BOOTH_STATUSES, "AVAILABLE")
    if booth_model_id not in db.booth_models:
        raise err(errors.ERR_NOT_FOUND, "Booth model not found.")
    # Uniqueness (priority 21).
    for b in db.booths.values():
        if b["asset_tag"] == asset_tag:
            raise err(errors.ERR_DUPLICATE_KEY, "Booth asset_tag already in use.")

    rec = db.common_create()
    rec.update({
        "booth_model_id": booth_model_id,
        "asset_tag": asset_tag,
        "status": status,
    })
    db.booths[rec["id"]] = rec
    return success(plain_out(rec), 201)


@bp.route("/booths/<booth_id>", methods=["GET"])
def get_booth(booth_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin"})
    rec = db.booths.get(booth_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Booth not found.")
    return success(plain_out(rec), 200)


@bp.route("/booths", methods=["GET"])
def list_booths():
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin"})
    limit, offset = helpers.pagination_params()
    from flask import request
    model_filter = request.args.get("booth_model_id")
    recs = list(db.booths.values())
    if model_filter is not None:
        recs = [r for r in recs if r["booth_model_id"] == model_filter]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([plain_out(r) for r in window], limit, offset, total)


@bp.route("/booths/<booth_id>", methods=["PATCH"])
def patch_booth(booth_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = db.booths.get(booth_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Booth not found.")
    body = helpers.get_json()
    status = helpers.require_enum(body, "status", BOOTH_STATUSES)
    rec["status"] = status
    db.touch(rec)
    return success(plain_out(rec), 200)


# ---------------- Attendants ----------------
@bp.route("/attendants", methods=["POST"])
def create_attendant():
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    body = helpers.get_json()
    full_name = helpers.require_string(body, "full_name")
    status = helpers.optional_enum(body, "status", ATTENDANT_STATUSES, "AVAILABLE")

    rec = db.common_create()
    rec.update({"full_name": full_name, "status": status})
    db.attendants[rec["id"]] = rec
    return success(plain_out(rec), 201)


@bp.route("/attendants/<att_id>", methods=["GET"])
def get_attendant(att_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin"})
    rec = db.attendants.get(att_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Attendant not found.")
    return success(plain_out(rec), 200)


# ---------------- Add-ons ----------------
@bp.route("/add-ons", methods=["POST"])
def create_addon():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = helpers.get_json()
    code = helpers.require_enum(body, "code", ADDON_CODES)
    name = helpers.require_string(body, "name")
    unit_price = helpers.require_money(body, "unit_price", minimum=0)
    requires_attendant = helpers.require_bool(body, "requires_attendant", False)
    max_qty = helpers.optional_int(body, "max_qty", 1, minimum=1)

    rec = db.common_create()
    rec.update({
        "code": code,
        "name": name,
        "unit_price": unit_price,
        "requires_attendant": requires_attendant,
        "max_qty": max_qty,
    })
    db.add_ons[rec["id"]] = rec
    return success(addon_out(rec), 201)


@bp.route("/add-ons/<addon_id>", methods=["GET"])
def get_addon(addon_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "OperationsManager", "Customer"})
    rec = db.add_ons.get(addon_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Add-on not found.")
    return success(addon_out(rec), 200)
