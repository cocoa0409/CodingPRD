"""Ledger recomputation, derived postures, state machines and the cascade chains."""

from datetime import timedelta
from decimal import Decimal

from flask import g

import calc
from errors import ApiError
from store import clock, store
from util import ZERO, dec, half_open_overlap, closed_overlap, new_id, real_now, rhu


# ==========================================================================
# record creation / mutation bookkeeping (PRD 2.4)
# ==========================================================================
def base_record(versioned=True):
    record = {
        "id": new_id(),
        "created_at": real_now(),
        "_seq": store.next_seq(),
    }
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record, force=False):
    """Bump version + updated_at.  Idempotent within one request unless forced."""
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    key = record["id"]
    if force or key not in seen:
        record["version"] = int(record["version"]) + 1
        seen.add(key)
    record["updated_at"] = real_now()
    return record


def sorted_records(values):
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))


# ==========================================================================
# turf area derived fields
# ==========================================================================
def recompute_turf_moisture(area):
    reading = calc.latest_reading(area["id"])
    area["current_moisture_pct"] = reading["moisture_pct"] if reading else None


def recompute_turf_rei(area):
    """Latest REI expiry across the area's records whose posting is still up."""
    best = None
    for app in store.applications.values():
        if app["turf_area_id"] != area["id"]:
            continue
        if app["posting_status"] != "POSTED":
            continue
        expiry = app["rei_expires_at"]
        if expiry is None:
            continue
        if best is None or expiry > best:
            best = expiry
    area["rei_expires_at"] = best


def recompute_turf_nitrogen(area):
    applied, projected = calc.turf_nitrogen_load(area)
    area["nitrogen_applied_lb_per_1000_ytd"] = applied
    area["nitrogen_projected_lb_per_1000"] = projected


def sync_turf_ledgers(area, force=False):
    """Recompute the nitrogen ledgers; bump the version when a figure moved."""
    before = (
        area["nitrogen_applied_lb_per_1000_ytd"],
        area["nitrogen_projected_lb_per_1000"],
    )
    recompute_turf_nitrogen(area)
    after = (
        area["nitrogen_applied_lb_per_1000_ytd"],
        area["nitrogen_projected_lb_per_1000"],
    )
    if force or before != after:
        touch(area)


# ==========================================================================
# plan ledger and the compound close / reopen machine
# ==========================================================================
def recompute_plan_ledger(plan):
    plan["committed_nitrogen_lb"] = calc.plan_committed_nitrogen_lb(plan["id"])
    touch(plan)


def plan_tasks_of(plan_id):
    return [t for t in store.plan_tasks.values() if t["plan_id"] == plan_id]


def evaluate_plan_close(plan):
    if plan["status"] != "ACTIVE":
        return
    tasks = plan_tasks_of(plan["id"])
    if not tasks:
        return
    if all(t["status"] in ("COMPLETED", "CANCELLED") for t in tasks):
        plan["status"] = "CLOSED"
        recompute_plan_ledger(plan)


def evaluate_plan_reopen(plan):
    if plan["status"] != "CLOSED":
        return
    tasks = plan_tasks_of(plan["id"])
    if any(t["status"] in ("PLANNED", "SCHEDULED") for t in tasks):
        plan["status"] = "ACTIVE"
        recompute_plan_ledger(plan)


# ==========================================================================
# plan task transitions driven by the window it is bound to
# ==========================================================================
def revert_task_to_planned(task):
    task["status"] = "PLANNED"
    touch(task)
    plan = store.plans.get(task["plan_id"])
    if plan is not None:
        recompute_plan_ledger(plan)
        evaluate_plan_reopen(plan)
    area = store.turf_areas.get(task["turf_area_id"])
    if area is not None:
        recompute_turf_nitrogen(area)
        touch(area)


def advance_task_to_scheduled(task):
    task["status"] = "SCHEDULED"
    touch(task)
    plan = store.plans.get(task["plan_id"])
    if plan is not None:
        recompute_plan_ledger(plan)
        evaluate_plan_reopen(plan)
    area = store.turf_areas.get(task["turf_area_id"])
    if area is not None:
        recompute_turf_nitrogen(area)
        touch(area)


def complete_task(task):
    task["status"] = "COMPLETED"
    touch(task)
    plan = store.plans.get(task["plan_id"])
    if plan is not None:
        recompute_plan_ledger(plan)
        evaluate_plan_close(plan)


def cancel_task(task):
    origin = task["status"]
    if origin not in ("PLANNED", "SCHEDULED"):
        return
    task["status"] = "CANCELLED"
    touch(task)
    area = store.turf_areas.get(task["turf_area_id"])
    if area is not None:
        recompute_turf_nitrogen(area)
        touch(area)
    plan = store.plans.get(task["plan_id"])
    if plan is not None:
        if origin == "SCHEDULED":
            recompute_plan_ledger(plan)
        evaluate_plan_close(plan)


def revert_task_from_completed(task):
    task["status"] = "SCHEDULED"
    touch(task)
    plan = store.plans.get(task["plan_id"])
    if plan is not None:
        recompute_plan_ledger(plan)
        evaluate_plan_reopen(plan)


