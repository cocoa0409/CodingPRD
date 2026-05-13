"""Run-sheet lifecycle: create, transitions, cascades, vehicle/substitute selection."""
from __future__ import annotations

from datetime import timedelta

import db
from clock import iso, now
from errors import err
from services.audit import append_audit
from services.route_calc import compute_duration_minutes_peak_adjusted
from services.util import (
    parse_dt, time_in_peak_windows,
    intervals_overlap_closed_closed,
)


MIN_CAPACITY = 20
OCCUPATION_BUFFER_MIN = 15
OVERFLOW_TOLERANCE_PCT = 10


def _route_version_for(route: dict) -> dict | None:
    """Return the RouteVersion row that matches (code, version_number) currently."""
    code = route.get("code")
    vn = route.get("version_number")
    for rv in db.route_versions.values():
        if rv.get("route_code") == code and rv.get("version_number") == vn:
            return rv
    return None


def compute_run_arrival(route: dict, scheduled_departure_dt) -> str:
    """Compute scheduled_arrival via PEAK_ADJUSTED variant."""
    rv = _route_version_for(route)
    peak_windows = (rv.get("peak_windows") if rv else None) or route.get("peak_windows", [])
    is_peak = time_in_peak_windows(scheduled_departure_dt, peak_windows)
    distance = route.get("estimated_distance_km") or 0.0
    intermediate_count = len(route.get("intermediate_stop_ids", []))
    duration = compute_duration_minutes_peak_adjusted(distance, intermediate_count, is_peak)
    arrival = scheduled_departure_dt + timedelta(minutes=duration)
    return iso(arrival)


def _vehicle_overlap_conflict(vehicle_id: str, dep_dt, arr_dt, exclude_rs_id=None) -> bool:
    """Closed-closed overlap of vehicle occupation windows
    [scheduled_departure - 15m, scheduled_arrival + 15m]."""
    a_start = dep_dt - timedelta(minutes=OCCUPATION_BUFFER_MIN)
    a_end = arr_dt + timedelta(minutes=OCCUPATION_BUFFER_MIN)
    for rs in db.run_sheets.values():
        if exclude_rs_id and rs["id"] == exclude_rs_id:
            continue
        if rs.get("assigned_vehicle_id") != vehicle_id:
            continue
        if rs.get("status") not in ("PLANNED", "BOARDING", "IN_TRANSIT", "DELAYED"):
            continue
        b_start = parse_dt(rs["scheduled_departure"]) - timedelta(minutes=OCCUPATION_BUFFER_MIN)
        b_end = parse_dt(rs["scheduled_arrival"]) + timedelta(minutes=OCCUPATION_BUFFER_MIN)
        if intervals_overlap_closed_closed(a_start, a_end, b_start, b_end):
            return True
    return False


def _driver_overlap_conflict(driver_id: str, dep_dt, arr_dt, exclude_rs_id=None) -> bool:
    """Closed-open overlap with touching boundaries treated as conflict."""
    for rs in db.run_sheets.values():
        if exclude_rs_id and rs["id"] == exclude_rs_id:
            continue
        if rs.get("assigned_driver_id") != driver_id:
            continue
        if rs.get("status") not in ("PLANNED", "BOARDING", "IN_TRANSIT", "DELAYED"):
            continue
        b_start = parse_dt(rs["scheduled_departure"])
        b_end = parse_dt(rs["scheduled_arrival"])
        # touching counts as conflict
        if not (arr_dt < b_start or b_end < dep_dt):
            return True
    return False


def _vehicle_maintenance_intersects(vehicle: dict, dep_dt, arr_dt) -> bool:
    """Does vehicle's maintenance window intersect run's occupation [dep-15m, arr+15m]?"""
    ms = vehicle.get("maintenance_window_start")
    me = vehicle.get("maintenance_window_end")
    if not ms or not me:
        return False
    a_start = dep_dt - timedelta(minutes=OCCUPATION_BUFFER_MIN)
    a_end = arr_dt + timedelta(minutes=OCCUPATION_BUFFER_MIN)
    b_start = parse_dt(ms)
    b_end = parse_dt(me)
    return intervals_overlap_closed_closed(a_start, a_end, b_start, b_end)


