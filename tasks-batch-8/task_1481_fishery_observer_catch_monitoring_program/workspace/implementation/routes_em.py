"""Electronic monitoring: enrollments and trips (PRD 3.8)."""

from flask import Blueprint

import logic
import store
from core import (
    ALL_ROLES, ApiError, body, dec, err_forbidden, err_invalid, err_state,
    get_or_404, list_response, ok, parse_dt, req_decimal2, req_dt, req_num,
    req_str, require_roles, round2, round4,
)

bp = Blueprint("em", __name__, url_prefix="/observer-program")


def _owned_vessel(a, vessel_id):
    vessel = store.db["vessels"].get(vessel_id) if isinstance(vessel_id, str) else None
    if vessel is not None and vessel["operator_id"] != a["id"]:
        raise err_forbidden("The acting operator does not own this vessel")
    return vessel


# ---------------------------------------------------------------------------
# EMEnrollment
# ---------------------------------------------------------------------------


@bp.post("/em-enrollments")
def create_enrollment():
    a = require_roles("VesselOperator")
    b = body()
    vessel_id = b.get("vessel_id")
    if isinstance(vessel_id, str):
        get_or_404("vessels", vessel_id, "Vessel")
    _owned_vessel(a, vessel_id)
    vessel_id = req_str(b, "vessel_id")
    vendor = req_str(b, "equipment_vendor")
    install_date = req_dt(b, "equipment_install_date")
    vessel = store.db["vessels"][vessel_id]
    open_existing = any(
        e["vessel_id"] == vessel["id"] and e["status"] in logic.OPEN_ENROLLMENT_STATUSES
        for e in store.db["em_enrollments"].values()
    )
    if open_existing:
        raise ApiError("ERR_EM_ENROLLMENT_OPEN_EXISTS", 409,
                       "The vessel already holds an open EM enrollment")
    e = store.new_entity({
        "vessel_id": vessel["id"],
        "equipment_vendor": vendor,
        "equipment_install_date": install_date,
        "reviewed_by_user_id": None,
        "rejection_reason": None,
        "status": "PENDING_REVIEW",
    })
    store.db["em_enrollments"][e["id"]] = e
    return ok(e, status=201)


@bp.get("/em-enrollments")
def list_enrollments():
    require_roles(*ALL_ROLES)
    return list_response("em_enrollments", {"vessel_id": "vessel_id", "status": "status"})


@bp.get("/em-enrollments/<eid>")
def get_enrollment(eid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("em_enrollments", eid, "EMEnrollment"))


@bp.post("/em-enrollments/<eid>/approve")
def approve_enrollment(eid):
    a = require_roles("ProgramAdmin")
    e = get_or_404("em_enrollments", eid, "EMEnrollment")
    if e["status"] != "PENDING_REVIEW":
        raise err_state("Only a PENDING_REVIEW enrollment can be approved")
    e["status"] = "APPROVED"
    e["reviewed_by_user_id"] = a["id"]
    store.touch(e)
    return ok(e)


@bp.post("/em-enrollments/<eid>/reject")
def reject_enrollment(eid):
    a = require_roles("ProgramAdmin")
    e = get_or_404("em_enrollments", eid, "EMEnrollment")
    b = body()
    reason = req_str(b, "rejection_reason")
    if e["status"] != "PENDING_REVIEW":
        raise err_state("Only a PENDING_REVIEW enrollment can be rejected")
    e["status"] = "REJECTED"
    e["rejection_reason"] = reason
    e["reviewed_by_user_id"] = a["id"]
    store.touch(e)
    return ok(e)


@bp.post("/em-enrollments/<eid>/activate")
def activate_enrollment(eid):
    require_roles("ProgramCoordinator")
    e = get_or_404("em_enrollments", eid, "EMEnrollment")
    if e["status"] not in ("APPROVED", "SUSPENDED"):
        raise err_state("Only an APPROVED or SUSPENDED enrollment can be activated")
    vessel = store.db["vessels"].get(e["vessel_id"])
    if e["status"] == "APPROVED" and vessel is not None:
        # The full cascade fires only on APPROVED -> ACTIVE.
        logic.em_activation_cascade(vessel)
    e["status"] = "ACTIVE"
    store.touch(e)
    return ok(e)


@bp.post("/em-enrollments/<eid>/suspend")
def suspend_enrollment(eid):
    require_roles("ProgramAdmin")
    e = get_or_404("em_enrollments", eid, "EMEnrollment")
    if e["status"] != "ACTIVE":
        raise err_state("Only an ACTIVE enrollment can be suspended")
    e["status"] = "SUSPENDED"
    store.touch(e)
    return ok(e)


