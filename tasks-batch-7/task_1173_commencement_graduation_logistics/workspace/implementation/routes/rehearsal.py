"""Rehearsal session & attendance routes."""
from flask import request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VENUE_TIME_OVERLAP,
    ERR_DUPLICATE_REGISTRATION,
    ERR_REHEARSAL_FULL,
)
from middleware import get_caller, require_role, get_json_body, require_graduate_ownership
from response import success, success_list, parse_pagination, paginate
from services.common import (
    get_ceremony_or_404,
    get_venue_or_404,
    get_graduate_or_404,
    get_session_or_404,
    get_attendance_or_404,
    require_body_fields,
    require_int,
    require_string,
    graduate_eligible_gate,
)
from services.serialize import session_out, attendance_out


def _recompute_strikes(graduate):
    count = sum(
        1 for a in db.rehearsal_attendances.values()
        if a["graduate_id"] == graduate["id"] and a["status"] == "ABSENT"
    )
    graduate["conduct_strike_count"] = count
    graduate["walk_privilege_revoked"] = count >= 2
    db.touch(graduate)


def register(bp):
    @bp.route("/ceremonies/<cid>/rehearsal-sessions", methods=["POST"])
    def create_session(cid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        ceremony = get_ceremony_or_404(cid)
        body = get_json_body()
        require_body_fields(body, ["venue_id", "start_utc", "end_utc", "capacity"])
        get_venue_or_404(body["venue_id"])
        require_string(body, "start_utc")
        require_string(body, "end_utc")
        require_int(body, "capacity", 1)
        start_dt = db.parse_dt(body["start_utc"])
        end_dt = db.parse_dt(body["end_utc"])
        if end_dt <= start_dt:
            raise_err(ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")

        # half-open [start, end) overlap among SCHEDULED sessions at the same venue
        for s in db.rehearsal_sessions.values():
            if s["venue_id"] == body["venue_id"] and s["status"] == "SCHEDULED":
                ex_start = db.parse_dt(s["start_utc"])
                ex_end = db.parse_dt(s["end_utc"])
                if start_dt < ex_end and ex_start < end_dt:
                    raise_err(ERR_VENUE_TIME_OVERLAP, "Session overlaps another SCHEDULED session at this venue")

        now = db.now_iso()
        sid = db.new_id()
        session = {
            "id": sid,
            "ceremony_id": cid,
            "venue_id": body["venue_id"],
            "start_utc": body["start_utc"],
            "end_utc": body["end_utc"],
            "capacity": body["capacity"],
            "registered_count": 0,
            "status": "SCHEDULED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.rehearsal_sessions[sid] = session
        return success(session_out(session), status=201)

    @bp.route("/rehearsal-sessions/<sid>", methods=["GET"])
    def get_session(sid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        s = get_session_or_404(sid)
        return success(session_out(s))

    @bp.route("/rehearsal-sessions/<sid>/register", methods=["POST"])
    def register_for_session(sid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        session = get_session_or_404(sid)
        g = get_graduate_or_404(user_id)  # Graduate identity is entity-backed
        # graduate must belong to the ceremony of the session
        graduate_eligible_gate(g)
        if session["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Session is not SCHEDULED")
        existing = next(
            (a for a in db.rehearsal_attendances.values()
             if a["rehearsal_session_id"] == sid and a["graduate_id"] == g["id"]
             and a["status"] in {"REGISTERED", "ATTENDED"}),
            None,
        )
        if existing is not None:
            raise_err(ERR_DUPLICATE_REGISTRATION, "Graduate already registered for this session")
        registered = sum(
            1 for a in db.rehearsal_attendances.values()
            if a["rehearsal_session_id"] == sid and a["status"] in {"REGISTERED", "ATTENDED"}
        )
        if registered >= session["capacity"]:
            raise_err(ERR_REHEARSAL_FULL, "Session is full")

        now = db.now_iso()
        aid = db.new_id()
        att = {
            "id": aid,
            "rehearsal_session_id": sid,
            "graduate_id": g["id"],
            "status": "REGISTERED",
            "checked_in_at": None,
            "recorded_by_user_id": None,
            "waived_by_user_id": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.rehearsal_attendances[aid] = att
        session["registered_count"] = registered + 1
        db.touch(session)
        return success(attendance_out(att), status=201)

    @bp.route("/rehearsal-sessions/<sid>/complete", methods=["POST"])
    def complete_session(sid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        session = get_session_or_404(sid)
        if session["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Session is not SCHEDULED")
        affected_grads = set()
        for a in db.rehearsal_attendances.values():
            if a["rehearsal_session_id"] == sid and a["status"] == "REGISTERED":
                a["status"] = "ABSENT"
                a["recorded_by_user_id"] = user_id
                a["version"] += 1
                db.touch(a)
                affected_grads.add(a["graduate_id"])
        for gid in affected_grads:
            g = db.graduates.get(gid)
            if g is not None:
                _recompute_strikes(g)
        session["status"] = "COMPLETED"
        session["version"] += 1
        db.touch(session)
        return success(session_out(session))

    @bp.route("/rehearsal-sessions/<sid>/cancel", methods=["POST"])
    def cancel_session(sid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        session = get_session_or_404(sid)
        if session["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Session is not SCHEDULED")
        for a in db.rehearsal_attendances.values():
            if a["rehearsal_session_id"] == sid and a["status"] == "REGISTERED":
                a["status"] = "CANCELLED"
                a["version"] += 1
                db.touch(a)
        session["status"] = "CANCELLED"
        session["registered_count"] = sum(
            1 for a in db.rehearsal_attendances.values()
            if a["rehearsal_session_id"] == sid and a["status"] in {"REGISTERED", "ATTENDED"}
        )
        session["version"] += 1
        db.touch(session)
        return success(session_out(session))

    @bp.route("/rehearsal-sessions/<sid>/attendances", methods=["GET"])
    def list_session_attendances(sid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        get_session_or_404(sid)
        limit, offset = parse_pagination(request.args)
        items = [a for a in db.rehearsal_attendances.values() if a["rehearsal_session_id"] == sid]
        status_f = request.args.get("status")
        if status_f:
            items = [a for a in items if a["status"] == status_f]
        items.sort(key=lambda a: a["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([attendance_out(a) for a in page], limit, offset, total)

    @bp.route("/rehearsal-attendances/<aid>/check-in", methods=["POST"])
    def check_in(aid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        att = get_attendance_or_404(aid)
        session = get_session_or_404(att["rehearsal_session_id"])
        if att["status"] != "REGISTERED":
            raise_err(ERR_INVALID_STATE, "Attendance is not REGISTERED")
        if session["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Session is not SCHEDULED")
        att["status"] = "ATTENDED"
        att["checked_in_at"] = db.now_iso()
        att["version"] += 1
        db.touch(att)
        return success(attendance_out(att))

    @bp.route("/rehearsal-attendances/<aid>/waive", methods=["POST"])
    def waive(aid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        att = get_attendance_or_404(aid)
        # SoD (priority 6) before state (priority 8)
        if att["recorded_by_user_id"] is not None and user_id == att["recorded_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES, "Waiving coordinator must differ from recorder")
        if att["status"] != "ABSENT":
            raise_err(ERR_INVALID_STATE, "Attendance is not ABSENT")
        att["status"] = "EXCUSED"
        att["waived_by_user_id"] = user_id
        att["version"] += 1
        db.touch(att)
        g = db.graduates.get(att["graduate_id"])
        if g is not None:
            _recompute_strikes(g)
        return success(attendance_out(att))