def vehicle_rotation_select(dep_dt, arr_dt) -> dict:
    """Pick a vehicle for a new run via the rotation rule. Raises ERR_NO_VEHICLE_AVAILABLE."""
    candidates = []
    for v in db.vehicles.values():
        if v.get("status") != "ACTIVE":
            continue
        if v.get("seat_capacity", 0) < MIN_CAPACITY:
            continue
        if _vehicle_maintenance_intersects(v, dep_dt, arr_dt):
            continue
        if _vehicle_overlap_conflict(v["id"], dep_dt, arr_dt):
            continue
        candidates.append(v)
    if not candidates:
        raise err("ERR_NO_VEHICLE_AVAILABLE",
                  "No eligible vehicle available for rotation")
    # Sort: ascending last_run_completed_at (null = -inf), tie-break plate_number asc
    def _key(v):
        lrc = v.get("last_run_completed_at")
        return (0 if lrc is None else 1, lrc or "", v.get("plate_number") or "")
    candidates.sort(key=_key)
    return candidates[0]


def substitute_vehicle_select(run_sheet: dict) -> dict:
    """Pick a substitute vehicle. Waterfall: compliant subset first, else largest by capacity."""
    dep_dt = parse_dt(run_sheet["scheduled_departure"])
    arr_dt = parse_dt(run_sheet["scheduled_arrival"])

    # Count CONFIRMED riders + CHECKED_IN
    confirmed_count = sum(
        1 for r in db.reservations.values()
        if r.get("run_sheet_id") == run_sheet["id"]
        and r.get("status") in ("CONFIRMED", "CHECKED_IN")
    )

    excluded_ids = {run_sheet.get("assigned_vehicle_id")}
    # Also exclude any vehicle currently substituting another active run
    for rs in db.run_sheets.values():
        if rs["id"] == run_sheet["id"]:
            continue
        if rs.get("status") in ("PLANNED", "BOARDING", "IN_TRANSIT", "DELAYED"):
            sub = rs.get("substitute_vehicle_id")
            if sub:
                excluded_ids.add(sub)

    pool = []
    for v in db.vehicles.values():
        if v["id"] in excluded_ids:
            continue
        if v.get("status") != "ACTIVE":
            continue
        if v.get("seat_capacity", 0) < MIN_CAPACITY:
            continue
        if _vehicle_maintenance_intersects(v, dep_dt, arr_dt):
            continue
        if _vehicle_overlap_conflict(v["id"], dep_dt, arr_dt, exclude_rs_id=run_sheet["id"]):
            continue
        pool.append(v)

    if not pool:
        raise err("ERR_NO_SUBSTITUTE_VEHICLE",
                  "No substitute vehicle available")

    compliant = [v for v in pool if v.get("seat_capacity", 0) >= confirmed_count]
    if compliant:
        def _key(v):
            lrc = v.get("last_run_completed_at")
            return (0 if lrc is None else 1, lrc or "", v.get("plate_number") or "")
        compliant.sort(key=_key)
        return compliant[0]

    # Non-compliant fallback: largest by seat_capacity desc, tie-break plate_number asc
    non_compliant = sorted(pool, key=lambda v: (-(v.get("seat_capacity") or 0),
                                                  v.get("plate_number") or ""))
    largest = non_compliant[0]
    # Overflow tolerance check
    limit = largest["seat_capacity"] * (100 + OVERFLOW_TOLERANCE_PCT) / 100.0
    if confirmed_count > limit:
        raise err("ERR_NO_SUBSTITUTE_VEHICLE",
                  "No substitute vehicle within overflow tolerance")
    return largest


