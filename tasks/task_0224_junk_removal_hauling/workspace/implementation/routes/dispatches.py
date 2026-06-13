"""Dispatch routes: create (reserve), list, get, activate."""
from flask import Blueprint, request
import errors
from errors import err
from db import db
from middleware import authenticate, require_role
from response import success, success_list
import helpers as H
import models
from services.recompute import recompute_crew_reserved_minutes
from services import lookups as L
from util import parse_iso

bp = Blueprint("dispatches", __name__)


def _window_minutes(start_dt, end_dt):
    delta = end_dt - start_dt
    return int(delta.total_seconds() // 60)


def _job_has_freon(job_id):
    for it in db.job_items.values():
        if it["haul_job_id"] == job_id and it["category"] == "FREON_APPLIANCE":
            return True
    return False


@bp.route("/dispatches", methods=["POST"])
def create_dispatch():
    auth = authenticate()
    require_role(auth, {"Dispatcher"})
    body = H.get_json_body()
    H.require_fields(body, ["haul_job_id", "crew_id", "truck_id",
                            "window_start_utc", "window_end_utc", "expected_crew_version"])
    haul_job_id = H.as_str(body["haul_job_id"], "haul_job_id")
    crew_id = H.as_str(body["crew_id"], "crew_id")
    truck_id = H.as_str(body["truck_id"], "truck_id")

    # existence (priority 3), left-to-right: crew_id, truck_id, then job
    crew = L.get_crew_or_404(crew_id)
    truck = L.get_truck_or_404(truck_id)
    job = L.get_job_or_404(haul_job_id)

    # well-formedness (priority 4)
    ws = H.as_str(body["window_start_utc"], "window_start_utc")
    we = H.as_str(body["window_end_utc"], "window_end_utc")
    start_dt = parse_iso(ws)
    end_dt = parse_iso(we)
    if start_dt is None:
        err(errors.ERR_INVALID_REQUEST, "window_start_utc must be a valid ISO8601 datetime")
    if end_dt is None:
        err(errors.ERR_INVALID_REQUEST, "window_end_utc must be a valid ISO8601 datetime")
    if not (end_dt > start_dt):
        err(errors.ERR_INVALID_REQUEST, "window_end_utc must be strictly after window_start_utc")
    expected_crew_version = H.as_int(body["expected_crew_version"], "expected_crew_version")

    # state (priority 5): job must be ESTIMATED
    if job["status"] != "ESTIMATED":
        err(errors.ERR_JOB_NOT_ESTIMATED, "Dispatch requires the job to be in ESTIMATED status")

    # cross-entity state guards (priority 6): crew on duty, truck in service
    if crew["status"] != "ON_DUTY":
        err(errors.ERR_CREW_OFF_DUTY, "Crew must be ON_DUTY")
    if truck["status"] != "IN_SERVICE":
        err(errors.ERR_TRUCK_OUT_OF_SERVICE, "Truck must be IN_SERVICE")

    # hazmat safety guard (priority 7)
    if _job_has_freon(job["id"]) and not crew["hazmat_certified"]:
        err(errors.ERR_CREW_NOT_HAZMAT, "Crew must be hazmat-certified for FREON_APPLIANCE items")

    # temporal guards (priority 8): shift containment, crew buffer, truck overlap
    shift_start = parse_iso(crew["shift_start_utc"])
    shift_end = parse_iso(crew["shift_end_utc"])
    if not (start_dt >= shift_start and end_dt <= shift_end):
        err(errors.ERR_WINDOW_OUTSIDE_SHIFT, "Pickup window must lie within the crew shift")

    buffer_seconds = crew["buffer_minutes"] * 60
    for d in db.dispatches.values():
        if d["crew_id"] != crew_id or d["dispatch_status"] not in ("RESERVED", "ACTIVE"):
            continue
        ods = parse_iso(d["window_start_utc"])
        ode = parse_iso(d["window_end_utc"])
        # Required gap of >= buffer_minutes between the two windows. The gap between
        # non-overlapping windows is max(0, later.start - earlier.end). If the
        # windows overlap, gap is negative -> conflict.
        if start_dt >= ode:
            gap = (start_dt - ode).total_seconds()
        elif ods >= end_dt:
            gap = (ods - end_dt).total_seconds()
        else:
            gap = -1  # overlap
        if gap < buffer_seconds:
            err(errors.ERR_CREW_WINDOW_CONFLICT,
                "Pickup window violates the crew buffer against another dispatch")

    for d in db.dispatches.values():
        if d["truck_id"] != truck_id or d["dispatch_status"] not in ("RESERVED", "ACTIVE"):
            continue
        ods = parse_iso(d["window_start_utc"])
        ode = parse_iso(d["window_end_utc"])
        # half-open [start, end) intersection
        if start_dt < ode and ods < end_dt:
            err(errors.ERR_TRUCK_WINDOW_CONFLICT,
                "Pickup window intersects another truck dispatch")

    # fiscal guard (priority 9): outstanding + this job's exposure vs credit limit
    customer = db.customers.get(job["customer_id"])
    if customer is not None:
        exposure = job["estimated_total_cents"] or 0
        if customer["outstanding_balance_cents"] + exposure > customer["credit_limit_cents"]:
            err(errors.ERR_CREDIT_LIMIT_EXCEEDED, "Dispatch would exceed customer credit limit")

    # OCC guard (priority 10): expected_crew_version must match
    if expected_crew_version != crew["version"]:
        err(errors.ERR_STALE_CREW_VERSION, "expected_crew_version does not match current crew version")

    # All guards passed -> create the dispatch.
    wm = _window_minutes(start_dt, end_dt)
    dispatch = models.make_dispatch(job["id"], crew_id, truck_id, ws, we, wm)
    db.dispatches[dispatch["id"]] = dispatch
    recompute_crew_reserved_minutes(crew)
    job["status"] = "SCHEDULED"
    models.touch(job)
    return success(models.ser_dispatch(dispatch), 201)


@bp.route("/dispatches", methods=["GET"])
def list_dispatches():
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "CrewLead"})
    limit, offset = H.pagination_params()
    job_filter = request.args.get("haul_job_id")
    crew_filter = request.args.get("crew_id")
    truck_filter = request.args.get("truck_id")
    ds_filter = request.args.get("dispatch_status")
    items = list(db.dispatches.values())
    if auth.role == "CrewLead":
        items = [d for d in items if d["crew_id"] == auth.user_id]
    if job_filter is not None:
        items = [d for d in items if d["haul_job_id"] == job_filter]
    if crew_filter is not None:
        items = [d for d in items if d["crew_id"] == crew_filter]
    if truck_filter is not None:
        items = [d for d in items if d["truck_id"] == truck_filter]
    if ds_filter is not None:
        items = [d for d in items if d["dispatch_status"] == ds_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_dispatch(d) for d in page], limit, offset, total)


