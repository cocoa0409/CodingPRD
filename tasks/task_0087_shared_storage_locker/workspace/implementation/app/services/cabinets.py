"""Cabinet business logic."""
from __future__ import annotations

from typing import Any, Optional

from .. import constants
from ..auth import current_actor
from ..calculations import haversine_km
from ..clock import now_iso_ms
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .capacity import recompute_cabinet_capacity
from .serializers import serialize_cabinet
from .validation import (
    require_field,
    require_in,
    require_int,
    require_number,
    require_str,
)


# -------- Helpers --------


def _check_version(entity: dict[str, Any], supplied_version: Any) -> None:
    if supplied_version is None:
        return
    if not isinstance(supplied_version, int) or isinstance(supplied_version, bool):
        raise ApiError("ERR_BAD_REQUEST", "version must be an integer.")
    if supplied_version != int(entity.get("version", 0)):
        raise ApiError("ERR_VERSION_CONFLICT", "Resource version mismatch.")


def get_cabinet_or_404(cabinet_id: str) -> dict[str, Any]:
    store = get_store()
    cabinet = store.cabinets.get(cabinet_id)
    if cabinet is None:
        raise ApiError("ERR_NOT_FOUND", f"Cabinet {cabinet_id} not found.")
    return cabinet


# -------- Create --------


def create_cabinet(body: dict[str, Any]) -> dict[str, Any]:
    location_code = require_str(require_field(body, "location_code"), "location_code")
    latitude = require_number(require_field(body, "latitude"), "latitude")
    longitude = require_number(require_field(body, "longitude"), "longitude")
    partner_id = require_str(require_field(body, "partner_id"), "partner_id")
    partner_share_pct_raw = require_field(body, "partner_share_pct")
    partner_share_pct = require_int(partner_share_pct_raw, "partner_share_pct", 0, 100)
    firmware_version = require_str(require_field(body, "firmware_version"), "firmware_version")

    store = get_store()
    cabinet = common_fields_create()
    cabinet.update(
        {
            "location_code": location_code,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "partner_id": partner_id,
            "partner_share_pct": partner_share_pct,
            "firmware_version": firmware_version,
            "online_status": "ONLINE",
            "last_heartbeat_at": None,
            "total_compartments": 0,
            "small_capacity_total": 0,
            "medium_capacity_total": 0,
            "large_capacity_total": 0,
            "small_occupancy_pct": 0.0,
            "medium_occupancy_pct": 0.0,
            "large_occupancy_pct": 0.0,
            "capacity_alert_level": "NONE",
        }
    )
    store.cabinets[cabinet["id"]] = cabinet
    return serialize_cabinet(cabinet)


# -------- Get/List --------


def get_cabinet(cabinet_id: str) -> dict[str, Any]:
    return serialize_cabinet(get_cabinet_or_404(cabinet_id))


def list_cabinets(
    online_status: Optional[str],
    capacity_alert_level: Optional[str],
) -> list[dict[str, Any]]:
    store = get_store()
    items = list(store.cabinets.values())
    if online_status:
        items = [c for c in items if c["online_status"] == online_status]
    if capacity_alert_level:
        items = [c for c in items if c["capacity_alert_level"] == capacity_alert_level]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return [serialize_cabinet(c) for c in items]


# -------- Update --------


def update_cabinet(cabinet_id: str, body: dict[str, Any]) -> dict[str, Any]:
    cabinet = get_cabinet_or_404(cabinet_id)
    _check_version(cabinet, body.get("version"))

    if "firmware_version" in body:
        cabinet["firmware_version"] = require_str(body["firmware_version"], "firmware_version")
    if "partner_id" in body:
        cabinet["partner_id"] = require_str(body["partner_id"], "partner_id")
    if "partner_share_pct" in body:
        cabinet["partner_share_pct"] = require_int(body["partner_share_pct"], "partner_share_pct", 0, 100)

    bump_version(cabinet)
    return serialize_cabinet(cabinet)


# -------- Heartbeat --------


def heartbeat_cabinet(cabinet_id: str) -> dict[str, Any]:
    cabinet = get_cabinet_or_404(cabinet_id)
    cabinet["last_heartbeat_at"] = now_iso_ms()
    if cabinet["online_status"] in ("DEGRADED", "OFFLINE"):
        cabinet["online_status"] = "ONLINE"
    bump_version(cabinet)
    return serialize_cabinet(cabinet)


# -------- Redistribution suggestion --------


def redistribution_suggestion(cabinet_id: str) -> dict[str, Any]:
    src = get_cabinet_or_404(cabinet_id)
    store = get_store()

    # Determine the offending size class(es): every class whose level is WARNING/CRITICAL.
    src_levels = {
        "SMALL": src["small_occupancy_pct"],
        "MEDIUM": src["medium_occupancy_pct"],
        "LARGE": src["large_occupancy_pct"],
    }
    offending = [
        sz
        for sz, pct in src_levels.items()
        if pct >= constants.WARNING_PCT
    ]
    if not offending:
        return {"suggestion": None, "reason": "NO_TARGET_AVAILABLE"}

    candidates: list[tuple[dict[str, Any], float]] = []
    for cab in store.cabinets.values():
        if cab["id"] == src["id"]:
            continue
        if cab["online_status"] != "ONLINE":
            continue
        if cab["capacity_alert_level"] != "NONE":
            continue
        dist = haversine_km(src["latitude"], src["longitude"], cab["latitude"], cab["longitude"])
        if dist > constants.REDISTRIBUTION_RADIUS_KM:
            continue
        # Has at least one IDLE+OK compartment in any offending size class
        has_idle_in_class = False
        for c in store.compartments.values():
            if c["cabinet_id"] != cab["id"]:
                continue
            if c["operational_status"] != "OK":
                continue
            if c["occupancy_status"] != "IDLE":
                continue
            if c["size_class"] in offending:
                has_idle_in_class = True
                break
        if not has_idle_in_class:
            continue
        candidates.append((cab, dist))

    if not candidates:
        return {"suggestion": None, "reason": "NO_TARGET_AVAILABLE"}

    def score(item: tuple[dict[str, Any], float]) -> tuple[float, str]:
        cab, dist = item
        s = (dist * constants.DISTANCE_WEIGHT) + (
            cab["small_occupancy_pct"] + cab["medium_occupancy_pct"] + cab["large_occupancy_pct"]
        ) * constants.OCC_WEIGHT
        return (s, cab["id"])

    candidates.sort(key=score)
    winner = candidates[0][0]
    return {"suggestion": serialize_cabinet(winner), "reason": None}
