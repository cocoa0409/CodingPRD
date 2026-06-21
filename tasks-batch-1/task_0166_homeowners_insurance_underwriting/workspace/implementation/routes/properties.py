"""Property routes (PRD §3.1, §2.10)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.calc import replacement_cost
from services.common import (
    get_json_body, require_field, as_string, as_int, as_enum,
    get_or_404, parse_pagination, paginate,
)
from services.models import base_record, serialize, touch

bp = Blueprint("properties", __name__)

CONSTRUCTION_TYPES = {"FRAME", "MASONRY", "FIRE_RESISTIVE"}


@bp.post("/properties")
@require_roles("Agent")
def create_property():
    body = get_json_body()
    street_address = as_string(require_field(body, "street_address"), "street_address")
    state_code = as_string(require_field(body, "state_code"), "state_code")
    year_built = as_int(require_field(body, "year_built"), "year_built")
    if not (1800 <= year_built <= 2026):
        raise err("ERR_INVALID_REQUEST", "year_built must be between 1800 and 2026.")
    square_footage = as_int(require_field(body, "square_footage"), "square_footage")
    if square_footage <= 0:
        raise err("ERR_INVALID_REQUEST", "square_footage must be > 0.")
    construction_type = as_enum(
        require_field(body, "construction_type"), "construction_type", CONSTRUCTION_TYPES
    )
    roof_age_years = as_int(require_field(body, "roof_age_years"), "roof_age_years")
    if roof_age_years < 0:
        raise err("ERR_INVALID_REQUEST", "roof_age_years must be >= 0.")
    # stories optional, default 1
    if "stories" in body and body["stories"] is not None:
        stories = as_int(body["stories"], "stories")
        if stories < 1:
            raise err("ERR_INVALID_REQUEST", "stories must be >= 1.")
    else:
        stories = 1

    with db.lock:
        rec = base_record()
        rec.update({
            "street_address": street_address,
            "state_code": state_code,
            "year_built": year_built,
            "square_footage": square_footage,
            "construction_type": construction_type,
            "roof_age_years": roof_age_years,
            "stories": stories,
            "replacement_cost": Decimal("0"),
            "total_insured_value": Decimal("0"),
            "estimate_variant": "NONE",
            "status": "ACTIVE",
        })
        db.properties[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/properties")
@require_roles("Admin", "Agent", "Underwriter")
def list_properties():
    limit, offset = parse_pagination()
    include_archived = request.args.get("include_archived", "").lower() == "true"
    with db.lock:
        items = list(db.properties.values())
        if not include_archived:
            items = [p for p in items if p["status"] != "ARCHIVED"]
        window, meta = paginate(items, limit, offset)
        data = [serialize(p) for p in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/properties/<rid>")
@require_roles("Admin", "Agent", "Underwriter")
def get_property(rid):
    with db.lock:
        rec = get_or_404("property", rid)
        return success(serialize(rec), status=200)


@bp.post("/properties/<rid>/estimate-replacement-cost")
@require_roles("Agent")
def estimate_replacement_cost(rid):
    body = get_json_body()
    method = as_enum(require_field(body, "method"), "method", {"COMPONENT", "SQFT_BLEND"})
    with db.lock:
        prop = get_or_404("property", rid)
        rc = replacement_cost(prop, method)
        prop["replacement_cost"] = rc
        prop["estimate_variant"] = method
        # committing an estimate resets total_insured_value to replacement_cost (§2.10)
        prop["total_insured_value"] = rc
        touch(prop)
        return success(serialize(prop), status=200)