# ==========================================================================
# maintenance window transitions (deferral / cancellation are server-driven)
# ==========================================================================
DEFERRAL_LIMIT = 2


def defer_window(window, weather_event=None):
    """SCHEDULED -> DEFERRED, or CANCELLED when the deferral cap is exhausted."""
    if window["status"] != "SCHEDULED":
        return False
    if int(window["deferral_count"]) >= DEFERRAL_LIMIT:
        cancel_window(window)
        return False
    window["status"] = "DEFERRED"
    window["deferral_count"] = int(window["deferral_count"]) + 1
    touch(window)
    task_id = window.get("plan_task_id")
    if task_id:
        task = store.plan_tasks.get(task_id)
        if task is not None and task["status"] == "SCHEDULED":
            revert_task_to_planned(task)
    if weather_event is not None:
        weather_event["deferred_window_count"] = int(weather_event["deferred_window_count"]) + 1
    return True


def cancel_window(window):
    if window["status"] not in ("SCHEDULED", "DEFERRED"):
        return False
    task_id = window.get("plan_task_id")
    window["status"] = "CANCELLED"
    window["plan_task_id"] = None
    touch(window)
    if task_id:
        task = store.plan_tasks.get(task_id)
        if task is not None:
            cancel_task(task)
    return True


def window_overlap_conflict(turf_area_id, start, end, exclude_id=None):
    for other in store.windows.values():
        if other["turf_area_id"] != turf_area_id:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ("SCHEDULED", "DEFERRED", "IN_PROGRESS"):
            continue
        if closed_overlap(start, end, other["window_start"], other["window_end"]):
            return True
    return False


def _hole_occupancy(event, hole_number):
    """The interval during which a play event occupies one hole, or None."""
    if hole_number is None:
        return None
    if hole_number > int(event["holes_in_play"]):
        return None
    effective = event["effective_start_at"]
    if event["event_type"] == "SHOTGUN_START":
        return effective, event["end_at"]
    pace = calc.HOLE_PACE_MINUTES
    return (
        effective + timedelta(minutes=pace * (hole_number - 1)),
        effective + timedelta(minutes=pace * hole_number),
    )


def window_play_conflict(course_id, hole_number, start, end):
    if hole_number is None:
        return False
    extended_end = end + timedelta(minutes=calc.PLAY_CLEARANCE_MINUTES)
    for event in store.play_events.values():
        if event["course_id"] != course_id:
            continue
        if event["status"] not in ("SCHEDULED", "DELAYED"):
            continue
        occupancy = _hole_occupancy(event, hole_number)
        if occupancy is None:
            continue
        if half_open_overlap(start, extended_end, occupancy[0], occupancy[1]):
            return True
    return False


# ==========================================================================
# water ledgers, water posture and its mirror onto stations / runs
# ==========================================================================
def recompute_station_withdrawn(station):
    today = clock().date()
    total = ZERO
    for run in store.irrigation_runs.values():
        if run["pump_station_id"] != station["id"]:
            continue
        if run["status"] != "COMPLETED":
            continue
        if run["window_start"].date() != today:
            continue
        total += dec(run["volume_gal"])
    station["withdrawn_today_gal"] = rhu(total, 1)
    touch(station)


def stations_of(course_id):
    return [s for s in store.pump_stations.values() if s["course_id"] == course_id]


def recompute_course_water(course):
    station_ids = {s["id"] for s in stations_of(course["id"])}
    total = ZERO
    for run in store.irrigation_runs.values():
        if run["pump_station_id"] not in station_ids:
            continue
        if run["status"] != "COMPLETED":
            continue
        total += dec(run["volume_gal"])
    course["water_used_gal"] = rhu(total, 1)
    touch(course)
    rederive_water_posture(course)


def rederive_water_posture(course):
    previous = course["water_posture"]
    new_posture = calc.course_water_posture(course)
    if new_posture == previous:
        return
    course["water_posture"] = new_posture
    touch(course)
    if new_posture in ("RESTRICTED", "SUSPENDED"):
        for station in stations_of(course["id"]):
            if station["status"] == "ONLINE":
                station["status"] = "RESTRICTED"
                touch(station)
    if new_posture == "SUSPENDED":
        cancel_scheduled_runs_of_course(course["id"])
    if new_posture == "OPEN":
        for station in stations_of(course["id"]):
            if station["status"] == "RESTRICTED":
                station["status"] = "ONLINE"
                touch(station)


def cancel_scheduled_runs_of_course(course_id):
    station_ids = {s["id"] for s in stations_of(course_id)}
    for run in store.irrigation_runs.values():
        if run["pump_station_id"] not in station_ids:
            continue
        if run["status"] != "SCHEDULED":
            continue
        cancel_run(run)


def cancel_run(run):
    run["status"] = "CANCELLED"
    run["volume_gal"] = Decimal("0.0")
    touch(run)


# ==========================================================================
# play posture
# ==========================================================================
def rederive_play_posture(course):
    posture, frost_minutes = calc.course_play_posture(course["id"])
    course["play_posture"] = posture
    course["frost_delay_minutes"] = frost_minutes
    touch(course)


