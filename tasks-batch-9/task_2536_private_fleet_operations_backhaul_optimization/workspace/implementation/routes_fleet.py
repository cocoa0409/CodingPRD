"""Drivers, tractors and trailers -- PRD §3.2 and §3.3."""

from flask import Blueprint, g

import calc
from core import (
    ALL_ROLES, apply_filters, auth, bump, fail, must_exist, new_row, out, page,
    respond, db,
)
import validate as v

bp = Blueprint("fleet_assets", __name__)

READ_ROLES = ALL_ROLES
COMMITTED = calc.COMMITTED_PLAN_STATUSES


# ===========================================================================
# Drivers
# ===========================================================================
@bp.post("/drivers")
def create_driver():
    auth(["TransportManager"])
    data = v.body()
    domicile = v.fk(data, "domicile_id", "domiciles")
    plan = v.fk(data, "pay_plan_id", "pay_plans")
    driver_code = v.rstr(data, "driver_code", 1, 16)
    domicile_id = v.rref(data, "domicile_id")
    pay_plan_id = v.rref(data, "pay_plan_id")
    seniority_date = v.rdate(data, "seniority_date")
    from core import unique_code
    unique_code(db.drivers, "driver_code", driver_code)
    row = new_row({
        "driver_code": driver_code,
        "domicile_id": domicile_id,
        "pay_plan_id": pay_plan_id,
        "seniority_date": seniority_date,
        "status": "ACTIVE",
        "hos_status": "AVAILABLE",
        "drive_minutes_used_today": 0,
        "duty_minutes_used_today": 0,
        "weekly_on_duty_minutes": 0,
        "open_penalty_points": 0,
        "safety_score": 100,
        "coaching_hold": False,
        "ytd_gross_cents": 0,
    })
    db.drivers[row["id"]] = row
    # §3.3: the hire raises the domicile's headcount and recomputes its index.
    calc.recompute_domicile_counters(domicile)
    bump(domicile)
    return respond(out(row), 201)


@bp.get("/drivers/<driver_id>")
def get_driver(driver_id):
    auth(READ_ROLES)
    return respond(out(must_exist("drivers", driver_id)))


@bp.get("/drivers")
def list_drivers():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.drivers.values()), [
        ("domicile_id", v.qstr("domicile_id")),
        ("pay_plan_id", v.qstr("pay_plan_id")),
        ("status", v.qenum("status", ("ACTIVE", "TERMINATED"))),
        ("coaching_hold", v.qbool("coaching_hold")),
    ])
    return page(rows, limit, offset)


@bp.post("/drivers/<driver_id>/pay-plan-assignments")
def assign_pay_plan(driver_id):
    auth(["PayrollAnalyst"])
    driver = must_exist("drivers", driver_id)
    data = v.body()
    v.fk(data, "pay_plan_id", "pay_plans")
    pay_plan_id = v.rref(data, "pay_plan_id")
    expected = v.rint(data, "expected_driver_version")
    if expected != driver["version"]:
        fail("ERR_STALE_DRIVER_VERSION")
    driver["pay_plan_id"] = pay_plan_id
    bump(driver)
    return respond(out(driver))


@bp.post("/drivers/<driver_id>/hos-reset")
def hos_reset(driver_id):
    auth(["TransportManager"])
    driver = must_exist("drivers", driver_id)
    data = v.body()
    reset_kind = v.renum(data, "reset_kind", ("DAILY", "WEEKLY"))
    driver["drive_minutes_used_today"] = 0
    driver["duty_minutes_used_today"] = 0
    if reset_kind == "WEEKLY":
        driver["weekly_on_duty_minutes"] = 0
    driver["hos_status"] = "AVAILABLE"
    bump(driver)
    return respond(out(driver))


@bp.post("/drivers/<driver_id>/duty-log-adjustments")
def duty_log_adjustment(driver_id):
    auth(["TransportManager"])
    driver = must_exist("drivers", driver_id)
    data = v.body()
    drive = v.oint(data, "drive_minutes_used_today", None, 0)
    duty = v.oint(data, "duty_minutes_used_today", None, 0)
    weekly = v.oint(data, "weekly_on_duty_minutes", None, 0)
    if drive is not None:
        driver["drive_minutes_used_today"] = drive
    if duty is not None:
        driver["duty_minutes_used_today"] = duty
    if weekly is not None:
        driver["weekly_on_duty_minutes"] = weekly
    bump(driver)
    return respond(out(driver))


@bp.post("/drivers/<driver_id>/termination")
def terminate_driver(driver_id):
    auth(["TransportManager"])
    driver = must_exist("drivers", driver_id)
    data = v.body()
    reason = v.ostr(data, "termination_reason")
    if driver["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "TERMINATED is terminal.")
    for trip in db.trips.values():
        if trip.get("driver_id") == driver["id"] and trip["plan_status"] in COMMITTED:
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "A driver cannot be walked out from under committed work.",
            )
    driver["status"] = "TERMINATED"
    driver["_termination_reason"] = reason
    bump(driver)
    domicile = db.domiciles.get(driver["domicile_id"])
    if domicile is not None:
        calc.recompute_domicile_counters(domicile)
        bump(domicile)
    # §3.3: every SUBMITTED bid is passed over, lowering its posting's count.
    for bid in db.bids.values():
        if bid["driver_id"] == driver["id"] and bid["status"] == "SUBMITTED":
            bid["status"] = "PASSED_OVER"
            bump(bid)
            posting = db.postings.get(bid["route_posting_id"])
            if posting is not None:
                posting["bid_count"] = int(posting["bid_count"]) - 1
                bump(posting)
    return respond(out(driver))


