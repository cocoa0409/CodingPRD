"""Secure-environment sessions: scheduling, seats and the lifecycle (PRD 3.5)."""

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
    role,
    user_id,
)
from response import created_response, object_response, paginated
from routes.matters import require_not_suspended
from services import cascade, compute
from validation import present, req_enum, req_id, req_instant

bp = Blueprint("sessions", __name__)

WORKSTATION_CLASSES = ("ONSITE_SECURE", "REMOTE_VDI")
LIFECYCLE_TARGETS = ("ACTIVE", "CLOSED")
OCCUPYING = ("SCHEDULED", "ACTIVE")


@bp.route("/sessions", methods=["POST"])
def schedule_session():
    require_roles(ROLE_REVIEWER, ROLE_STAFFING_COORDINATOR)
    payload = body()

    # Rank 5 - body foreign keys.
    reviewer = None
    matter = None
    if present(payload, "reviewer_id") and isinstance(payload["reviewer_id"], str):
        reviewer = compute.get_reviewer(payload["reviewer_id"])
    if present(payload, "matter_id") and isinstance(payload["matter_id"], str):
        matter = compute.get_matter(payload["matter_id"])

    # Rank 6 - a reviewer schedules only for themselves.
    if role() == ROLE_REVIEWER and reviewer is not None and user_id() != reviewer["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A reviewer may only schedule their own sessions.")

    req_id(payload, "reviewer_id")
    req_id(payload, "matter_id")
    if reviewer is None:
        reviewer = compute.get_reviewer(payload["reviewer_id"])
    if matter is None:
        matter = compute.get_matter(payload["matter_id"])
    if role() == ROLE_REVIEWER and user_id() != reviewer["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A reviewer may only schedule their own sessions.")
    workstation_class = req_enum(payload, "workstation_class", WORKSTATION_CLASSES)
    start_dt, start_raw = req_instant(payload, "starts_at_utc")
    end_dt, end_raw = req_instant(payload, "ends_at_utc")

    # Rank 9.
    if not start_dt < end_dt:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "'starts_at_utc' must be strictly before 'ends_at_utc'.")

    require_not_suspended(matter)
    if reviewer["engagement_status"] == "REMOVED":
        raise ApiError("ERR_REVIEWER_REMOVED", "The reviewer has been removed.")

    # Rank 18 - live coverage, consulted after lazy expiry.
    cascade.apply_lazy_expiry_many(compute.agreements_of_pair(reviewer["id"], matter["id"]))
    agreement = compute.live_agreement(reviewer["id"], matter["id"])
    if agreement is None:
        raise ApiError("ERR_CONFIDENTIALITY_NOT_EXECUTED",
                       "No executed confidentiality agreement covers the logical clock.")

    # Rank 22 - three independent remote authorisations.
    if workstation_class == "REMOTE_VDI":
        if not (matter["remote_work_permitted"] and reviewer["remote_work_authorized"]
                and agreement["remote_work_addendum"]):
            raise ApiError("ERR_REMOTE_WORK_NOT_AUTHORIZED",
                           "Remote virtual-desktop access is not authorised for this pair.")

    # Rank 29 - the window sits inside the closed coverage interval.
    if not (agreement["_coverage_start_dt"] <= start_dt
            and end_dt <= agreement["_coverage_end_dt"]):
        raise ApiError("ERR_SESSION_OUTSIDE_COVERAGE",
                       "The requested window is not wholly inside executed coverage.")

    # Rank 30 - one reviewer, one place at a time, across every matter.
    for other in compute.sessions_of_reviewer(reviewer["id"]):
        if other["status"] in OCCUPYING and compute.windows_overlap(other, start_dt, end_dt):
            raise ApiError("ERR_SESSION_WINDOW_OVERLAP",
                           "The reviewer already holds an overlapping session window.")

    # Rank 31 - onsite seat capacity over the half-open interval.
    if workstation_class == "ONSITE_SECURE":
        occupancy = 0
        for other in compute.sessions_of_matter(matter["id"]):
            if other["workstation_class"] != "ONSITE_SECURE":
                continue
            if other["status"] not in OCCUPYING:
                continue
            if compute.windows_overlap(other, start_dt, end_dt):
                occupancy += 1
        if occupancy + 1 > matter["onsite_seat_count"]:
            raise ApiError("ERR_ONSITE_SEATS_EXHAUSTED",
                           "No onsite secure seat is free for the requested window.")

    row = base_row()
    row.update({
        "reviewer_id": reviewer["id"],
        "matter_id": matter["id"],
        "workstation_class": workstation_class,
        "starts_at_utc": start_raw,
        "ends_at_utc": end_raw,
        "_starts_at_dt": start_dt,
        "_ends_at_dt": end_dt,
        "status": "SCHEDULED",
        "activated_at": None,
        "closed_at": None,
    })
    db.sessions[row["id"]] = row
    return created_response(compute.session_out(row))


@bp.route("/sessions/<session_id>", methods=["GET"])
def read_session(session_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    session = compute.get_session(session_id)
    return object_response(compute.session_out(session))


@bp.route("/sessions", methods=["GET"])
def list_sessions():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    rows = by_creation(list(db.sessions.values()))
    reviewer_id = request.args.get("reviewer_id")
    matter_id = request.args.get("matter_id")
    status = request.args.get("status")
    if reviewer_id:
        rows = [r for r in rows if r["reviewer_id"] == reviewer_id]
    if matter_id:
        rows = [r for r in rows if r["matter_id"] == matter_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, compute.session_out)


@bp.route("/sessions/<session_id>/lifecycle", methods=["POST"])
def session_lifecycle(session_id):
    require_roles(ROLE_REVIEWER)
    session = compute.get_session(session_id)
    matter = compute.get_matter(session["matter_id"])
    if user_id() != session["reviewer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A reviewer may only drive their own session window.")
    payload = body()
    to_status = req_enum(payload, "to_status", LIFECYCLE_TARGETS)

    if to_status == "ACTIVE":
        if session["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a SCHEDULED session may be activated.")
        require_not_suspended(matter)
        cascade.apply_lazy_expiry_many(
            compute.agreements_of_pair(session["reviewer_id"], matter["id"]))
        if compute.live_agreement(session["reviewer_id"], matter["id"]) is None:
            raise ApiError("ERR_CONFIDENTIALITY_NOT_EXECUTED",
                           "No executed confidentiality agreement covers the logical clock.")
        if not compute.window_contains(session, db.now()):
            raise ApiError("ERR_INVALID_STATE",
                           "The logical clock is outside the session's own window.")
        session["status"] = "ACTIVE"
        session["activated_at"] = db.now_iso()
        touch(session)
        return object_response(compute.session_out(session))

    if session["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE session may be closed.")
    require_not_suspended(matter)
    session["status"] = "CLOSED"
    session["closed_at"] = db.now_iso()
    touch(session)
    return object_response(compute.session_out(session))