def get_vehicle_capacity(rs: dict) -> int:
    """Get effective vehicle capacity for this run."""
    vid = rs.get("substitute_vehicle_id") or rs.get("assigned_vehicle_id")
    v = db.vehicles.get(vid) if vid else None
    return int(v.get("seat_capacity", 0)) if v else 0


def recompute_capacity_remaining(rs: dict) -> int:
    """Recompute capacity_remaining = seat_capacity - count(CONFIRMED + CHECKED_IN)."""
    base = get_vehicle_capacity(rs)
    used = sum(1 for r in db.reservations.values()
               if r.get("run_sheet_id") == rs["id"]
               and r.get("status") in ("CONFIRMED", "CHECKED_IN"))
    rs["capacity_remaining"] = max(base - used, 0)
    return rs["capacity_remaining"]


def cancel_run_sheet_cascade(rs: dict, actor_role: str, actor_id: str,
                             cause: str | None = None) -> None:
    """Cancel a PLANNED run-sheet and cascade reservations -> CANCELLED."""
    if rs.get("status") != "PLANNED":
        # PRD: idempotent / state error
        raise err("ERR_INVALID_STATE",
                  f"Cannot cancel a {rs.get('status')} run-sheet")

    rs["status"] = "CANCELLED"
    db.stamp_update(rs)

    # Cascade: every CONFIRMED or WAITLISTED reservation -> CANCELLED
    from services.reservations_svc import cancel_reservation_cascade
    for r in list(db.reservations.values()):
        if r.get("run_sheet_id") != rs["id"]:
            continue
        if r.get("status") in ("CONFIRMED", "WAITLISTED"):
            cancel_reservation_cascade(r, actor_role=actor_role,
                                        actor_id=actor_id,
                                        cause=cause or "run_cancelled",
                                        is_cascade=True)
    recompute_capacity_remaining(rs)


def start_boarding(rs: dict, actor_role: str, actor_id: str) -> None:
    if rs.get("status") != "PLANNED":
        raise err("ERR_INVALID_STATE",
                  f"Run-sheet must be PLANNED to start boarding (current: {rs.get('status')})")

    # Vehicle must be ACTIVE
    vid = rs.get("assigned_vehicle_id")
    v = db.vehicles.get(vid) if vid else None
    if not v or v.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "Assigned vehicle is not ACTIVE")

    # within +/- 30 min of scheduled_departure
    sd = parse_dt(rs["scheduled_departure"])
    n = now()
    delta = abs((n - sd).total_seconds())
    if delta > 30 * 60:
        raise err("ERR_INVALID_STATE",
                  "Not within ±30 minutes of scheduled_departure")

    rs["status"] = "BOARDING"
    db.stamp_update(rs)

    # Promote WAITLISTED reservations in ascending waitlist_position order while
    # capacity_remaining allows.
    recompute_capacity_remaining(rs)
    wait = [r for r in db.reservations.values()
            if r.get("run_sheet_id") == rs["id"] and r.get("status") == "WAITLISTED"]
    wait.sort(key=lambda r: (r.get("waitlist_position") or 0))
    for r in wait:
        if rs["capacity_remaining"] <= 0:
            break
        r["status"] = "CONFIRMED"
        r["waitlist_position"] = None
        db.stamp_update(r)
        recompute_capacity_remaining(rs)


def depart(rs: dict, actor_role: str, actor_id: str) -> None:
    if rs.get("status") != "BOARDING":
        raise err("ERR_INVALID_STATE",
                  f"Run-sheet must be BOARDING to depart (current: {rs.get('status')})")

    rs["status"] = "IN_TRANSIT"
    db.stamp_update(rs)

    # Cascade: every CONFIRMED reservation that did NOT check in -> NO_SHOW
    for r in list(db.reservations.values()):
        if r.get("run_sheet_id") != rs["id"]:
            continue
        if r.get("status") != "CONFIRMED":
            continue
        _cascade_no_show(r, rs, actor_role=actor_role, actor_id=actor_id)
    recompute_capacity_remaining(rs)


