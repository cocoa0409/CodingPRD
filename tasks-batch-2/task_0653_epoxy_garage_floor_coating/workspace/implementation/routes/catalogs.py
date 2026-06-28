"""Catalog entities: CoatingSystem, ColorOption, FinancingPlan, Crew
(SCAFFOLD §1.5 / PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.common import (get_body, new_row, parse_pagination, paginate,
                             require_bool, require_int, require_str, require_enum)

bp = Blueprint("catalogs", __name__)

ALL_ROLES = {"PlatformAdmin", "SalesRep", "Scheduler", "WarrantyAgent", "Customer"}


# ---------------------------------------------------------------------------
# CoatingSystem
# ---------------------------------------------------------------------------
@bp.route("/coating-systems", methods=["POST"])
def create_coating_system():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = require_str(body, "name")
    family = require_enum(body, "family", {"FLAKE", "METALLIC"})
    sku = require_enum(body, "sku", {"FLAKE_STANDARD", "FLAKE_PREMIUM", "METALLIC"})
    active = require_bool(body, "active", default=True)
    row = new_row({
        "name": name,
        "family": family,
        "sku": sku,
        "requires_metallic_certified_crew": (family == "METALLIC"),
        "active": active,
    })
    db.coating_systems[row["id"]] = row
    return success(serialize.coating_system(row), 201)


@bp.route("/coating-systems/<id>", methods=["GET"])
def get_coating_system(id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    row = db.coating_systems.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Coating system not found")
    return success(serialize.coating_system(row), 200)


@bp.route("/coating-systems/<id>/color-options", methods=["GET"])
def list_color_options(id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.coating_systems.get(id) is None:
        raise err("ERR_NOT_FOUND", "Coating system not found")
    limit, offset = parse_pagination()
    rows = [c for c in db.color_options.values() if c["coating_system_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.color_option(r) for r in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# ColorOption
# ---------------------------------------------------------------------------
@bp.route("/color-options", methods=["POST"])
def create_color_option():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    coating_system_id = require_str(body, "coating_system_id")
    name = require_str(body, "name")
    flake_blend_code = require_str(body, "flake_blend_code")
    active = require_bool(body, "active", default=True)
    # body reference must resolve (priority 5)
    if db.coating_systems.get(coating_system_id) is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "coating_system_id does not resolve")
    row = new_row({
        "coating_system_id": coating_system_id,
        "name": name,
        "flake_blend_code": flake_blend_code,
        "active": active,
    })
    db.color_options[row["id"]] = row
    return success(serialize.color_option(row), 201)


# ---------------------------------------------------------------------------
# FinancingPlan
# ---------------------------------------------------------------------------
@bp.route("/financing-plans", methods=["POST"])
def create_financing_plan():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = require_str(body, "name")
    apr_bps = require_int(body, "apr_bps", minimum=0, maximum=3500)
    term_months = require_int(body, "term_months", minimum=1, maximum=84)
    if "min_principal_cents" in body and body["min_principal_cents"] is not None:
        min_principal_cents = require_int(body, "min_principal_cents", minimum=0)
    else:
        min_principal_cents = 0
    active = require_bool(body, "active", default=True)
    row = new_row({
        "name": name,
        "apr_bps": apr_bps,
        "term_months": term_months,
        "min_principal_cents": min_principal_cents,
        "active": active,
    })
    db.financing_plans[row["id"]] = row
    return success(serialize.financing_plan(row), 201)


# ---------------------------------------------------------------------------
# Crew
# ---------------------------------------------------------------------------
@bp.route("/crews", methods=["POST"])
def create_crew():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = require_str(body, "name")
    metallic_certified = require_bool(body, "metallic_certified", default=False)
    max_sqft_per_day = require_int(body, "max_sqft_per_day", minimum=1)
    active = require_bool(body, "active", default=True)
    row = new_row({
        "name": name,
        "metallic_certified": metallic_certified,
        "max_sqft_per_day": max_sqft_per_day,
        "active": active,
    })
    db.crews[row["id"]] = row
    return success(serialize.crew(row), 201)


@bp.route("/crews/<id>", methods=["GET"])
def get_crew(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "Scheduler"})
    row = db.crews.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Crew not found")
    return success(serialize.crew(row), 200)


@bp.route("/crews/<id>/install-jobs", methods=["GET"])
def list_crew_install_jobs(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "Scheduler"})
    if db.crews.get(id) is None:
        raise err("ERR_NOT_FOUND", "Crew not found")
    limit, offset = parse_pagination()
    rows = [j for j in db.install_jobs.values() if j["crew_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.install_job(r) for r in page], 200, pagination=meta)
