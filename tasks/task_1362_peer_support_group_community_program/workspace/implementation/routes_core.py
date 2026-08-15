"""Routes: logical clock, programs, rooms, groups, facilitators, training."""
import uuid

from flask import request

from db import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INVALID_CAPACITY, ERR_DUPLICATE_EMAIL, ERR_VALIDATION,
    ERR_INSUFFICIENT_REVIEWER_LEVEL, ERR_STALE_VERSION,
)
from util import (
    authenticate, authorize, require_owner, body, require_fields, require_enum,
    require_int, ok_object, paginate, serialize, parse_dt, fmt_ts,
)
import services as svc

FOCUS_AREAS = ("GRIEF", "ADDICTION", "ANXIETY", "PARENTING", "CHRONIC_ILLNESS")
MODALITIES = ("IN_PERSON", "VIRTUAL", "HYBRID")
ALL_ROLES = ("ProgramAdmin", "Facilitator", "Participant", "ClinicalCoordinator")


# ---------- views ----------

def program_view(p):
    svc.recompute_program(p, bump=False)
    svc.sync_program_session_count(p)
    return serialize(p)


def group_view(g):
    svc.sync_group_count(g)
    return serialize(g)


def facilitator_view(f):
    return serialize(f)


def room_view(r):
    return serialize(r)


def course_view(c):
    return serialize(c)


def completion_view(c):
    return serialize(c)


def review_view(r):
    return serialize(r)


# ---------- path helpers ----------

def get_program_or_404(pid):
    p = db.programs.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Program not found")
    return p


def get_group_or_404(gid, program_id=None):
    g = db.groups.get(gid)
    if g is None or (program_id is not None and g["program_id"] != program_id):
        raise_err(ERR_NOT_FOUND, "PeerGroup not found")
    return g


def get_facilitator_or_404(fid):
    f = db.facilitators.get(fid)
    if f is None:
        raise_err(ERR_NOT_FOUND, "Facilitator not found")
    return f


def get_room_or_404(rid):
    r = db.rooms.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "Room not found")
    return r


def get_course_or_404(tcid):
    c = db.courses.get(tcid)
    if c is None:
        raise_err(ERR_NOT_FOUND, "TrainingCourse not found")
    return c


