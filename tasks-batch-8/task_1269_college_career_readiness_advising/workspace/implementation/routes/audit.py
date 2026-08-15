"""Senior audits, outcome records, ops-run deadline sweep (PRD §3.7, §3.8)."""

from datetime import timedelta

from flask import Blueprint, g

from store import stores, mint, bump, touch, now
from util import (
    ok_object, paginate, fail, get_body, validate_schema, require_role,
    parse_datetime, sort_records, d,
    ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NOT_AUDITOR, ERR_NOT_SENIOR,
    ERR_AUDITOR_IS_ASSIGNED_ADVISOR, ERR_OPEN_ENROLLMENTS,
    ERR_CREDITS_SHORTFALL, ERR_PATHWAY_INCOMPLETE,
    ERR_CERTIFICATION_MISSING, ERR_WORK_HOURS_SHORTFALL,
    ERR_OUTCOME_EXISTS, ERR_STUDENT_NOT_GRADUATED, ERR_VALIDATION,
)
from computed import ser_audit, ser_outcome, ser_ops_run, audit_live_values
from routes.students import get_student_or_404, student_ownership

bp = Blueprint("audit", __name__)

AUDIT_STATUSES = ("DRAFT", "IN_REVIEW", "FLAGGED", "CERTIFIED")
OUTCOME_TYPES = ("ENROLLED_4YR", "ENROLLED_2YR", "APPRENTICESHIP", "EMPLOYED",
                 "MILITARY", "OTHER")
OUTCOME_STATUSES = ("UNVERIFIED", "VERIFIED", "DISPUTED")


# ---------------------------------------------------------------------------
# Senior audits
# ---------------------------------------------------------------------------

@bp.post("/ccr/students/<sid>/senior-audits")
def audit_create(sid):
    body = get_body()
    validate_schema(body, {
        "auditor_advisor_id": {"kind": "str", "required": True},
    })
    require_role(g.user_role, "DistrictAdmin")
    student = get_student_or_404(sid)
    auditor = stores["advisors"].get(body["auditor_advisor_id"])
    if auditor is None:
        fail(ERR_NOT_FOUND, 404, "Auditor advisor not found")
    # Seniority (stage 10): audit opens only for grade_level 12.
    if student["grade_level"] != 12:
        fail(ERR_NOT_SENIOR, 409, "Senior audit requires grade_level 12")
    rec = mint("audits")
    rec.update({
        "student_id": sid,
        "auditor_advisor_id": auditor["id"],
        "status": "DRAFT",
        "flag_reason": None,
        "required_credits": 24,
        "certified_at": None,
        "frozen": None,
    })
    stores["audits"][rec["id"]] = rec
    return ok_object(ser_audit(rec), 201)


