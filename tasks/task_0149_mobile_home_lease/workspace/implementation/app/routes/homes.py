"""Home routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..errors import ApiError
from ..responses import success_response
from ..services.entities import (
    get_home_or_404,
    get_lot_body_or_404,
    get_park_or_404,
    get_resident_body_or_404,
    init_common_fields,
    touch,
)
from ..services.serialization import serialize_home
from ..store import store
from ..validation import (
    get_json_body,
    optional_string,
    require_int,
    require_string,
    require_vin,
)


bp = Blueprint("homes", __name__)


@bp.route("/parks/<park_id>/homes", methods=["POST"])
@require_auth("ParkManager")
def create_home(park_id: str):
    park = get_park_or_404(park_id)
    body = get_json_body()
    vin = require_vin(body, "vin")
    lot_id = require_string(body, "lot_id")
    assessed_value_cents = require_int(body, "assessed_value_cents", strict_positive=True)
    owner_resident_id = optional_string(body, "owner_resident_id")

    # Body-resource existence checks (after path resource)
    lot = get_lot_body_or_404(lot_id)
    if lot["park_id"] != park_id:
        # Lot belongs to a different park -> treat as not found relative to URL park
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "Lot does not belong to this park.")
    if owner_resident_id:
        get_resident_body_or_404(owner_resident_id)

    # Uniqueness of VIN
    for h in store.homes.values():
        if h["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN", f"VIN {vin} already exists.")

    # owner_resident_id rules based on lot ownership mode
    if lot["ownership_mode"] == "RESIDENT_OWNED":
        if not owner_resident_id:
            raise ApiError("ERR_VALIDATION", "owner_resident_id is required when lot is RESIDENT_OWNED.")
        owner = owner_resident_id
    else:
        owner = None  # PARK_OWNED -> always null

    with store.lock:
        home = init_common_fields({
            "park_id": park_id,
            "lot_id": lot_id,
            "owner_resident_id": owner,
            "vin": vin,
            "assessed_value_cents": int(assessed_value_cents),
        })
        store.homes[home["id"]] = home
        # Link the home onto the lot
        lot["home_id"] = home["id"]
        touch(lot)

    return success_response(serialize_home(home), status=201)


@bp.route("/homes/<home_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_home(home_id: str):
    home = get_home_or_404(home_id)
    return success_response(serialize_home(home), status=200)


__all__ = ["bp"]
