"""Deterministic clock-advance + housekeeping sweep routes."""
from __future__ import annotations

from typing import Any

from flask import Flask

from ..audit import emit_sync_event, write_audit
from ..auth import require_auth
from ..errors import ApiError
from ..services.posture import recompute_zone_posture
from ..services.validation import require_int, require_keys
from ..store import LOCK, bump_version, get_store
from ._helpers import get_json_body, ok


def _sweep_warehouse(wid: str) -> dict[str, Any]:
    """Idempotent sweep — see PRD §2.7."""
    store = get_store()
    wh = store.warehouses[wid]
    clock = int(wh["clock_minutes"])
    overdue_capas: list[str] = []
    advanced_recalls: list[str] = []
    posture_zones: list[str] = []

    # 1. Mark CAPAs OVERDUE.
    for c in store.capas.values():
        if c["warehouse_id"] != wid:
            continue
        if c["status"] in ("OPEN", "IN_PROGRESS") and c.get("due_minutes") is not None and int(c["due_minutes"]) < clock:
            c["status"] = "OVERDUE"
            bump_version(c)
            overdue_capas.append(c["id"])
            emit_sync_event(
                warehouse_id=wid,
                target_system="REGULATORY_AUTHORITY",
                event_type="CAPA_OVERDUE",
                payload={"capa_id": c["id"], "due_minutes": int(c["due_minutes"])},
            )
            write_audit(
                warehouse_id=wid,
                action="CAPA_OVERDUE",
                target_id=c["id"],
                at_minutes=clock,
            )

    # 2. Auto-advance recalls past their deadline.
    for r in store.recalls.values():
        if r["warehouse_id"] != wid:
            continue
        if r["status"] == "RETURNS_IN_PROGRESS":
            due = r.get("report_due_minutes")
            if due is not None and clock >= int(due):
                r["status"] = "EFFECTIVENESS_CHECK"
                bump_version(r)
                advanced_recalls.append(r["id"])

    # 3. Recompute zone postures.
    for z in store.zones.values():
        if z["warehouse_id"] != wid:
            continue
        prev = z.get("current_posture")
        recompute_zone_posture(z["id"])
        if z.get("current_posture") != prev:
            posture_zones.append(z["id"])

    return {
        "warehouse_id": wid,
        "clock_minutes": clock,
        "overdue_capas": overdue_capas,
        "advanced_recalls": advanced_recalls,
        "posture_recomputed_zones": posture_zones,
    }


def register(app: Flask) -> None:
    @app.route("/warehouses/<wid>/_clock/advance", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def clock_advance(wid: str):
        body = get_json_body()
        store = get_store()
        wh = store.warehouses.get(wid)
        if not wh:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        require_keys(body, ["minutes"])
        minutes = require_int(body["minutes"], "minutes", allow_zero=False)
        if minutes <= 0:
            raise ApiError("ERR_VALIDATION_FAILED", "minutes must be > 0")
        with LOCK:
            wh["clock_minutes"] = int(wh["clock_minutes"]) + int(minutes)
            bump_version(wh)
            _sweep_warehouse(wid)
        return ok(wh)

    @app.route("/warehouses/<wid>/_sweep/run", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def sweep_run(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        with LOCK:
            summary = _sweep_warehouse(wid)
        return ok(summary)