def _cascade_no_show(reservation: dict, rs: dict, actor_role: str, actor_id: str) -> None:
    """Apply CONFIRMED -> NO_SHOW with penalty computation per scaffold."""
    from services.util import time_in_peak_windows

    # Peak flag from route version snapshot
    route = db.routes.get(rs.get("route_id"))
    rv = None
    if route:
        for r in db.route_versions.values():
            if r.get("route_code") == route.get("code") and \
                    r.get("version_number") == rs.get("route_version_number"):
                rv = r
                break
    peak_windows = (rv or {}).get("peak_windows") or (route or {}).get("peak_windows", [])
    is_peak = time_in_peak_windows(parse_dt(rs["scheduled_departure"]), peak_windows)
    delay_mitigation = 1 if (rs.get("delay_minutes_accumulated") or 0) >= 30 else 0

    # repeat_count: count prior NO_SHOW reservations for same employee whose
    # run's scheduled_departure is within [now-30d, now] exclusive of this run
    n = now()
    cutoff = n - timedelta(days=30)
    repeat = 0
    for other in db.reservations.values():
        if other["id"] == reservation["id"]:
            continue
        if other.get("employee_id") != reservation.get("employee_id"):
            continue
        if other.get("status") != "NO_SHOW":
            continue
        other_rs = db.run_sheets.get(other.get("run_sheet_id"))
        if not other_rs:
            continue
        sd = parse_dt(other_rs["scheduled_departure"])
        if cutoff <= sd <= n:
            repeat += 1

    raw = 10 + 5 * (1 if is_peak else 0) - 3 * delay_mitigation + 2 * repeat
    penalty = max(0, raw)

    reservation["status"] = "NO_SHOW"
    reservation["no_show_penalty_points"] = penalty
    db.stamp_update(reservation)
    append_audit(
        event_type="RESERVATION_NO_SHOW",
        subject_type="Reservation",
        subject_id=reservation["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"penalty_points": penalty,
                 "peak": is_peak,
                 "delay_mitigation": bool(delay_mitigation),
                 "repeat_count": repeat},
    )


def complete(rs: dict, actor_role: str, actor_id: str) -> None:
    if rs.get("status") not in ("IN_TRANSIT", "DELAYED"):
        raise err("ERR_INVALID_STATE",
                  f"Cannot complete from status {rs.get('status')}")

    n = now()
    rs["status"] = "COMPLETED"
    rs["completed_at"] = iso(n)
    db.stamp_update(rs)

    # Update vehicle.last_run_completed_at
    vid = rs.get("substitute_vehicle_id") or rs.get("assigned_vehicle_id")
    v = db.vehicles.get(vid) if vid else None
    if v:
        v["last_run_completed_at"] = iso(n)
        db.stamp_update(v)

    # Cascade: every CHECKED_IN reservation -> COMPLETED, and complete ridership rows
    for r in list(db.reservations.values()):
        if r.get("run_sheet_id") != rs["id"]:
            continue
        if r.get("status") == "CHECKED_IN":
            r["status"] = "COMPLETED"
            db.stamp_update(r)
            for rr in db.ridership_records.values():
                if rr.get("reservation_id") == r["id"]:
                    if rr.get("alighted_at") is None:
                        rr["alighted_at"] = iso(n)
                        if rr.get("alighted_stop_id") in (None, ""):
                            rr["alighted_stop_id"] = r.get("alighting_stop_id")
    recompute_capacity_remaining(rs)


def resume(rs: dict, actor_role: str, actor_id: str) -> None:
    if rs.get("status") != "DELAYED":
        raise err("ERR_INVALID_STATE",
                  f"Cannot resume from status {rs.get('status')}")
    rs["status"] = "IN_TRANSIT"
    db.stamp_update(rs)


