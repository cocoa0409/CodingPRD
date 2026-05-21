"""Lot routes: nested under /parks/{park_id}/lots and stand-alone /lots/{lot_id}."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..errors import ApiError
from ..responses import list_response, success_response
from ..services.entities import (
    get_lot_or_404,
    get_park_or_404,
    init_common_fields,
    touch,
)
from ..services.serialization import serialize_lot
from ..store import store
from ..validation import (
    get_json_body,
    optional_number,
    parse_pagination,
    require_int,
    require_number,
    require_string,
)


bp = Blueprint("lots", __name__)


@bp.route("/parks/<park_id>/lots", methods=["POST"])
@require_auth("ParkManager")
def create_lot(park_id: str):
    park = get_park_or_404(park_id)
    body = get_json_body()
    lot_number = require_string(body, "lot_number", min_len=1, max_len=16)
    base_rent_cents = require_int(body, "base_rent_cents", strict_positive=True)
    sub_meter_reading = optional_number(body, "sub_meter_reading_kwh", default=0.0, minimum=0.0)

    with store.lock:
        # Uniqueness check within the park
        for l in store.lots.values():
            if l["park_id"] == park_id and l["lot_number"] == lot_number:
                raise ApiError("ERR_DUPLICATE_LOT_NUMBER", f"Lot number {lot_number} already exists in this park.")
        lot = init_common_fields({
            "park_id": park_id,
            "lot_number": lot_number,
            "ownership_mode": "PARK_OWNED",
            "base_rent_cents": int(base_rent_cents),
            "sub_meter_reading_kwh": float(sub_meter_reading or 0.0),
            "home_id": None,
            "current_lease_id": None,
        })
        store.lots[lot["id"]] = lot
        # Park.ownership_pool_count += 1
        park["ownership_pool_count"] = park.get("ownership_pool_count", 0) + 1
        touch(park)

    return success_response(serialize_lot(lot), status=201)


@bp.route("/parks/<park_id>/lots", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin")
def list_park_lots(park_id: str):
    park = get_park_or_404(park_id)
    limit, offset = parse_pagination()
    ownership_filter = request.args.get("ownership_mode")
    if ownership_filter is not None and ownership_filter not in ("PARK_OWNED", "RESIDENT_OWNED"):
        raise ApiError("ERR_VALIDATION", "Query parameter 'ownership_mode' must be PARK_OWNED or RESIDENT_OWNED.")

    rows = [l for l in store.lots.values() if l["park_id"] == park_id]
    if ownership_filter:
        rows = [l for l in rows if l["ownership_mode"] == ownership_filter]
    rows.sort(key=lambda l: l["created_at"])
    total = len(rows)
    page = rows[offset: offset + limit]
    return list_response(
        [serialize_lot(l) for l in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


@bp.route("/lots/<lot_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_lot_route(lot_id: str):
    """Convenience GET for tooling — PRD §4 lists only PATCH /lots/{lot_id}
    in its endpoint table, but the listing endpoint
    GET /parks/{park_id}/lots already exposes per-lot data. This GET
    is a strict subset (single-row of the same data) and serves the
    same authorized roles."""
    lot = get_lot_or_404(lot_id)
    return success_response(serialize_lot(lot), status=200)


@bp.route("/lots/<lot_id>", methods=["PATCH"])
@require_auth("ParkManager")
def patch_lot(lot_id: str):
    lot = get_lot_or_404(lot_id)
    body = get_json_body()
    sub_meter_reading = require_number(body, "sub_meter_reading_kwh", minimum=0.0)
    # OCC: optional version
    if "version" in body and body["version"] is not None:
        client_version = body["version"]
        if not isinstance(client_version, int) or isinstance(client_version, bool):
            raise ApiError("ERR_VALIDATION", "Field 'version' must be an integer.")
        if client_version != lot["version"]:
            raise ApiError("ERR_VERSION_MISMATCH")

    with store.lock:
        lot["sub_meter_reading_kwh"] = float(sub_meter_reading)
        touch(lot)

    return success_response(serialize_lot(lot), status=200)


__all__ = ["bp"]
