"""Restock runs: forecasting, dispatch, arrival, completion, verification."""
from datetime import datetime

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_SITE_NOT_ACTIVE, ERR_DRIVER_CERT_EXPIRED,
    ERR_DRIVER_ROUTE_CONFLICT, ERR_DOT_PAYLOAD_EXCEEDED, ERR_EMPTY_ROUTE,
    ERR_DEPOT_STOCK_LOW, ERR_VALIDATION, ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import get_actor, require_roles
from response import success_object, success_list
from services import core
from util import body, req_str, req_int, req_date, paginate, sorted_by_creation

bp = Blueprint("logistics", __name__)

RUN_READ_ROLES = ("PlatformAdmin", "Driver", "SiteClerk")


def _get_run(run_id):
    r = db.restock_runs.get(run_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Restock run not found")
    return r


def _days_between(a, b):
    """Whole days from date string a to date string b."""
    da = datetime.strptime(a, "%Y-%m-%d").date()
    db_ = datetime.strptime(b, "%Y-%m-%d").date()
    return (db_ - da).days


def restock_suggested_qty(site, planned_date):
    """restock_suggested_qty (SCAFFOLD calculations)."""
    today = db.current_date()
    window_start = _shift_days(today, -core.FORECAST_WINDOW_DAYS)
    swaps = 0
    for o in db.exchange_orders.values():
        if (
            o["site_id"] == site["id"]
            and o["status"] == "COMPLETED"
            and o["business_date"] is not None
            and window_start <= o["business_date"] < today
        ):
            swaps += 1
    # avg_daily_swaps = swaps / 14 (exact rational); forecast = ceil(avg * days_until)
    days_until = max(0, _days_between(today, planned_date))
    forecast = -(-(swaps * days_until) // core.FORECAST_WINDOW_DAYS)  # ceil
    full, _, _ = core.cage_counts(site["id"])
    projected_full = full - forecast
    suggested = min(
        site["cage_capacity_cylinders"] - full,
        max(0, site["par_level_full"] - projected_full),
    )
    return suggested


def _shift_days(date_str, delta):
    from datetime import timedelta
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (d + timedelta(days=delta)).isoformat()


@bp.route("/restock-runs", methods=["POST"])
def create_run():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    b = body()
    site_id = req_str(b, "site_id")
    driver_id = req_str(b, "driver_id")
    planned_date = req_date(b, "planned_date")
    expected = req_int(b, "expected_site_version")

    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "site_id does not reference an existing site")
    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "driver_id does not reference an existing driver")
    # Stage 5: OCC.
    if expected != site["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_site_version does not match current site version")

    planned_full = restock_suggested_qty(site, planned_date)
    _, empty_on_hand, _ = core.cage_counts(site_id)

    # Supersede: any existing DRAFT run for the same site is auto-cancelled.
    for r in db.restock_runs.values():
        if r["site_id"] == site_id and r["status"] == "DRAFT":
            r["status"] = "CANCELLED"
            db.touch(r)

    run = db.new_entity({
        "site_id": site_id,
        "driver_id": driver_id,
        "planned_date": planned_date,
        "planned_full_count": planned_full,
        "planned_empty_pickup_count": empty_on_hand,
        "delivered_full_count": None,
        "picked_up_empty_count": None,
        "variance_full_count": None,
        "verified_by": None,
        "status": "DRAFT",
    })
    db.restock_runs[run["id"]] = run
    db.touch(site)  # creation advances the site's version by one
    return success_object(core.serialize_run(run), 201)


@bp.route("/restock-runs/<runId>", methods=["GET"])
def get_run(runId):
    uid, role = get_actor()
    require_roles(role, RUN_READ_ROLES)
    return success_object(core.serialize_run(_get_run(runId)))


@bp.route("/restock-runs", methods=["GET"])
def list_runs():
    uid, role = get_actor()
    require_roles(role, RUN_READ_ROLES)
    items = list(db.restock_runs.values())
    for param in ("site_id", "driver_id", "status", "planned_date"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize_run(r) for r in page], total, limit, offset)


@bp.route("/restock-runs/<runId>/dispatch", methods=["POST"])
def dispatch_run(runId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    run = _get_run(runId)
    # Stage 6: state legality.
    if run["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT run can be dispatched")
    site = db.sites[run["site_id"]]
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_NOT_ACTIVE, 409, "Site is not ACTIVE")
    driver = db.drivers[run["driver_id"]]
    if driver["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Driver is not ACTIVE")
    # Stage 9: DOT gates.
    if run["planned_date"] > driver["dot_medical_expires_on"]:
        raise ApiError(ERR_DRIVER_CERT_EXPIRED, 409, "planned_date is after the driver's DOT medical expiry")
    payload = (
        run["planned_full_count"] * core.FULL_CYLINDER_LBS
        + run["planned_empty_pickup_count"] * core.EMPTY_CYLINDER_LBS
    )
    if payload > driver["vehicle_max_payload_lbs"]:
        raise ApiError(ERR_DOT_PAYLOAD_EXCEEDED, 409, "Planned payload exceeds vehicle_max_payload_lbs")
    # Stage 11: uniqueness / magnitude.
    for r in db.restock_runs.values():
        if (
            r["id"] != run["id"]
            and r["driver_id"] == run["driver_id"]
            and r["planned_date"] == run["planned_date"]
            and r["status"] in ("DISPATCHED", "IN_PROGRESS")
        ):
            raise ApiError(ERR_DRIVER_ROUTE_CONFLICT, 409, "Driver already has a dispatched/in-progress run on this date")
    if run["planned_full_count"] + run["planned_empty_pickup_count"] <= 0:
        raise ApiError(ERR_EMPTY_ROUTE, 422, "Route has no planned fulls or empty pickups")
    pool = core.depot_pool()
    if len(pool) < run["planned_full_count"]:
        raise ApiError(ERR_DEPOT_STOCK_LOW, 409, "Depot pool has fewer eligible cylinders than planned_full_count")

    for c in pool[:run["planned_full_count"]]:
        c["in_transit_run_id"] = run["id"]
        db.touch(c)
    run["status"] = "DISPATCHED"
    db.touch(run)
    return success_object(core.serialize_run(run))