# ==========================================================================
# equipment scoring
# ==========================================================================
def rescore_equipment(unit):
    if unit["status"] == "RETIRED":
        return
    score, projected, flag = calc.equipment_replacement_score(unit)
    unit["replacement_score"] = score
    unit["replacement_score_projected"] = projected
    unit["replacement_flag"] = flag


def recompute_engine_hours(unit):
    unit["hours_since_service"] = rhu(
        dec(unit["engine_hours"]) - dec(unit["engine_hours_at_last_service"]), 1
    )


def equipment_retirement_cascade(unit):
    """Defer scheduled windows that depended on the retired machine's class."""
    unit_type = unit["unit_type"]
    course_id = unit["course_id"]
    remaining = any(
        other["id"] != unit["id"]
        and other["course_id"] == course_id
        and other["unit_type"] == unit_type
        and other["status"] == "IN_SERVICE"
        for other in store.equipment.values()
    )
    if remaining:
        return
    for window in sorted_records(list(store.windows.values())):
        if window["course_id"] != course_id:
            continue
        if window["status"] != "SCHEDULED":
            continue
        if window.get("required_unit_type") != unit_type:
            continue
        defer_window(window)


# ==========================================================================
# the weather chain
# ==========================================================================
def weather_declaration_cascade(course, event):
    rederive_play_posture(course)

    if event["event_type"] == "FROST":
        for play_event, effective, delayed in calc.frost_release_schedule(
            course["id"], event["delay_minutes"], event["expected_clear_at"]
        ):
            play_event["effective_start_at"] = effective
            play_event["delayed_minutes"] = delayed
            play_event["status"] = "DELAYED"
            touch(play_event)

    if event["event_type"] in ("LIGHTNING", "STORM_DAMAGE"):
        for play_event in sorted_records(list(store.play_events.values())):
            if play_event["course_id"] != course["id"]:
                continue
            if play_event["status"] == "SCHEDULED":
                reference = play_event["start_at"]
            elif play_event["status"] == "DELAYED":
                reference = play_event["effective_start_at"]
            else:
                continue
            if reference < event["expected_clear_at"]:
                play_event["status"] = "CANCELLED"
                touch(play_event)

    if event["event_type"] in ("FROST", "LIGHTNING", "HEAVY_RAIN"):
        for window in sorted_records(list(store.windows.values())):
            if window["course_id"] != course["id"]:
                continue
            if window["status"] != "SCHEDULED":
                continue
            if half_open_overlap(
                window["window_start"], window["window_end"],
                event["declared_at"], event["expected_clear_at"],
            ):
                defer_window(window, event)

    if event["event_type"] == "STORM_DAMAGE":
        affected = event["affected_turf_area_ids"] or []
        for area_id in affected:
            area = store.turf_areas.get(area_id)
            if area is None:
                continue
            if area["agronomic_status"] != "OUT_OF_PLAY":
                area["agronomic_status"] = "OUT_OF_PLAY"
                touch(area)
        for window in sorted_records(list(store.windows.values())):
            if window["turf_area_id"] not in affected:
                continue
            if window["task_type"] == "STORM_CLEANUP":
                continue
            if window["status"] not in ("SCHEDULED", "DEFERRED"):
                continue
            cancel_window(window)


def weather_clear_cascade(course, event):
    rederive_play_posture(course)
    if event["event_type"] != "STORM_DAMAGE":
        return
    still_named = set()
    for other in store.weather_events.values():
        if other["id"] == event["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if other["event_type"] != "STORM_DAMAGE":
            continue
        for area_id in other["affected_turf_area_ids"] or []:
            still_named.add(area_id)
    for area_id in event["affected_turf_area_ids"] or []:
        if area_id in still_named:
            continue
        area = store.turf_areas.get(area_id)
        if area is None:
            continue
        if area["agronomic_status"] == "OUT_OF_PLAY":
            area["agronomic_status"] = "ACTIVE"
            touch(area)


# ==========================================================================
# the void chain
# ==========================================================================
def void_application_cascade(application, reason):
    area = store.turf_areas.get(application["turf_area_id"])
    if area is not None:
        recompute_turf_nitrogen(area)
        recompute_turf_rei(area)
        touch(area)
    if reason == "SAFETY_VIOLATION":
        applicator = store.applicators.get(application["applicator_id"])
        if applicator is not None:
            applicator["suspended_at"] = clock()
            touch(applicator)
    task_id = application.get("plan_task_id")
    if task_id:
        task = store.plan_tasks.get(task_id)
        if task is not None and task["status"] == "COMPLETED":
            revert_task_from_completed(task)


# ==========================================================================
# licence category authority table (PRD 3.4)
# ==========================================================================
def category_authorises(license_category, required_category):
    if license_category == "CAT_3_AND_7":
        return required_category in ("CAT_3_TURF", "CAT_7_AQUATIC")
    return license_category == required_category


# ==========================================================================
# lookup helpers -- existence band of the validation order
# ==========================================================================
def require(collection, record_id, error_id):
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record
