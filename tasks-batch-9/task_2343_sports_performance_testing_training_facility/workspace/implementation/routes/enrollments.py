"""Enrollment booking, the funding waterfall, cancellation and attendance."""

from datetime import timedelta

from flask import Blueprint

import response
import serializers
from db import create, now, ordered, store, touch
from errors import ApiError
from middleware import (body_json, guard, pagination, query_enum, query_str,
                        resolve_acting_staff, slice_page, v_bool, v_enum)
from routes.common import (get_athlete, get_enrollment, get_group_session,
                           require_state)
from services import calc, domain

bp = Blueprint("enrollments", __name__)

FUNDING_PREFERENCES = ("ANY", "PACKAGE_ONLY", "DROP_IN_OK")
ENROLLMENT_STATUSES = (
    "RESERVED",
    "WAITLISTED",
    "ATTENDED",
    "NO_SHOW",
    "LATE_CANCEL",
    "CANCELED",
)
ENROLLMENT_TERMINAL = ("NO_SHOW", "LATE_CANCEL", "CANCELED")
RESTRICTED_PHASES_ALLOWED = ("GENERAL_PREP", "TRANSITION")


@bp.post("/enrollments")
def create_enrollment():
    ctx = guard("FrontDesk", "Coach", "Athlete", "Guardian")
    resolve_acting_staff(ctx)
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))
    session = get_group_session(body.get("group_session_id"))

    funding_preference = v_enum(
        body, "funding_preference", FUNDING_PREFERENCES, required=False, default="ANY"
    )
    request_waitlist = v_bool(body, "request_waitlist", default=False)

    domain.enforce_athlete_scope(ctx, athlete)

    if athlete["membership_status"] == "SUSPENDED":
        raise ApiError("ERR_ATHLETE_SUSPENDED", "A suspended athlete may not be enrolled")

    for existing in domain.session_enrollments(session["id"]):
        if existing["athlete_id"] == athlete["id"] and existing["status"] in domain.ACTIVE_ENROLLMENT_STATUSES:
            raise ApiError(
                "ERR_DUPLICATE_ENROLLMENT",
                "The athlete already holds an enrollment on this session",
            )

    require_state(
        session,
        "session_status",
        ("SCHEDULED", "ROSTER_LOCKED"),
        ("CANCELED",),
        "GroupSession",
    )

    if athlete["training_clearance"] == "SCREEN_PENDING":
        raise ApiError(
            "ERR_MOVEMENT_SCREEN_REQUIRED",
            "The athlete must complete the intake movement screen before enrolling",
        )
    if athlete["training_clearance"] == "MEDICAL_HOLD":
        raise ApiError(
            "ERR_ATHLETE_MEDICAL_HOLD", "An athlete on medical hold may not be enrolled"
        )

    waitlist = False
    derived = domain.session_derived(session)
    if derived["reserved_count"] >= session["max_athletes"]:
        if not request_waitlist:
            raise ApiError("ERR_SESSION_FULL", "The session has reached max_athletes")
        waitlist = True

    if not waitlist:
        extra = calc.athlete_unit(
            domain.athlete_age_years(athlete), domain.open_rts_plan(athlete["id"]) is not None
        )
        projected = domain.session_derived(session, extra_units=extra)
        if projected["required_coach_count"] > projected["compliant_coach_count"]:
            if not request_waitlist:
                raise ApiError(
                    "ERR_COACH_RATIO_EXCEEDED",
                    "This booking would exceed the session's coaching ratio",
                )
            waitlist = True

    if athlete["training_clearance"] == "RESTRICTED" and session["phase_focus"] not in RESTRICTED_PHASES_ALLOWED:
        raise ApiError(
            "ERR_RESTRICTED_PHASE_NOT_PERMITTED",
            "A restricted athlete may only train in GENERAL_PREP or TRANSITION sessions",
        )
    if session["phase_focus"] == "COMPETITION":
        if domain.athlete_readiness(athlete) < calc.COMPETITION_READINESS_MIN:
            raise ApiError(
                "ERR_READINESS_BELOW_THRESHOLD",
                "A competition session requires a readiness_index of at least 60.00",
            )

    for other in ordered(store.enrollments):
        if other["athlete_id"] != athlete["id"]:
            continue
        if other["status"] not in ("RESERVED", "WAITLISTED"):
            continue
        neighbour = store.group_sessions.get(other["group_session_id"])
        if neighbour is None or neighbour["id"] == session["id"]:
            continue
        if neighbour["_start_at"] < session["_end_at"] and session["_start_at"] < neighbour["_end_at"]:
            raise ApiError(
                "ERR_ATHLETE_SCHEDULE_CONFLICT",
                "The athlete already holds an enrollment overlapping this session",
            )

    if session["_start_at"] <= now():
        raise ApiError(
            "ERR_ENROLLMENT_WINDOW_CLOSED",
            "Enrollment closes once the session's start_at has been reached",
        )

    record = {
        "athlete_id": athlete["id"],
        "group_session_id": session["id"],
        "funding_preference": funding_preference,
        "funding_source": "UNFUNDED",
        "membership_package_id": None,
        "charge_cents": 0,
        "status": "WAITLISTED" if waitlist else "RESERVED",
        "cancel_reason": None,
        "station_number": None,
        "no_show_fee_cents": 0,
        "strike_index_at_no_show": None,
        "promoted_from_waitlist": False,
        "_team_contract_id": None,
    }
    if not waitlist:
        domain.allocate_funding(record, athlete, session)

    enrollment = create(store.enrollments, record)
    return response.created(serializers.enrollment(enrollment))


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    ctx = guard("PerformanceDirector", "Coach", "FrontDesk", "Athlete", "Guardian")
    enrollment = get_enrollment(enrollment_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.enrollment(enrollment))


