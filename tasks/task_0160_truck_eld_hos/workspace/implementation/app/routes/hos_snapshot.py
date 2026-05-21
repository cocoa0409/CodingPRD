"""/drivers/{id}/hos-snapshot endpoint."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import ApiError, ERR_NOT_FOUND
from ..services import hos
from ..services.exemptions import active_exemption_for_driver_on_date
from ..store import store
from ..timeutil import clock, iso_now, local_date_str


hos_snapshot_bp = Blueprint("hos_snapshot", __name__)


@hos_snapshot_bp.get("/drivers/<driver_id>/hos-snapshot")
@require_auth({"Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def get_snapshot(driver_id: str):
    driver = store.drivers.get(driver_id)
    if driver is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")

    now = clock.now()
    active_events = [
        e
        for e in store.duty_events.values()
        if e.get("driver_id") == driver_id and e.get("edit_state", "ACTIVE") == "ACTIVE"
    ]

    tz = driver.get("home_terminal_timezone") or "America/New_York"
    today = local_date_str(now, tz)
    active_ex = active_exemption_for_driver_on_date(driver_id, today)
    has_extension = active_ex is not None

    drv_un = hos.available_driving_hours_minutes(active_events, now, False)
    win_un = hos.available_on_duty_window_minutes(active_events, now, False)
    cyc = hos.cycle_hours_remaining_minutes(
        active_events,
        now,
        driver.get("cycle_type", "SEVENTY_HOUR_EIGHT_DAY"),
        driver.get("last_34_hour_restart_completed_at"),
    )

    body = {
        "driver_id": driver_id,
        "cycle_type": driver.get("cycle_type", "SEVENTY_HOUR_EIGHT_DAY"),
        "duty_status": driver.get("duty_status", "OFF_DUTY"),
        "computed_at": iso_now(now),
        "unextended": {
            "available_driving_minutes_remaining": drv_un,
            "available_on_duty_window_minutes_remaining": win_un,
            "cycle_hours_minutes_remaining": cyc,
        },
    }
    # Cycle is NEVER extended by an adverse-conditions exemption.
    if has_extension:
        drv_ex = hos.available_driving_hours_minutes(active_events, now, True)
        win_ex = hos.available_on_duty_window_minutes(active_events, now, True)
        body["adverse_extended"] = {
            "available_driving_minutes_remaining": drv_ex,
            "available_on_duty_window_minutes_remaining": win_ex,
            "cycle_hours_minutes_remaining": cyc,
            "exemption_id": active_ex["id"],
        }
    return ok_object(body)
