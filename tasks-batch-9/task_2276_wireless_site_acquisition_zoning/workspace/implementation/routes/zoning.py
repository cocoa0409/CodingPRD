"""Zoning entitlement: filing, tolling, hearings, decisions and the shot clock."""

from datetime import timedelta

from flask import Blueprint

import calc
import services
from db import (add_days, db, fmt_dt, get_dt, new_record, now, serialize,
                set_dt, sorted_records, whole_days)
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, DATETIME, NUMBER, ROLE_DIRECTOR,
                        ROLE_PLANNER, STRING, authenticate, f,
                        require_conditional, validate_body)

bp = Blueprint("zoning", __name__)

APPLICATION_TYPES = ["BY_RIGHT", "CONDITIONAL_USE", "VARIANCE"]
COMPLETENESS_OUTCOMES = ["COMPLETE", "INCOMPLETE", "CURED"]
HEARING_ACTIONS = ["SCHEDULE", "HOLD", "CONTINUE"]
DECISION_OUTCOMES = ["APPROVED", "DENIED"]

DEEM_GRANTABLE_FROM = ("SUBMITTED", "UNDER_REVIEW", "INCOMPLETE",
                       "HEARING_SCHEDULED", "HEARING_HELD")


def _jurisdiction_of(app):
    candidate = db.candidates.get(app["candidate_id"])
    if candidate is None:
        return None
    return db.jurisdictions.get(candidate["jurisdiction_id"])


def _recompute_deadline(app):
    jurisdiction = _jurisdiction_of(app)
    submitted = get_dt(app, "submitted_date")
    if jurisdiction is None or submitted is None:
        return None
    days = calc.review_days_for(app["application_type"], jurisdiction) + int(app["tolled_days"])
    return add_days(submitted, days)


def _promote_candidate(app):
    candidate = db.candidates.get(app["candidate_id"])
    if candidate is not None and candidate["feasibility_status"] == "STRUCTURALLY_CLEARED":
        services.apply(candidate, {"feasibility_status": "ENTITLED"})


@bp.post("/zoning-applications")
def create_application():
    authenticate([ROLE_PLANNER])
    body = validate_body([
        f("candidate_id", STRING),
        f("application_type", STRING, enum=APPLICATION_TYPES),
        f("filed_by_user_id", STRING),
    ])
    candidate = db.candidates.get(body["candidate_id"])
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404)

    for existing in services.zoning_apps_of_candidate(candidate["id"]):
        if existing["status"] not in ("WITHDRAWN", "DENIED"):
            raise ApiError("ERR_DUPLICATE_ZONING_APPLICATION", 409)

    app = new_record({
        "candidate_id": candidate["id"],
        "application_type": body["application_type"],
        "filed_by_user_id": body["filed_by_user_id"],
        "status": "PREPARING",
        "submitted_date": None,
        "visual_simulation_count": 0,
        "hearing_date": None,
        "hearings_held_count": 0,
        "continuance_count": 0,
        "incomplete_since_date": None,
        "tolled_days": 0,
        "shot_clock_deadline_date": None,
        "zoning_fee_total_usd": None,
        "decision_date": None,
    })
    for field in ("submitted_date", "hearing_date", "incomplete_since_date",
                  "shot_clock_deadline_date", "decision_date"):
        set_dt(app, field, None)
    db.zoning_applications[app["id"]] = app
    return created(serialize(app))


@bp.get("/zoning-applications")
def list_applications():
    authenticate(ALL_ROLES)
    return listing("zoning_applications", ["candidate_id", "status"])


@bp.get("/zoning-applications/<app_id>")
def read_application(app_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("zoning_applications", app_id)))


@bp.post("/zoning-applications/<app_id>/visual-simulations")
def add_simulation(app_id):
    authenticate([ROLE_PLANNER])
    validate_body([
        f("view_angle_deg", NUMBER),
        f("photo_reference", STRING),
    ])
    app = fetch("zoning_applications", app_id)
    if app["status"] != "PREPARING":
        raise ApiError("ERR_INVALID_ZONING_STATE", 409)
    services.apply(app, {"visual_simulation_count": app["visual_simulation_count"] + 1})
    return ok(serialize(app))