@bp.get("/ccr/students/<sid>/senior-audits")
def audit_list_for_student(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    get_student_or_404(sid)
    student_ownership(sid)
    items = [a for a in stores["audits"].values() if a["student_id"] == sid]
    return paginate(items, ser_audit)


def get_audit_or_404(aid):
    a = stores["audits"].get(aid)
    if a is None:
        fail(ERR_NOT_FOUND, 404, "Senior audit not found")
    return a


@bp.get("/ccr/senior-audits/<aid>")
def audit_get(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    audit = get_audit_or_404(aid)
    if g.user_role == "Student":
        student_ownership(audit["student_id"])
    return ok_object(ser_audit(audit), 200)


_AUDIT_TRANSITIONS = {
    "IN_REVIEW": ("DRAFT", "FLAGGED"),
    "FLAGGED": ("IN_REVIEW",),
    "CERTIFIED": ("IN_REVIEW",),
    "DRAFT": (),
}


@bp.post("/ccr/senior-audits/<aid>/transition")
def audit_transition(aid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": AUDIT_STATUSES},
        "flag_reason": {"kind": "str", "required": False},
    })
    # Stage 2 schema: FLAGGED requires a non-empty flag_reason.
    if body["to_status"] == "FLAGGED":
        fr = body.get("flag_reason")
        if not isinstance(fr, str) or fr == "":
            fail(ERR_VALIDATION, 400, "flag_reason must be non-empty")
    require_role(g.user_role, "Advisor")
    audit = get_audit_or_404(aid)
    # Ownership (stage 7): only the named auditor may drive the audit.
    if g.user_id != audit["auditor_advisor_id"]:
        fail(ERR_NOT_AUDITOR, 403, "Only the named auditor may transition this audit")
    target = body["to_status"]
    if audit["status"] not in _AUDIT_TRANSITIONS[target]:
        fail(ERR_INVALID_STATE, 409,
             f"Cannot move audit from {audit['status']} to {target}")
    if target == "IN_REVIEW":
        if audit["status"] == "FLAGGED":
            audit["flag_reason"] = None
        audit["status"] = "IN_REVIEW"
        audit["frozen"] = None
        bump(audit)
        return ok_object(ser_audit(audit), 200)
    if target == "FLAGGED":
        audit["status"] = "FLAGGED"
        audit["flag_reason"] = body["flag_reason"]
        bump(audit)
        return ok_object(ser_audit(audit), 200)
    # CERTIFIED: SoD (stage 9) then graduation gates in pinned order (PRD §3.7).
    student = stores["students"][audit["student_id"]]
    if audit["auditor_advisor_id"] == student["assigned_advisor_id"]:
        fail(ERR_AUDITOR_IS_ASSIGNED_ADVISOR, 409,
             "Certifying auditor must differ from the student's assigned advisor")
    vals = audit_live_values(audit)
    open_enrollments = [e for e in stores["enrollments"].values()
                        if e["student_id"] == audit["student_id"]
                        and e["status"] in ("PLANNED", "ENROLLED")]
    if open_enrollments:
        fail(ERR_OPEN_ENROLLMENTS, 409, "Open PLANNED/ENROLLED enrollments remain")
    # credits_earned >= required_credits; equality passes (comparison exact).
    if d(vals["credits_earned"]) < d(audit["required_credits"]):
        fail(ERR_CREDITS_SHORTFALL, 409, "credits_earned below required_credits")
    if not vals["pathway_requirements_met"]:
        fail(ERR_PATHWAY_INCOMPLETE, 409, "Pathway course requirements not met")
    if not vals["certification_requirement_met"]:
        fail(ERR_CERTIFICATION_MISSING, 409, "Required certification not PASSED")
    if not vals["work_hours_met"]:
        fail(ERR_WORK_HOURS_SHORTFALL, 409, "WBL hours below pathway requirement")
    audit["status"] = "CERTIFIED"
    audit["certified_at"] = now()
    audit["frozen"] = vals  # computed fields freeze while CERTIFIED
    bump(audit)
    return ok_object(ser_audit(audit), 200)


# ---------------------------------------------------------------------------
# Outcome records
# ---------------------------------------------------------------------------

@bp.post("/ccr/students/<sid>/outcome-records")
def outcome_create(sid):
    body = get_body()
    validate_schema(body, {
        "outcome_type": {"kind": "str", "required": True, "choices": OUTCOME_TYPES},
        "reported_at": {"kind": "datetime", "required": True},
        "institution_name": {"kind": "str", "required": False},
    })
    require_role(g.user_role, "DistrictAdmin")
    student = get_student_or_404(sid)
    # One record per student (stage 10) precedes the GRADUATED gate (stage 12).
    if any(o["student_id"] == sid for o in stores["outcomes"].values()):
        fail(ERR_OUTCOME_EXISTS, 409, "An outcome record already exists for this student")
    if student["status"] != "GRADUATED":
        fail(ERR_STUDENT_NOT_GRADUATED, 409, "Student is not GRADUATED")
    rec = mint("outcomes")
    rec.update({
        "student_id": sid,
        "outcome_type": body["outcome_type"],
        "institution_name": body.get("institution_name"),
        "reported_at": parse_datetime(body["reported_at"]),
        "verification_status": "UNVERIFIED",
        "verified_at": None,
    })
    stores["outcomes"][rec["id"]] = rec
    return ok_object(ser_outcome(rec), 201)


@bp.get("/ccr/students/<sid>/outcome-records")
def outcome_list(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    get_student_or_404(sid)
    items = [o for o in stores["outcomes"].values() if o["student_id"] == sid]
    return paginate(items, ser_outcome)


@bp.get("/ccr/outcome-records/<oid>")
def outcome_get(oid):
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    o = stores["outcomes"].get(oid)
    if o is None:
        fail(ERR_NOT_FOUND, 404, "Outcome record not found")
    return ok_object(ser_outcome(o), 200)


_OUTCOME_TRANSITIONS = {
    "VERIFIED": ("UNVERIFIED", "DISPUTED"),
    "DISPUTED": ("UNVERIFIED",),
    "UNVERIFIED": (),
}


@bp.post("/ccr/outcome-records/<oid>/transition")
def outcome_transition(oid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": OUTCOME_STATUSES},
    })
    require_role(g.user_role, "DistrictAdmin")
    o = stores["outcomes"].get(oid)
    if o is None:
        fail(ERR_NOT_FOUND, 404, "Outcome record not found")
    target = body["to_status"]
    if o["verification_status"] not in _OUTCOME_TRANSITIONS[target]:
        fail(ERR_INVALID_STATE, 409,
             f"Cannot move outcome from {o['verification_status']} to {target}")
    o["verification_status"] = target
    if target == "VERIFIED":
        o["verified_at"] = now()
    bump(o)
    return ok_object(ser_outcome(o), 200)


# ---------------------------------------------------------------------------
# Ops runs (deadline sweep, PRD §3.8)
# ---------------------------------------------------------------------------

@bp.post("/ccr/ops-runs")
def ops_run_create():
    body = get_body()
    validate_schema(body, {})
    require_role(g.user_role, "DistrictAdmin")
    executed_at = now()
    run_index = len(stores["ops_runs"]) + 1

    # 1) Overdue sweep: PENDING/READY milestones with due_at strictly before
    #    executed_at -> MISSED, processed due_at ASC then created_at ASC.
    overdue = [m for m in stores["milestones"].values()
               if m["status"] in ("PENDING", "READY") and m["due_at"] < executed_at]
    overdue.sort(key=lambda m: (m["due_at"], m["created_at"], m["_seq"]))
    marked = 0
    regressed = 0
    for m in overdue:
        m["status"] = "MISSED"
        bump(m)
        marked += 1
        # Regression: a newly MISSED required milestone drops a READY
        # application back to DRAFT (counted once per application).
        if m["required"]:
            app = stores["applications"][m["application_id"]]
            if app["submission_status"] == "READY":
                app["submission_status"] = "DRAFT"
                bump(app)
                regressed += 1

    # 2) Reminders: due_at in [now, now+7d) and last_reminder_sent_at unset or
    #    strictly more than 24h in the past. Stamping refreshes
    #    last_reminder_sent_at and updated_at without a version bump (not a
    #    state transition or PATCH write, PRD §2.4).
    window_end = executed_at + timedelta(days=7)
    reminder_cutoff = executed_at - timedelta(hours=24)
    queued = 0
    for m in stores["milestones"].values():
        if not (executed_at <= m["due_at"] < window_end):
            continue
        last = m["last_reminder_sent_at"]
        if last is None or last < reminder_cutoff:
            m["last_reminder_sent_at"] = executed_at
            touch(m)
            queued += 1

    # 3) Every ACTIVE/REVISING plan recomputes (derived fields are computed
    #    live at read time; recomputation never bumps a version, PRD §2.4).
    plans_recomputed = sum(1 for p in stores["plans"].values()
                           if p["status"] in ("ACTIVE", "REVISING"))

    rec = mint("ops_runs")
    rec.update({
        "run_index": run_index,
        "executed_at": executed_at,
        "milestones_marked_missed": marked,
        "applications_regressed": regressed,
        "reminders_queued": queued,
        "plans_recomputed": plans_recomputed,
    })
    stores["ops_runs"][rec["id"]] = rec
    return ok_object(ser_ops_run(rec), 201)


@bp.get("/ccr/ops-runs/<rid>")
def ops_run_get(rid):
    require_role(g.user_role, "DistrictAdmin")
    r = stores["ops_runs"].get(rid)
    if r is None:
        fail(ERR_NOT_FOUND, 404, "Ops run not found")
    return ok_object(ser_ops_run(r), 200)