@bp.route("/restock-runs/<runId>/arrive", methods=["POST"])
def arrive_run(runId):
    uid, role = get_actor()
    require_roles(role, ("Driver",))
    run = _get_run(runId)
    if uid != run["driver_id"]:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the assigned driver may mark arrival")
    if run["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DISPATCHED run can be arrived")
    if db.current_date() != run["planned_date"]:
        raise ApiError(ERR_INVALID_STATE, 409, "Arrival date must equal the run's planned_date")
    run["status"] = "IN_PROGRESS"
    db.touch(run)
    return success_object(core.serialize_run(run))


@bp.route("/restock-runs/<runId>/complete", methods=["POST"])
def complete_run(runId):
    uid, role = get_actor()
    require_roles(role, ("Driver",))
    run = _get_run(runId)
    if uid != run["driver_id"]:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the assigned driver may complete the run")
    b = body()
    delivered = req_int(b, "delivered_full_count")
    picked_up = req_int(b, "picked_up_empty_count")
    if run["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an IN_PROGRESS run can be completed")
    assigned = core.assigned_cylinder_count(run["id"])
    _, site_empty, _ = core.cage_counts(run["site_id"])
    if delivered < 0 or delivered > assigned:
        raise ApiError(ERR_VALIDATION, 400, "delivered_full_count must be between 0 and assigned_cylinder_count")
    if picked_up < 0 or picked_up > site_empty:
        raise ApiError(ERR_VALIDATION, 400, "picked_up_empty_count must be between 0 and the site's empty_on_hand")

    # Move the metal: delivered assigned cylinders arrive at the site.
    assigned_cyls = [c for c in db.cylinders.values() if c["in_transit_run_id"] == run["id"] and c["fill_status"] == "FULL"]
    assigned_cyls.sort(key=lambda c: (c["certified_on"], c["_created_seq"]))
    for c in assigned_cyls[:delivered]:
        c["current_site_id"] = run["site_id"]
        c["in_transit_run_id"] = None
        db.touch(c)
    # Undelivered assigned cylinders return to the depot.
    for c in assigned_cyls[delivered:]:
        c["in_transit_run_id"] = None
        db.touch(c)
    # Picked-up empties leave the site into transit.
    site_empties = [
        c for c in db.cylinders.values()
        if c["owner_kind"] == "FLEET"
        and c["current_site_id"] == run["site_id"]
        and c["in_transit_run_id"] is None
        and c["fill_status"] == "EMPTY"
        and c["cert_status"] != "CONDEMNED"
    ]
    site_empties.sort(key=lambda c: c["_created_seq"])
    for c in site_empties[:picked_up]:
        c["current_site_id"] = None
        c["in_transit_run_id"] = run["id"]
        db.touch(c)

    run["delivered_full_count"] = delivered
    run["picked_up_empty_count"] = picked_up
    run["variance_full_count"] = delivered - run["planned_full_count"]
    run["status"] = "COMPLETED"
    db.touch(run)
    return success_object(core.serialize_run(run))


@bp.route("/restock-runs/<runId>/verify", methods=["POST"])
def verify_run(runId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "SiteClerk"))
    run = _get_run(runId)
    if run["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a COMPLETED run can be verified")
    # Stage 14: segregation of duties.
    if uid == run["driver_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Verifier must differ from the run's driver")
    run["verified_by"] = uid
    run["status"] = "VERIFIED"
    db.touch(run)
    # Picked-up empties are accepted at the depot.
    for c in db.cylinders.values():
        if c["in_transit_run_id"] == run["id"]:
            c["in_transit_run_id"] = None
            db.touch(c)
    return success_object(core.serialize_run(run))


@bp.route("/restock-runs/<runId>/cancel", methods=["POST"])
def cancel_run(runId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    run = _get_run(runId)
    if run["status"] not in ("DRAFT", "DISPATCHED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT or DISPATCHED run can be cancelled")
    # Assigned cylinders return to the depot.
    for c in db.cylinders.values():
        if c["in_transit_run_id"] == run["id"]:
            c["in_transit_run_id"] = None
            db.touch(c)
    run["status"] = "CANCELLED"
    db.touch(run)
    return success_object(core.serialize_run(run))
