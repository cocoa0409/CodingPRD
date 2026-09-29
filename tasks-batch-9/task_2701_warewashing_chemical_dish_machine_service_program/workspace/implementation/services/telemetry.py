"""Telemetry ingest and cascade beta (breach -> alert -> health -> ticket)."""

from decimal import Decimal

import db
from errors import ApiError
from services import calc, derive
from util import dec, rhu

ALERT_ORDER = (
    "LOW_FINAL_RINSE_TEMP",
    "LOW_WASH_TEMP",
    "LOW_RINSE_PRESSURE",
    "HIGH_RINSE_PRESSURE",
    "HIGH_CYCLE_RATE",
    "CALIBRATION_OVERDUE",
)


def preceding_device_reading(placement_id, reading_at):
    """Greatest reading_at strictly earlier; ties keep the smaller created_at."""
    best = None
    for reading in db.rows("telemetry_readings"):
        if reading["placement_id"] != placement_id:
            continue
        if reading["source"] != "DEVICE":
            continue
        if reading["reading_at"] >= reading_at:
            continue
        if best is None or reading["reading_at"] > best["reading_at"]:
            best = reading
    return best


def baseline_cycle_count(placement, previous):
    if previous is None:
        return placement["initial_cycle_count"]
    return previous["cycle_count_total"]


def open_alert_of_type(placement_id, alert_type):
    for alert in db.rows("telemetry_alerts"):
        if (alert["placement_id"] == placement_id
                and alert["alert_type"] == alert_type
                and alert["status"] in calc.OPEN_ALERT_STATUSES):
            return alert
    return None


def ingest(placement, model, site, reading_at, cycle_count_total, wash_temp_f,
           final_rinse_temp_f, rinse_pressure_psi, source):
    previous = preceding_device_reading(placement["id"], reading_at)
    baseline = baseline_cycle_count(placement, previous)
    reading = db.insert("telemetry_readings", {
        "placement_id": placement["id"],
        "reading_at": reading_at,
        "cycle_count_total": cycle_count_total,
        "wash_temp_f": wash_temp_f,
        "final_rinse_temp_f": final_rinse_temp_f,
        "rinse_pressure_psi": rinse_pressure_psi,
        "source": source,
        "cycle_delta": cycle_count_total - baseline,
        "triggered_alert_types": [],
    }, common=False)

    derive.recompute_cycles(placement)

    if source == "DEVICE":
        opened = evaluate_alerts(placement, model, reading, previous)
        reading["triggered_alert_types"] = [a["alert_type"] for a in opened]
        apply_health(placement, opened)
        # PRD 3.4: the placement's own version increments by one for the ingest.
        db.mark(placement)
    derive.recompute_placement_alerts(placement)
    derive.recompute_site(site)
    return reading


def _open_alert(placement, reading, alert_type, severity, measured_value):
    if open_alert_of_type(placement["id"], alert_type) is not None:
        return None
    return db.insert("telemetry_alerts", {
        "placement_id": placement["id"],
        "triggering_reading_id": reading["id"],
        "alert_type": alert_type,
        "severity": severity,
        "status": "OPEN",
        "opened_at": db.now(),
        "acknowledged_by_user_id": None,
        "measured_value": measured_value,
    })


def evaluate_alerts(placement, model, reading, previous):
    opened = []

    def add(alert_type, severity, measured_value):
        alert = _open_alert(placement, reading, alert_type, severity,
                            measured_value)
        if alert is not None:
            opened.append(alert)

    rinse = reading["final_rinse_temp_f"]
    min_rinse = model["min_final_rinse_temp_f"]
    if rinse < min_rinse:
        severity = "CRITICAL" if rinse <= min_rinse - 5 else "WARNING"
        add("LOW_FINAL_RINSE_TEMP", severity, rinse)

    wash = reading["wash_temp_f"]
    min_wash = model["min_wash_temp_f"]
    if wash < min_wash:
        severity = "CRITICAL" if wash <= min_wash - 10 else "WARNING"
        add("LOW_WASH_TEMP", severity, wash)

    pressure = reading["rinse_pressure_psi"]
    min_pressure = model["min_rinse_pressure_psi"]
    if pressure < min_pressure:
        severity = "CRITICAL" if pressure <= min_pressure - 3 else "WARNING"
        add("LOW_RINSE_PRESSURE", severity, pressure)

    if pressure > model["max_rinse_pressure_psi"]:
        add("HIGH_RINSE_PRESSURE", "WARNING", pressure)

    if previous is not None:
        seconds = int(
            (reading["reading_at"] - previous["reading_at"]).total_seconds()
        )
        if seconds > 0:
            delta = dec(reading["cycle_delta"])
            limit = dec(model["racks_per_hour"]) * Decimal("1.10")
            if delta * Decimal(3600) > limit * dec(seconds):
                rate = rhu(delta * Decimal(3600) / dec(seconds), 4)
                add("HIGH_CYCLE_RATE", "WARNING", rate)

    if placement["cycles_since_calibration"] >= model["max_cycles_between_calibrations"]:
        add("CALIBRATION_OVERDUE", "WARNING",
            placement["cycles_since_calibration"])

    return opened


def apply_health(placement, opened):
    critical = [a for a in opened if a["severity"] == "CRITICAL"]
    if critical:
        derive.drive_down(placement, critical[0])
        return
    if opened:
        derive.drive_degraded(placement)
