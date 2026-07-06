"""Outlet endpoints (PRD 3.2). Immutable reference data: only id + created_at."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_outlet_record, paginate,
                    parse_pagination, require_enum, require_int, require_str)
from errors import err
from middleware import authorize
from response import success
from services.serialize import outlet_out

bp = Blueprint("outlets", __name__)

OUTLET_TIERS = {"NATIONAL", "REGIONAL", "TRADE", "BLOG"}


@bp.post("/agency/outlets")
@authorize(["PlatformAdmin"])
def create_outlet():
    body = get_json_body()
    name = require_str(body, "name")
    tier = require_enum(body, "tier", OUTLET_TIERS)
    monthly_unique_visitors = require_int(body, "monthly_unique_visitors", minimum=0)
    domain_authority = require_int(body, "domain_authority", minimum=0, maximum=100)

    rec = new_outlet_record({
        "name": name,
        "tier": tier,
        "monthly_unique_visitors": monthly_unique_visitors,
        "domain_authority": domain_authority,
    })
    db.outlets[rec["id"]] = rec
    return success(outlet_out(rec), status=201)


@bp.get("/agency/outlets/<outlet_id>")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def get_outlet(outlet_id):
    rec = get_or_404(db.outlets, outlet_id)
    return success(outlet_out(rec))


@bp.get("/agency/outlets")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def list_outlets():
    limit, offset = parse_pagination()
    tier = request.args.get("tier")
    if tier is not None and tier not in OUTLET_TIERS:
        raise err("ERR_INVALID_REQUEST", "tier filter invalid")
    records = [r for r in db.outlets.values() if tier is None or r["tier"] == tier]
    page, meta = paginate(records, limit, offset)
    return success([outlet_out(r) for r in page], pagination=meta)
