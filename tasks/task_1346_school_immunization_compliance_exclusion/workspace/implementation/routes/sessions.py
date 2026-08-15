"""ClinicSession endpoints (PRD §3.7)."""

from datetime import timedelta

from flask import request

import db
from db import clock, parse_iso, format_iso, stamp_new, touch
from errors import (
    ApiError,
    ERR_SESSION_GAP_VIOLATION,
    ERR_SESSION_NOT_CANCELLABLE,
    ERR_SESSION_NOT_CLOSABLE,
    ERR_SESSION_NOT_FOUND,
    ERR_SESSION_NOT_OPENABLE,
)
from middleware import require_roles
from response import success_object, success_list
from services.evaluation import session_view
from services.validate import (
    parse_pagination, paginate, req_datetime, req_int, req_string, require_body,
)

ALL_ROLES = ("HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator")

MIN_SESSION_GAP_DAYS = 7


def _recompute_booked_count(session):
    session["booked_count"] = sum(
        1 for a in db.clinic_appointments.values()
        if a["clinic_session_id"] == session["id"] and a["status"] == "BOOKED"
    )


def register(app):

    @app.post("/api/clinic-sessions")
    def create_session():
        require_roles("SchoolNurse")
        body = require_body(request.get_json(silent=True))
        school_code = req_string(body, "school_code")
        session_date = req_datetime(body, "session_date")
        duration_minutes = req_int(body, "duration_minutes", minimum=1)
        capacity = req_int(body, "capacity", minimum=1)

        # 7a: same-school gap >= 7 days against SCHEDULED/OPEN/CLOSED sessions
        gap = timedelta(days=MIN_SESSION_GAP_DAYS)
        for existing in db.clinic_sessions.values():
            if existing["school_code"] != school_code:
                continue
            if existing["status"] not in ("SCHEDULED", "OPEN", "CLOSED"):
                continue
            existing_date = parse_iso(existing["session_date"])
            if abs(existing_date - session_date) < gap:
                raise ApiError(
                    ERR_SESSION_GAP_VIOLATION,
                    "New session is less than 7 days from an existing non-CANCELLED session for this school.",
                    409,
                )

        session = {
            "school_code": school_code,
            "session_date": format_iso(session_date),
            "duration_minutes": duration_minutes,
            "capacity": capacity,
            "booked_count": 0,
            "status": "SCHEDULED",
        }
        stamp_new(session)
        db.clinic_sessions[session["id"]] = session
        return success_object(session_view(session), status=201)

    @app.get("/api/clinic-sessions/<sid>")
    def get_session(sid):
        require_roles(*ALL_ROLES)
        session = db.clinic_sessions.get(sid)
        if session is None:
            raise ApiError(ERR_SESSION_NOT_FOUND, "Clinic session not found.", 404)
        return success_object(session_view(session))

    @app.post("/api/clinic-sessions/<sid>/open")
    def open_session(sid):
        require_roles("SchoolNurse")
        session = db.clinic_sessions.get(sid)
        if session is None:
            raise ApiError(ERR_SESSION_NOT_FOUND, "Clinic session not found.", 404)
        if session["status"] != "SCHEDULED":
            raise ApiError(
                ERR_SESSION_NOT_OPENABLE,
                "open requires the session to be in SCHEDULED.",
                409,
            )
        session["status"] = "OPEN"
        touch(session)
        return success_object(session_view(session))

    @app.post("/api/clinic-sessions/<sid>/close")
    def close_session(sid):
        require_roles("SchoolNurse")
        session = db.clinic_sessions.get(sid)
        if session is None:
            raise ApiError(ERR_SESSION_NOT_FOUND, "Clinic session not found.", 404)
        if session["status"] != "OPEN":
            raise ApiError(
                ERR_SESSION_NOT_CLOSABLE,
                "close requires the session to be in OPEN.",
                409,
            )
        session["status"] = "CLOSED"
        touch(session)
        return success_object(session_view(session))

    @app.post("/api/clinic-sessions/<sid>/cancel")
    def cancel_session(sid):
        require_roles("SchoolNurse")
        session = db.clinic_sessions.get(sid)
        if session is None:
            raise ApiError(ERR_SESSION_NOT_FOUND, "Clinic session not found.", 404)
        if session["status"] not in ("SCHEDULED", "OPEN"):
            raise ApiError(
                ERR_SESSION_NOT_CANCELLABLE,
                "cancel requires the session to be in SCHEDULED or OPEN.",
                409,
            )
        # Cascade: all BOOKED appointments -> CANCELLED
        for appt in db.clinic_appointments.values():
            if appt["clinic_session_id"] == session["id"] and appt["status"] == "BOOKED":
                appt["status"] = "CANCELLED"
                touch(appt)
        session["status"] = "CANCELLED"
        _recompute_booked_count(session)
        touch(session)
        return success_object(session_view(session))
