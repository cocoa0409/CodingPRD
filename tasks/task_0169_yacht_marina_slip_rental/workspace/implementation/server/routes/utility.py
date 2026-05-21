"""Utility reading + settlement routes (under /reservations/:id/)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format
from ..common import get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import (
    enforce_boater_owns,
    get_marina,
    get_reservation,
    parse_required_iso,
)
from ..response import respond
from ..serializers import reading_view, settlement_view
from ..store import store


bp = Blueprint("utility", __name__, url_prefix="/marinas")


@bp.post("/<marina_id>/reservations/<reservation_id>/utility-readings")
@require_auth("DockMaster")
def append_reading(marina_id: str, reservation_id: str):
    body = get_json_body()
    require_fields(body, "read_at", "kwh_delta", "water_gallons_delta")
    read_at = parse_required_iso(body, "read_at")
    kwh = positive_int(body["kwh_delta"], "kwh_delta", allow_zero=True)
    water = positive_int(body["water_gallons_delta"], "water_gallons_delta", allow_zero=True)
    with store.lock:
        get_marina(marina_id)
        res = get_reservation(marina_id, reservation_id)
        reading = {
            "reservation_id": res["id"],
            "read_at": iso_format(read_at),
            "kwh_delta": kwh,
            "water_gallons_delta": water,
            "applied_in_settlement": False,
        }
        stamp_new(reading, with_common=False)
        store.utility_readings[reading["id"]] = reading
    return respond(reading_view(reading), 201)


@bp.get("/<marina_id>/reservations/<reservation_id>/utility-settlement")
@require_auth("DockMaster", "BillingClerk", "Boater")
def fetch_settlement(marina_id: str, reservation_id: str):
    with store.lock:
        get_marina(marina_id)
        res = get_reservation(marina_id, reservation_id)
        if g.user_role == "Boater":
            enforce_boater_owns(res["boater_id"])
        # Pick the latest settlement for this reservation (by created_at)
        matching = [
            s for s in store.utility_settlements.values() if s.get("reservation_id") == res["id"]
        ]
        if not matching:
            raise ApiError("ERR_NOT_FOUND", "No utility settlement for this reservation")
        matching.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return respond(settlement_view(matching[0]), 200)
