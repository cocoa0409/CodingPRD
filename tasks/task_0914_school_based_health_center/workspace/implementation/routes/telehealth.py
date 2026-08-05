"""Telehealth-into-the-classroom sessions (PRD 3.6)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import calc, cascades, serialize

bp = Blueprint("telehealth", __name__)


def _window(start_raw, end_raw):
    start_dt = clock.parse_datetime(start_raw)
    end_dt = clock.parse_datetime(end_raw)
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_SESSION_WINDOW", "end_at must be strictly after start_at."
        )
    duration = int((end_dt - start_dt).total_seconds() // 60)
    if (
        duration < config.TELEHEALTH_MIN_DURATION_MINUTES
        or duration > config.TELEHEALTH_MAX_DURATION_MINUTES
    ):
        raise ApiError(
            "ERR_INVALID_SESSION_WINDOW",
            "A session must last between 15 and 60 minutes inclusive.",
        )
    return start_dt, end_dt, duration


@bp.post("/sbhc/telehealth-sessions")
def create_session():
    op = Op("POST /sbhc/telehealth-sessions", ["Clinician"])
    op.body_id("visit", "visits", "visit_id", "ERR_VISIT_NOT_FOUND")
    op.schema(
        [
            Field("visit_id", "string", required=True),
            Field("start_at", "datetime", required=True),
            Field("end_at", "datetime", required=True),
        ]
    )

    def _session_window(op):
        start_dt, end_dt, duration = _window(op.body["start_at"], op.body["end_at"])
        op.rows["_window"] = (start_dt, end_dt, duration)

    def _site_posture(op):
        school = store.get("schools", op.get("visit")["school_id"])
        op.rows["school"] = school
        if school is not None and school["program_status"] != "ACTIVE":
            raise ApiError("ERR_SCHOOL_SUSPENDED", "The site's program is suspended.")

    def _state(op):
        visit = op.get("visit")
        if visit["delivery_mode"] != "TELEHEALTH":
            raise ApiError(
                "ERR_INVALID_STATE", "Only a TELEHEALTH encounter carries a session."
            )
        if visit["clinical_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "The encounter must be SCHEDULED or IN_PROGRESS.",
            )

    def _telehealth_consent(op):
        if helpers.find_usable_consent(op.get("visit")["student_id"], "TELEHEALTH") is None:
            raise ApiError(
                "ERR_TELEHEALTH_CONSENT_REQUIRED",
                "No ACTIVE unexpired TELEHEALTH consent is on file.",
            )

    def _clinician_axis(op):
        start_dt, end_dt, _ = op.rows["_window"]
        if calc.clinician_conflict(op.get("visit")["clinician_id"], start_dt, end_dt):
            raise ApiError(
                "ERR_CLINICIAN_SLOT_CONFLICT",
                "The clinician has a buffered-overlap conflict in this window.",
            )

    def _school_axis(op):
        start_dt, end_dt, _ = op.rows["_window"]
        school = op.rows.get("school")
        overlapping = calc.school_overlap_count(op.get("visit")["school_id"], start_dt, end_dt)
        capacity = school["telehealth_concurrent_capacity"] if school else 0
        if overlapping >= capacity:
            raise ApiError(
                "ERR_SCHOOL_CAPACITY_EXCEEDED",
                "The site's concurrent telehealth capacity is fully booked.",
            )

    op.hook(9, _session_window)
    op.hook(14, _site_posture)
    op.hook(17, _state)
    op.hook(19, _telehealth_consent)
    op.hook(26, _clinician_axis)
    op.hook(27, _school_axis)
    op.run()

    visit = op.get("visit")
    _, _, duration = op.rows["_window"]
    session = store.new_row(
        "sessions",
        {
            "visit_id": visit["id"],
            "clinician_id": visit["clinician_id"],
            "school_id": visit["school_id"],
            "start_at": op.body["start_at"],
            "end_at": op.body["end_at"],
            "duration_minutes": duration,
            "reschedule_count": 0,
            "closure_reason": None,
            "status": "SCHEDULED",
        },
    )
    school = op.rows.get("school")
    if school is not None:
        cascades.resync_school_minutes(school)
    return envelope.created(serialize.dump(session))


@bp.get("/sbhc/telehealth-sessions/<id>")
def read_session(id):
    op = Op("GET /sbhc/telehealth-sessions/{id}", ["Clinician", "SbhcAdmin", "Registrar"])
    op.path_id("session", "sessions", id, "ERR_RESOURCE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("session")))


@bp.get("/sbhc/telehealth-sessions")
def list_sessions():
    op = Op("GET /sbhc/telehealth-sessions", ["Clinician", "SbhcAdmin", "Registrar"])
    op.paginated()
    op.run()
    rows = store.all_rows("sessions")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "visit_id": "visit_id",
            "clinician_id": "clinician_id",
            "school_id": "school_id",
            "status": "status",
        },
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/telehealth-sessions/<id>/complete")
def complete_session(id):
    op = Op("POST /sbhc/telehealth-sessions/{id}/complete", ["Clinician"])
    op.path_id("session", "sessions", id, "ERR_RESOURCE_NOT_FOUND")

    def _state(op):
        if op.get("session")["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED session may be completed.")

    op.hook(17, _state)
    op.run()

    session = op.get("session")
    # SCHEDULED and COMPLETED both keep the booking, so the site total is unchanged.
    session["status"] = "COMPLETED"
    store.touch(session)
    return envelope.ok(serialize.dump(session))


@bp.post("/sbhc/telehealth-sessions/<id>/close")
def close_session(id):
    op = Op("POST /sbhc/telehealth-sessions/{id}/close", ["Clinician"])
    op.path_id("session", "sessions", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema(
        [
            Field("outcome", "enum", required=True, values=config.SESSION_CLOSE_OUTCOMES),
            Field("closure_reason", "string"),
        ]
    )

    def _state(op):
        session = op.get("session")
        if op.body["outcome"] == "CANCELLED":
            if session["status"] not in ("SCHEDULED", "NO_SHOW"):
                raise ApiError("ERR_INVALID_STATE", "This session cannot be cancelled.")
        else:
            if session["status"] != "SCHEDULED":
                raise ApiError(
                    "ERR_INVALID_STATE", "Only a SCHEDULED session may be a no-show."
                )

    def _grace(op):
        if op.body["outcome"] != "NO_SHOW":
            return
        session = op.get("session")
        earliest = clock.add_minutes(
            clock.parse_datetime(session["start_at"]), config.NO_SHOW_GRACE_MINUTES
        )
        if clock.now_dt() < earliest:
            raise ApiError(
                "ERR_NO_SHOW_TOO_EARLY", "The 10-minute no-show grace has not elapsed."
            )

    op.hook(17, _state)
    op.hook(25, _grace)
    op.run()

    session = op.get("session")
    session["closure_reason"] = op.field("closure_reason", None)
    cascades.move_session(session, op.body["outcome"])
    return envelope.ok(serialize.dump(session))


@bp.post("/sbhc/telehealth-sessions/<id>/reschedule")
def reschedule_session(id):
    op = Op("POST /sbhc/telehealth-sessions/{id}/reschedule", ["Clinician"])
    op.path_id("session", "sessions", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema(
        [
            Field("start_at", "datetime", required=True),
            Field("end_at", "datetime", required=True),
        ]
    )

    def _session_window(op):
        start_dt, end_dt, duration = _window(op.body["start_at"], op.body["end_at"])
        op.rows["_window"] = (start_dt, end_dt, duration)

    def _state(op):
        if op.get("session")["status"] != "NO_SHOW":
            raise ApiError("ERR_INVALID_STATE", "Only a NO_SHOW session may be rescheduled.")

    def _clinician_axis(op):
        start_dt, end_dt, _ = op.rows["_window"]
        session = op.get("session")
        if calc.clinician_conflict(
            session["clinician_id"], start_dt, end_dt, exclude_session_id=session["id"]
        ):
            raise ApiError(
                "ERR_CLINICIAN_SLOT_CONFLICT",
                "The clinician has a buffered-overlap conflict in this window.",
            )

    def _school_axis(op):
        start_dt, end_dt, _ = op.rows["_window"]
        session = op.get("session")
        school = store.get("schools", session["school_id"])
        overlapping = calc.school_overlap_count(
            session["school_id"], start_dt, end_dt, exclude_session_id=session["id"]
        )
        capacity = school["telehealth_concurrent_capacity"] if school else 0
        if overlapping >= capacity:
            raise ApiError(
                "ERR_SCHOOL_CAPACITY_EXCEEDED",
                "The site's concurrent telehealth capacity is fully booked.",
            )

    def _cap(op):
        if op.get("session")["reschedule_count"] >= config.MAX_SESSION_RESCHEDULES:
            raise ApiError(
                "ERR_RESCHEDULE_LIMIT_EXCEEDED",
                "This session has already been rescheduled twice.",
            )

    op.hook(9, _session_window)
    op.hook(17, _state)
    op.hook(26, _clinician_axis)
    op.hook(27, _school_axis)
    op.hook(30, _cap)
    op.run()

    session = op.get("session")
    _, _, duration = op.rows["_window"]
    session["start_at"] = op.body["start_at"]
    session["end_at"] = op.body["end_at"]
    session["duration_minutes"] = duration
    session["reschedule_count"] = session["reschedule_count"] + 1
    cascades.move_session(session, "SCHEDULED")
    return envelope.ok(serialize.dump(session))
