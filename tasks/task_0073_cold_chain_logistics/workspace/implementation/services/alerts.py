"""Alert lifecycle: open, recompute level, channels."""

from decimal import Decimal

from clock import clock, parse_iso8601
from db import db, new_id
from services import audit
from services.precision import to_float_2, round_half_up_2

UNRESOLVED_STATUSES = {"OPEN", "ACKNOWLEDGED", "IN_RESPONSE", "ESCALATED"}


def _level_for(duration_seconds: int, peak_deviation: Decimal) -> str:
    if duration_seconds >= 1800 or peak_deviation >= Decimal("5.00"):
        return "CRITICAL"
    if duration_seconds >= 600 or peak_deviation >= Decimal("2.00"):
        return "MAJOR"
    return "WARNING"


def _channels_for(level: str) -> set:
    if level == "WARNING":
        return {"DRIVER"}
    if level == "MAJOR":
        return {"DRIVER", "DISPATCH"}
    return {"DRIVER", "DISPATCH", "CUSTOMER"}


def _bump(alert: dict):
    alert["updated_at"] = clock.now_iso()
    alert["version"] = alert.get("version", 0) + 1


def _compute_peak_deviation(task: dict, alert: dict) -> Decimal:
    """Max(0, temp_min - reading.temp, reading.temp - temp_max) across VALID
    readings on the same task with captured_at in [opened_at, resolved_at or now]."""
    opened_at = parse_iso8601(alert["opened_at"])
    end_at = parse_iso8601(alert.get("resolved_at")) if alert.get("resolved_at") else clock.now()
    temp_min = Decimal(str(task["temp_min_celsius"]))
    temp_max = Decimal(str(task["temp_max_celsius"]))
    peak = Decimal("0")
    for r in db.readings_for_task(task["id"]):
        if r["validity"] != "VALID":
            continue
        captured = parse_iso8601(r["captured_at"])
        if captured is None:
            continue
        if captured < opened_at or captured > end_at:
            continue
        temp = Decimal(str(r["temperature_celsius"]))
        below = temp_min - temp
        above = temp - temp_max
        candidate = max(Decimal("0"), below, above)
        if candidate > peak:
            peak = candidate
    return round_half_up_2(peak)


def _compute_duration(alert: dict) -> int:
    opened_at = parse_iso8601(alert["opened_at"])
    end_at = parse_iso8601(alert.get("resolved_at")) if alert.get("resolved_at") else clock.now()
    seconds = (end_at - opened_at).total_seconds()
    if seconds < 0:
        seconds = 0
    return int(seconds)


def recompute_level(alert: dict, task: dict):
    """Recompute duration_seconds, peak_deviation_celsius, level, and union notified_channels."""
    duration = _compute_duration(alert)
    peak = _compute_peak_deviation(task, alert)
    level = _level_for(duration, peak)
    alert["duration_seconds"] = duration
    alert["peak_deviation_celsius"] = to_float_2(peak)
    alert["level"] = level
    existing = set(alert.get("notified_channels", []))
    contrib = _channels_for(level)
    merged = existing | contrib
    alert["notified_channels"] = _stable_channels(merged)


def _stable_channels(s: set) -> list:
    order = ["DRIVER", "DISPATCH", "CUSTOMER"]
    return [c for c in order if c in s]


def maybe_open_alert(task: dict, reading: dict):
    """Auto-open an Alert when a VALID reading violates the bounds and no prior unresolved alert
    of the same violation exists on this task. Returns the alert (new or refreshed) or None."""
    if reading["validity"] != "VALID":
        return None
    if reading["violation"] == "WITHIN":
        return None

    # Look for existing unresolved alert on same task with same violation
    existing = None
    for a in db.alerts_for_task(task["id"]):
        if a["violation"] == reading["violation"] and a["status"] in UNRESOLVED_STATUSES:
            existing = a
            break

    if existing is None:
        # Open a new alert
        now_iso = clock.now_iso()
        alert = {
            "id": new_id(),
            "task_id": task["id"],
            "opening_reading_id": reading["id"],
            "violation": reading["violation"],
            "level": "WARNING",
            "duration_seconds": 0,
            "peak_deviation_celsius": 0.0,
            "notified_channels": [],
            "status": "OPEN",
            "opened_at": reading["captured_at"],
            "resolved_at": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        # Recompute level with the reading present
        recompute_level(alert, task)
        db.alerts.put(alert)
        audit.log("ALERT", alert["id"], "OPENED", "SYSTEM", "system")
        return alert
    else:
        # Recompute on existing unresolved alert
        recompute_level(existing, task)
        _bump(existing)
        return existing