@bp.route("/dispatches/<dispatch_id>", methods=["GET"])
def get_dispatch(dispatch_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "CrewLead"})
    d = L.get_dispatch_or_404(dispatch_id)
    if auth.role == "CrewLead" and d["crew_id"] != auth.user_id:
        err(errors.ERR_FORBIDDEN_ROLE, "CrewLead may only read its own dispatches")
    return success(models.ser_dispatch(d), 200)


@bp.route("/dispatches/<dispatch_id>/activate", methods=["POST"])
def activate_dispatch(dispatch_id):
    auth = authenticate()
    require_role(auth, {"Dispatcher"})
    d = L.get_dispatch_or_404(dispatch_id)
    # state (priority 5): dispatch must be RESERVED
    if d["dispatch_status"] != "RESERVED":
        err(errors.ERR_DISPATCH_NOT_RESERVED, "Activate requires the dispatch to be RESERVED")
    # cross-entity guard (priority 6): crew on duty
    crew = db.crews.get(d["crew_id"])
    if crew is not None and crew["status"] != "ON_DUTY":
        err(errors.ERR_CREW_OFF_DUTY, "Crew must be ON_DUTY to activate")
    d["dispatch_status"] = "ACTIVE"
    models.touch(d)
    job = db.haul_jobs.get(d["haul_job_id"])
    if job is not None:
        job["status"] = "DISPATCHED"
        models.touch(job)
    return success(models.ser_dispatch(d), 200)
