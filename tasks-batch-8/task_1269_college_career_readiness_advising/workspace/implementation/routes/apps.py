"""Applications (two state dimensions), milestones, decisions (PRD §3.4)."""

from flask import Blueprint, g

from store import stores, mint, bump, now
from util import (
    ok_object, paginate, fail, get_body, validate_schema, require_role,
    parse_datetime,
    ERR_VALIDATION, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STUDENT_NOT_ENROLLED, ERR_PLAN_NOT_ACTIVE, ERR_DEADLINE_PASSED,
    ERR_MILESTONES_INCOMPLETE, ERR_PENDING_REC_LETTERS,
    ERR_DECISION_NOT_ALLOWED, ERR_MILESTONE_NOT_ACTIONABLE,
    ERR_PREREQUISITE_INCOMPLETE, ERR_DUE_DATE_PAST,
)
from computed import ser_application, ser_milestone, student_active_plan
from cascades import waive_open_milestones
from routes.students import get_student_or_404, student_ownership

bp = Blueprint("apps", __name__)

PROGRAM_TYPES = ("COLLEGE_4YR", "COLLEGE_2YR", "TRADE_PROGRAM")
SUBMISSION_STATUSES = ("DRAFT", "READY", "SUBMITTED", "CONFIRMED", "WITHDRAWN")
DECISION_STATUSES = ("NONE", "PENDING", "ACCEPTED", "WAITLISTED", "DENIED", "DEFERRED")
MILESTONE_KINDS = ("ESSAY", "TRANSCRIPT", "FEE_PAYMENT", "TEST_SCORES",
                   "REC_LETTERS", "FAFSA", "INTERVIEW", "OTHER")
MILESTONE_STATUSES = ("PENDING", "READY", "COMPLETED", "MISSED", "WAIVED")
SEEDED_MILESTONES = ("ESSAY", "TRANSCRIPT", "FEE_PAYMENT")


def get_application_or_404(aid):
    a = stores["applications"].get(aid)
    if a is None:
        fail(ERR_NOT_FOUND, 404, "Application not found")
    return a


def get_milestone_or_404(mid):
    m = stores["milestones"].get(mid)
    if m is None:
        fail(ERR_NOT_FOUND, 404, "Milestone not found")
    return m


def app_ownership(app):
    student_ownership(app["student_id"])