def report_delay(rs: dict, body: dict, actor_role: str, actor_id: str) -> dict:
    if rs.get("status") not in ("PLANNED", "IN_TRANSIT", "DELAYED"):
        # Per PRD: report against PLANNED or IN_TRANSIT (DELAYED is implicitly allowed
        # since a run may accumulate delays while already in DELAYED — accept it).
        raise err("ERR_INVALID_STATE",
                  f"Cannot report delay against a {rs.get('status')} run")

    cause = body.get("cause")
    delay_min = body.get("delay_minutes")
    afs = body.get("affected_from_stop_id")
    if cause not in ("TRAFFIC", "BREAKDOWN", "WEATHER"):
        raise err("ERR_VALIDATION", "cause must be TRAFFIC|BREAKDOWN|WEATHER")
    if not isinstance(delay_min, int) or isinstance(delay_min, bool) or \
            not (1 <= delay_min <= 480):
        raise err("ERR_VALIDATION", "delay_minutes must be int in [1,480]")
    if not isinstance(afs, str) or afs not in db.stops:
        raise err("ERR_REFERENCE_NOT_FOUND",
                  "affected_from_stop_id not found")

    # Append delay event
    ev = {
        "run_sheet_id": rs["id"],
        "cause": cause,
        "delay_minutes": int(delay_min),
        "affected_from_stop_id": afs,
        "notification_dispatched": False,
        "substitute_dispatched": False,
        "reported_at": iso(now()),
    }
    db.stamp_create(ev, common_fields=False)
    db.delay_events[ev["id"]] = ev

    # Mutate run-sheet
    prior_status = rs.get("status")
    if prior_status in ("PLANNED", "IN_TRANSIT"):
        rs["status"] = "DELAYED"
    rs["delay_minutes_accumulated"] = (rs.get("delay_minutes_accumulated") or 0) + int(delay_min)
    new_arr = parse_dt(rs["scheduled_arrival"]) + timedelta(minutes=int(delay_min))
    rs["scheduled_arrival"] = iso(new_arr)
    db.stamp_update(rs)

    # Threshold: cumulative >= 30 -> dispatch IM notification
    if (rs["delay_minutes_accumulated"]) >= 30:
        ev["notification_dispatched"] = True

    # Substitute for BREAKDOWN
    if cause == "BREAKDOWN" and rs.get("substitute_vehicle_id") is None:
        try:
            sub = substitute_vehicle_select(rs)
            rs["substitute_vehicle_id"] = sub["id"]
            db.stamp_update(rs)
            ev["substitute_dispatched"] = True
            append_audit(
                event_type="SUBSTITUTE_DISPATCHED",
                subject_type="RunSheet",
                subject_id=rs["id"],
                actor_role=actor_role,
                actor_id=actor_id,
                payload={"substitute_vehicle_id": sub["id"], "auto": True},
            )
        except Exception as exc:
            # Re-raise the API error: callers expect the error to bubble
            raise

    append_audit(
        event_type="DELAY_REPORTED",
        subject_type="DelayEvent",
        subject_id=ev["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"run_sheet_id": rs["id"], "cause": cause,
                 "delay_minutes": int(delay_min)},
    )

    return ev