@bp.get("/enrollments")
def list_enrollments():
    ctx = guard("PerformanceDirector", "Coach", "FrontDesk")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    athlete_id = query_str("athlete_id")
    group_session_id = query_str("group_session_id")
    membership_package_id = query_str("membership_package_id")
    status = query_enum("status", ENROLLMENT_STATUSES)

    rows = ordered(store.enrollments)
    if athlete_id:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if group_session_id:
        rows = [r for r in rows if r["group_session_id"] == group_session_id]
    if membership_package_id:
        rows = [r for r in rows if r["membership_package_id"] == membership_package_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.enrollment(r) for r in page], limit, offset, total)


@bp.post("/enrollments/<enrollment_id>/cancel")
def cancel_enrollment(enrollment_id):
    ctx = guard("FrontDesk", "Athlete", "Guardian")
    enrollment = get_enrollment(enrollment_id)
    body_json()
    athlete = store.athletes.get(enrollment["athlete_id"])
    if athlete is not None:
        domain.enforce_athlete_scope(ctx, athlete)

    require_state(
        enrollment,
        "status",
        ("RESERVED", "WAITLISTED"),
        ENROLLMENT_TERMINAL,
        "Enrollment",
    )
    session = store.group_sessions[enrollment["group_session_id"]]
    require_state(
        session,
        "session_status",
        ("SCHEDULED", "ROSTER_LOCKED"),
        ("CANCELED",),
        "GroupSession",
    )

    was_reserved = enrollment["status"] == "RESERVED"
    gap = session["_start_at"] - now()
    timely = gap >= timedelta(hours=calc.LATE_CANCEL_WINDOW_HOURS)

    if timely:
        if was_reserved:
            domain.refund_funding(enrollment, session)
        enrollment["status"] = "CANCELED"
        enrollment["station_number"] = None
    else:
        if was_reserved:
            domain.forfeit_funding_late_cancel(enrollment, session)
            enrollment["status"] = "LATE_CANCEL"
        else:
            enrollment["status"] = "CANCELED"
            enrollment["station_number"] = None
    enrollment["cancel_reason"] = "ATHLETE_REQUEST"
    touch(enrollment)
    touch(session)

    if was_reserved:
        domain.promote_waitlist(session)
        domain.apply_staffing_side_effects(session)
    return response.ok(serializers.enrollment(enrollment))


@bp.post("/enrollments/<enrollment_id>/attend")
def attend_enrollment(enrollment_id):
    ctx = guard("Coach")
    enrollment = get_enrollment(enrollment_id)
    resolve_acting_staff(ctx)
    body_json()

    require_state(enrollment, "status", ("RESERVED",), ENROLLMENT_TERMINAL, "Enrollment")
    session = store.group_sessions[enrollment["group_session_id"]]
    require_state(session, "session_status", ("IN_PROGRESS",), ("CANCELED",), "GroupSession")

    enrollment["status"] = "ATTENDED"
    domain.consume_package_credit(enrollment)
    touch(enrollment)
    athlete = store.athletes.get(enrollment["athlete_id"])
    if athlete is not None:
        athlete["attended_count"] += 1
        touch(athlete)
    return response.ok(serializers.enrollment(enrollment))


@bp.post("/enrollments/<enrollment_id>/no-show")
def no_show_enrollment(enrollment_id):
    ctx = guard("Coach")
    enrollment = get_enrollment(enrollment_id)
    resolve_acting_staff(ctx)
    body_json()

    require_state(enrollment, "status", ("RESERVED",), ENROLLMENT_TERMINAL, "Enrollment")
    session = store.group_sessions[enrollment["group_session_id"]]
    require_state(
        session, "session_status", ("IN_PROGRESS", "COMPLETED"), ("CANCELED",), "GroupSession"
    )

    domain.mark_no_show(enrollment, session)
    return response.ok(serializers.enrollment(enrollment))