@bp.post("/em-enrollments/<eid>/terminate")
def terminate_enrollment(eid):
    require_roles("ProgramAdmin")
    e = get_or_404("em_enrollments", eid, "EMEnrollment")
    if e["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_state("Only an ACTIVE or SUSPENDED enrollment can be terminated")
    open_trip = any(
        t["em_enrollment_id"] == e["id"] and t["status"] in logic.OPEN_EM_TRIP_STATUSES
        for t in store.db["em_trips"].values()
    )
    if open_trip:
        raise err_state("The enrollment still has open EM trips")
    e["status"] = "TERMINATED"
    store.touch(e)
    vessel = store.db["vessels"].get(e["vessel_id"])
    if vessel is not None:
        vessel["monitoring_mode"] = "HUMAN_OBSERVER"
        store.touch(vessel)
    return ok(e)


# ---------------------------------------------------------------------------
# EMTrip
# ---------------------------------------------------------------------------


@bp.post("/em-trips")
def create_trip():
    a = require_roles("VesselOperator")
    b = body()
    vessel_id = b.get("vessel_id")
    if isinstance(vessel_id, str):
        get_or_404("vessels", vessel_id, "Vessel")
    _owned_vessel(a, vessel_id)
    vessel_id = req_str(b, "vessel_id")
    dep_s = req_dt(b, "departure_date")
    ret_s = req_dt(b, "return_date")
    vessel = store.db["vessels"][vessel_id]
    # Temporal (priority 8) precedes referential state (priority 9).
    dep_dt = parse_dt(dep_s)
    ret_dt = parse_dt(ret_s)
    if ret_dt <= dep_dt:
        raise ApiError("ERR_DATE_RANGE_INVALID", 422,
                       "return_date must fall after departure_date")
    for t in store.db["em_trips"].values():
        if t["vessel_id"] != vessel["id"] or t["status"] not in logic.OPEN_EM_TRIP_STATUSES:
            continue
        t_dep = parse_dt(t["departure_date"])
        t_ret = parse_dt(t["return_date"])
        if dep_dt <= t_ret and t_dep <= ret_dt:
            raise ApiError("ERR_EM_TRIP_OVERLAP", 409,
                           "The trip overlaps another open EM trip")
    for d in store.db["deployments"].values():
        if d["vessel_id"] != vessel["id"] or d["status"] not in logic.ACTIVE_DEPLOYMENT_STATUSES:
            continue
        d_dep = parse_dt(d["scheduled_departure_date"])
        d_ret = parse_dt(d["scheduled_return_date"])
        if dep_dt <= d_ret and d_dep <= ret_dt:
            raise ApiError("ERR_EM_TRIP_OVERLAP", 409,
                           "The trip overlaps an active deployment")
    if vessel["monitoring_mode"] != "ELECTRONIC_MONITORING":
        raise ApiError("ERR_VESSEL_NOT_EM_MODE", 409,
                       "The vessel is not in ELECTRONIC_MONITORING mode")
    enrollment = next(
        (e for e in store.db["em_enrollments"].values()
         if e["vessel_id"] == vessel["id"] and e["status"] == "ACTIVE"),
        None,
    )
    if enrollment is None:
        raise ApiError("ERR_EM_ENROLLMENT_NOT_ACTIVE", 409,
                       "The vessel has no ACTIVE EM enrollment")
    trip = store.new_entity({
        "vessel_id": vessel["id"],
        "em_enrollment_id": enrollment["id"],
        "assigned_reviewer_id": None,
        "departure_date": dep_s,
        "return_date": ret_s,
        "trip_sea_days": logic.days_between(ret_dt, dep_dt) + 1,
        "video_hours": None,
        "reviewed_hours": dec(0),
        "reviewed_pct": None,
        "sampled_catch_kg": dec(0),
        "estimated_total_catch_kg": None,
        "status": "DECLARED",
    })
    store.db["em_trips"][trip["id"]] = trip
    return ok(trip, status=201)


@bp.get("/em-trips")
def list_trips():
    require_roles(*ALL_ROLES)
    return list_response("em_trips", {
        "vessel_id": "vessel_id",
        "em_enrollment_id": "em_enrollment_id",
        "assigned_reviewer_id": "assigned_reviewer_id",
        "status": "status",
    })


@bp.get("/em-trips/<tid>")
def get_trip(tid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("em_trips", tid, "EMTrip"))


@bp.post("/em-trips/<tid>/submit-footage")
def submit_footage(tid):
    a = require_roles("VesselOperator")
    t = get_or_404("em_trips", tid, "EMTrip")
    _owned_vessel(a, t["vessel_id"])
    b = body()
    if "video_hours" not in b or b["video_hours"] is None:
        raise err_invalid("Field 'video_hours' is required")
    video = req_decimal2(b, "video_hours")
    if video <= 0:
        raise err_invalid("video_hours must be > 0")
    if t["status"] != "DECLARED":
        raise err_state("Footage can only be submitted for a DECLARED trip")
    t["video_hours"] = video
    t["reviewed_pct"] = round4(t["reviewed_hours"] / video)
    t["status"] = "FOOTAGE_SUBMITTED"
    store.touch(t)
    return ok(t)


@bp.post("/em-trips/<tid>/assign-reviewer")
def assign_reviewer(tid):
    require_roles("ProgramCoordinator")
    t = get_or_404("em_trips", tid, "EMTrip")
    b = body()
    reviewer_id = b.get("reviewer_id")
    if isinstance(reviewer_id, str):
        get_or_404("em_reviewers", reviewer_id, "EMReviewer")
    reviewer_id = req_str(b, "reviewer_id")
    reviewer = store.db["em_reviewers"][reviewer_id]
    if t["status"] != "FOOTAGE_SUBMITTED":
        raise err_state("A reviewer can only be assigned to a FOOTAGE_SUBMITTED trip")
    if reviewer["status"] != "ACTIVE":
        raise err_state("The assigned EM reviewer must be ACTIVE")
    t["assigned_reviewer_id"] = reviewer_id
    t["status"] = "IN_REVIEW"
    store.touch(t)
    return ok(t)


@bp.post("/em-trips/<tid>/record-review")
def record_review(tid):
    a = require_roles("EMReviewer")
    t = get_or_404("em_trips", tid, "EMTrip")
    if t["assigned_reviewer_id"] is not None and t["assigned_reviewer_id"] != a["id"]:
        raise err_forbidden("The acting reviewer is not the assigned reviewer")
    b = body()
    hours = req_num(b, "additional_reviewed_hours")
    catch_delta = req_num(b, "sampled_catch_kg_delta")
    if dec(hours) <= 0:
        raise err_invalid("additional_reviewed_hours must be > 0")
    if dec(catch_delta) < 0:
        raise err_invalid("sampled_catch_kg_delta must be >= 0")
    if t["assigned_reviewer_id"] is None:
        raise ApiError("ERR_REVIEWER_NOT_ASSIGNED", 409,
                       "No reviewer has been assigned to the trip")
    if t["status"] != "IN_REVIEW":
        raise err_state("Review can only be recorded while the trip is IN_REVIEW")
    t["reviewed_hours"] = dec(t["reviewed_hours"]) + dec(hours)
    t["sampled_catch_kg"] = dec(t["sampled_catch_kg"]) + dec(catch_delta)
    t["reviewed_pct"] = round4(t["reviewed_hours"] / dec(t["video_hours"]))
    if t["reviewed_pct"] >= logic.EM_REVIEW_MIN_PCT:
        t["status"] = "REVIEWED"
    store.touch(t)
    return ok(t)


@bp.post("/em-trips/<tid>/accept")
def accept_trip(tid):
    require_roles("ProgramCoordinator")
    t = get_or_404("em_trips", tid, "EMTrip")
    if t["status"] in ("ACCEPTED", "REJECTED"):
        raise err_state("The trip is already in a terminal state")
    if t["status"] != "REVIEWED":
        raise ApiError("ERR_EM_REVIEW_MIN_NOT_MET", 409,
                       "The trip has not reached the minimum review threshold")
    vessel = store.db["vessels"].get(t["vessel_id"])
    dep_dt = parse_dt(t["departure_date"])
    ret_dt = parse_dt(t["return_date"])
    matches = []
    for p in store.db["coverage_plans"].values():
        if vessel is None or p["fishery_id"] != vessel["fishery_id"]:
            continue
        if p["status"] != "SELECTION_COMPLETED":
            continue
        if parse_dt(p["period_start"]) <= dep_dt and parse_dt(p["period_end"]) >= ret_dt:
            matches.append(p)
    if len(matches) != 1:
        raise ApiError("ERR_NO_COVERAGE_PLAN_FOR_TRIP", 409,
                       "No unique SELECTION_COMPLETED coverage plan contains the trip")
    plan = matches[0]
    t["estimated_total_catch_kg"] = round2(
        dec(t["sampled_catch_kg"]) * dec(t["video_hours"]) / dec(t["reviewed_hours"])
    )
    t["status"] = "ACCEPTED"
    store.touch(t)
    plan["actual_em_sea_days"] += t["trip_sea_days"]
    store.touch(plan)
    return ok(t)


@bp.post("/em-trips/<tid>/reject")
def reject_trip(tid):
    require_roles("ProgramCoordinator")
    t = get_or_404("em_trips", tid, "EMTrip")
    b = body()
    req_str(b, "rejection_reason")
    if t["status"] != "REVIEWED":
        raise err_state("Only a REVIEWED trip can be rejected")
    t["status"] = "REJECTED"
    store.touch(t)
    return ok(t)
