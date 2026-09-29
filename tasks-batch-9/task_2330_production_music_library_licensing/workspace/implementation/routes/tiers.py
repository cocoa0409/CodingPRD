"""LicenseTier rate-card endpoints."""

from flask import Blueprint

from db import DB
from errors import fail
from middleware import (
    body,
    opt_bool,
    opt_int,
    req_enum,
    req_enum_array,
    req_int,
    req_string,
    require_role,
)
from response import object_response
from routes.common import MEDIA_TYPES, PREFIX, SCALES
from services.derive import lookup, serialize_tier

bp = Blueprint("tiers", __name__)


@bp.post(PREFIX + "/license-tiers")
def create_tier():
    data = body()
    code = req_string(data, "code", allow_empty=False)
    media_type = req_enum(data, "media_type", MEDIA_TYPES)
    scales = req_enum_array(data, "allowed_scales", SCALES, 1, 3)
    base_rate = req_int(data, "base_rate_cents", 1, None)
    min_term = opt_int(data, "min_term_months", 1, 120, 1)
    max_term = opt_int(data, "max_term_months", 1, 120, 120)
    per_use = opt_bool(data, "per_use_eligible", True)
    blanket = opt_bool(data, "blanket_eligible", False)
    if max_term < min_term:
        fail("ERR_VALIDATION", "max_term_months must be >= min_term_months.")
    for existing in DB.tiers.values():                      # shape check, schema pass
        if existing["code"] == code:
            fail("ERR_TIER_CODE_DUPLICATE", "another rate-card row already uses this code.")
    require_role("CatalogAdmin")

    row = DB.new_row()
    row.update(
        {
            "code": code,
            "media_type": media_type,
            "allowed_scales": scales,
            "base_rate_cents": base_rate,
            "min_term_months": min_term,
            "max_term_months": max_term,
            "per_use_eligible": per_use,
            "blanket_eligible": blanket,
        }
    )
    DB.tiers[row["id"]] = row
    return object_response(serialize_tier(row), 201)


@bp.get(PREFIX + "/license-tiers/<tier_id>")
def get_tier(tier_id):
    row = lookup("tiers", tier_id)
    require_role("CatalogAdmin", "LicensingAgent", "Licensee")
    return object_response(serialize_tier(row))