@bp.post("/zoning-applications/<app_id>/submit")
def submit_application(app_id):
    authenticate([ROLE_PLANNER])
    validate_body([])
    app = fetch("zoning_applications", app_id)

    if app["status"] != "PREPARING":
        raise ApiError("ERR_INVALID_ZONING_STATE", 409)

    candidate = db.candidates.get(app["candidate_id"])
    if candidate is None or candidate["acquisition_status"] != "LEASE_EXECUTED":
        raise ApiError("ERR_LEASE_NOT_EXECUTED", 409)

    jurisdiction = db.jurisdictions.get(candidate["jurisdiction_id"])
    if (jurisdiction is not None and jurisdiction["requires_visual_simulation"]
            and app["visual_simulation_count"] < int(jurisdiction["min_visual_simulations"])):
        raise ApiError("ERR_VISUAL_SIMULATION_REQUIRED", 422)

    clock = now()
    set_dt(app, "submitted_date", clock)
    fee = calc.zoning_fee_total(app, jurisdiction)
    deadline = _recompute_deadline(app)
    set_dt(app, "shot_clock_deadline_date", deadline)
    services.apply(app, {
        "submitted_date": fmt_dt(clock),
        "zoning_fee_total_usd": fee,
        "shot_clock_deadline_date": fmt_dt(deadline),
        "status": "SUBMITTED",
    })
    return ok(serialize(app))


@bp.post("/zoning-applications/<app_id>/completeness")
def completeness(app_id):
    authenticate([ROLE_PLANNER])
    body = validate_body([
        f("outcome", STRING, enum=COMPLETENESS_OUTCOMES),
        f("note", STRING, required=False),
    ])
    app = fetch("zoning_applications", app_id)
    outcome = body["outcome"]
    status = app["status"]

    if outcome == "COMPLETE":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_ZONING_STATE", 409)
        services.apply(app, {"status": "UNDER_REVIEW"})
    elif outcome == "INCOMPLETE":
        if status not in ("SUBMITTED", "UNDER_REVIEW"):
            raise ApiError("ERR_INVALID_ZONING_STATE", 409)
        clock = now()
        set_dt(app, "incomplete_since_date", clock)
        services.apply(app, {"incomplete_since_date": fmt_dt(clock),
                             "status": "INCOMPLETE"})
    else:  # CURED
        since = get_dt(app, "incomplete_since_date")
        if status != "INCOMPLETE" or since is None:
            raise ApiError("ERR_INVALID_ZONING_STATE", 409)
        tolled = int(app["tolled_days"]) + max(0, whole_days(now(), since))
        app["tolled_days"] = tolled
        deadline = _recompute_deadline(app)
        set_dt(app, "shot_clock_deadline_date", deadline)
        set_dt(app, "incomplete_since_date", None)
        services.apply(app, {
            "tolled_days": tolled,
            "shot_clock_deadline_date": fmt_dt(deadline),
            "incomplete_since_date": None,
            "status": "UNDER_REVIEW",
        })
    return ok(serialize(app))


def _hearing_conflict(app, requested_dt, cadence_days):
    window = timedelta(days=int(cadence_days))
    candidate = db.candidates.get(app["candidate_id"])
    if candidate is None:
        return False
    jurisdiction_id = candidate["jurisdiction_id"]
    for other in sorted_records(db.zoning_applications):
        if other["id"] == app["id"]:
            continue
        other_candidate = db.candidates.get(other["candidate_id"])
        if other_candidate is None or other_candidate["jurisdiction_id"] != jurisdiction_id:
            continue
        other_dt = get_dt(other, "hearing_date")
        if other_dt is None:
            continue
        separation = other_dt - requested_dt
        if separation < timedelta(0):
            separation = -separation
        if separation < window:
            return True
    return False


