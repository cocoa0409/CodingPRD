"""Duty-event append + edit processing, including validation pipeline,
HOS gating, violation creation, exemption consumption, and 34-hour restart
detection (PRD §3.3-§3.4, §3.5, §3.7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..errors import (
    ApiError,
    ERR_ANNOTATION_REQUIRED,
    ERR_CYCLE_LIMIT_EXCEEDED,
    ERR_DRIVER_NOT_BOUND,
    ERR_DUTY_EVENT_OUT_OF_ORDER,
    ERR_ELEVEN_HOUR_LIMIT_EXCEEDED,
    ERR_EXEMPTION_NOT_ACTIVE,
    ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED,
    ERR_INSUFFICIENT_REST,
    ERR_LOG_ALREADY_CERTIFIED,
    ERR_ODOMETER_DECREASED,
    ERR_VEHICLE_MISMATCH,
)
from ..store import new_id, store
from ..timeutil import clock, iso_now, local_date_str, parse_iso
from . import hos
from .daily_logs import find_or_create_daily_log, recompute_log_full
from .exemptions import active_exemption_for_driver_on_date


ON_VEHICLE_STATES = {"DRIVING", "ON_DUTY_NOT_DRIVING", "YARD_MOVES", "PERSONAL_CONVEYANCE"}
ON_DUTY_STATES = {"DRIVING", "ON_DUTY_NOT_DRIVING", "YARD_MOVES"}
REST_STATES = {"OFF_DUTY", "SLEEPER_BERTH"}


def _driver_events(driver_id: str) -> List[dict]:
    return [e for e in store.duty_events.values() if e.get("driver_id") == driver_id]


def _active_driver_events(driver_id: str) -> List[dict]:
    return [
        e
        for e in store.duty_events.values()
        if e.get("driver_id") == driver_id and e.get("edit_state", "ACTIVE") == "ACTIVE"
    ]


def _latest_event_time(driver_id: str) -> Optional[datetime]:
    events = _driver_events(driver_id)
    if not events:
        return None
    return max(parse_iso(e["event_time"]) for e in events)


def _latest_odometer_for_vehicle(vehicle_id: str) -> Optional[float]:
    best = None
    for e in store.duty_events.values():
        if e.get("vehicle_id") != vehicle_id:
            continue
        odo = e.get("odometer_miles")
        if odo is None:
            continue
        if best is None or float(odo) > best:
            best = float(odo)
    return best


def _detect_34h_restart(
    driver_events_with_new: List[dict],
    new_event_time: datetime,
    new_status: str,
) -> Optional[datetime]:
    """If the new event closes a continuous OFF_DUTY+SLEEPER_BERTH window
    >= 2040 minutes, return new_event_time; else None.

    A rest window "closes" when the driver transitions OUT of rest (i.e., the
    new event's status is not in REST_STATES).  We then look back through
    prior ACTIVE events that were in REST_STATES and accumulate.
    """
    if new_status in REST_STATES:
        # The window does not "close" until the driver leaves rest.
        return None
    # Walk backwards.  Need prior events (excluding the new one).
    prior_active = [
        e for e in driver_events_with_new
        if e.get("edit_state", "ACTIVE") == "ACTIVE"
        and parse_iso(e["event_time"]) < new_event_time
    ]
    prior_active.sort(key=lambda e: parse_iso(e["event_time"]))
    # Build intervals from the latest event back.
    if not prior_active:
        return None
    # Walk from the last prior event backward.
    total = 0
    end_of_rest = new_event_time
    cursor = new_event_time
    for e in reversed(prior_active):
        t = parse_iso(e["event_time"])
        if e["new_status"] in REST_STATES:
            total += int((cursor - t).total_seconds() // 60)
            cursor = t
        else:
            break
    if total >= hos.RESTART_MIN_MINUTES:
        return new_event_time
    return None


def _violation_rule_code(reason: str, cycle_type: str) -> str:
    if reason == "ELEVEN_HOUR":
        return "ELEVEN_HOUR_DRIVING"
    if reason == "FOURTEEN_HOUR":
        return "FOURTEEN_HOUR_WINDOW"
    if reason == "CYCLE":
        return "SEVENTY_HOUR_CYCLE" if cycle_type == "SEVENTY_HOUR_EIGHT_DAY" else "SIXTY_HOUR_CYCLE"
    raise ValueError(reason)


def _create_violation(
    driver: dict,
    triggering_event_id: str,
    reason: str,
    overage_minutes: int,
) -> dict:
    v = {
        "driver_id": driver["id"],
        "triggering_duty_event_id": triggering_event_id,
        "rule_code": _violation_rule_code(reason, driver.get("cycle_type", "SEVENTY_HOUR_EIGHT_DAY")),
        "detected_at": iso_now(clock.now()),
        "status": "OPEN",
        "reported_to_fmcsa_at": None,
        "fmcsa_report_id": None,
        "overage_minutes": int(overage_minutes),
    }
    store.stamp_create(v)
    store.violations[v["id"]] = v
    return v


def _expire_active_exemptions_on_rest_completion(
    driver_id: str,
    new_event_time: datetime,
    driver_events: List[dict],
) -> None:
    """If an unbroken 10h OFF_DUTY+SLEEPER_BERTH rest just completed, expire
    any ACTIVE exemptions for the driver (PRD §3.6)."""
    # Compute continuous rest ending at new_event_time using helper.
    cont = hos.continuous_off_duty_minutes_ending_at(driver_events, new_event_time)
    if cont >= hos.QUALIFYING_BREAK_MINUTES:
        for ex in store.adverse_exemptions.values():
            if ex.get("driver_id") == driver_id and ex.get("status") == "ACTIVE":
                ex["status"] = "EXPIRED"
                store.bump(ex)


def append_duty_event(driver: dict, payload: dict) -> dict:
    """Process a duty-event create request (after auth/role/existence checks
    are done by the caller).  Runs the priority-ordered validation pipeline
    and on success appends an ACTIVE DutyEvent and cascades side effects.
    """
    # ---- Parse & basic shape checks (priority 23 falls back here too) ----
    from ..util import (
        optional_number,
        optional_str,
        require_enum,
        require_number,
        require_str,
    )

    new_status = require_enum(
        payload,
        "new_status",
        [
            "OFF_DUTY",
            "SLEEPER_BERTH",
            "DRIVING",
            "ON_DUTY_NOT_DRIVING",
            "PERSONAL_CONVEYANCE",
            "YARD_MOVES",
        ],
    )
    event_time_iso = require_str(payload, "event_time")
    try:
        event_time = parse_iso(event_time_iso)
    except Exception:
        raise ApiError(
            "ERR_INVALID_INPUT", 400, "event_time must be a valid ISO 8601 UTC timestamp."
        )
    latitude = require_number(payload, "latitude", minimum=-90.0, maximum=90.0)
    longitude = require_number(payload, "longitude", minimum=-180.0, maximum=180.0)
    vehicle_id = optional_str(payload, "vehicle_id")
    odometer_miles = optional_number(payload, "odometer_miles", minimum=0.0)
    annotation = optional_str(payload, "annotation")
    exemption_id = optional_str(payload, "adverse_conditions_exemption_id")

    # ---- Priority 4: bound check ----
    if new_status in ON_VEHICLE_STATES:
        if not driver.get("bound_vehicle_id"):
            raise ApiError(
                ERR_DRIVER_NOT_BOUND,
                409,
                "Driver must be bound to a vehicle to record this status.",
            )

    # ---- Priority 5: log certified state check ----
    tz = driver.get("home_terminal_timezone") or "America/New_York"
    target_log_date = local_date_str(event_time, tz)
    existing_log = None
    for log in store.daily_logs.values():
        if log["driver_id"] == driver["id"] and log["log_date"] == target_log_date:
            existing_log = log
            break
    if existing_log is not None and existing_log.get("status") in ("CERTIFIED", "RECERTIFIED"):
        raise ApiError(
            ERR_LOG_ALREADY_CERTIFIED,
            409,
            "Cannot append a duty event to a certified log; use the edit endpoint instead.",
        )

    # ---- Priority 7: strict monotonic event_time per driver ----
    latest_et = _latest_event_time(driver["id"])
    if latest_et is not None and event_time <= latest_et:
        raise ApiError(
            ERR_DUTY_EVENT_OUT_OF_ORDER,
            409,
            "event_time must be strictly greater than the latest accepted event_time.",
        )

    # ---- Priority 8: annotation required for PC / YM ----
    if new_status in ("PERSONAL_CONVEYANCE", "YARD_MOVES"):
        if not annotation or len(annotation) < 10:
            raise ApiError(
                ERR_ANNOTATION_REQUIRED,
                422,
                "PERSONAL_CONVEYANCE and YARD_MOVES events require annotation >= 10 chars.",
            )

    # ---- Determine whether exemption attaches to current 14-hour window ----
    active_events = _active_driver_events(driver["id"])
    # Validate exemption referential (priority 21) — needed before HOS checks
    # so the ADVERSE_EXTENDED variant can be applied to the limit checks.
    exemption: Optional[dict] = None
    if exemption_id:
        ex = store.adverse_exemptions.get(exemption_id)
        if (
            ex is None
            or ex.get("driver_id") != driver["id"]
            or ex.get("status") != "ACTIVE"
            or ex.get("applies_to_log_date") != target_log_date
        ):
            # Per priority order, ERR_EXEMPTION_NOT_ACTIVE is priority 21, AFTER
            # priority 9-12 HOS checks.  We surface 21 only if none of 9-12
            # would fail.  To keep things simple, we defer the actual raise
            # until after HOS checks unless the exemption clearly invalid
            # for the active path.  Since the spec says priority-ordered, we
            # surface HOS errors first.
            exemption = None  # treat as no exemption attached
            _invalid_exemption = True
        else:
            exemption = ex
            _invalid_exemption = False
    else:
        _invalid_exemption = False

    adverse_extended = exemption is not None

    # ---- Priority 9: SLEEPER_BERTH → DRIVING insufficient rest ----
    prev_status = driver.get("duty_status", "OFF_DUTY")
    if prev_status == "SLEEPER_BERTH" and new_status == "DRIVING":
        cont = hos.continuous_off_duty_minutes_ending_at(active_events, event_time)
        if cont < hos.QUALIFYING_BREAK_MINUTES:
            if not hos.sleeper_berth_pair_qualifies(active_events, event_time):
                raise ApiError(
                    ERR_INSUFFICIENT_REST,
                    409,
                    "SLEEPER_BERTH → DRIVING requires 10h reset or qualifying sleeper-berth pair.",
                )

    # ---- Priority 10: 11-hour driving limit ----
    if new_status == "DRIVING":
        rem = hos.available_driving_hours_minutes(active_events, event_time, adverse_extended)
        if rem <= 0:
            raise ApiError(
                ERR_ELEVEN_HOUR_LIMIT_EXCEEDED,
                409,
                "11-hour driving limit exceeded.",
            )

    # ---- Priority 11: 14-hour on-duty window ----
    if new_status in ON_DUTY_STATES:
        rem = hos.available_on_duty_window_minutes(active_events, event_time, adverse_extended)
        if rem <= 0:
            raise ApiError(
                ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED,
                409,
                "14-hour on-duty window exceeded.",
            )

    # ---- Priority 12: cycle limit ----
    if new_status in ON_DUTY_STATES:
        rem = hos.cycle_hours_remaining_minutes(
            active_events,
            event_time,
            driver.get("cycle_type", "SEVENTY_HOUR_EIGHT_DAY"),
            driver.get("last_34_hour_restart_completed_at"),
        )
        if rem <= 0:
            raise ApiError(
                ERR_CYCLE_LIMIT_EXCEEDED,
                409,
                "Cycle hours limit exceeded.",
            )

    # ---- Priority 13: vehicle mismatch ----
    if new_status in ON_VEHICLE_STATES:
        if not vehicle_id:
            raise ApiError(
                ERR_VEHICLE_MISMATCH,
                422,
                "vehicle_id is required for on-vehicle statuses and must match Driver.bound_vehicle_id.",
            )
        if vehicle_id != driver.get("bound_vehicle_id"):
            raise ApiError(
                ERR_VEHICLE_MISMATCH,
                422,
                "vehicle_id does not match the driver's bound vehicle.",
            )

    # ---- Priority 21: exemption validity (if attempted but invalid) ----
    if _invalid_exemption:
        raise ApiError(
            ERR_EXEMPTION_NOT_ACTIVE,
            422,
            "adverse_conditions_exemption_id references an inactive or mismatched exemption.",
        )

    # ---- Priority 22: odometer monotonic ----
    if odometer_miles is not None and vehicle_id:
        last_odo = _latest_odometer_for_vehicle(vehicle_id)
        if last_odo is not None and odometer_miles < last_odo:
            raise ApiError(
                ERR_ODOMETER_DECREASED,
                422,
                "odometer_miles cannot decrease for a vehicle.",
            )

    # ---- All validations passed — append and cascade. ----
    log = find_or_create_daily_log(driver, event_time)

    event = {
        "driver_id": driver["id"],
        "vehicle_id": vehicle_id,
        "new_status": new_status,
        "event_time": event_time_iso_normalized(event_time),
        "latitude": latitude,
        "longitude": longitude,
        "odometer_miles": odometer_miles,
        "annotation": annotation,
        "edit_state": "ACTIVE",
        "superseded_by_event_id": None,
        "daily_log_id": log["id"],
        "adverse_conditions_exemption_id": exemption_id if exemption else None,
    }
    store.stamp_create(event, versioned=False)
    store.duty_events[event["id"]] = event

    # ---- Driver status update ----
    driver["duty_status"] = new_status
    store.bump(driver)

    # ---- Vehicle odometer update ----
    if vehicle_id and odometer_miles is not None:
        veh = store.vehicles.get(vehicle_id)
        if veh is not None:
            veh["odometer_miles"] = odometer_miles
            store.bump(veh)

    # ---- 34-hour restart detection ----
    new_events_with_this = _active_driver_events(driver["id"])  # includes the new one now
    restart_at = _detect_34h_restart(new_events_with_this, event_time, new_status)
    if restart_at is not None:
        driver["last_34_hour_restart_completed_at"] = event_time_iso_normalized(restart_at)
        store.bump(driver)

    # ---- Exemption consumption ----
    if exemption is not None and new_status == "DRIVING":
        # An exemption is consumed when this DRIVING event_time is past the
        # driver's UNEXTENDED 11-h or 14-h limit (i.e., would have been rejected
        # without the extension).
        prior_active = [e for e in new_events_with_this if e["id"] != event["id"]]
        un_drv = hos.available_driving_hours_minutes(prior_active, event_time, False)
        un_win = hos.available_on_duty_window_minutes(prior_active, event_time, False)
        if un_drv <= 0 or un_win <= 0:
            exemption["status"] = "CONSUMED"
            store.bump(exemption)

    # ---- Rest completion expires ACTIVE exemptions (10h continuous) ----
    if new_status not in REST_STATES:
        # We just left rest; check if a 10h rest just completed.
        # Use the prior events (without the new event) ending at event_time.
        prior_active = [e for e in new_events_with_this if e["id"] != event["id"]]
        cont = hos.continuous_off_duty_minutes_ending_at(prior_active, event_time)
        if cont >= hos.QUALIFYING_BREAK_MINUTES:
            for ex in list(store.adverse_exemptions.values()):
                if ex.get("driver_id") == driver["id"] and ex.get("status") == "ACTIVE":
                    ex["status"] = "EXPIRED"
                    store.bump(ex)

    # ---- DailyLog recompute ----
    recompute_log_full(log)
    # Also recompute neighboring logs whose totals may have changed because the
    # interval that was previously open-ended on the prior event now closes at
    # this event's time.
    if new_events_with_this:
        # Find prior event's log (if different from current).
        sorted_e = sorted(new_events_with_this, key=lambda e: parse_iso(e["event_time"]))
        idx = next((i for i, e in enumerate(sorted_e) if e["id"] == event["id"]), None)
        if idx is not None and idx > 0:
            prev_log_id = sorted_e[idx - 1].get("daily_log_id")
            if prev_log_id and prev_log_id != log["id"]:
                prev_log = store.daily_logs.get(prev_log_id)
                if prev_log is not None:
                    recompute_log_full(prev_log)

    # ---- Violation creation (cascade depth 2) ----
    # Per PRD §3.4 + SCAFFOLD state machine: a violation is generated on the
    # transition that "closes the over-limit DRIVING interval" — i.e., when a
    # DRIVING interval ends.  We also check on on-duty status events whose own
    # event_time pushes the cumulative on-duty past the cap.
    #
    # We compute remaining minutes "at event_time" using the snapshot BEFORE
    # the new event was appended (intervals are open at event_time so the new
    # event itself does not contribute yet).
    events_excluding_new = [e for e in new_events_with_this if e["id"] != event["id"]]
    closes_driving_interval = prev_status == "DRIVING" and new_status != "DRIVING"

    if closes_driving_interval or new_status == "DRIVING":
        drv_rem = hos.available_driving_hours_minutes(
            events_excluding_new, event_time, adverse_extended
        )
        if drv_rem < 0:
            _create_violation(driver, event["id"], "ELEVEN_HOUR", -drv_rem)

    if closes_driving_interval or new_status in ON_DUTY_STATES:
        win_rem = hos.available_on_duty_window_minutes(
            events_excluding_new, event_time, adverse_extended
        )
        if win_rem < 0:
            _create_violation(driver, event["id"], "FOURTEEN_HOUR", -win_rem)
        cyc_rem = hos.cycle_hours_remaining_minutes(
            events_excluding_new,
            event_time,
            driver.get("cycle_type", "SEVENTY_HOUR_EIGHT_DAY"),
            driver.get("last_34_hour_restart_completed_at"),
        )
        if cyc_rem < 0:
            _create_violation(driver, event["id"], "CYCLE", -cyc_rem)

    return event


def event_time_iso_normalized(dt: datetime) -> str:
    """Return ISO 8601 UTC string with three fractional digits."""
    from ..timeutil import iso_now
    return iso_now(dt)


def edit_duty_event(driver: dict, event_id: str, payload: dict) -> dict:
    """Driver edit on an earlier event.  The old event becomes SUPERSEDED,
    a fresh ACTIVE event is appended carrying the corrected fields.

    Triggers DailyLog status → RECERTIFIED, re-evaluates Violations.
    """
    from ..errors import ERR_EDIT_WINDOW_EXPIRED, ERR_NOT_FOUND
    from ..util import optional_number, optional_str

    old = store.duty_events.get(event_id)
    if old is None or old.get("driver_id") != driver["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, "Duty event not found for this driver.")
    if old.get("edit_state") != "ACTIVE":
        raise ApiError(ERR_NOT_FOUND, 404, "Duty event is already superseded.")

    # Edit window check.
    et = parse_iso(old["event_time"])
    now = clock.now()
    if now >= et + timedelta(days=8):
        raise ApiError(ERR_EDIT_WINDOW_EXPIRED, 422, "Edit window has expired.")

    # Build new event by merging the old fields with any provided updates.
    new_status_in = payload.get("new_status", old["new_status"])
    event_time_in = payload.get("event_time", old["event_time"])
    latitude_in = payload.get("latitude", old["latitude"])
    longitude_in = payload.get("longitude", old["longitude"])
    odometer_in = payload.get("odometer_miles", old.get("odometer_miles"))
    annotation_in = payload.get("annotation", old.get("annotation"))

    # Light validation.
    if new_status_in not in {
        "OFF_DUTY",
        "SLEEPER_BERTH",
        "DRIVING",
        "ON_DUTY_NOT_DRIVING",
        "PERSONAL_CONVEYANCE",
        "YARD_MOVES",
    }:
        raise ApiError("ERR_INVALID_INPUT", 400, "Invalid new_status.")
    try:
        new_event_time = parse_iso(event_time_in)
    except Exception:
        raise ApiError("ERR_INVALID_INPUT", 400, "Invalid event_time.")
    if not isinstance(latitude_in, (int, float)) or not -90 <= float(latitude_in) <= 90:
        raise ApiError("ERR_INVALID_INPUT", 400, "Invalid latitude.")
    if not isinstance(longitude_in, (int, float)) or not -180 <= float(longitude_in) <= 180:
        raise ApiError("ERR_INVALID_INPUT", 400, "Invalid longitude.")

    new_event = {
        "driver_id": driver["id"],
        "vehicle_id": old.get("vehicle_id"),
        "new_status": new_status_in,
        "event_time": iso_now(new_event_time),
        "latitude": float(latitude_in),
        "longitude": float(longitude_in),
        "odometer_miles": odometer_in,
        "annotation": annotation_in,
        "edit_state": "ACTIVE",
        "superseded_by_event_id": None,
        "daily_log_id": old.get("daily_log_id"),
        "adverse_conditions_exemption_id": old.get("adverse_conditions_exemption_id"),
    }
    store.stamp_create(new_event, versioned=False)
    store.duty_events[new_event["id"]] = new_event

    # Supersede the old event.
    old["edit_state"] = "SUPERSEDED"
    old["superseded_by_event_id"] = new_event["id"]

    # Recompute affected daily log(s).
    log = store.daily_logs.get(new_event["daily_log_id"])
    if log is not None:
        cur_status = log.get("status", "UNCERTIFIED")
        if cur_status in ("CERTIFIED", "RECERTIFIED"):
            log["status"] = "RECERTIFIED"
            log["certification_count"] = int(log.get("certification_count", 0)) + 1
        recompute_log_full(log)

    # Re-evaluate violations on the affected window.
    _reevaluate_violations(driver)

    return new_event


def _reevaluate_violations(driver: dict) -> None:
    """Walk OPEN/ACKNOWLEDGED violations for this driver; if the recomputed
    minutes-remaining at the triggering event's event_time is now non-negative,
    flip status to RESOLVED."""
    active_events = _active_driver_events(driver["id"])
    for v in list(store.violations.values()):
        if v.get("driver_id") != driver["id"]:
            continue
        if v.get("status") not in ("OPEN", "ACKNOWLEDGED"):
            continue
        trig = store.duty_events.get(v.get("triggering_duty_event_id"))
        if trig is None:
            continue
        et = parse_iso(trig["event_time"])
        events_excluding = [e for e in active_events if e["id"] != trig["id"]]
        rule = v.get("rule_code")
        ok = False
        if rule == "ELEVEN_HOUR_DRIVING":
            rem = hos.available_driving_hours_minutes(events_excluding, et, False)
            ok = rem >= 0
        elif rule == "FOURTEEN_HOUR_WINDOW":
            rem = hos.available_on_duty_window_minutes(events_excluding, et, False)
            ok = rem >= 0
        elif rule in ("SEVENTY_HOUR_CYCLE", "SIXTY_HOUR_CYCLE"):
            rem = hos.cycle_hours_remaining_minutes(
                events_excluding,
                et,
                driver.get("cycle_type", "SEVENTY_HOUR_EIGHT_DAY"),
                driver.get("last_34_hour_restart_completed_at"),
            )
            ok = rem >= 0
        if ok:
            v["status"] = "RESOLVED"
            store.bump(v)
