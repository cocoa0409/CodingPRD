"""ServiceCatalog endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_SERVICE_TYPE_TAKEN
from middleware import require
from response import ok_array, ok_object
from services.common import (
    by_created_asc,
    get_json_body,
    init_common,
    paginate,
    parse_pagination,
    public,
    public_list,
    require_enum,
    require_int,
)
from services.lookups import get_catalog

bp = Blueprint("catalogs", __name__)

SERVICE_TYPES = {"STEAM", "DRY"}


@bp.post("/service-catalogs")
def create_catalog():
    require(["ServiceManager"])
    body = get_json_body()
    service_type = require_enum(body, "service_type", SERVICE_TYPES)
    # base_rate_cents_per_sqft >= 1; dry_time_minutes >= 1; the four add-on/
    # surcharge rates must each be >= 0 (PRD §3.1, §2.6).
    base_rate = require_int(body, "base_rate_cents_per_sqft", minimum=1)
    stain = require_int(body, "stain_addon_cents", minimum=0)
    pet = require_int(body, "pet_addon_cents", minimum=0)
    protectant = require_int(body, "protectant_cents_per_sqft", minimum=0)
    move_furn = require_int(body, "move_furniture_flat_cents", minimum=0)
    dry_time = require_int(body, "dry_time_minutes", minimum=1)

    # one catalog per service_type (PRD §3.1) -> ERR_SERVICE_TYPE_TAKEN (409)
    for c in db.service_catalogs.values():
        if c["service_type"] == service_type:
            raise APIError(ERR_SERVICE_TYPE_TAKEN, 409, "A catalog already exists for this service type")

    record = init_common({
        "service_type": service_type,
        "base_rate_cents_per_sqft": base_rate,
        "stain_addon_cents": stain,
        "pet_addon_cents": pet,
        "protectant_cents_per_sqft": protectant,
        "move_furniture_flat_cents": move_furn,
        "dry_time_minutes": dry_time,
    })
    db.service_catalogs[record["id"]] = record
    return ok_object(public(record), 201)


@bp.get("/service-catalogs/<cid>")
def get_catalog_ep(cid):
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    c = get_catalog(cid)
    return ok_object(public(c), 200)


@bp.get("/service-catalogs")
def list_catalogs():
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    limit, offset = parse_pagination()
    rows = list(db.service_catalogs.values())
    service_type = request.args.get("service_type")
    if service_type is not None:
        rows = [c for c in rows if c["service_type"] == service_type]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)