@bp.post("/zoning-applications/<app_id>/hearings")
def hearings(app_id):
    authenticate([ROLE_PLANNER])
    body = validate_body([
        f("action", STRING, enum=HEARING_ACTIONS),
        f("hearing_date", DATETIME, required=False),
    ])
    action = body["action"]
    if action in ("SCHEDULE", "CONTINUE"):
        require_conditional(body, "hearing_date")

    app = fetch("zoning_applications", app_id)
    status = app["status"]
    allowed = {
        "SCHEDULE": ("UNDER_REVIEW", "HEARING_HELD"),
        "HOLD": ("HEARING_SCHEDULED",),
        "CONTINUE": ("HEARING_HELD",),
    }[action]
    if status not in allowed:
        raise ApiError("ERR_INVALID_ZONING_STATE", 409)

    jurisdiction = _jurisdiction_of(app)
    clock = now()

    if action == "HOLD":
        scheduled = get_dt(app, "hearing_date")
        if scheduled is not None and clock < scheduled:
            raise ApiError("ERR_HEARING_NOT_YET_HELD", 409)
        services.apply(app, {"hearings_held_count": app["hearings_held_count"] + 1,
                             "status": "HEARING_HELD"})
        return ok(serialize(app))

    if action == "CONTINUE":
        if (jurisdiction is not None
                and app["continuance_count"] >= int(jurisdiction["max_continuances"])):
            raise ApiError("ERR_CONTINUANCE_LIMIT_REACHED", 409)

    requested = body["hearing_date"]
    cadence = int(jurisdiction["hearing_cadence_days"]) if jurisdiction is not None else 1
    if _hearing_conflict(app, requested.dt, cadence):
        raise ApiError("ERR_HEARING_WINDOW_CONFLICT", 409)
    if requested.dt < clock:
        raise ApiError("ERR_HEARING_DATE_IN_PAST", 422)

    updates = {"hearing_date": requested.raw, "status": "HEARING_SCHEDULED"}
    if action == "CONTINUE":
        updates["continuance_count"] = app["continuance_count"] + 1
    set_dt(app, "hearing_date", requested.dt, raw=requested.raw)
    services.apply(app, updates)
    return ok(serialize(app))


@bp.post("/zoning-applications/<app_id>/decide")
def decide(app_id):
    authenticate([ROLE_PLANNER])
    body = validate_body([
        f("outcome", STRING, enum=DECISION_OUTCOMES),
        f("decision_date", DATETIME),
    ])
    app = fetch("zoning_applications", app_id)
    outcome = body["outcome"]
    status = app["status"]

    if status == "HEARING_HELD":
        pass
    elif status == "UNDER_REVIEW":
        if outcome == "APPROVED" and app["application_type"] != "BY_RIGHT":
            raise ApiError("ERR_INVALID_ZONING_STATE", 409)
    else:
        raise ApiError("ERR_INVALID_ZONING_STATE", 409)

    decision = body["decision_date"]
    if decision.dt > now():
        raise ApiError("ERR_DATE_IN_FUTURE", 422)
    submitted = get_dt(app, "submitted_date")
    if submitted is not None and decision.dt < submitted:
        raise ApiError("ERR_DECISION_DATE_INVALID", 422)

    set_dt(app, "decision_date", decision.dt, raw=decision.raw)
    services.apply(app, {"decision_date": decision.raw, "status": outcome})
    if outcome == "APPROVED":
        _promote_candidate(app)
    return ok(serialize(app))


@bp.post("/zoning-applications/<app_id>/deem-granted")
def deem_granted(app_id):
    authenticate([ROLE_DIRECTOR])
    validate_body([])
    app = fetch("zoning_applications", app_id)

    if app["status"] not in DEEM_GRANTABLE_FROM:
        raise ApiError("ERR_INVALID_ZONING_STATE", 409)

    deadline = get_dt(app, "shot_clock_deadline_date")
    clock = now()
    if deadline is None or clock <= deadline:
        raise ApiError("ERR_SHOT_CLOCK_NOT_EXPIRED", 409)

    set_dt(app, "decision_date", clock)
    services.apply(app, {"decision_date": fmt_dt(clock), "status": "DEEMED_GRANTED"})
    _promote_candidate(app)
    return ok(serialize(app))


@bp.get("/zoning-applications/<app_id>/shot-clock")
def shot_clock(app_id):
    authenticate([ROLE_PLANNER, ROLE_DIRECTOR])
    app = fetch("zoning_applications", app_id)
    jurisdiction = _jurisdiction_of(app)
    review_days = (calc.review_days_for(app["application_type"], jurisdiction)
                   if jurisdiction is not None else None)
    deadline = get_dt(app, "shot_clock_deadline_date")
    clock = now()
    days_remaining = whole_days(deadline, clock) if deadline is not None else None
    return ok({
        "review_days": review_days,
        "tolled_days": int(app["tolled_days"]),
        "shot_clock_deadline_date": app["shot_clock_deadline_date"],
        "days_remaining": days_remaining,
        "deemed_grantable": deadline is not None and clock > deadline,
    })