# ===========================================================================
# Tractors
# ===========================================================================
def _derive_tractor(tractor):
    tractor["miles_since_pm"] = int(tractor["odometer_miles"]) - int(
        tractor["pm_last_service_odometer"]
    )
    return tractor


@bp.post("/tractors")
def create_tractor():
    auth(["MaintenanceCoordinator"])
    data = v.body()
    v.fk(data, "domicile_id", "domiciles")
    unit_code = v.rstr(data, "unit_code", 1, 16)
    domicile_id = v.rref(data, "domicile_id")
    odometer = v.rint(data, "odometer_miles", 0)
    pm_interval = v.rint(data, "pm_interval_miles", 1)
    pm_last = v.rint(data, "pm_last_service_odometer", 0, odometer)
    from core import unique_code
    unique_code(db.tractors, "unit_code", unit_code)
    row = new_row({
        "unit_code": unit_code,
        "domicile_id": domicile_id,
        "odometer_miles": odometer,
        "pm_interval_miles": pm_interval,
        "pm_last_service_odometer": pm_last,
        "miles_since_pm": 0,
        "pm_hold": False,
        "status": "AVAILABLE",
    })
    _derive_tractor(row)
    row["pm_hold"] = row["miles_since_pm"] >= row["pm_interval_miles"]
    db.tractors[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/tractors/<tractor_id>")
def get_tractor(tractor_id):
    auth(READ_ROLES)
    return respond(out(must_exist("tractors", tractor_id)))


@bp.get("/tractors")
def list_tractors():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.tractors.values()), [
        ("domicile_id", v.qstr("domicile_id")),
        ("status", v.qenum("status", ("AVAILABLE", "ASSIGNED", "IN_SHOP"))),
        ("pm_hold", v.qbool("pm_hold")),
    ])
    return page(rows, limit, offset)


@bp.patch("/tractors/<tractor_id>")
def patch_tractor(tractor_id):
    auth(["MaintenanceCoordinator"])
    tractor = must_exist("tractors", tractor_id)
    data = v.body()
    odometer = v.oint(data, "odometer_miles", None, 0)
    pm_interval = v.oint(data, "pm_interval_miles", None, 1)
    pm_last = v.oint(data, "pm_last_service_odometer", None, 0)
    new_odometer = tractor["odometer_miles"] if odometer is None else odometer
    new_last = tractor["pm_last_service_odometer"] if pm_last is None else pm_last
    if new_last > new_odometer:
        fail(
            "ERR_INVALID_REQUEST",
            "'pm_last_service_odometer' must not exceed 'odometer_miles'.",
        )
    tractor["odometer_miles"] = new_odometer
    tractor["pm_last_service_odometer"] = new_last
    if pm_interval is not None:
        tractor["pm_interval_miles"] = pm_interval
    _derive_tractor(tractor)
    tractor["pm_hold"] = tractor["miles_since_pm"] >= tractor["pm_interval_miles"]
    bump(tractor)
    return respond(out(tractor))


# ===========================================================================
# Trailers
# ===========================================================================
@bp.post("/trailers")
def create_trailer():
    auth(["MaintenanceCoordinator"])
    data = v.body()
    v.fk(data, "domicile_id", "domiciles")
    trailer_code = v.rstr(data, "trailer_code", 1, 16)
    domicile_id = v.rref(data, "domicile_id")
    trailer_type = v.renum(data, "trailer_type", ("DRY_VAN", "REEFER"))
    capacity_cases = v.rint(data, "capacity_cases", 1)
    inspection_due_at = v.rinstant(data, "inspection_due_at")
    from core import unique_code
    unique_code(db.trailers, "trailer_code", trailer_code)
    row = new_row({
        "trailer_code": trailer_code,
        "domicile_id": domicile_id,
        "trailer_type": trailer_type,
        "capacity_cases": capacity_cases,
        "inspection_due_at": inspection_due_at,
        "status": "AVAILABLE",
    })
    db.trailers[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/trailers/<trailer_id>")
def get_trailer(trailer_id):
    auth(READ_ROLES)
    return respond(out(must_exist("trailers", trailer_id)))


@bp.get("/trailers")
def list_trailers():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.trailers.values()), [
        ("domicile_id", v.qstr("domicile_id")),
        ("trailer_type", v.qenum("trailer_type", ("DRY_VAN", "REEFER"))),
        ("status", v.qenum("status", ("AVAILABLE", "ASSIGNED", "IN_SHOP"))),
    ])
    return page(rows, limit, offset)
