"""Visit endpoints: schedule, clock-in/out, transitions, mileage (PRD §3.5, §3.6, §3.8)."""
from flask import Blueprint, request

import db
import errors
from clock import _format_iso
from errors import ApiError
from middleware import get_auth, require_roles
from money import D, round_half_up
from response import success, list_success
from services import requtil, scheduling
from services.calc import (
    compute_billable_minutes,
    compute_visit_charge,
    recompute_continuity_score,
)
from services.lookup import (
    get_caregiver, get_client, get_care_plan, get_visit, get_mileage,
)

bp = Blueprint("visits", __name__)

READ_ROLES = {"AgencyAdmin", "Scheduler", "BillingClerk", "Caregiver"}
EVV_SOURCES = {"TELEPHONY", "MOBILE", "MANUAL"}


def _has_active_match(caregiver_id, client_id):
    for m in db.matches.values():
        if (m["caregiver_id"] == caregiver_id
                and m["client_id"] == client_id
                and m["match_status"] == "ACTIVE"):
            return True
    return False


@bp.post("/visits")
def create_visit():
    _, role = get_auth()
    require_roles(role, {"Scheduler", "AgencyAdmin"})
    body = requtil.get_body()

    caregiver_id = requtil.require_str(body, "caregiver_id")
    client_id = requtil.require_str(body, "client_id")
    care_plan_id = requtil.require_str(body, "care_plan_id")
    # Existence left-to-right: caregiver, client, then plan.
    caregiver = get_caregiver(caregiver_id)
    client = get_client(client_id)
    plan = get_care_plan(care_plan_id)

    billing_mode = requtil.require_enum(body, "billing_mode", {"HOURLY", "LIVE_IN"})
    start = requtil.require_datetime(body, "scheduled_start")
    end = requtil.require_datetime(body, "scheduled_end")
    if not (end > start):
        raise requtil.invalid("scheduled_end must be after scheduled_start")

    # Business-temporal / constraint tier in declared order (PRD §3.5).
    agency = db.agencies.get(caregiver["agency_id"])
    travel_buffer = agency["travel_buffer_minutes"] if agency else 30
    scheduling.check_caregiver_double_booked(caregiver_id, start, end)
    scheduling.check_client_conflict(client_id, start, end, travel_buffer)
    scheduling.check_weekly_hours(caregiver, start, end)

    visit = {
        "caregiver_id": caregiver_id,
        "client_id": client_id,
        "care_plan_id": care_plan_id,
        "billing_mode": billing_mode,
        "scheduled_start": _format_iso(start),
        "scheduled_end": _format_iso(end),
        "_scheduled_start_dt": start,
        "_scheduled_end_dt": end,
        "clock_in_at": None,
        "clock_out_at": None,
        "_clock_in_dt": None,
        "_clock_out_dt": None,
        "evv_source": None,
        "evv_log": [],
        "billable_minutes": 0,
        "visit_charge": 0,
        "status": "SCHEDULED",
    }
    db.stamp_new(visit)
    db.visits[visit["id"]] = visit
    return success(_public_visit(visit), status=201)


def _public_visit(visit):
    pub = db.public(visit)
    return {k: v for k, v in pub.items() if not k.startswith("_")}


