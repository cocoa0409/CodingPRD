"""Routes: participants, agreements, sessions, enrollments, attendance."""
import uuid

from flask import request

from db import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_EMAIL, ERR_VALIDATION, ERR_AGREEMENT_EXPIRED,
    ERR_AGREEMENT_VERSION_REGRESSION, ERR_PROGRAM_LOCKED_DOWN,
    ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT, ERR_GROUP_NOT_ACTIVE,
    ERR_GROUP_AT_CAPACITY, ERR_STALE_VERSION, ERR_INVALID_TIME_RANGE,
    ERR_COFACILITATOR_SAME_AS_PRIMARY, ERR_ROOM_OVERLAP,
    ERR_FACILITATOR_BUFFER_CONFLICT, ERR_FACILITATOR_LEVEL_TOO_LOW,
    ERR_SUPERVISION_REQUIRED, ERR_MODALITY_MISMATCH,
)
from util import (
    authenticate, authorize, require_owner, body, require_fields, require_enum,
    require_int, ok_object, paginate, serialize, parse_dt, fmt_ts,
)
import services as svc
from routes_core import (
    get_program_or_404, get_group_or_404, program_view, group_view,
)


# ---------- views ----------

def participant_view(p):
    return serialize(p)


def agreement_view(a):
    return serialize(a)


def session_view(s):
    reserved, confirmed = svc.seat_counts(s["group_id"])
    s["reserved_seats"] = reserved
    s["confirmed_seats"] = confirmed
    return serialize(s)


def enrollment_view(e):
    return serialize(e)


def attendance_view(a):
    return serialize(a)


# ---------- path helpers ----------

def get_participant_or_404(pid):
    p = db.participants.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Participant not found")
    return p


def get_session_or_404(sid, group_id=None):
    s = db.sessions.get(sid)
    if s is None or (group_id is not None and s["group_id"] != group_id):
        raise_err(ERR_NOT_FOUND, "Session not found")
    return s


def resolve_group_session(pid, gid, sid):
    """Left-to-right path validation: Program -> PeerGroup -> Session."""
    program = get_program_or_404(pid)
    group = get_group_or_404(gid, pid)
    session = get_session_or_404(sid, gid)
    return program, group, session


def get_enrollment_or_404(eid, group_id=None):
    e = db.enrollments.get(eid)
    if e is None or (group_id is not None and e["group_id"] != group_id):
        raise_err(ERR_NOT_FOUND, "Enrollment not found")
    return e


def get_attendance_or_404(aid, session_id=None):
    a = db.attendance.get(aid)
    if a is None or (session_id is not None and a["session_id"] != session_id):
        raise_err(ERR_NOT_FOUND, "AttendanceRecord not found")
    return a


def check_participant_self(ctx, participant_id):
    if ctx.role == "Participant":
        require_owner(ctx.user_id == participant_id)


def check_facilitator_assigned(ctx, session):
    if ctx.role == "Facilitator":
        require_owner(
            ctx.user_id == session["primary_facilitator_id"]
            or ctx.user_id == session.get("cofacilitator_id")
        )