def dispatch_substitute(rs: dict, body: dict, actor_role: str, actor_id: str) -> None:
    vid = body.get("vehicle_id")
    if not isinstance(vid, str) or not vid:
        raise err("ERR_VALIDATION", "vehicle_id is required")
    v = db.vehicles.get(vid)
    if not v:
        raise err("ERR_REFERENCE_NOT_FOUND", "vehicle_id not found")

    if rs.get("status") not in ("PLANNED", "BOARDING", "IN_TRANSIT", "DELAYED"):
        raise err("ERR_INVALID_STATE",
                  f"Cannot dispatch substitute for run in status {rs.get('status')}")

    # Vehicle invariant: double-booking
    dep_dt = parse_dt(rs["scheduled_departure"])
    arr_dt = parse_dt(rs["scheduled_arrival"])
    if _vehicle_overlap_conflict(vid, dep_dt, arr_dt, exclude_rs_id=rs["id"]):
        raise err("ERR_VEHICLE_DOUBLE_BOOKED",
                  "Substitute vehicle conflicts with another assignment")

    rs["substitute_vehicle_id"] = vid
    db.stamp_update(rs)

    append_audit(
        event_type="SUBSTITUTE_DISPATCHED",
        subject_type="RunSheet",
        subject_id=rs["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"substitute_vehicle_id": vid, "auto": False},
    )


def create_run_sheet(body: dict, actor_role: str, actor_id: str) -> dict:
    # Validate inputs / FK
    route_id = body.get("route_id")
    sched_date = body.get("scheduled_date")
    sched_dep = body.get("scheduled_departure")
    driver_id = body.get("assigned_driver_id")
    veh_id = body.get("assigned_vehicle_id")

    if not isinstance(route_id, str) or not route_id:
        raise err("ERR_VALIDATION", "route_id is required")
    if not isinstance(sched_date, str) or not sched_date:
        raise err("ERR_VALIDATION", "scheduled_date is required")
    if not isinstance(sched_dep, str) or not sched_dep:
        raise err("ERR_VALIDATION", "scheduled_departure is required")
    if not isinstance(driver_id, str) or not driver_id:
        raise err("ERR_VALIDATION", "assigned_driver_id is required")

    route = db.routes.get(route_id)
    if not route:
        raise err("ERR_REFERENCE_NOT_FOUND", "route_id not found")
    driver = db.drivers.get(driver_id)
    if not driver:
        raise err("ERR_REFERENCE_NOT_FOUND", "assigned_driver_id not found")
    if veh_id is not None:
        veh = db.vehicles.get(veh_id)
        if not veh:
            raise err("ERR_REFERENCE_NOT_FOUND", "assigned_vehicle_id not found")
    else:
        veh = None

    # Route must be ACTIVE
    if route.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  f"Route must be ACTIVE (current: {route.get('status')})")

    dep_dt = parse_dt(sched_dep, "scheduled_departure")
    sched_date_dt = parse_dt(sched_date, "scheduled_date")
    arr_iso = compute_run_arrival(route, dep_dt)
    arr_dt = parse_dt(arr_iso)

    # Driver license: license_expiry_date strictly after scheduled_departure
    led = parse_dt(driver["license_expiry_date"], "license_expiry_date")
    if not (led > dep_dt):
        raise err("ERR_DRIVER_LICENSE_EXPIRED",
                  "Driver license expired before scheduled_departure")

    # Driver double-booking
    if _driver_overlap_conflict(driver_id, dep_dt, arr_dt):
        raise err("ERR_DRIVER_DOUBLE_BOOKED",
                  "Driver already assigned to a run that conflicts")

    # Vehicle assignment
    if veh is None:
        veh = vehicle_rotation_select(dep_dt, arr_dt)
    else:
        # Validate the supplied vehicle
        if veh.get("status") != "ACTIVE":
            raise err("ERR_INVALID_STATE",
                      f"assigned_vehicle is not ACTIVE (current: {veh.get('status')})")
        if _vehicle_maintenance_intersects(veh, dep_dt, arr_dt):
            raise err("ERR_VEHICLE_HAS_BOOKED_RUNS",
                      "Vehicle maintenance window intersects run occupation")
        if _vehicle_overlap_conflict(veh["id"], dep_dt, arr_dt):
            raise err("ERR_VEHICLE_DOUBLE_BOOKED",
                      "Vehicle already assigned to a run that conflicts")

    rs = {
        "route_id": route["id"],
        "route_version_number": route["version_number"],
        "scheduled_date": iso(sched_date_dt),
        "scheduled_departure": iso(dep_dt),
        "scheduled_arrival": arr_iso,
        "assigned_vehicle_id": veh["id"],
        "assigned_driver_id": driver["id"],
        "substitute_vehicle_id": None,
        "status": "PLANNED",
        "capacity_remaining": veh["seat_capacity"],
        "completed_at": None,
        "delay_minutes_accumulated": 0,
    }
    db.stamp_create(rs)
    db.run_sheets[rs["id"]] = rs
    return rs
