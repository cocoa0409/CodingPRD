"""Park routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..errors import ApiError
from ..responses import success_response
from ..services.entities import get_park_or_404, init_common_fields
from ..services.serialization import serialize_park
from ..store import store
from ..validation import (
    get_json_body,
    require_enum,
    require_int,
    require_number,
    require_string,
)


bp = Blueprint("parks", __name__)


@bp.route("/parks", methods=["POST"])
@require_auth("ParkManager", "PlatformAdmin")
def create_park():
    body = get_json_body()
    name = require_string(body, "name", min_len=1, max_len=120)
    state_code = require_enum(body, "state_code", {"CA", "FL", "OR", "AZ", "TX"})
    master_cpi_pct = require_number(body, "master_cpi_pct", minimum=0.0, maximum=20.0)
    apportionment = require_enum(body, "utility_apportionment_method", {"SUB_METER", "EQUAL_SPLIT"})
    anchor_day = require_int(body, "billing_period_anchor_day", minimum=1, maximum=28)

    with store.lock:
        for p in store.parks.values():
            if p["name"] == name:
                # uniqueness "per park" — interpret as global uniqueness of park name
                raise ApiError("ERR_VALIDATION", f"Park name '{name}' already in use.")
        park = init_common_fields({
            "name": name,
            "state_code": state_code,
            "master_cpi_pct": float(master_cpi_pct),
            "utility_apportionment_method": apportionment,
            "billing_period_anchor_day": anchor_day,
            "ownership_pool_count": 0,
        })
        store.parks[park["id"]] = park

    return success_response(serialize_park(park), status=201)


@bp.route("/parks/<park_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_park(park_id: str):
    park = get_park_or_404(park_id)
    return success_response(serialize_park(park), status=200)


__all__ = ["bp"]
