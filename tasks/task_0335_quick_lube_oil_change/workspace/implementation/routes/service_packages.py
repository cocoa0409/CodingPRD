"""ServicePackage endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_int, require_enum,
                    parse_pagination, paginate, sort_by_created, stamp_create, new_id,
                    touch)
from response import success_object, success_array
from services import lookup
from services.serialize import service_package_out

bp = Blueprint("service_packages", __name__)

ALL_ROLES = ("ShopManager", "ServiceAdvisor", "Technician", "FleetManager")
OIL_GRADES = {"CONVENTIONAL", "SYNTHETIC_BLEND", "FULL_SYNTHETIC", "HIGH_MILEAGE"}
SYNTHETIC_GRADES = {"FULL_SYNTHETIC", "HIGH_MILEAGE"}


@bp.route("/service-packages", methods=["POST"])
def create_package():
    require_role("ShopManager")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    oil_grade = require_enum(body, "oil_grade", OIL_GRADES)
    name = require_str(body, "name")
    base_price = require_int(body, "base_price_cents", minimum=0)
    included_quarts = require_int(body, "included_quarts", minimum=1)
    labor_minutes = require_int(body, "labor_minutes", minimum=1)
    interval_miles = require_int(body, "interval_miles", minimum=1)
    interval_days = require_int(body, "interval_days", minimum=1)
    lookup.get_shop(shop_id)
    pkg = {
        "id": new_id(),
        "shop_id": shop_id,
        "oil_grade": oil_grade,
        "name": name,
        "base_price_cents": base_price,
        "included_quarts": included_quarts,
        "labor_minutes": labor_minutes,
        "interval_miles": interval_miles,
        "interval_days": interval_days,
        "requires_synthetic_certified_bay": oil_grade in SYNTHETIC_GRADES,
        "active": True,
    }
    stamp_create(pkg)
    db.service_packages[pkg["id"]] = pkg
    return success_object(service_package_out(pkg), 201)


@bp.route("/service-packages", methods=["GET"])
def list_packages():
    require_role(*ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.service_packages.values())
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        rows = [p for p in rows if p["shop_id"] == shop_id]
    oil_grade = request.args.get("oil_grade")
    if oil_grade is not None:
        rows = [p for p in rows if p["oil_grade"] == oil_grade]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([service_package_out(p) for p in page], limit, offset, total)


@bp.route("/service-packages/<pkg_id>", methods=["GET"])
def get_package(pkg_id):
    require_role(*ALL_ROLES)
    pkg = lookup.get_package(pkg_id)
    return success_object(service_package_out(pkg), 200)


@bp.route("/service-packages/<pkg_id>/retire", methods=["POST"])
def retire_package(pkg_id):
    require_role("ShopManager")
    pkg = lookup.get_package(pkg_id)
    pkg["active"] = False
    touch(pkg)
    return success_object(service_package_out(pkg), 200)