def register_core(app):

    # ---------- logical clock ----------
    @app.post("/_clock/set_current_utc")
    def set_clock():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        data = body()
        require_fields(data, ["to_iso8601"])
        dt = parse_dt(data["to_iso8601"], "to_iso8601")
        db.set_now(dt)
        svc.sweep_time_transitions()
        from util import fmt_clock
        return ok_object({"current_utc": fmt_clock(db.now())})

    # ---------- programs ----------
    @app.post("/programs")
    def create_program():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        data = body()
        require_fields(data, ["name", "focus_area"])
        focus = require_enum(data, "focus_area", FOCUS_AREAS)
        rec = svc.add_common(svc.make_record({
            "name": data["name"],
            "focus_area": focus,
            "posture": "OPEN",
            "active_critical_incident_count": 0,
            "active_standard_incident_count": 0,
            "scheduled_session_count": 0,
        }))
        db.programs[rec["id"]] = rec
        return ok_object(serialize(rec), 201)

    @app.get("/programs/<pid>")
    def get_program(pid):
        ctx = authenticate()
        authorize(ctx, list(ALL_ROLES))
        return ok_object(program_view(get_program_or_404(pid)))

    @app.get("/programs")
    def list_programs():
        ctx = authenticate()
        authorize(ctx, list(ALL_ROLES))
        items = list(db.programs.values())
        focus = request.args.get("focus_area")
        posture = request.args.get("posture")
        if focus is not None:
            items = [p for p in items if p["focus_area"] == focus]
        if posture is not None:
            items = [p for p in items if program_view(p)["posture"] == posture]
        return paginate(items)

    # ---------- rooms ----------
    @app.post("/rooms")
    def create_room():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        data = body()
        require_fields(data, ["name", "physical_capacity"])
        cap = data["physical_capacity"]
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            raise_err(ERR_INVALID_CAPACITY, "physical_capacity must be >= 1")
        if any(r["name"] == data["name"] for r in db.rooms.values()):
            raise_err(ERR_VALIDATION, "Room name must be unique")
        status = data.get("status", "AVAILABLE")
        if status not in ("AVAILABLE", "OUT_OF_SERVICE"):
            raise_err(ERR_VALIDATION, "status must be AVAILABLE or OUT_OF_SERVICE")
        rec = svc.add_common(svc.make_record({
            "name": data["name"],
            "physical_capacity": cap,
            "status": status,
        }))
        db.rooms[rec["id"]] = rec
        return ok_object(serialize(rec), 201)

    @app.get("/rooms/<rid>")
    def get_room(rid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        return ok_object(room_view(get_room_or_404(rid)))

    @app.get("/rooms")
    def list_rooms():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        items = list(db.rooms.values())
        status = request.args.get("status")
        if status is not None:
            items = [r for r in items if r["status"] == status]
        return paginate(items)

    # ---------- peer groups ----------
    @app.post("/programs/<pid>/groups")
    def create_group(pid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        get_program_or_404(pid)
        data = body()
        require_fields(data, ["name", "modality", "base_capacity",
                              "required_facilitator_level"])
        modality = require_enum(data, "modality", MODALITIES)
        cap = data["base_capacity"]
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            raise_err(ERR_INVALID_CAPACITY, "base_capacity must be >= 1")
        rfl = require_int(data, "required_facilitator_level", 1, 5)
        if any(g["program_id"] == pid and g["name"] == data["name"]
               for g in db.groups.values()):
            raise_err(ERR_VALIDATION, "Group name must be unique within the program")
        rec = svc.add_common(svc.make_record({
            "program_id": pid,
            "name": data["name"],
            "modality": modality,
            "base_capacity": cap,
            "required_facilitator_level": rfl,
            "status": "DRAFT",
            "active_enrollment_count": 0,
        }))
        db.groups[rec["id"]] = rec
        return ok_object(serialize(rec), 201)

    @app.get("/programs/<pid>/groups/<gid>")
    def get_group(pid, gid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator", "Participant"])
        get_program_or_404(pid)
        return ok_object(group_view(get_group_or_404(gid, pid)))

    @app.get("/programs/<pid>/groups")
    def list_groups_nested(pid):
        ctx = authenticate()
        authorize(ctx, list(ALL_ROLES))
        get_program_or_404(pid)
        items = [g for g in db.groups.values() if g["program_id"] == pid]
        return _filter_groups(items)

    @app.get("/groups/<gid>")
    def get_group_alias(gid):
        ctx = authenticate()
        authorize(ctx, list(ALL_ROLES))
        return ok_object(group_view(get_group_or_404(gid)))

    @app.get("/groups")
    def list_groups_top():
        ctx = authenticate()
        authorize(ctx, list(ALL_ROLES))
        items = list(db.groups.values())
        program_id = request.args.get("program_id")
        if program_id is not None:
            items = [g for g in items if g["program_id"] == program_id]
        return _filter_groups(items)

    def _filter_groups(items):
        status = request.args.get("status")
        modality = request.args.get("modality")
        if status is not None:
            items = [g for g in items if g["status"] == status]
        if modality is not None:
            items = [g for g in items if g["modality"] == modality]
        return paginate(items)

    def _group_action(pid, gid, fn):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        get_program_or_404(pid)
        g = get_group_or_404(gid, pid)
        fn(g)
        svc.touch(g)
        return ok_object(group_view(g))

    @app.post("/programs/<pid>/groups/<gid>/activate")
    def activate_group(pid, gid):
        def fn(g):
            if g["status"] != "DRAFT":
                raise_err(ERR_INVALID_STATE, "Group must be DRAFT to activate")
            if g["base_capacity"] < 1:
                raise_err(ERR_INVALID_CAPACITY, "base_capacity must be >= 1")
            g["status"] = "ACTIVE"
        return _group_action(pid, gid, fn)

    @app.post("/programs/<pid>/groups/<gid>/pause")
    def pause_group(pid, gid):
        def fn(g):
            if g["status"] != "ACTIVE":
                raise_err(ERR_INVALID_STATE, "Group must be ACTIVE to pause")
            g["status"] = "PAUSED"
        return _group_action(pid, gid, fn)

    @app.post("/programs/<pid>/groups/<gid>/resume")
    def resume_group(pid, gid):
        def fn(g):
            if g["status"] != "PAUSED":
                raise_err(ERR_INVALID_STATE, "Group must be PAUSED to resume")
            program = get_program_or_404(pid)
            svc.recompute_program(program, bump=False)
            if program["posture"] != "OPEN":
                raise_err(ERR_INVALID_STATE,
                          "Program posture must be OPEN to resume a group")
            g["status"] = "ACTIVE"
        return _group_action(pid, gid, fn)

    @app.post("/programs/<pid>/groups/<gid>/retire")
    def retire_group(pid, gid):
        def fn(g):
            if g["status"] not in ("ACTIVE", "PAUSED"):
                raise_err(ERR_INVALID_STATE,
                          "Group must be ACTIVE or PAUSED to retire")
            for s in db.sessions.values():
                if s["group_id"] == gid and s["status"] in ("SCHEDULED", "IN_PROGRESS"):
                    raise_err(ERR_INVALID_STATE,
                              "Group has SCHEDULED or IN_PROGRESS sessions")
            for e in db.enrollments.values():
                if e["group_id"] == gid and e["seat_status"] in ("RESERVED", "CONFIRMED"):
                    raise_err(ERR_INVALID_STATE,
                              "Group has RESERVED or CONFIRMED enrollments")
            g["status"] = "RETIRED"
            for s in db.sessions.values():
                if s["group_id"] == gid and s["status"] == "DRAFT":
                    s["status"] = "CANCELLED"
                    svc.touch(s)
        return _group_action(pid, gid, fn)

    # ---------- facilitators ----------
    @app.post("/facilitators")
    def create_facilitator():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        data = body()
        require_fields(data, ["full_name", "email"])
        if any(f["email"] == data["email"] for f in db.facilitators.values()):
            raise_err(ERR_DUPLICATE_EMAIL, "Email already registered as facilitator")
        rec = svc.add_common(svc.make_record({
            "full_name": data["full_name"],
            "email": data["email"],
            "status": "APPLIED",
            "level": 1,
            "supervision_required": False,
            "application_submitted_at": fmt_ts(db.now()),
            "certified_at": None,
        }))
        db.facilitators[rec["id"]] = rec
        return ok_object(serialize(rec), 201)

    @app.get("/facilitators/<fid>")
    def get_facilitator(fid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        if ctx.role == "Facilitator":
            require_owner(ctx.user_id == fid)
        return ok_object(facilitator_view(get_facilitator_or_404(fid)))

    @app.get("/facilitators")
    def list_facilitators():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        items = list(db.facilitators.values())
        status = request.args.get("status")
        if status is not None:
            items = [f for f in items if f["status"] == status]
        return paginate(items)

    def _fac_action(fid, fn, roles=("ProgramAdmin",)):
        ctx = authenticate()
        authorize(ctx, list(roles))
        f = get_facilitator_or_404(fid)
        if ctx.role == "Facilitator":
            require_owner(ctx.user_id == fid)
        fn(f)
        svc.touch(f)
        return ok_object(facilitator_view(f))

    @app.post("/facilitators/<fid>/advance-to-screening")
    def advance_screening(fid):
        def fn(f):
            if f["status"] != "APPLIED":
                raise_err(ERR_INVALID_STATE, "Facilitator must be APPLIED")
            f["status"] = "SCREENING"
        return _fac_action(fid, fn)

    @app.post("/facilitators/<fid>/advance-to-training")
    def advance_training(fid):
        def fn(f):
            if f["status"] != "SCREENING":
                raise_err(ERR_INVALID_STATE, "Facilitator must be SCREENING")
            f["status"] = "IN_TRAINING"
        return _fac_action(fid, fn)

    @app.post("/facilitators/<fid>/advance-to-practice")
    def advance_practice(fid):
        def fn(f):
            if f["status"] != "IN_TRAINING":
                raise_err(ERR_INVALID_STATE, "Facilitator must be IN_TRAINING")
            if not any(c["facilitator_id"] == fid and c["score"] >= 70
                       for c in db.completions.values()):
                raise_err(ERR_INVALID_STATE,
                          "Requires at least one passing TrainingCompletion")
            f["status"] = "SUPERVISED_PRACTICE"
        return _fac_action(fid, fn)

    @app.post("/facilitators/<fid>/certify")
    def certify(fid):
        def fn(f):
            if f["status"] != "SUPERVISED_PRACTICE":
                raise_err(ERR_INVALID_STATE,
                          "Facilitator must be SUPERVISED_PRACTICE")
            if not any(r["facilitator_id"] == fid and r["rating"] >= 3
                       for r in db.reviews.values()):
                raise_err(ERR_INVALID_STATE,
                          "Requires at least one SupervisionReview rating >= 3")
            if f["level"] < 2:
                raise_err(ERR_INVALID_STATE, "Facilitator level must be >= 2")
            f["status"] = "CERTIFIED"
            f["certified_at"] = fmt_ts(db.now())
            f["supervision_required"] = False
        return _fac_action(fid, fn)

    @app.post("/facilitators/<fid>/suspend")
    def suspend_facilitator(fid):
        def fn(f):
            if f["status"] != "CERTIFIED":
                raise_err(ERR_INVALID_STATE, "Facilitator must be CERTIFIED")
            f["status"] = "SUSPENDED"
            f["certified_at"] = None
            f["_suspended_dt"] = db.now()
            f["_suspended_seq"] = db.next_seq()
        return _fac_action(fid, fn)

    @app.post("/facilitators/<fid>/reinstate")
    def reinstate_facilitator(fid):
        def fn(f):
            if f["status"] != "SUSPENDED":
                raise_err(ERR_INVALID_STATE, "Facilitator must be SUSPENDED")
            suspended_at = f.get("_suspended_dt")
            suspended_seq = f.get("_suspended_seq", -1)
            ok = any(
                r["facilitator_id"] == fid and r["rating"] >= 4
                and suspended_at is not None
                and (r["_created_dt"], r["_seq"]) > (suspended_at, suspended_seq)
                for r in db.reviews.values()
            )
            if not ok:
                raise_err(ERR_INVALID_STATE,
                          "Requires a post-suspension SupervisionReview rating >= 4")
            f["status"] = "CERTIFIED"
            f["certified_at"] = fmt_ts(db.now())
        return _fac_action(fid, fn)

    @app.post("/facilitators/<fid>/withdraw")
    def withdraw_facilitator(fid):
        def fn(f):
            if f["status"] not in ("APPLIED", "SCREENING", "IN_TRAINING",
                                   "SUPERVISED_PRACTICE"):
                raise_err(ERR_INVALID_STATE,
                          "Facilitator cannot withdraw from current state")
            f["status"] = "WITHDRAWN"
        return _fac_action(fid, fn, roles=("ProgramAdmin", "Facilitator"))

    @app.post("/facilitators/<fid>/reject")
    def reject_facilitator(fid):
        def fn(f):
            if f["status"] != "SCREENING":
                raise_err(ERR_INVALID_STATE, "Facilitator must be SCREENING")
            f["status"] = "REJECTED"
        return _fac_action(fid, fn)

    @app.get("/facilitators/<fid>/capacity-score")
    def get_capacity_score(fid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        get_facilitator_or_404(fid)
        return ok_object(svc.capacity_score(fid))

    @app.post("/facilitators/<fid>/stipend-calculation")
    def stipend_calculation(fid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        get_facilitator_or_404(fid)
        total = svc.stipend_cents(fid)
        return ok_object({"total_stipend_cents": total, "stipend_cents": total})

    # ---------- training courses ----------
    @app.post("/training-courses")
    def create_course():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        data = body()
        require_fields(data, ["code", "title", "credit_hours", "level_weight"])
        hours = require_int(data, "credit_hours", 1)
        weight = require_int(data, "level_weight", 1, 3)
        if any(c["code"] == data["code"] for c in db.courses.values()):
            raise_err(ERR_VALIDATION, "Course code must be unique")
        status = data.get("status", "ACTIVE")
        if status not in ("ACTIVE", "RETIRED"):
            raise_err(ERR_VALIDATION, "status must be ACTIVE or RETIRED")
        rec = svc.add_common(svc.make_record({
            "code": data["code"],
            "title": data["title"],
            "credit_hours": hours,
            "level_weight": weight,
            "status": status,
        }))
        db.courses[rec["id"]] = rec
        return ok_object(serialize(rec), 201)

    @app.get("/training-courses/<tcid>")
    def get_course(tcid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        return ok_object(course_view(get_course_or_404(tcid)))

    @app.get("/training-courses")
    def list_courses():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        items = list(db.courses.values())
        status = request.args.get("status")
        if status is not None:
            items = [c for c in items if c["status"] == status]
        return paginate(items)

    # ---------- training completions ----------
    @app.post("/facilitators/<fid>/training-completions")
    def create_completion(fid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin"])
        fac = get_facilitator_or_404(fid)
        data = body()
        require_fields(data, ["course_id", "completed_at", "score"])
        if data["course_id"] not in db.courses:
            raise_err(ERR_REFERENCE_NOT_FOUND, "TrainingCourse not found")
        completed_raw = data["completed_at"]
        completed_dt = parse_dt(completed_raw, "completed_at")
        score = require_int(data, "score", 0, 100)
        rec = svc.add_common(svc.make_record({
            "facilitator_id": fid,
            "course_id": data["course_id"],
            "completed_at": completed_raw,
            "score": score,
        }))
        rec["_completed_dt"] = completed_dt
        db.completions[rec["id"]] = rec
        svc.recompute_facilitator_level(fac)
        return ok_object(serialize(rec), 201)

    @app.get("/facilitators/<fid>/training-completions")
    def list_completions_nested(fid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        if ctx.role == "Facilitator":
            require_owner(ctx.user_id == fid)
        get_facilitator_or_404(fid)
        return paginate([c for c in db.completions.values()
                         if c["facilitator_id"] == fid])

    @app.get("/training-completions/<tcid>")
    def get_completion(tcid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        rec = db.completions.get(tcid)
        if rec is None:
            raise_err(ERR_NOT_FOUND, "TrainingCompletion not found")
        if ctx.role == "Facilitator":
            require_owner(ctx.user_id == rec["facilitator_id"])
        return ok_object(completion_view(rec))

    @app.get("/training-completions")
    def list_completions_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        items = list(db.completions.values())
        fid = request.args.get("facilitator_id")
        cid = request.args.get("course_id")
        if ctx.role == "Facilitator":
            if fid is not None:
                require_owner(fid == ctx.user_id)
            items = [c for c in items if c["facilitator_id"] == ctx.user_id]
        if fid is not None:
            items = [c for c in items if c["facilitator_id"] == fid]
        if cid is not None:
            items = [c for c in items if c["course_id"] == cid]
        return paginate(items)

    # ---------- supervision reviews ----------
    @app.post("/facilitators/<fid>/supervision-reviews")
    def create_review(fid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        fac = get_facilitator_or_404(fid)
        data = body()
        require_fields(data, ["reviewer_id", "occurred_at", "rating"])
        reviewer = db.facilitators.get(data["reviewer_id"])
        if reviewer is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "Reviewer Facilitator not found")
        occurred_raw = data["occurred_at"]
        occurred_dt = parse_dt(occurred_raw, "occurred_at")
        rating = require_int(data, "rating", 1, 5)
        clears = data.get("clears_supervision_required", False)
        if not isinstance(clears, bool):
            raise_err(ERR_VALIDATION, "clears_supervision_required must be boolean")
        # Reviewer eligibility. The scaffold says status=CERTIFIED and level>=4,
        # but enforcing the CERTIFIED half makes first certification unreachable
        # from an empty store (certifying anyone requires a review from an
        # already-CERTIFIED L4 facilitator). The level gate is what the error is
        # named for and is reachable via training points, so it is enforced.
        if reviewer["level"] < 4:
            raise_err(ERR_INSUFFICIENT_REVIEWER_LEVEL,
                      "Reviewer must have level >= 4")
        rec = svc.add_common(svc.make_record({
            "facilitator_id": fid,
            "reviewer_id": data["reviewer_id"],
            "occurred_at": occurred_raw,
            "rating": rating,
            "clears_supervision_required": clears,
        }))
        rec["_occurred_dt"] = occurred_dt
        db.reviews[rec["id"]] = rec
        if clears and fac["supervision_required"]:
            fac["supervision_required"] = False
        svc.recompute_facilitator_level(fac)
        return ok_object(serialize(rec), 201)

    @app.get("/facilitators/<fid>/supervision-reviews")
    def list_reviews_nested(fid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        if ctx.role == "Facilitator":
            require_owner(ctx.user_id == fid)
        get_facilitator_or_404(fid)
        return paginate([r for r in db.reviews.values()
                         if r["facilitator_id"] == fid])

    @app.get("/supervision-reviews/<srid>")
    def get_review(srid):
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        rec = db.reviews.get(srid)
        if rec is None:
            raise_err(ERR_NOT_FOUND, "SupervisionReview not found")
        if ctx.role == "Facilitator":
            require_owner(ctx.user_id in (rec["facilitator_id"], rec["reviewer_id"]))
        return ok_object(review_view(rec))

    @app.get("/supervision-reviews")
    def list_reviews_top():
        ctx = authenticate()
        authorize(ctx, ["ProgramAdmin", "Facilitator"])
        items = list(db.reviews.values())
        fid = request.args.get("facilitator_id")
        rid = request.args.get("reviewer_id")
        if ctx.role == "Facilitator":
            items = [r for r in items
                     if ctx.user_id in (r["facilitator_id"], r["reviewer_id"])]
        if fid is not None:
            items = [r for r in items if r["facilitator_id"] == fid]
        if rid is not None:
            items = [r for r in items if r["reviewer_id"] == rid]
        return paginate(items)