def register_ops(app):

    # ---------- participants ----------
    @app.post("/participants")
    def create_participant():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        data = body()
        require_fields(data, ["full_name", "email", "household_size"])
        household = require_int(data, "household_size", 1, 8)
        if any(p["email"] == data["email"] for p in db.participants.values()):
            raise_err(ERR_DUPLICATE_EMAIL, "Email already registered as participant")
        rec = svc.add_common(svc.make_record({
            "full_name": data["full_name"],
            "email": data["email"],
            "household_size": household,
            "status": "REGISTERED",
            "attendance_streak": 0,
            "total_no_shows": 0,
            "current_agreement_id": None,
        }))
        db.participants[rec["id"]] = rec
        return ok_object(serialize(rec), 201)

    @app.get("/participants/<pid>")
    def get_participant(pid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant", "ClinicalCoordinator"])
        if ctx.role == "Participant":
            require_owner(ctx.user_id == pid)
        return ok_object(participant_view(get_participant_or_404(pid)))

    @app.get("/participants")
    def list_participants():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "ClinicalCoordinator"])
        items = list(db.participants.values())
        status = request.args.get("status")
        caid = request.args.get("current_agreement_id")
        if status is not None:
            items = [p for p in items if p["status"] == status]
        if caid is not None:
            items = [p for p in items if p.get("current_agreement_id") == caid]
        return paginate(items)

    def _participant_action(pid, fn):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        p = get_participant_or_404(pid)
        fn(p)
        svc.touch(p)
        return ok_object(participant_view(p))

    def _current_agreement_valid(p):
        aid = p.get("current_agreement_id")
        if not aid:
            return False
        a = db.agreements.get(aid)
        return (a is not None and a["status"] == "SIGNED"
                and a["_expires_dt"] > db.now())

    @app.post("/participants/<pid>/activate")
    def activate_participant(pid):
        def fn(p):
            if p["status"] != "REGISTERED":
                raise_err(ERR_INVALID_STATE, "Participant must be REGISTERED")
            if not _current_agreement_valid(p):
                raise_err(ERR_INVALID_STATE,
                          "Participant lacks a current SIGNED agreement")
            p["status"] = "ACTIVE"
        return _participant_action(pid, fn)

    @app.post("/participants/<pid>/suspend")
    def suspend_participant(pid):
        def fn(p):
            if p["status"] != "ACTIVE":
                raise_err(ERR_INVALID_STATE, "Participant must be ACTIVE")
            p["status"] = "SUSPENDED"
            svc.cancel_participant_enrollments(pid)
        return _participant_action(pid, fn)

    @app.post("/participants/<pid>/reinstate")
    def reinstate_participant(pid):
        def fn(p):
            if p["status"] != "SUSPENDED":
                raise_err(ERR_INVALID_STATE, "Participant must be SUSPENDED")
            if not _current_agreement_valid(p):
                raise_err(ERR_INVALID_STATE,
                          "Participant lacks a current SIGNED agreement")
            p["status"] = "ACTIVE"
        return _participant_action(pid, fn)

    @app.post("/participants/<pid>/deactivate")
    def deactivate_participant(pid):
        def fn(p):
            if p["status"] not in ("ACTIVE", "SUSPENDED"):
                raise_err(ERR_INVALID_STATE,
                          "Participant must be ACTIVE or SUSPENDED")
            for e in db.enrollments.values():
                if (e["participant_id"] == pid
                        and e["seat_status"] in ("RESERVED", "CONFIRMED")):
                    raise_err(ERR_INVALID_STATE,
                              "Participant has RESERVED or CONFIRMED enrollments")
            p["status"] = "DEACTIVATED"
            aid = p.get("current_agreement_id")
            if aid:
                a = db.agreements.get(aid)
                if a is not None and a["status"] == "SIGNED":
                    a["status"] = "REVOKED"
            p["current_agreement_id"] = None
        return _participant_action(pid, fn)

    # ---------- confidentiality agreements ----------
    @app.post("/participants/<pid>/agreements")
    def create_agreement(pid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        p = get_participant_or_404(pid)
        check_participant_self(ctx, pid)
        data = body()
        require_fields(data, ["signed_at", "expires_at", "agreement_version"])
        signed_raw = data["signed_at"]
        expires_raw = data["expires_at"]
        signed_dt = parse_dt(signed_raw, "signed_at")
        expires_dt = parse_dt(expires_raw, "expires_at")
        version = require_int(data, "agreement_version")
        # priority 16: expiry at signing
        if expires_dt <= signed_dt or expires_dt <= db.now():
            raise_err(ERR_AGREEMENT_EXPIRED,
                      "expires_at must be after signed_at and in the future")
        # priority 17: version regression
        existing = [a["agreement_version"] for a in db.agreements.values()
                    if a["participant_id"] == pid]
        if existing and version <= max(existing):
            raise_err(ERR_AGREEMENT_VERSION_REGRESSION,
                      "agreement_version must strictly increase per participant")
        rec = svc.make_record({
            "participant_id": pid,
            "signed_at": signed_raw,
            "expires_at": expires_raw,
            "status": "SIGNED",
            "agreement_version": version,
        })
        rec["_signed_dt"] = signed_dt
        rec["_expires_dt"] = expires_dt
        db.agreements[rec["id"]] = rec
        p["current_agreement_id"] = rec["id"]
        svc.touch(p)
        return ok_object(agreement_view(rec), 201)

    @app.get("/participants/<pid>/agreements")
    def list_agreements_nested(pid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        get_participant_or_404(pid)
        check_participant_self(ctx, pid)
        items = [a for a in db.agreements.values() if a["participant_id"] == pid]
        status = request.args.get("status")
        if status is not None:
            items = [a for a in items if a["status"] == status]
        return paginate(items)

    @app.get("/participants/<pid>/agreements/<aid>")
    def get_agreement_nested(pid, aid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        get_participant_or_404(pid)
        check_participant_self(ctx, pid)
        a = db.agreements.get(aid)
        if a is None or a["participant_id"] != pid:
            raise_err(ERR_NOT_FOUND, "ConfidentialityAgreement not found")
        return ok_object(agreement_view(a))

    @app.post("/participants/<pid>/agreements/<aid>/revoke")
    def revoke_agreement(pid, aid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        p = get_participant_or_404(pid)
        a = db.agreements.get(aid)
        if a is None or a["participant_id"] != pid:
            raise_err(ERR_NOT_FOUND, "ConfidentialityAgreement not found")
        if a["status"] != "SIGNED":
            raise_err(ERR_INVALID_STATE, "Agreement must be SIGNED to revoke")
        a["status"] = "REVOKED"
        if p.get("current_agreement_id") == aid:
            p["current_agreement_id"] = None
            svc.touch(p)
        svc.cancel_participant_enrollments(pid)
        return ok_object(agreement_view(a))

    @app.get("/agreements/<aid>")
    def get_agreement_alias(aid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        a = db.agreements.get(aid)
        if a is None:
            raise_err(ERR_NOT_FOUND, "ConfidentialityAgreement not found")
        check_participant_self(ctx, a["participant_id"])
        return ok_object(agreement_view(a))

    @app.get("/agreements")
    def list_agreements_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        items = list(db.agreements.values())
        pid = request.args.get("participant_id")
        if ctx.role == "Participant":
            if pid is not None:
                require_owner(pid == ctx.user_id)
            items = [a for a in items if a["participant_id"] == ctx.user_id]
        if pid is not None:
            items = [a for a in items if a["participant_id"] == pid]
        status = request.args.get("status")
        if status is not None:
            items = [a for a in items if a["status"] == status]
        return paginate(items)

    # ---------- sessions ----------
    @app.post("/programs/<pid>/groups/<gid>/sessions")
    def create_session(pid, gid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        get_program_or_404(pid)
        group = get_group_or_404(gid, pid)
        data = body()
        require_fields(data, ["start_at", "end_at", "primary_facilitator_id"])
        # priority 5: body FK existence
        room_id = data.get("room_id")
        room = None
        if room_id is not None:
            room = db.rooms.get(room_id)
            if room is None:
                raise_err(ERR_REFERENCE_NOT_FOUND, "Room not found")
        if data["primary_facilitator_id"] not in db.facilitators:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Primary facilitator not found")
        cofac_id = data.get("cofacilitator_id")
        if cofac_id is not None and cofac_id not in db.facilitators:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Cofacilitator not found")
        # modality/room compatibility
        if group["modality"] in ("IN_PERSON", "HYBRID") and room_id is None:
            raise_err(ERR_MODALITY_MISMATCH,
                      "room_id is required for IN_PERSON or HYBRID groups")
        if group["modality"] == "VIRTUAL" and room_id is not None:
            raise_err(ERR_MODALITY_MISMATCH,
                      "room_id is forbidden for VIRTUAL groups")
        start_raw, end_raw = data["start_at"], data["end_at"]
        start_dt = parse_dt(start_raw, "start_at")
        end_dt = parse_dt(end_raw, "end_at")
        # priority 13: time range
        if end_dt <= start_dt:
            raise_err(ERR_INVALID_TIME_RANGE, "end_at must be after start_at")
        # priority 18: cofacilitator distinctness
        if cofac_id is not None and cofac_id == data["primary_facilitator_id"]:
            raise_err(ERR_COFACILITATOR_SAME_AS_PRIMARY,
                      "cofacilitator_id must differ from primary_facilitator_id")
        rec = svc.add_common(svc.make_record({
            "group_id": gid,
            "room_id": room_id,
            "start_at": start_raw,
            "end_at": end_raw,
            "primary_facilitator_id": data["primary_facilitator_id"],
            "cofacilitator_id": cofac_id,
            "status": "DRAFT",
            "reserved_seats": 0,
            "confirmed_seats": 0,
            "effective_capacity": svc.effective_capacity(group, room),
            "virtual_link_token": None,
        }))
        rec["_start_dt"] = start_dt
        rec["_end_dt"] = end_dt
        rec["_program_id"] = pid
        db.sessions[rec["id"]] = rec
        return ok_object(session_view(rec), 201)

    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>")
    def get_session(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        _, _, s = resolve_group_session(pid, gid, sid)
        return ok_object(session_view(s))

    @app.get("/programs/<pid>/groups/<gid>/sessions")
    def list_sessions_nested(pid, gid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        get_program_or_404(pid)
        get_group_or_404(gid, pid)
        items = [s for s in db.sessions.values() if s["group_id"] == gid]
        status = request.args.get("status")
        if status is not None:
            items = [s for s in items if s["status"] == status]
        return paginate(items)

    @app.get("/sessions/<sid>")
    def get_session_alias(sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        return ok_object(session_view(get_session_or_404(sid)))

    @app.get("/sessions")
    def list_sessions_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        items = list(db.sessions.values())
        for param, field in (("group_id", "group_id"), ("room_id", "room_id"),
                             ("primary_facilitator_id", "primary_facilitator_id"),
                             ("cofacilitator_id", "cofacilitator_id"),
                             ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [s for s in items if s.get(field) == v]
        return paginate(items)

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/schedule")
    def schedule_session(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        program, group, s = resolve_group_session(pid, gid, sid)
        data = body()
        # priority 6: state
        if s["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Session must be DRAFT to schedule")
        # priority 7: lockdown
        svc.recompute_program(program, bump=False)
        if program["posture"] == "LOCKDOWN":
            raise_err(ERR_PROGRAM_LOCKED_DOWN,
                      "Program is in LOCKDOWN; scheduling blocked")
        # priority 11: group active
        if group["status"] != "ACTIVE":
            raise_err(ERR_GROUP_NOT_ACTIVE, "PeerGroup must be ACTIVE")
        # priority 14: room overlap
        if svc.room_conflict(s):
            raise_err(ERR_ROOM_OVERLAP, "Room booking conflict")
        # priority 15: facilitator buffer
        if svc.facilitator_conflict(s):
            raise_err(ERR_FACILITATOR_BUFFER_CONFLICT,
                      "Facilitator 30-minute buffer conflict")
        # priority 21: facilitator certification / level
        primary = db.facilitators[s["primary_facilitator_id"]]
        if primary["status"] != "CERTIFIED" or \
                primary["level"] < group["required_facilitator_level"]:
            raise_err(ERR_FACILITATOR_LEVEL_TOO_LOW,
                      "Primary facilitator must be CERTIFIED with sufficient level")
        cofac_id = s.get("cofacilitator_id")
        if cofac_id:
            cofac = db.facilitators[cofac_id]
            if cofac["status"] != "CERTIFIED" or cofac["level"] < 2:
                raise_err(ERR_FACILITATOR_LEVEL_TOO_LOW,
                          "Cofacilitator must be CERTIFIED with level >= 2")
        # priority 22: supervision gate
        if primary["supervision_required"]:
            raise_err(ERR_SUPERVISION_REQUIRED,
                      "Primary facilitator requires supervision first")
        # priority 26: OCC on facilitator version
        expected = data.get("expected_facilitator_version")
        if expected is not None and expected != primary["version"]:
            raise_err(ERR_STALE_VERSION,
                      "expected_facilitator_version does not match current version")
        # side effects
        s["status"] = "SCHEDULED"
        if group["modality"] in ("VIRTUAL", "HYBRID"):
            s["virtual_link_token"] = uuid.uuid4().hex
        svc.touch(s)
        program["scheduled_session_count"] = \
            svc.scheduled_session_count(program["id"])
        svc.touch(program)
        svc.touch(primary)
        return ok_object(session_view(s))

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/cancel")
    def cancel_session(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        program, group, s = resolve_group_session(pid, gid, sid)
        if s["status"] not in ("DRAFT", "SCHEDULED"):
            raise_err(ERR_INVALID_STATE,
                      "Only DRAFT or SCHEDULED sessions can be cancelled")
        was_scheduled = s["status"] == "SCHEDULED"
        s["status"] = "CANCELLED"
        svc.touch(s)
        if was_scheduled:
            for rec in db.attendance.values():
                if rec["session_id"] == sid and rec["status"] == "CHECKED_IN":
                    rec["status"] = "VOIDED"
                    svc.touch(rec)
                    p = db.participants.get(rec["participant_id"])
                    if p is not None and \
                            p["attendance_streak"] != rec.get("_streak_at_checkin", p["attendance_streak"]):
                        p["attendance_streak"] = rec.get("_streak_at_checkin", p["attendance_streak"])
                        svc.touch(p)
            program["scheduled_session_count"] = \
                svc.scheduled_session_count(program["id"])
            svc.touch(program)
        return ok_object(session_view(s))

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/complete")
    def complete_session(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        program, group, s = resolve_group_session(pid, gid, sid)
        check_facilitator_assigned(ctx, s)
        if s["status"] != "IN_PROGRESS":
            raise_err(ERR_INVALID_STATE, "Session must be IN_PROGRESS to complete")
        if db.now() < s["_end_dt"]:
            raise_err(ERR_INVALID_STATE, "Session end_at has not been reached")
        # attendance reconciliation: remaining CHECKED_IN become ATTENDED
        # once end_at has passed
        for rec in db.attendance.values():
            if rec["session_id"] == sid and rec["status"] == "CHECKED_IN":
                rec["status"] = "ATTENDED"
                svc.touch(rec)
        has_open_critical = any(
            inc["session_id"] == sid and inc["severity"] == "CRITICAL"
            and inc["status"] in ("OPEN", "ACKNOWLEDGED")
            for inc in db.incidents.values()
        )
        if has_open_critical:
            s["status"] = "COMPLETED_WITH_INCIDENT"
            primary = db.facilitators.get(s["primary_facilitator_id"])
            if primary is not None and not primary["supervision_required"]:
                primary["supervision_required"] = True
                svc.touch(primary)
            cofac_id = s.get("cofacilitator_id")
            if cofac_id:
                cofac = db.facilitators.get(cofac_id)
                if cofac is not None and not cofac["supervision_required"]:
                    cofac["supervision_required"] = True
                    svc.touch(cofac)
        else:
            s["status"] = "COMPLETED"
        svc.touch(s)
        program["scheduled_session_count"] = \
            svc.scheduled_session_count(program["id"])
        svc.touch(program)
        return ok_object(session_view(s))

    # ---------- enrollments ----------
    @app.post("/programs/<pid>/groups/<gid>/enrollments")
    def create_enrollment(pid, gid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        program = get_program_or_404(pid)
        group = get_group_or_404(gid, pid)
        data = body()
        require_fields(data, ["participant_id"])
        participant = db.participants.get(data["participant_id"])
        if participant is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Participant not found")
        check_participant_self(ctx, participant["id"])
        # priority 7: lockdown
        svc.recompute_program(program, bump=False)
        if program["posture"] == "LOCKDOWN":
            raise_err(ERR_PROGRAM_LOCKED_DOWN,
                      "Program is in LOCKDOWN; enrollment blocked")
        # priority 11: group active
        if group["status"] != "ACTIVE":
            raise_err(ERR_GROUP_NOT_ACTIVE, "PeerGroup must be ACTIVE")
        # priority 12: caution blocks creation
        if program["posture"] == "CAUTION":
            raise_err(ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT,
                      "Program is in CAUTION; new enrollments blocked")
        fee = svc.enrollment_fee_cents(participant)
        now = db.now()
        rec = svc.add_common(svc.make_record({
            "group_id": gid,
            "participant_id": participant["id"],
            "seat_status": "RESERVED",
            "agreement_status": "PENDING",
            "reserved_at": fmt_ts(now),
            "confirmed_at": None,
            "waitlist_position": None,
            "fee_cents": fee,
            "fee_after_subsidy_cents": fee,
        }))
        rec["_reserved_dt"] = now
        db.enrollments[rec["id"]] = rec
        if svc.active_enrollment_count(gid) > group["base_capacity"]:
            # group was already at capacity: seat goes straight to WAITLISTED
            rec["seat_status"] = "WAITLISTED"
        svc.renumber_waitlist(gid)
        svc.sync_group_count(group)
        svc.touch(group)
        return ok_object(enrollment_view(rec), 201)

    @app.get("/programs/<pid>/groups/<gid>/enrollments")
    def list_enrollments_nested(pid, gid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        get_program_or_404(pid)
        get_group_or_404(gid, pid)
        items = [e for e in db.enrollments.values() if e["group_id"] == gid]
        seat_status = request.args.get("seat_status")
        participant_id = request.args.get("participant_id")
        if seat_status is not None:
            items = [e for e in items if e["seat_status"] == seat_status]
        if participant_id is not None:
            items = [e for e in items if e["participant_id"] == participant_id]
        return paginate(items)

    @app.get("/programs/<pid>/groups/<gid>/enrollments/<eid>")
    def get_enrollment(pid, gid, eid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        get_program_or_404(pid)
        get_group_or_404(gid, pid)
        e = get_enrollment_or_404(eid, gid)
        check_participant_self(ctx, e["participant_id"])
        return ok_object(enrollment_view(e))

    @app.get("/enrollments/<eid>")
    def get_enrollment_alias(eid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        e = get_enrollment_or_404(eid)
        check_participant_self(ctx, e["participant_id"])
        return ok_object(enrollment_view(e))

    @app.get("/enrollments")
    def list_enrollments_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        items = list(db.enrollments.values())
        gid = request.args.get("group_id")
        pid = request.args.get("participant_id")
        seat_status = request.args.get("seat_status")
        if ctx.role == "Participant":
            if pid is not None:
                require_owner(pid == ctx.user_id)
            items = [e for e in items if e["participant_id"] == ctx.user_id]
        if gid is not None:
            items = [e for e in items if e["group_id"] == gid]
        if pid is not None:
            items = [e for e in items if e["participant_id"] == pid]
        if seat_status is not None:
            items = [e for e in items if e["seat_status"] == seat_status]
        return paginate(items)

    @app.post("/programs/<pid>/groups/<gid>/enrollments/<eid>/confirm")
    def confirm_enrollment(pid, gid, eid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        program = get_program_or_404(pid)
        group = get_group_or_404(gid, pid)
        e = get_enrollment_or_404(eid, gid)
        check_participant_self(ctx, e["participant_id"])
        data = body()
        # priority 6: state (enrollment + participant)
        if e["seat_status"] != "RESERVED":
            raise_err(ERR_INVALID_STATE, "Enrollment must be RESERVED to confirm")
        participant = db.participants.get(e["participant_id"])
        if participant is None or participant["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "Participant must be ACTIVE to confirm")
        # priority 7: lockdown
        svc.recompute_program(program, bump=False)
        if program["posture"] == "LOCKDOWN":
            raise_err(ERR_PROGRAM_LOCKED_DOWN,
                      "Program is in LOCKDOWN; confirmation blocked")
        # priority 11: group active
        if group["status"] != "ACTIVE":
            raise_err(ERR_GROUP_NOT_ACTIVE, "PeerGroup must be ACTIVE")
        # priority 16: agreement validity at confirmation
        aid = participant.get("current_agreement_id")
        agreement = db.agreements.get(aid) if aid else None
        if (agreement is None or agreement["status"] != "SIGNED"
                or agreement["_expires_dt"] <= db.now()):
            raise_err(ERR_AGREEMENT_EXPIRED,
                      "Participant's current agreement is missing or lapsed")
        # priority 20: capacity (this RESERVED seat already occupies capacity)
        svc.sync_group_count(group)
        if group["active_enrollment_count"] - 1 >= group["base_capacity"]:
            # confirmation attempt against a full group: seat -> WAITLISTED
            e["seat_status"] = "WAITLISTED"
            svc.touch(e)
            svc.renumber_waitlist(gid)
            svc.sync_group_count(group)
            svc.touch(group)
            raise_err(ERR_GROUP_AT_CAPACITY, "Group is at capacity")
        # priority 26: OCC on group version
        expected = data.get("expected_group_version")
        if expected is not None and expected != group["version"]:
            raise_err(ERR_STALE_VERSION,
                      "expected_group_version does not match current version")
        e["seat_status"] = "CONFIRMED"
        e["agreement_status"] = "SIGNED"
        e["confirmed_at"] = fmt_ts(db.now())
        svc.touch(e)
        svc.sync_group_count(group)
        svc.touch(group)  # explicit PeerGroup.version +1 per PRD §3.4
        return ok_object(enrollment_view(e))

    @app.post("/programs/<pid>/groups/<gid>/enrollments/<eid>/release")
    def release_enrollment(pid, gid, eid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Participant"])
        get_program_or_404(pid)
        group = get_group_or_404(gid, pid)
        e = get_enrollment_or_404(eid, gid)
        check_participant_self(ctx, e["participant_id"])
        if e["seat_status"] not in ("RESERVED", "CONFIRMED"):
            raise_err(ERR_INVALID_STATE,
                      "Only RESERVED or CONFIRMED enrollments can be released")
        svc.release_seat(e, group, "RELEASED")
        return ok_object(enrollment_view(e))

    # ---------- attendance ----------
    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/attendance")
    def check_in(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        program, group, s = resolve_group_session(pid, gid, sid)
        data = body()
        require_fields(data, ["participant_id", "access_modality"])
        participant = db.participants.get(data["participant_id"])
        if participant is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Participant not found")
        check_participant_self(ctx, participant["id"])
        access = require_enum(data, "access_modality", ("IN_PERSON", "VIRTUAL"))
        # priority 6: session must be IN_PROGRESS to accept check-ins
        if s["status"] != "IN_PROGRESS":
            raise_err(ERR_INVALID_STATE,
                      "Session is not IN_PROGRESS; check-in unavailable")
        # priority 7: lockdown
        svc.recompute_program(program, bump=False)
        if program["posture"] == "LOCKDOWN":
            raise_err(ERR_PROGRAM_LOCKED_DOWN,
                      "Program is in LOCKDOWN; check-in blocked")
        # priority 23: modality compatibility
        if group["modality"] == "IN_PERSON" and access != "IN_PERSON":
            raise_err(ERR_MODALITY_MISMATCH,
                      "IN_PERSON group accepts only IN_PERSON check-ins")
        if group["modality"] == "VIRTUAL" and access != "VIRTUAL":
            raise_err(ERR_MODALITY_MISMATCH,
                      "VIRTUAL group accepts only VIRTUAL check-ins")
        if access == "VIRTUAL":
            token = data.get("virtual_link_token")
            if not token or token != s.get("virtual_link_token"):
                raise_err(ERR_MODALITY_MISMATCH,
                          "VIRTUAL check-in requires the session virtual_link_token")
        if access == "IN_PERSON" and group["modality"] == "HYBRID":
            in_person_now = sum(
                1 for r in db.attendance.values()
                if r["session_id"] == sid and r["access_modality"] == "IN_PERSON"
                and r["status"] in ("CHECKED_IN", "ATTENDED")
            )
            if in_person_now >= svc.in_person_subcapacity(s, group):
                raise_err(ERR_MODALITY_MISMATCH,
                          "In-person sub-capacity reached for HYBRID session")
        now = db.now()
        rec = svc.add_common(svc.make_record({
            "session_id": sid,
            "participant_id": participant["id"],
            "check_in_at": fmt_ts(now),
            "check_out_at": None,
            "access_modality": access,
            "status": "CHECKED_IN",
        }))
        rec["_streak_at_checkin"] = participant["attendance_streak"]
        db.attendance[rec["id"]] = rec
        return ok_object(attendance_view(rec), 201)

    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>/attendance")
    def list_attendance_nested(pid, gid, sid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        resolve_group_session(pid, gid, sid)
        items = [a for a in db.attendance.values() if a["session_id"] == sid]
        status = request.args.get("status")
        if status is not None:
            items = [a for a in items if a["status"] == status]
        return paginate(items)

    @app.get("/programs/<pid>/groups/<gid>/sessions/<sid>/attendance/<aid>")
    def get_attendance_nested(pid, gid, sid, aid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        resolve_group_session(pid, gid, sid)
        rec = get_attendance_or_404(aid, sid)
        check_participant_self(ctx, rec["participant_id"])
        return ok_object(attendance_view(rec))

    @app.get("/attendance-records/<aid>")
    def get_attendance_alias(aid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        rec = get_attendance_or_404(aid)
        check_participant_self(ctx, rec["participant_id"])
        return ok_object(attendance_view(rec))

    @app.get("/attendance-records")
    def list_attendance_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        items = list(db.attendance.values())
        sid = request.args.get("session_id")
        pid = request.args.get("participant_id")
        status = request.args.get("status")
        if ctx.role == "Participant":
            if pid is not None:
                require_owner(pid == ctx.user_id)
            items = [a for a in items if a["participant_id"] == ctx.user_id]
        if sid is not None:
            items = [a for a in items if a["session_id"] == sid]
        if pid is not None:
            items = [a for a in items if a["participant_id"] == pid]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        return paginate(items)

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/attendance/<aid>/checkout")
    def checkout(pid, gid, sid, aid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        _, _, s = resolve_group_session(pid, gid, sid)
        rec = get_attendance_or_404(aid, sid)
        check_facilitator_assigned(ctx, s)
        check_participant_self(ctx, rec["participant_id"])
        if rec["status"] != "CHECKED_IN":
            raise_err(ERR_INVALID_STATE, "Record must be CHECKED_IN to check out")
        if db.now() < s["_start_dt"]:
            raise_err(ERR_INVALID_STATE,
                      "Checkout allowed once the session has started")
        rec["status"] = "ATTENDED"
        rec["check_out_at"] = fmt_ts(db.now())
        svc.touch(rec)
        p = db.participants.get(rec["participant_id"])
        if p is not None:
            p["attendance_streak"] = p.get("attendance_streak", 0) + 1
            svc.touch(p)
        return ok_object(attendance_view(rec))

    @app.post("/programs/<pid>/groups/<gid>/sessions/<sid>/attendance/<aid>/void")
    def void_attendance(pid, gid, sid, aid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        _, _, s = resolve_group_session(pid, gid, sid)
        rec = get_attendance_or_404(aid, sid)
        check_facilitator_assigned(ctx, s)
        if rec["status"] != "CHECKED_IN":
            raise_err(ERR_INVALID_STATE, "Record must be CHECKED_IN to void")
        rec["status"] = "VOIDED"
        svc.touch(rec)
        p = db.participants.get(rec["participant_id"])
        if p is not None:
            # compensating invariant: restore streak to its pre-check-in value
            prior = rec.get("_streak_at_checkin", p["attendance_streak"])
            if p["attendance_streak"] != prior:
                p["attendance_streak"] = prior
                svc.touch(p)
        return ok_object(attendance_view(rec))