def _new_milestone(app, kind, due_at, required, depends_on):
    rec = mint("milestones")
    if depends_on is None:
        status = "READY"
    else:
        dep = stores["milestones"][depends_on]
        status = "READY" if dep["status"] == "COMPLETED" else "PENDING"
    rec.update({
        "application_id": app["id"],
        "kind": kind,
        "required": required,
        "due_at": due_at,
        "depends_on_milestone_id": depends_on,
        "status": status,
        "completed_at": None,
        "last_reminder_sent_at": None,
    })
    stores["milestones"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.post("/ccr/students/<sid>/applications")
def application_create(sid):
    body = get_body()
    validate_schema(body, {
        "college_name": {"kind": "str", "required": True},
        "program_type": {"kind": "str", "required": True, "choices": PROGRAM_TYPES},
        "deadline_at": {"kind": "datetime", "required": True},
    })
    # Field constraint: deadline_at must be strictly in the future at creation.
    deadline = parse_datetime(body["deadline_at"])
    if deadline <= now():
        fail(ERR_VALIDATION, 400, "deadline_at must be in the future")
    require_role(g.user_role, "Student")
    student = get_student_or_404(sid)
    student_ownership(sid)
    if student["status"] != "ENROLLED":
        fail(ERR_STUDENT_NOT_ENROLLED, 409, "Student is not ENROLLED")
    if student_active_plan(sid) is None:
        fail(ERR_PLAN_NOT_ACTIVE, 409, "Student has no ACTIVE plan")
    rec = mint("applications")
    rec.update({
        "student_id": sid,
        "college_name": body["college_name"],
        "program_type": body["program_type"],
        "deadline_at": deadline,
        "submission_status": "DRAFT",
        "decision_status": "NONE",
        "submitted_at": None,
        "decided_at": None,
    })
    stores["applications"][rec["id"]] = rec
    # Auto-seed three required milestones due at deadline_at, no dependencies,
    # so all three arrive READY within the create response (PRD §3.4).
    for kind in SEEDED_MILESTONES:
        _new_milestone(rec, kind, deadline, True, None)
    return ok_object(ser_application(rec), 201)


@bp.get("/ccr/students/<sid>/applications")
def application_list(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    get_student_or_404(sid)
    student_ownership(sid)
    items = [a for a in stores["applications"].values() if a["student_id"] == sid]
    from flask import request
    status = request.args.get("submission_status")
    if status is not None:
        items = [a for a in items if a["submission_status"] == status]
    return paginate(items, ser_application)


@bp.get("/ccr/applications/<aid>")
def application_get(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    app = get_application_or_404(aid)
    app_ownership(app)
    return ok_object(ser_application(app), 200)


# Submission machine from-states; READY->DRAFT regression is system-only.
_SUBMISSION_TRANSITIONS = {
    "READY": ("DRAFT",),
    "SUBMITTED": ("READY",),
    "CONFIRMED": ("SUBMITTED",),
    "WITHDRAWN": ("DRAFT", "READY", "SUBMITTED"),
    "DRAFT": (),
}
# Per-target roles (PRD §4): Student drives READY/SUBMITTED/WITHDRAWN;
# DistrictAdmin drives CONFIRMED.
_SUBMISSION_TARGET_ROLES = {
    "READY": ("Student",),
    "SUBMITTED": ("Student",),
    "WITHDRAWN": ("Student",),
    "CONFIRMED": ("DistrictAdmin",),
}


@bp.post("/ccr/applications/<aid>/transition")
def application_transition(aid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": SUBMISSION_STATUSES},
    })
    require_role(g.user_role, "Student", "DistrictAdmin")
    target = body["to_status"]
    target_roles = _SUBMISSION_TARGET_ROLES.get(target)
    if target_roles is not None:
        require_role(g.user_role, *target_roles)
    app = get_application_or_404(aid)
    if g.user_role == "Student":
        app_ownership(app)
    allowed_from = _SUBMISSION_TRANSITIONS.get(target, ())
    if app["submission_status"] not in allowed_from:
        fail(ERR_INVALID_STATE, 409,
             f"Cannot move application from {app['submission_status']} to {target}")
    # Clock-relative gates (stage 11) precede cross-entity gates (stage 12).
    if target in ("READY", "SUBMITTED") and now() > app["deadline_at"]:
        fail(ERR_DEADLINE_PASSED, 409, "Application deadline has passed")
    if target == "READY":
        blockers = [m for m in stores["milestones"].values()
                    if m["application_id"] == aid and m["required"]
                    and m["status"] not in ("COMPLETED", "WAIVED")]
        if blockers:
            fail(ERR_MILESTONES_INCOMPLETE, 409, "Required milestones are incomplete")
    if target == "SUBMITTED":
        pending = [r for r in stores["rec_requests"].values()
                   if r["application_id"] == aid and r["status"] in ("REQUESTED", "ACCEPTED")]
        if pending:
            fail(ERR_PENDING_REC_LETTERS, 409, "Pending recommendation letters block submission")
    prior = app["submission_status"]
    app["submission_status"] = target
    if target == "SUBMITTED":
        app["submitted_at"] = now()
        if app["decision_status"] == "NONE":
            app["decision_status"] = "PENDING"
    if target == "WITHDRAWN" and prior in ("DRAFT", "READY"):
        waive_open_milestones(app)
    bump(app)
    return ok_object(ser_application(app), 200)


# Decision machine (parallel dimension). Legal client moves; decided_at is
# stamped only when the decision leaves PENDING (PRD §3.4, entity field note).
_DECISION_TRANSITIONS = {
    "PENDING": {"ACCEPTED", "WAITLISTED", "DENIED", "DEFERRED"},
    "DEFERRED": {"PENDING"},
    "WAITLISTED": {"ACCEPTED", "DENIED"},
    "ACCEPTED": set(),
    "DENIED": set(),
    "NONE": set(),
}


@bp.post("/ccr/applications/<aid>/decision")
def application_decision(aid):
    body = get_body()
    validate_schema(body, {
        "to_decision": {"kind": "str", "required": True, "choices": DECISION_STATUSES},
    })
    require_role(g.user_role, "DistrictAdmin")
    app = get_application_or_404(aid)
    if app["submission_status"] not in ("SUBMITTED", "CONFIRMED"):
        fail(ERR_DECISION_NOT_ALLOWED, 409,
             "Decisions require submission_status SUBMITTED or CONFIRMED")
    target = body["to_decision"]
    if target not in _DECISION_TRANSITIONS[app["decision_status"]]:
        fail(ERR_DECISION_NOT_ALLOWED, 409,
             f"Illegal decision move from {app['decision_status']} to {target}")
    if app["decision_status"] == "PENDING":
        app["decided_at"] = now()
    app["decision_status"] = target
    bump(app)
    return ok_object(ser_application(app), 200)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

@bp.post("/ccr/applications/<aid>/milestones")
def milestone_create(aid):
    body = get_body()
    validate_schema(body, {
        "kind": {"kind": "str", "required": True, "choices": MILESTONE_KINDS},
        "due_at": {"kind": "datetime", "required": True},
        "required": {"kind": "bool", "required": False},
        "depends_on_milestone_id": {"kind": "str", "required": False},
    })
    require_role(g.user_role, "Student")
    app = get_application_or_404(aid)
    dep = None
    if body.get("depends_on_milestone_id") is not None:
        dep = stores["milestones"].get(body["depends_on_milestone_id"])
        if dep is None:
            fail(ERR_NOT_FOUND, 404, "Dependency milestone not found")
    app_ownership(app)
    # Dependency well-formedness (stage 10) precedes clock rules (stage 11)
    # and the application state gate (stage 12).
    if dep is not None:
        if dep["application_id"] != aid or dep["status"] in ("WAIVED", "MISSED"):
            fail(ERR_PREREQUISITE_INCOMPLETE, 409,
                 "depends_on_milestone_id must reference a same-application milestone "
                 "that is not WAIVED or MISSED")
    due_at = parse_datetime(body["due_at"])
    if due_at <= now():
        fail(ERR_DUE_DATE_PAST, 409, "due_at must be in the future")
    if app["submission_status"] not in ("DRAFT", "READY"):
        fail(ERR_INVALID_STATE, 409, "Milestones may only be added while DRAFT or READY")
    rec = _new_milestone(app, body["kind"], due_at,
                         body.get("required", True) if body.get("required") is not None else True,
                         dep["id"] if dep is not None else None)
    return ok_object(ser_milestone(rec), 201)


@bp.get("/ccr/applications/<aid>/milestones")
def milestone_list(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    app = get_application_or_404(aid)
    app_ownership(app)
    items = [m for m in stores["milestones"].values() if m["application_id"] == aid]
    return paginate(items, ser_milestone)


@bp.get("/ccr/milestones/<mid>")
def milestone_get(mid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    m = get_milestone_or_404(mid)
    app = stores["applications"][m["application_id"]]
    app_ownership(app)
    return ok_object(ser_milestone(m), 200)


@bp.get("/ccr/milestones/<mid>/dependents")
def milestone_dependents(mid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    m = get_milestone_or_404(mid)
    app = stores["applications"][m["application_id"]]
    app_ownership(app)
    items = [x for x in stores["milestones"].values() if x["depends_on_milestone_id"] == mid]
    return paginate(items, ser_milestone)


@bp.post("/ccr/milestones/<mid>/transition")
def milestone_transition(mid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": MILESTONE_STATUSES},
    })
    require_role(g.user_role, "Student", "Advisor")
    target = body["to_status"]
    # Per-target roles: completion belongs to the student, waiver to the advisor.
    if target == "COMPLETED":
        require_role(g.user_role, "Student")
    elif target == "WAIVED":
        require_role(g.user_role, "Advisor")
    m = get_milestone_or_404(mid)
    app = stores["applications"][m["application_id"]]
    if g.user_role == "Student":
        app_ownership(app)
    if target == "COMPLETED":
        # The state error outranks the dependency complaint (PRD §3.4).
        if m["status"] != "READY":
            fail(ERR_MILESTONE_NOT_ACTIONABLE, 409,
                 "Milestone completion requires status READY")
        if app["submission_status"] not in ("DRAFT", "READY"):
            fail(ERR_INVALID_STATE, 409,
                 "Owning application must be DRAFT or READY")
        m["status"] = "COMPLETED"
        m["completed_at"] = now()
        bump(m)
        # Dependency bubble-up: PENDING dependents whose dependency is now
        # COMPLETED advance to READY.
        for x in stores["milestones"].values():
            if x["application_id"] == m["application_id"] and x["status"] == "PENDING" \
                    and x["depends_on_milestone_id"] == m["id"]:
                x["status"] = "READY"
                bump(x)
        return ok_object(ser_milestone(m), 200)
    if target == "WAIVED":
        if m["status"] not in ("PENDING", "READY", "MISSED"):
            fail(ERR_INVALID_STATE, 409,
                 f"Cannot waive a milestone in status {m['status']}")
        m["status"] = "WAIVED"
        bump(m)
        return ok_object(ser_milestone(m), 200)
    # PENDING/READY/MISSED are not client-invokable targets.
    fail(ERR_INVALID_STATE, 409, f"No client transition to {target}")
