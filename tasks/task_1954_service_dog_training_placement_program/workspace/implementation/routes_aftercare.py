"""Routes: partnerships, follow-ups, recertifications, support requests."""
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, request

from core import (
    STORE,
    ApiError,
    base_fields,
    body,
    check_terminal,
    err_invalid_state,
    err_ownership,
    err_ref_not_found,
    get_or_404,
    list_all,
    now,
    paginate,
    require_roles,
    respond,
    today,
    touch,
    v_date,
    v_enum,
    v_int,
    v_str,
)
from services import ser_followup, ser_partnership, ser_recert, ser_support

bp = Blueprint("aftercare", __name__)

SUPPORT_CATEGORIES = {"EQUIPMENT", "BEHAVIOR", "HEALTH", "TRAVEL", "HOUSING", "OTHER"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}
FOLLOWUP_OUTCOMES = {"SATISFACTORY", "NEEDS_SUPPORT"}


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _load_partnership_scoped(rid, role, uid):
    p = get_or_404("partnerships", rid)
    if role == "Applicant" and p["applicant_id"] != uid:
        raise err_ownership("Applicant may only access its own partnerships")
    return p


# ---------------------------------------------------------------------------
# Partnerships
# ---------------------------------------------------------------------------
@bp.route("/api/partnerships/<rid>", methods=["GET"])
def get_partnership(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "IntakeCoordinator", "Applicant"
    )
    p = _load_partnership_scoped(rid, role, uid)
    return respond(ser_partnership(p))


