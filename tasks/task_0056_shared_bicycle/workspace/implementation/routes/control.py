"""Test-driving control endpoints — _clock, _sweep, _events (PRD §3.9, §3.12)."""
from __future__ import annotations

from flask import Blueprint

from constants import (
    LONG_STATIONARY_THRESHOLD_MIN,
    LOW_BATTERY_THRESHOLD_PCT,
    SWEEP_DEFAULT_SLA_MINUTES,
)
from db import LOCK, bikes, new_id, regions, work_orders
from errors import ERR_VALIDATION, raise_err
from middleware import require_role
from response import success_object
from services.audit import write_audit
from services.regions import recompute_region_counts
from services.validators import (
    bump_version,
    ensure_non_negative_int,
    get_json_body,
)
from time_utils import now_iso


bp = Blueprint("control", __name__)


@bp.post("/_clock/advance")
def advance_clock():
    require_role("Admin")
    body = get_json_body()
    if "minutes" not in body:
        raise_err(ERR_VALIDATION, "minutes is required")
    minutes = ensure_non_negative_int(body["minutes"], "minutes")
    with LOCK:
        # PRD §2.6: every region has its own clock_minutes; advance all by `minutes`.
        new_clock = 0
        for region in regions.values():
            region["clock_minutes"] = int(region.get("clock_minutes", 0)) + minutes
            new_clock = region["clock_minutes"]
    return success_object({"clock_minutes": new_clock})


@bp.post("/_sweep/run")
def run_sweep():
    require_role("Admin")
    opened = 0
    with LOCK:
        for bike in list(bikes.values()):
            if bike["status"] != "AVAILABLE":
                continue
            region_id = bike.get("region_id")
            if not region_id or region_id not in regions:
                continue
            clock = int(regions[region_id].get("clock_minutes", 0))
            causes = []
            if clock - int(bike.get("last_motion_minute", 0)) >= LONG_STATIONARY_THRESHOLD_MIN:
                causes.append(("LONG_STATIONARY", "OTHER"))
            if int(bike.get("battery_pct", 100)) <= LOW_BATTERY_THRESHOLD_PCT:
                causes.append(("LOW_BATTERY", "BATTERY_SWAP"))
            if bike.get("lock_state") == "UNKNOWN" and bike.get("shelf_state") == "ON_SHELF":
                causes.append(("LOCK_ABNORMAL", "LOCK_FAILURE"))
            if not causes:
                continue

            prior_status = bike["status"]
            bike["status"] = "FAULT"
            bump_version(bike)

            for cause, category in causes:
                wo_id = new_id()
                ts = now_iso()
                wo = {
                    "id": wo_id,
                    "bike_id": bike["id"],
                    "region_id": region_id,
                    "cause": cause,
                    "category": category,
                    "status": "OPEN",
                    "assigned_operator_id": None,
                    "sla_minutes": SWEEP_DEFAULT_SLA_MINUTES,
                    "opened_minute": clock,
                    "resolved_minute": None,
                    "resolution_note": None,
                    "created_at": ts,
                    "updated_at": ts,
                    "version": 1,
                }
                work_orders[wo_id] = wo
                if category not in bike["fault_categories"]:
                    bike["fault_categories"].append(category)
                opened += 1
            recompute_region_counts(region_id)
            write_audit(
                event_kind="OPS_ACTION",
                action="BIKE_FAULT_OPEN",
                subject_type="Bike",
                subject_id=bike["id"],
                before={"status": prior_status},
                after={"status": "FAULT", "fault_categories": list(bike["fault_categories"])},
                region_id=region_id,
            )
    return success_object({"opened_count": opened})


@bp.post("/_events/emit")
def emit_event():
    require_role("Admin")
    body = get_json_body()
    for f in ("target_system", "subject_type", "subject_id", "payload"):
        if f not in body:
            raise_err(ERR_VALIDATION, f"{f} is required")
    entry = write_audit(
        event_kind="EXTERNAL_SYNC",
        action="EVENT_EMIT",
        subject_type=str(body["subject_type"]),
        subject_id=str(body["subject_id"]),
        before={},
        after={
            "target_system": body["target_system"],
            "payload": body["payload"],
        },
    )
    return success_object(entry)
