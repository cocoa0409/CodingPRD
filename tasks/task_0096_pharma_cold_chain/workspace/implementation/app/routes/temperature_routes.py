"""Temperature event ingestion + deviation lifecycle cascades."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from flask import Flask

from ..audit import emit_sync_event, write_audit
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..services.calculations import (
    classify_deviation,
    classify_temperature,
    magnitude_from_bound,
    round_half_up_dp,
)
from ..services.posture import (
    open_deviations_for_zone,
    recompute_zone_posture,
)
from ..services.validation import require_int, require_keys, require_number
from ..store import (
    LOCK,
    bump_version,
    common_fields_append_only,
    common_fields_create,
    get_store,
)
from ._helpers import created, get_json_body, list_ok, ok


def _open_deviation_with_open_status(zone_id: str) -> dict[str, Any] | None:
    """Return the currently-OPEN deviation on this zone, if any."""
    store = get_store()
    for d in store.deviations.values():
        if d["zone_id"] == zone_id and d["status"] == "OPEN":
            return d
    return None


def _close_deviation(
    deviation: dict[str, Any],
    *,
    ended_at_minutes: int,
    zone: dict[str, Any],
    warehouse: dict[str, Any],
) -> None:
    """OPEN → CLOSED_PENDING_QA cascade."""
    store = get_store()
    duration = ended_at_minutes - int(deviation["started_at_minutes"]) + 1
    deviation["ended_at_minutes"] = ended_at_minutes
    deviation["duration_minutes"] = duration
    deviation["classification"] = classify_deviation(
        deviation.get("max_magnitude_c", Decimal("0.0")), duration
    )
    deviation["status"] = "CLOSED_PENDING_QA"
    bump_version(deviation)

    # Cascade: every lot whose bin is in this zone → cumulative_excursion_minutes += duration;
    # RELEASED→QUARANTINED.
    for L in store.lots.values():
        bin_id = L.get("bin_id")
        if not bin_id:
            continue
        b = store.bins.get(bin_id)
        if not b or b.get("zone_id") != zone["id"]:
            continue
        L["cumulative_excursion_minutes"] = int(L.get("cumulative_excursion_minutes", 0)) + duration
        if L.get("quality_status") == "RELEASED":
            L["quality_status"] = "QUARANTINED"
        bump_version(L)

    # Cascade shipments: every PACKED shipment whose pick_lot is now quarantined → QUARANTINED.
    for sh in store.shipments.values():
        if sh.get("status") != "PACKED":
            continue
        pick_lot = store.lots.get(sh.get("pick_lot_id")) if sh.get("pick_lot_id") else None
        if pick_lot is None:
            continue
        if pick_lot.get("quality_status") == "QUARANTINED":
            sh["status"] = "QUARANTINED"
            bump_version(sh)

    emit_sync_event(
        warehouse_id=zone["warehouse_id"],
        target_system="REGULATORY_AUTHORITY",
        event_type="DEVIATION_CLOSED",
        payload={
            "deviation_id": deviation["id"],
            "zone_id": zone["id"],
            "classification": deviation["classification"],
            "duration_minutes": duration,
        },
    )
    write_audit(
        warehouse_id=zone["warehouse_id"],
        action="DEVIATION_CLOSE",
        target_id=deviation["id"],
        at_minutes=int(warehouse["clock_minutes"]),
    )


def register(app: Flask) -> None:
    # ------------------------------------------------------------------
    # Record temperature event
    # ------------------------------------------------------------------
    @app.route("/zones/<zid>/temperature-events", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def create_temp_event(zid: str):
        body = get_json_body()
        store = get_store()
        zone = store.zones.get(zid)
        if not zone:
            raise ApiError("ERR_NOT_FOUND", "Zone not found")
        warehouse = store.warehouses[zone["warehouse_id"]]
        require_keys(body, ["at_minutes", "temp_c"])
        at_minutes = require_int(body["at_minutes"], "at_minutes", allow_zero=True)
        temp_c = require_number(body["temp_c"], "temp_c")
        clock = int(warehouse["clock_minutes"])
        if not (clock - 1 <= at_minutes <= clock):
            raise ApiError(
                "ERR_TEMP_EVENT_TIME_INVALID",
                f"at_minutes must be in [{clock - 1}, {clock}]",
            )

        with LOCK:
            kind = classify_temperature(temp_c, zone)

            ev = common_fields_append_only()
            ev.update(
                {
                    "zone_id": zid,
                    "warehouse_id": zone["warehouse_id"],
                    "at_minutes": at_minutes,
                    "temp_c": float(temp_c),
                    "kind": kind,
                    "deviation_id": None,
                }
            )
            store.temperature_events[ev["id"]] = ev

            # Update zone last_sensor_reading_c
            zone["last_sensor_reading_c"] = float(temp_c)
            # rounded to 2dp per PRD §2.9 (temperatures recorded to 2dp).
            zone["last_sensor_reading_c"] = float(
                round_half_up_dp(Decimal(str(temp_c)), 2)
            )
            bump_version(zone)

            current_open_dev = _open_deviation_with_open_status(zid)

            if kind == "IN_RANGE":
                # If a deviation was open, close it with ended_at = previous out-of-range event minute.
                if current_open_dev is not None:
                    # Find latest out-of-range event in this deviation BEFORE this reading.
                    related_events = [
                        e
                        for e in store.temperature_events.values()
                        if e.get("deviation_id") == current_open_dev["id"]
                        and e.get("kind") != "IN_RANGE"
                    ]
                    if related_events:
                        related_events.sort(
                            key=lambda e: (int(e["at_minutes"]), e["created_at"])
                        )
                        last_oor = related_events[-1]
                        ended_at = int(last_oor["at_minutes"])
                    else:
                        ended_at = at_minutes - 1
                    _close_deviation(
                        current_open_dev,
                        ended_at_minutes=ended_at,
                        zone=zone,
                        warehouse=warehouse,
                    )
            else:
                # Out-of-range: aggregate into deviation, open one if necessary.
                magnitude = magnitude_from_bound(temp_c, zone)
                if current_open_dev is None:
                    dev = common_fields_create()
                    dev.update(
                        {
                            "zone_id": zid,
                            "warehouse_id": zone["warehouse_id"],
                            "started_at_minutes": at_minutes,
                            "ended_at_minutes": None,
                            "max_magnitude_c": float(magnitude),
                            "duration_minutes": 0,
                            "classification": None,
                            "qa_decision": "PENDING",
                            "capa_id": None,
                            "status": "OPEN",
                        }
                    )
                    store.deviations[dev["id"]] = dev
                    current_open_dev = dev
                    emit_sync_event(
                        warehouse_id=zone["warehouse_id"],
                        target_system="REGULATORY_AUTHORITY",
                        event_type="DEVIATION_OPENED",
                        payload={
                            "deviation_id": dev["id"],
                            "zone_id": zid,
                            "started_at_minutes": at_minutes,
                            "kind": kind,
                        },
                    )
                    write_audit(
                        warehouse_id=zone["warehouse_id"],
                        action="DEVIATION_OPEN",
                        target_id=dev["id"],
                        at_minutes=int(warehouse["clock_minutes"]),
                    )
                else:
                    # Update max_magnitude.
                    prev_max = Decimal(str(current_open_dev.get("max_magnitude_c", "0.0")))
                    if magnitude > prev_max:
                        current_open_dev["max_magnitude_c"] = float(magnitude)
                        bump_version(current_open_dev)

                ev["deviation_id"] = current_open_dev["id"]

            # Recompute zone posture from open deviations.
            recompute_zone_posture(zid)

        return created(ev)

    # ------------------------------------------------------------------
    # List temperature events
    # ------------------------------------------------------------------
    @app.route("/zones/<zid>/temperature-events", methods=["GET"])
    @require_auth("WarehouseAdmin", "QAOfficer", "RecallOfficer")
    def list_temp_events(zid: str):
        store = get_store()
        if zid not in store.zones:
            raise ApiError("ERR_NOT_FOUND", "Zone not found")
        limit, offset = parse_limit_offset()
        kind_f = parse_filter("kind")
        items = [e for e in store.temperature_events.values() if e["zone_id"] == zid]
        if kind_f is not None:
            items = [e for e in items if e["kind"] == kind_f]
        items.sort(key=lambda e: e["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