@bp.route("/api/partnerships", methods=["GET"])
def list_partnerships():
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "IntakeCoordinator")
    items = list(STORE["partnerships"].values())
    status = _q("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, ser_partnership)


@bp.route("/api/partnerships/<rid>/suspend", methods=["POST"])
def suspend_partnership(rid):
    b = body()
    reason = v_str(b, "reason")
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("partnerships", rid)
    check_terminal("partnerships", p)
    if p["status"] not in ("ACTIVE", "RECERT_DUE"):
        raise err_invalid_state("Partnership is not ACTIVE or RECERT_DUE")
    p["status"] = "SUSPENDED"
    touch(p)
    return respond(ser_partnership(p))


@bp.route("/api/partnerships/<rid>/reinstate", methods=["POST"])
def reinstate_partnership(rid):
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("partnerships", rid)
    check_terminal("partnerships", p)
    if p["status"] != "SUSPENDED":
        raise err_invalid_state("Partnership is not SUSPENDED")
    # recert schedule re-evaluation
    if now() > p["recert_due_at"]:
        p["status"] = "RECERT_DUE"
    else:
        p["status"] = "ACTIVE"
    touch(p)
    return respond(ser_partnership(p))


def _retire_or_dissolve(p, target):
    for f in STORE["followups"].values():
        if f["partnership_id"] == p["id"] and f["status"] == "SCHEDULED":
            f["status"] = "WAIVED"
            touch(f)
    d = STORE["dogs"].get(p["dog_id"])
    if d is not None and d["status"] == "PLACED":
        d["status"] = "RETIRED" if target == "RETIRED" else "MATCH_READY"
        touch(d)
    p["status"] = target
    touch(p)


@bp.route("/api/partnerships/<rid>/retire", methods=["POST"])
def retire_partnership(rid):
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("partnerships", rid)
    check_terminal("partnerships", p)
    if p["status"] not in ("ACTIVE", "RECERT_DUE", "SUSPENDED"):
        raise err_invalid_state("Partnership cannot be retired from %s" % p["status"])
    _retire_or_dissolve(p, "RETIRED")
    return respond(ser_partnership(p))


@bp.route("/api/partnerships/<rid>/dissolve", methods=["POST"])
def dissolve_partnership(rid):
    b = body()
    reason = v_str(b, "reason")
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("partnerships", rid)
    check_terminal("partnerships", p)
    if p["status"] not in ("ACTIVE", "RECERT_DUE", "SUSPENDED"):
        raise err_invalid_state(
            "Partnership cannot be dissolved from %s" % p["status"]
        )
    _retire_or_dissolve(p, "DISSOLVED")
    return respond(ser_partnership(p))


@bp.route("/api/partnerships/<rid>/follow-ups", methods=["GET"])
def partnership_followups(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Applicant")
    p = _load_partnership_scoped(rid, role, uid)
    items = [
        f for f in STORE["followups"].values() if f["partnership_id"] == p["id"]
    ]
    return list_all(items, ser_followup)


@bp.route("/api/partnerships/<rid>/recertifications", methods=["GET"])
def partnership_recerts(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "Applicant", "Evaluator"
    )
    p = _load_partnership_scoped(rid, role, uid)
    items = [
        r for r in STORE["recerts"].values() if r["partnership_id"] == p["id"]
    ]
    return list_all(items, ser_recert)


@bp.route("/api/partnerships/<rid>/support-requests", methods=["GET"])
def partnership_support_requests(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "Applicant", "Trainer"
    )
    p = _load_partnership_scoped(rid, role, uid)
    items = [
        s for s in STORE["support_requests"].values() if s["partnership_id"] == p["id"]
    ]
    return list_all(items, ser_support)


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------
@bp.route("/api/partnerships/<rid>/follow-ups", methods=["POST"])
def create_followup(rid):
    b = body()
    due_on = v_date(b, "due_on")
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("partnerships", rid)
    check_terminal("partnerships", p)
    for f in STORE["followups"].values():
        if f["partnership_id"] != p["id"]:
            continue
        if f["status"] == "WAIVED":
            continue
        if abs((due_on - f["due_on"]).days) < 7:
            raise ApiError(
                "ERR_FOLLOWUP_TOO_SOON",
                409,
                "due_on must be at least 7 days from every other non-WAIVED follow-up",
            )
    f = base_fields()
    f.update(
        {
            "partnership_id": p["id"],
            "due_on": due_on,
            "auto_generated": False,
            "status": "SCHEDULED",
            "outcome": None,
            "completed_on": None,
        }
    )
    STORE["followups"][f["id"]] = f
    return respond(ser_followup(f), 201)


@bp.route("/api/follow-ups/<rid>", methods=["GET"])
def get_followup(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector")
    f = get_or_404("followups", rid)
    return respond(ser_followup(f))


@bp.route("/api/follow-ups/<rid>/complete", methods=["POST"])
def complete_followup(rid):
    b = body()
    outcome = v_enum(b, "outcome", FOLLOWUP_OUTCOMES)
    notes = v_str(b, "notes", required=False)
    role, uid = require_roles("TrainingDirector")
    f = get_or_404("followups", rid)
    check_terminal("followups", f)
    if f["status"] != "SCHEDULED":
        raise err_invalid_state("Follow-up is not SCHEDULED")
    p = get_or_404("partnerships", f["partnership_id"])
    if p["status"] not in ("ACTIVE", "RECERT_DUE"):
        raise err_invalid_state(
            "Partnership must be ACTIVE or RECERT_DUE to complete a follow-up"
        )
    f["status"] = "COMPLETED"
    f["outcome"] = outcome
    f["completed_on"] = today()
    touch(f)
    p["followups_completed"] += 1
    touch(p)
    return respond(ser_followup(f))


@bp.route("/api/follow-ups/<rid>/waive", methods=["POST"])
def waive_followup(rid):
    role, uid = require_roles("TrainingDirector")
    f = get_or_404("followups", rid)
    check_terminal("followups", f)
    if f["status"] != "SCHEDULED":
        raise err_invalid_state("Follow-up is not SCHEDULED")
    f["status"] = "WAIVED"
    touch(f)
    return respond(ser_followup(f))


# ---------------------------------------------------------------------------
# Recertifications
# ---------------------------------------------------------------------------
@bp.route("/api/partnerships/<rid>/recertifications", methods=["POST"])
def create_recert(rid):
    b = body()
    scheduled_on = v_date(b, "scheduled_on")
    evaluator_id = v_str(b, "evaluator_id")
    expected_version = v_int(b, "expected_partnership_version")
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("partnerships", rid)
    evaluator = STORE["trainers"].get(evaluator_id)
    if evaluator is None:
        raise err_ref_not_found("evaluator_id does not resolve")
    if expected_version != p["version"]:
        raise ApiError(
            "ERR_STALE_PARTNERSHIP_VERSION",
            412,
            "expected_partnership_version does not match",
        )
    check_terminal("partnerships", p)
    # window: [recert_due_at - 30d, recert_due_at + 30d] inclusive (date basis)
    due_date = p["recert_due_at"].date()
    if scheduled_on < due_date - timedelta(days=30) or scheduled_on > due_date + timedelta(days=30):
        raise ApiError(
            "ERR_RECERT_WINDOW",
            409,
            "scheduled_on outside [recert_due_at - 30d, recert_due_at + 30d]",
        )
    if not evaluator["pat_certified"] or evaluator["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_EVALUATOR_NOT_CERTIFIED",
            409,
            "Evaluator must be a pat_certified CERTIFIED trainer",
        )
    d = STORE["dogs"].get(p["dog_id"])
    if d is not None and d["primary_trainer_id"] == evaluator_id:
        raise ApiError(
            "ERR_EVALUATOR_CONFLICT",
            409,
            "Evaluator must differ from the dog's primary trainer",
        )
    r = base_fields()
    r.update(
        {
            "partnership_id": p["id"],
            "scheduled_on": scheduled_on,
            "evaluator_id": evaluator_id,
            "status": "SCHEDULED",
            "completed_on": None,
        }
    )
    STORE["recerts"][r["id"]] = r
    touch(p)
    return respond(ser_recert(r), 201)


@bp.route("/api/recertifications/<rid>", methods=["GET"])
def get_recert(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Evaluator")
    r = get_or_404("recerts", rid)
    return respond(ser_recert(r))


@bp.route("/api/recertifications/<rid>/record-result", methods=["POST"])
def record_recert_result(rid):
    b = body()
    outcome = v_enum(b, "outcome", {"PASS", "FAIL"})
    role, uid = require_roles("Evaluator")
    r = get_or_404("recerts", rid)
    if r["evaluator_id"] != uid:
        raise err_ownership("Evaluator may only record its own results")
    check_terminal("recerts", r)
    if r["status"] == "SCHEDULED":
        if outcome == "PASS":
            r["status"] = "COMPLETED_PASS"
        else:
            r["status"] = "REMEDIATION"
    elif r["status"] == "REMEDIATION":
        if outcome == "PASS":
            r["status"] = "COMPLETED_PASS"
        else:
            r["status"] = "FAILED_FINAL"
    else:
        raise err_invalid_state("Recertification is not SCHEDULED or REMEDIATION")
    r["completed_on"] = today()
    touch(r)
    p = get_or_404("partnerships", r["partnership_id"])
    if r["status"] == "COMPLETED_PASS":
        completed_dt = datetime.combine(
            r["completed_on"], time(0, 0, 0), tzinfo=timezone.utc
        )
        p["recert_due_at"] = completed_dt + timedelta(days=365)
        p["last_recert_passed_at"] = now()
        if p["status"] == "RECERT_DUE":
            p["status"] = "ACTIVE"
        touch(p)
    elif r["status"] == "FAILED_FINAL":
        if p["status"] in ("ACTIVE", "RECERT_DUE"):
            p["status"] = "SUSPENDED"
            touch(p)
    return respond(ser_recert(r))


# ---------------------------------------------------------------------------
# Support requests
# ---------------------------------------------------------------------------
@bp.route("/api/partnerships/<rid>/support-requests", methods=["POST"])
def create_support_request(rid):
    b = body()
    category = v_enum(b, "category", SUPPORT_CATEGORIES)
    description = v_str(b, "description")
    severity = v_enum(b, "severity", SEVERITIES, required=False) or "MEDIUM"
    role, uid = require_roles("Applicant", "TrainingDirector")
    p = get_or_404("partnerships", rid)
    if role == "Applicant" and p["applicant_id"] != uid:
        raise err_ownership("Applicant may only raise requests on its own partnership")
    check_terminal("partnerships", p)
    s = base_fields()
    s.update(
        {
            "partnership_id": p["id"],
            "raised_by_applicant_id": p["applicant_id"],
            "category": category,
            "description": description,
            "severity": severity,
            "priority": None,
            "status": "OPEN",
            "assigned_trainer_id": None,
            "resolved_at": None,
        }
    )
    STORE["support_requests"][s["id"]] = s
    return respond(ser_support(s), 201)


@bp.route("/api/support-requests", methods=["GET"])
def list_support_requests():
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Applicant")
    items = list(STORE["support_requests"].values())
    if role == "Applicant":
        items = [s for s in items if s["raised_by_applicant_id"] == uid]
    status = _q("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    category = _q("category")
    if category is not None:
        items = [s for s in items if s["category"] == category]
    raised_by = _q("raised_by_applicant_id")
    if raised_by is not None:
        items = [s for s in items if s["raised_by_applicant_id"] == raised_by]
    return paginate(items, ser_support)


@bp.route("/api/support-requests/<rid>", methods=["GET"])
def get_support_request(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Trainer", "Applicant")
    s = get_or_404("support_requests", rid)
    if role == "Applicant" and s["raised_by_applicant_id"] != uid:
        raise err_ownership("Applicant may only view its own support requests")
    return respond(ser_support(s))


@bp.route("/api/support-requests/<rid>/triage", methods=["POST"])
def triage_support_request(rid):
    b = body()
    priority = v_enum(b, "priority", SEVERITIES)
    role, uid = require_roles("TrainingDirector")
    s = get_or_404("support_requests", rid)
    check_terminal("support_requests", s)
    if s["status"] != "OPEN":
        raise err_invalid_state("Support request is not OPEN")
    s["status"] = "TRIAGED"
    s["priority"] = priority
    touch(s)
    return respond(ser_support(s))


@bp.route("/api/support-requests/<rid>/start", methods=["POST"])
def start_support_request(rid):
    b = body()
    trainer_id = v_str(b, "assigned_trainer_id")
    role, uid = require_roles("TrainingDirector")
    s = get_or_404("support_requests", rid)
    trainer = STORE["trainers"].get(trainer_id)
    if trainer is None:
        raise err_ref_not_found("assigned_trainer_id does not resolve")
    check_terminal("support_requests", s)
    if s["status"] not in ("TRIAGED", "REOPENED"):
        raise err_invalid_state("Support request is not TRIAGED or REOPENED")
    if trainer["status"] != "CERTIFIED":
        raise err_invalid_state("assigned_trainer_id must reference a CERTIFIED trainer")
    s["status"] = "IN_PROGRESS"
    s["assigned_trainer_id"] = trainer_id
    touch(s)
    return respond(ser_support(s))


@bp.route("/api/support-requests/<rid>/resolve", methods=["POST"])
def resolve_support_request(rid):
    b = body()
    note = v_str(b, "resolution_note")
    role, uid = require_roles("Trainer", "TrainingDirector")
    s = get_or_404("support_requests", rid)
    if role == "Trainer" and s["assigned_trainer_id"] != uid:
        raise err_ownership("Trainer may only resolve requests assigned to them")
    check_terminal("support_requests", s)
    if s["status"] != "IN_PROGRESS":
        raise err_invalid_state("Support request is not IN_PROGRESS")
    s["status"] = "RESOLVED"
    s["resolved_at"] = now()
    touch(s)
    return respond(ser_support(s))


@bp.route("/api/support-requests/<rid>/reopen", methods=["POST"])
def reopen_support_request(rid):
    role, uid = require_roles("Applicant")
    s = get_or_404("support_requests", rid)
    p = STORE["partnerships"].get(s["partnership_id"])
    if p is None or p["applicant_id"] != uid:
        raise err_ownership("Applicant may only reopen its own support requests")
    check_terminal("support_requests", s)
    if s["status"] != "RESOLVED":
        raise err_invalid_state("Support request is not RESOLVED")
    if now() > s["resolved_at"] + timedelta(days=14):
        raise ApiError(
            "ERR_REOPEN_WINDOW_EXPIRED",
            409,
            "Reopen window (14 days from resolution) has expired",
        )
    s["status"] = "REOPENED"
    s["resolved_at"] = None
    touch(s)
    return respond(ser_support(s))


@bp.route("/api/support-requests/<rid>/close", methods=["POST"])
def close_support_request(rid):
    role, uid = require_roles("TrainingDirector")
    s = get_or_404("support_requests", rid)
    check_terminal("support_requests", s)
    if s["status"] != "RESOLVED":
        raise err_invalid_state("Support request is not RESOLVED")
    s["status"] = "CLOSED"
    touch(s)
    return respond(ser_support(s))
