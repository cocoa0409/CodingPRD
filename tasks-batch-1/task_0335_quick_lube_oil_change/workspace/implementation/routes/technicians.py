"""Technician endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_bool, optional_int,
                    parse_pagination, paginate, sort_by_created, stamp_create, new_id)
from response import success_object, success_array
from services import lookup
from services.serialize import technician_out

bp = Blueprint("technicians", __name__)

READ_ROLES = ("ShopManager", "ServiceAdvisor", "Technician")


@bp.route("/technicians", methods=["POST"])
def create_technician():
    require_role("ShopManager")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    full_name = require_str(body, "full_name")
    synthetic = require_bool(body, "synthetic_certified", default=False)
    buffer = optional_int(body, "cleanup_buffer_seconds", 300, minimum=0)
    lookup.get_shop(shop_id)
    tech = {
        "id": new_id(),
        "shop_id": shop_id,
        "full_name": full_name,
        "synthetic_certified": synthetic,
        "cleanup_buffer_seconds": buffer,
        "active": True,
    }
    stamp_create(tech)
    db.technicians[tech["id"]] = tech
    return success_object(technician_out(tech), 201)


@bp.route("/technicians", methods=["GET"])
def list_technicians():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.technicians.values())
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        rows = [t for t in rows if t["shop_id"] == shop_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([technician_out(t) for t in page], limit, offset, total)


@bp.route("/technicians/<tech_id>", methods=["GET"])
def get_technician(tech_id):
    require_role(*READ_ROLES)
    tech = lookup.get_technician(tech_id)
    return success_object(technician_out(tech), 200)
