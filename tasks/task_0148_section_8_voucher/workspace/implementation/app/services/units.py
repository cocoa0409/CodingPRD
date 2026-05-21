"""Unit registration + listing."""

from __future__ import annotations

from typing import Optional

from app import clock, store
from app.errors import validation
from app.serializers import _occupancy_status
from app.util import new_id, require_int, require_str


_VALID_ZONES = ("ZONE_A", "ZONE_B", "ZONE_C")
_VALID_OCC = ("VACANT", "OCCUPIED_PENDING", "OCCUPIED_ACTIVE", "OCCUPIED_ABATED")


def create_unit(landlord_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")
    try:
        street_address = require_str(payload.get("street_address"), field="street_address")
        zone = require_str(payload.get("zone"), field="zone", allowed=_VALID_ZONES)
        bedroom_count = require_int(payload.get("bedroom_count"), field="bedroom_count", min_value=0, max_value=6)
        asking_rent = require_int(payload.get("asking_rent_cents"), field="asking_rent_cents", min_value=1)
        utilities = require_int(payload.get("tenant_paid_utilities_cents", 0), field="tenant_paid_utilities_cents", min_value=0)
    except ValueError as exc:
        raise validation(str(exc))

    now = clock.now()
    unit_id = new_id()
    record = {
        "id": unit_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "landlord_id": landlord_id,
        "street_address": street_address,
        "zone": zone,
        "bedroom_count": bedroom_count,
        "asking_rent_cents": asking_rent,
        "tenant_paid_utilities_cents": utilities,
    }
    store.units[unit_id] = record
    return record


def list_units(*, zone: Optional[str], bedroom_count: Optional[int], occupancy_status: Optional[str], landlord_id_filter: Optional[str]):
    out = []
    for u in store.units.values():
        if zone and u.get("zone") != zone:
            continue
        if bedroom_count is not None and u.get("bedroom_count") != bedroom_count:
            continue
        if landlord_id_filter and u.get("landlord_id") != landlord_id_filter:
            continue
        if occupancy_status and _occupancy_status(u["id"]) != occupancy_status:
            continue
        out.append(u)
    return out