@bp.get("/visits")
def list_visits():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = requtil.pagination()
    items = list(db.visits.values())
    for key in ("caregiver_id", "client_id", "care_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([_public_visit(v) for v in page], limit, offset, total)


@bp.get("/visits/<vid>")
def get_visit_route(vid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    visit = get_visit(vid)
    return success(_public_visit(visit))


@bp.post("/visits/<vid>/clock-in")
def clock_in(vid):
    _, role = get_auth()
    require_roles(role, {"Caregiver"})
    visit = get_visit(vid)
    body = requtil.get_body()
    event_at = requtil.require_datetime(body, "event_at")
    evv_source = body.get("evv_source")
    if evv_source is not None and evv_source not in EVV_SOURCES:
        raise requtil.invalid("evv_source must be one of TELEPHONY, MOBILE, MANUAL")
    caller_id = body.get("caller_id")

    # Tier-5 state, then business-referential preconditions (PRD §3.6 order).
    if visit["status"] not in ("SCHEDULED", "EN_ROUTE"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "clock-in requires SCHEDULED/EN_ROUTE")
    client = db.clients.get(visit["client_id"])
    if client is None or client["status"] != "ACTIVE":
        raise ApiError(errors.ERR_CLIENT_NOT_SCHEDULABLE, 409, "client not ACTIVE")
    plan = db.care_plans.get(visit["care_plan_id"])
    if plan is None or plan["status"] != "PUBLISHED":
        raise ApiError(errors.ERR_CARE_PLAN_NOT_PUBLISHED, 409, "care plan not PUBLISHED")
    if not _has_active_match(visit["caregiver_id"], visit["client_id"]):
        raise ApiError(errors.ERR_NO_ACTIVE_MATCH, 409, "no ACTIVE match")

    visit["clock_in_at"] = _format_iso(event_at)
    visit["_clock_in_dt"] = event_at
    visit["evv_source"] = evv_source
    visit["evv_log"].append({
        "event_type": "CLOCK_IN",
        "event_at": _format_iso(event_at),
        "evv_source": evv_source,
        "caller_id": caller_id,
    })
    visit["status"] = "IN_PROGRESS"
    db.touch(visit)
    return success(_public_visit(visit))


@bp.post("/visits/<vid>/clock-out")
def clock_out(vid):
    _, role = get_auth()
    require_roles(role, {"Caregiver"})
    visit = get_visit(vid)
    body = requtil.get_body()
    event_at = requtil.require_datetime(body, "event_at")
    evv_source = body.get("evv_source")
    if evv_source is not None and evv_source not in EVV_SOURCES:
        raise requtil.invalid("evv_source must be one of TELEPHONY, MOBILE, MANUAL")
    caller_id = body.get("caller_id")

    if visit["status"] != "IN_PROGRESS":
        raise ApiError(errors.ERR_VISIT_NOT_IN_PROGRESS, 409, "clock-out requires IN_PROGRESS")
    if not (event_at > visit["_clock_in_dt"]):
        raise ApiError(errors.ERR_INVALID_CLOCK_WINDOW, 409,
                       "event_at must be strictly after clock_in_at")

    visit["clock_out_at"] = _format_iso(event_at)
    visit["_clock_out_dt"] = event_at
    if evv_source is not None:
        visit["evv_source"] = evv_source
    visit["evv_log"].append({
        "event_type": "CLOCK_OUT",
        "event_at": _format_iso(event_at),
        "evv_source": evv_source,
        "caller_id": caller_id,
    })

    agency = db.agencies.get(_visit_agency_id(visit))
    bm = compute_billable_minutes(
        visit["_clock_in_dt"], visit["_clock_out_dt"], agency["evv_rounding_minutes"]
    )
    visit["billable_minutes"] = bm
    visit["visit_charge"] = compute_visit_charge(visit["billing_mode"], bm, agency)
    visit["status"] = "COMPLETED"
    db.touch(visit)

    client = db.clients.get(visit["client_id"])
    if client is not None:
        recompute_continuity_score(client)
    return success(_public_visit(visit))


def _visit_agency_id(visit):
    caregiver = db.caregivers.get(visit["caregiver_id"])
    return caregiver["agency_id"] if caregiver else None


@bp.post("/visits/<vid>/transition")
def transition_visit(vid):
    _, role = get_auth()
    require_roles(role, {"Scheduler", "AgencyAdmin", "Caregiver"})
    visit = get_visit(vid)
    body = requtil.get_body()
    action = requtil.require_enum(body, "action", {"DEPART", "CANCEL", "RESET", "MARK_MISSED"})

    if action == "DEPART":
        if visit["status"] != "SCHEDULED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "DEPART requires SCHEDULED")
        if not _has_active_match(visit["caregiver_id"], visit["client_id"]):
            raise ApiError(errors.ERR_NO_ACTIVE_MATCH, 409, "no ACTIVE match")
        visit["status"] = "EN_ROUTE"
        db.touch(visit)

    elif action == "CANCEL":
        if visit["status"] not in ("SCHEDULED", "EN_ROUTE"):
            raise ApiError(errors.ERR_INVALID_STATE, 409, "CANCEL requires SCHEDULED/EN_ROUTE")
        visit["status"] = "CANCELLED"
        visit["billable_minutes"] = 0
        visit["visit_charge"] = 0
        db.touch(visit)
        _recompute_client(visit)

    elif action == "RESET":
        if visit["status"] not in ("EN_ROUTE", "IN_PROGRESS"):
            raise ApiError(errors.ERR_INVALID_STATE, 409, "RESET requires EN_ROUTE/IN_PROGRESS")
        visit["status"] = "SCHEDULED"
        visit["clock_in_at"] = None
        visit["clock_out_at"] = None
        visit["_clock_in_dt"] = None
        visit["_clock_out_dt"] = None
        visit["evv_source"] = None
        visit["billable_minutes"] = 0
        visit["visit_charge"] = 0
        db.touch(visit)

    elif action == "MARK_MISSED":
        if visit["status"] != "SCHEDULED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "MARK_MISSED requires SCHEDULED")
        visit["status"] = "MISSED"
        db.touch(visit)
        _recompute_client(visit)

    return success(_public_visit(visit))


def _recompute_client(visit):
    client = db.clients.get(visit["client_id"])
    if client is not None:
        recompute_continuity_score(client)


# ---- Mileage on a visit (PRD §3.8) ----
@bp.post("/visits/<vid>/mileage")
def create_mileage(vid):
    _, role = get_auth()
    require_roles(role, {"Caregiver", "Scheduler"})
    visit = get_visit(vid)
    body = requtil.get_body()
    miles = requtil.require_number(body, "miles")
    purpose = requtil.require_str(body, "purpose")
    if miles <= 0:
        raise requtil.invalid("miles must be > 0")

    agency = db.agencies.get(_visit_agency_id(visit))
    line_charge = round_half_up(D(miles) * D(agency["mileage_rate"]))

    entry = {
        "visit_id": visit["id"],
        "miles": miles,
        "purpose": purpose,
        "line_charge": line_charge,
        "status": "RECORDED",
    }
    db.stamp_new(entry)
    db.mileage_entries[entry["id"]] = entry
    return success(db.public(entry), status=201)


@bp.get("/visits/<vid>/mileage")
def list_mileage(vid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    visit = get_visit(vid)
    limit, offset = requtil.pagination()
    items = [m for m in db.mileage_entries.values() if m["visit_id"] == visit["id"]]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([db.public(m) for m in page], limit, offset, total)


@bp.post("/mileage/<mid>/void")
def void_mileage(mid):
    _, role = get_auth()
    require_roles(role, {"Scheduler", "AgencyAdmin"})
    entry = get_mileage(mid)
    if entry["status"] != "VOIDED":
        entry["status"] = "VOIDED"
        db.touch(entry)
    return success(db.public(entry))
