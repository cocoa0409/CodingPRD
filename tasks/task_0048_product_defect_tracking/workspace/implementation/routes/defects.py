"""Defect endpoints — report, assign, reassign, start-progress, submit-fix,
verify, close, pause-sla, resume-sla."""

from __future__ import annotations

import re

from flask import Blueprint, g, request

import db
from config import (
    ACTIVE, ARCHIVED, TM_STATUS_ACTIVE,
    DEFECT_NEW, DEFECT_ASSIGNED, DEFECT_IN_PROGRESS, DEFECT_FIXED,
    DEFECT_VERIFIED, DEFECT_REOPENED, DEFECT_CLOSED,
    DEFECT_NON_TERMINAL,
    SLA_PAUSED, SLA_RUNNING,
    SEVERITIES, SOURCES, BUSINESS_IMPACTS, PAUSE_REASONS, BIMPACT_UNKNOWN,
    OUTCOME_PASSED, OUTCOME_FAILED,
    TM_ROLE_DEVELOPER, TM_ROLE_QA_ENGINEER,
    ROLE_TRIAGE_MANAGER, ROLE_DEVELOPER, ROLE_QA_ENGINEER, ROLE_ANY,
    RR_QUEUED, RR_RUNNING, RR_FAILED,
)
from errors import (
    AppError,
    ERR_DEFECT_ALREADY_LINKED, ERR_DEFECT_NOT_ASSIGNED, ERR_DEFECT_NOT_FIXED,
    ERR_DEFECT_NOT_IN_PROGRESS, ERR_DEFECT_NOT_VERIFIED,
    ERR_FIX_RECORD_STALE,
    ERR_INVALID_ENVIRONMENT, ERR_INVALID_REQUEST, ERR_INVALID_SLA_STATE_TRANSITION,
    ERR_MODULE_ARCHIVED, ERR_MODULE_OR_REPORTER_INVALID, ERR_MODULE_QUOTA_EXCEEDED,
    ERR_NO_ELIGIBLE_ASSIGNEE, ERR_REASSIGN_NOT_ASSIGNED, ERR_REASSIGN_SAME_ASSIGNEE,
    ERR_REGRESSION_NOT_PASSED, ERR_SLA_PAUSE_ADJACENT, ERR_SLA_PAUSE_INVALID_STATUS,
    ERR_TEAM_MEMBER_NOT_ELIGIBLE, ERR_VERIFIER_NOT_INDEPENDENT,
)
from middleware import require_role
from response import parse_pagination, success, success_list
from services.audit import append_audit
from services.defect_logic import recompute_score_and_due, reopen_cascade
from services.serializers import defect_dto, sla_pause_dto
from services.validators import (
    check_version, find_defect_or_404, find_fix_record_or_404, find_module_or_404,
    find_project_or_404, find_team_member_or_404, ensure_project_active,
    get_json, require_enum, require_int, require_str,
)

bp = Blueprint("defects", __name__)

COMMIT_SHA_RE = re.compile(r"^[a-fA-F0-9]{7,64}$")


def _ensure_module_active_for_mutate(module: dict):
    if module.get("status") != ACTIVE:
        raise AppError(ERR_MODULE_ARCHIVED, "Module is archived.", 409)


# ---------------------------------------------------------------------------
# Report a defect
# ---------------------------------------------------------------------------
@bp.post("/defects")
def create_defect():
    require_role(ROLE_DEVELOPER, ROLE_QA_ENGINEER, ROLE_TRIAGE_MANAGER)
    body = get_json()
    project_id = require_str(body, "project_id")
    module_id = require_str(body, "module_id")
    reporter_id = require_str(body, "reporter_id")
    title = require_str(body, "title")
    defect_source = require_enum(body, "defect_source", SOURCES)
    severity = require_enum(body, "severity", SEVERITIES)
    business_impact = body.get("business_impact", BIMPACT_UNKNOWN)
    if business_impact not in BUSINESS_IMPACTS:
        raise AppError(ERR_INVALID_REQUEST,
                       f"business_impact must be one of {sorted(BUSINESS_IMPACTS)}", 400)
    reproduction_steps = require_str(body, "reproduction_steps", non_empty=False)
    environment = body.get("environment")
    if not isinstance(environment, dict):
        raise AppError(ERR_INVALID_ENVIRONMENT, "environment must be object with 4 keys", 400)

    # Existence checks: project
    project = find_project_or_404(project_id)

    # Parent-project archival
    ensure_project_active(project)

    # PRD §3.2: "if either reference is dangling, points at an INACTIVE
    # row, or crosses a project boundary, the report is rejected with
    # ERR_MODULE_OR_REPORTER_INVALID". Dangling (= not-found) is the same
    # error as inactive/cross-project; do NOT raise the generic 404 here.
    module = db.find_by_id("modules", module_id)
    reporter = db.find_by_id("team_members", reporter_id)
    if (module is None or reporter is None
            or module["project_id"] != project_id
            or module.get("status") != ACTIVE
            or reporter["project_id"] != project_id
            or reporter.get("status") != TM_STATUS_ACTIVE):
        raise AppError(ERR_MODULE_OR_REPORTER_INVALID,
                       "module_id or reporter_id invalid or inactive or wrong project", 400)

    # Environment payload completeness
    required_env = ("os", "browser", "app_version", "build_id")
    for key in required_env:
        v = environment.get(key)
        if not v or not isinstance(v, str) or v == "":
            raise AppError(ERR_INVALID_ENVIRONMENT,
                           f"environment.{key} missing or empty", 400)

    # Module quota check
    if module.get("quota_remaining", 0) <= 0:
        raise AppError(ERR_MODULE_QUOTA_EXCEEDED,
                       "Module quota exhausted.", 409)

    clock = project["clock_minute"]
    defect = {
        "project_id": project_id,
        "module_id": module_id,
        "reporter_id": reporter_id,
        "assignee_id": None,
        "title": title,
        "defect_source": defect_source,
        "severity": severity,
        "effective_severity": severity,
        "business_impact": business_impact,
        "reproduction_steps": reproduction_steps,
        "environment": dict(environment),
        "priority_score": 0,
        "status": DEFECT_NEW,
        "sla_state": SLA_RUNNING,
        "reopen_count": 0,
        "total_paused_minutes": 0,
        "report_clock_minute": clock,
        "first_fixed_at_minute": None,
        "response_due_minute": 0,
        "resolution_due_minute": 0,
        "escalation_level": 0,
        "canonical_defect_id": None,
        "fix_version": None,
        "final_resolution_minutes": None,
    }
    # Compute priority/sla
    recompute_score_and_due(defect, project_clock=clock)
    defect = db.insert("defects", defect)

    # Update module counts (bump version + updated_at on module)
    db.update("modules", module_id, {
        "active_defect_count": module["active_defect_count"] + 1,
        "quota_remaining": module["quota_remaining"] - 1,
    }, bump=True)

    append_audit(
        defect_id=defect["id"],
        event_type="STATUS_CHANGE",
        actor_id=g.user_id,
        from_value=None,
        to_value=DEFECT_NEW,
        at_minute=clock,
    )
    return success(defect_dto(defect), 201)


@bp.get("/defects")
def list_defects():
    require_role(ROLE_ANY)
    limit, offset = parse_pagination(request.args)
    filters = {}
    for k in ("project_id", "module_id", "assignee_id", "status", "severity"):
        v = request.args.get(k)
        if v is not None and v != "":
            filters[k] = v
    rows, total = db.query("defects", filters=filters, limit=limit, offset=offset)
    return success_list([defect_dto(r) for r in rows], total, limit, offset)


@bp.get("/defects/<defect_id>")
def get_defect(defect_id):
    require_role(ROLE_ANY)
    d = find_defect_or_404(defect_id)
    return success(defect_dto(d))


# ---------------------------------------------------------------------------
# Assign / Reassign
# ---------------------------------------------------------------------------
def _eligible_for_assign(tm, project_id):
    return (tm["project_id"] == project_id
            and tm.get("status") == TM_STATUS_ACTIVE)


def _auto_select_assignee(defect, project_id):
    module = db.find_by_id("modules", defect["module_id"])
    candidates = [m for m in db.all_rows("team_members")
                  if m["project_id"] == project_id
                  and m.get("status") == TM_STATUS_ACTIVE
                  and m.get("role") in (TM_ROLE_DEVELOPER, TM_ROLE_QA_ENGINEER)]
    if not candidates:
        raise AppError(ERR_NO_ELIGIBLE_ASSIGNEE,
                       "No active DEVELOPER/QA_ENGINEER in project", 409)
    owner_id = module.get("owner_team_member_id") if module else None
    candidates.sort(key=lambda m: (
        m.get("active_workload", 0),
        0 if m["id"] == owner_id else 1,
        m["created_at"],
        m.get("_seq", 0),
    ))
    return candidates[0]["id"]


@bp.post("/defects/<defect_id>/assign")
def assign_defect(defect_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)
    module = find_module_or_404(d["module_id"])

    # State precondition: NEW or REOPENED → ASSIGNED
    if d["status"] not in (DEFECT_NEW, DEFECT_REOPENED):
        raise AppError(
            "ERR_DEFECT_NOT_NEW" if d["status"] != DEFECT_REOPENED else "ERR_DEFECT_NOT_NEW",
            f"Defect must be NEW or REOPENED to assign; was {d['status']}",
            409,
        )

    # Module must be ACTIVE
    if module.get("status") != ACTIVE:
        raise AppError(ERR_MODULE_ARCHIVED, "Module is archived.", 409)

    requested_id = body.get("assignee_id")
    if requested_id is not None:
        if not isinstance(requested_id, str) or not requested_id:
            raise AppError(ERR_INVALID_REQUEST, "assignee_id must be non-empty string", 400)
        target = db.find_by_id("team_members", requested_id)
        if not target or not _eligible_for_assign(target, d["project_id"]):
            raise AppError(ERR_TEAM_MEMBER_NOT_ELIGIBLE,
                           "Assignee not active or in different project", 400)
        new_assignee_id = requested_id
    else:
        new_assignee_id = _auto_select_assignee(d, d["project_id"])

    check_version(body, d)

    prior_assignee = d.get("assignee_id")
    d["assignee_id"] = new_assignee_id
    d["status"] = DEFECT_ASSIGNED
    db.update("defects", defect_id, d, bump=True)

    # Adjust workload counters
    if prior_assignee and prior_assignee != new_assignee_id:
        prior = db.find_by_id("team_members", prior_assignee)
        if prior:
            db.update("team_members", prior_assignee,
                      {"active_workload": max(0, prior.get("active_workload", 0) - 1)},
                      bump=True)
    if not prior_assignee or prior_assignee != new_assignee_id:
        new_tm = db.find_by_id("team_members", new_assignee_id)
        if new_tm:
            db.update("team_members", new_assignee_id,
                      {"active_workload": new_tm.get("active_workload", 0) + 1},
                      bump=True)

    append_audit(
        defect_id=defect_id,
        event_type="ASSIGNMENT_CHANGE",
        actor_id=g.user_id,
        from_value=prior_assignee,
        to_value=new_assignee_id,
        at_minute=project["clock_minute"],
    )
    updated = db.find_by_id("defects", defect_id)
    return success(defect_dto(updated))


@bp.post("/defects/<defect_id>/reassign")
def reassign_defect(defect_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if d["status"] != DEFECT_ASSIGNED:
        raise AppError(ERR_REASSIGN_NOT_ASSIGNED,
                       f"Defect must be ASSIGNED to reassign; was {d['status']}", 409)

    new_assignee_id = require_str(body, "new_assignee_id")
    if new_assignee_id == d.get("assignee_id"):
        raise AppError(ERR_REASSIGN_SAME_ASSIGNEE,
                       "new_assignee_id equals current assignee", 400)

    target = db.find_by_id("team_members", new_assignee_id)
    if not target or not _eligible_for_assign(target, d["project_id"]):
        raise AppError(ERR_TEAM_MEMBER_NOT_ELIGIBLE,
                       "Assignee not active or in different project", 400)
    check_version(body, d)

    prior_assignee = d["assignee_id"]
    d["assignee_id"] = new_assignee_id
    db.update("defects", defect_id, d, bump=True)
    prior = db.find_by_id("team_members", prior_assignee)
    if prior:
        db.update("team_members", prior_assignee,
                  {"active_workload": max(0, prior.get("active_workload", 0) - 1)},
                  bump=True)
    new_tm = db.find_by_id("team_members", new_assignee_id)
    db.update("team_members", new_assignee_id,
              {"active_workload": new_tm.get("active_workload", 0) + 1},
              bump=True)

    append_audit(
        defect_id=defect_id,
        event_type="ASSIGNMENT_CHANGE",
        actor_id=g.user_id,
        from_value=prior_assignee,
        to_value=new_assignee_id,
        at_minute=project["clock_minute"],
    )
    updated = db.find_by_id("defects", defect_id)
    return success(defect_dto(updated))


# ---------------------------------------------------------------------------
# Start-progress, submit-fix
# ---------------------------------------------------------------------------
@bp.post("/defects/<defect_id>/start-progress")
def start_progress(defect_id):
    require_role(ROLE_DEVELOPER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if d["status"] != DEFECT_ASSIGNED:
        raise AppError(ERR_DEFECT_NOT_ASSIGNED,
                       f"Defect must be ASSIGNED; was {d['status']}", 409)
    if d.get("assignee_id") != g.user_id:
        raise AppError(ERR_DEFECT_NOT_ASSIGNED,
                       "Only the assigned developer may start progress.", 409)
    if d.get("sla_state") != SLA_RUNNING:
        raise AppError(ERR_INVALID_SLA_STATE_TRANSITION,
                       "Cannot start progress while SLA is paused.", 409)
    check_version(body, d)

    db.update("defects", defect_id, {"status": DEFECT_IN_PROGRESS}, bump=True)
    append_audit(
        defect_id=defect_id,
        event_type="STATUS_CHANGE",
        actor_id=g.user_id,
        from_value=DEFECT_ASSIGNED,
        to_value=DEFECT_IN_PROGRESS,
        at_minute=project["clock_minute"],
    )
    return success(defect_dto(db.find_by_id("defects", defect_id)))


@bp.post("/defects/<defect_id>/submit-fix")
def submit_fix(defect_id):
    require_role(ROLE_DEVELOPER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if d["status"] != DEFECT_IN_PROGRESS:
        raise AppError(ERR_DEFECT_NOT_IN_PROGRESS,
                       f"Defect must be IN_PROGRESS; was {d['status']}", 409)
    if d.get("assignee_id") != g.user_id:
        raise AppError(ERR_DEFECT_NOT_IN_PROGRESS,
                       "Only the assigned developer may submit a fix.", 409)
    module = find_module_or_404(d["module_id"])
    if module.get("status") != ACTIVE:
        raise AppError(ERR_MODULE_ARCHIVED, "Module is archived.", 409)

    fix_version = require_str(body, "fix_version")
    fix_summary = require_str(body, "fix_summary")
    commit_sha = require_str(body, "commit_sha")
    if not COMMIT_SHA_RE.match(commit_sha):
        raise AppError(ERR_INVALID_REQUEST,
                       "commit_sha must be 7–64 hex chars", 400)
    check_version(body, d)

    # Create FixRecord
    fr = db.insert("fix_records", {
        "defect_id": defect_id,
        "fix_version": fix_version,
        "developer_id": d["assignee_id"],
        "fix_summary": fix_summary,
        "commit_sha": commit_sha,
    })
    # Update defect
    updates = {
        "status": DEFECT_FIXED,
        "fix_version": fix_version,
    }
    if d.get("first_fixed_at_minute") is None:
        updates["first_fixed_at_minute"] = project["clock_minute"]
        updates["final_resolution_minutes"] = (
            project["clock_minute"]
            - d["report_clock_minute"]
            - d.get("total_paused_minutes", 0)
        )
    db.update("defects", defect_id, updates, bump=True)
    append_audit(
        defect_id=defect_id,
        event_type="STATUS_CHANGE",
        actor_id=g.user_id,
        from_value=DEFECT_IN_PROGRESS,
        to_value=DEFECT_FIXED,
        at_minute=project["clock_minute"],
    )
    return success(defect_dto(db.find_by_id("defects", defect_id)))


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
@bp.post("/defects/<defect_id>/verify")
def verify_defect(defect_id):
    require_role(ROLE_QA_ENGINEER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    outcome = require_enum(body, "outcome", {OUTCOME_PASSED, OUTCOME_FAILED})
    fix_record_id = require_str(body, "fix_record_id")
    notes = body.get("notes")

    # State check first
    if d["status"] != DEFECT_FIXED:
        raise AppError(ERR_DEFECT_NOT_FIXED,
                       f"Defect must be FIXED; was {d['status']}", 409)

    fr = find_fix_record_or_404(fix_record_id)
    if fr["defect_id"] != defect_id:
        # treat as stale (wrong defect)
        raise AppError(ERR_FIX_RECORD_STALE,
                       "fix_record_id does not belong to this defect.", 409)

    # Verifier independence (priority 6 - BEFORE fix-record-stale, BEFORE OCC)
    if g.user_id == fr["developer_id"]:
        raise AppError(ERR_VERIFIER_NOT_INDEPENDENT,
                       "Verifier cannot be the fix author.", 403)

    # Latest FixRecord check
    frs = [r for r in db.all_rows("fix_records") if r["defect_id"] == defect_id]
    frs.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    if not frs or frs[-1]["id"] != fix_record_id:
        raise AppError(ERR_FIX_RECORD_STALE,
                       "fix_record_id is not the latest FixRecord for this defect.", 409)

    check_version(body, d)

    # Create VerificationRecord
    db.insert("verification_records", {
        "defect_id": defect_id,
        "fix_record_id": fix_record_id,
        "verifier_id": g.user_id,
        "outcome": outcome,
        "notes": notes,
    })

    if outcome == OUTCOME_PASSED:
        db.update("defects", defect_id, {"status": DEFECT_VERIFIED}, bump=True)
        append_audit(
            defect_id=defect_id,
            event_type="STATUS_CHANGE",
            actor_id=g.user_id,
            from_value=DEFECT_FIXED,
            to_value=DEFECT_VERIFIED,
            at_minute=project["clock_minute"],
        )
    else:
        # Reopen cascade
        d_fresh = db.find_by_id("defects", defect_id)
        reopen_cascade(d_fresh, project, g.user_id)
        db.update("defects", defect_id, d_fresh, bump=True)

    return success(defect_dto(db.find_by_id("defects", defect_id)))


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------
@bp.post("/defects/<defect_id>/close")
def close_defect(defect_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if d["status"] != DEFECT_VERIFIED:
        raise AppError(ERR_DEFECT_NOT_VERIFIED,
                       f"Defect must be VERIFIED; was {d['status']}", 409)

    # Regression gate
    runs = [r for r in db.all_rows("regression_runs") if r["defect_id"] == defect_id]
    if runs:
        for r in runs:
            if r["status"] != "PASSED":
                raise AppError(ERR_REGRESSION_NOT_PASSED,
                               "All regression runs must be PASSED before close.", 409)
    check_version(body, d)

    # Decrement assignee workload, module active count, increment quota_remaining
    assignee = db.find_by_id("team_members", d.get("assignee_id"))
    if assignee:
        db.update("team_members", assignee["id"],
                  {"active_workload": max(0, assignee.get("active_workload", 0) - 1)},
                  bump=True)
    module = db.find_by_id("modules", d["module_id"])
    if module:
        db.update("modules", module["id"], {
            "active_defect_count": max(0, module["active_defect_count"] - 1),
            "quota_remaining": module["quota_remaining"] + 1,
        }, bump=True)

    db.update("defects", defect_id, {"status": DEFECT_CLOSED}, bump=True)
    append_audit(
        defect_id=defect_id,
        event_type="STATUS_CHANGE",
        actor_id=g.user_id,
        from_value=DEFECT_VERIFIED,
        to_value=DEFECT_CLOSED,
        at_minute=project["clock_minute"],
    )
    return success(defect_dto(db.find_by_id("defects", defect_id)))


# ---------------------------------------------------------------------------
# Pause / Resume SLA
# ---------------------------------------------------------------------------
@bp.post("/defects/<defect_id>/pause-sla")
def pause_sla(defect_id):
    require_role(ROLE_DEVELOPER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if d.get("assignee_id") != g.user_id:
        raise AppError(ERR_SLA_PAUSE_INVALID_STATUS,
                       "Only the assigned developer may pause.", 409)

    if d["status"] not in (DEFECT_ASSIGNED, DEFECT_IN_PROGRESS):
        raise AppError(ERR_SLA_PAUSE_INVALID_STATUS,
                       f"Cannot pause defect in status {d['status']}", 409)

    if d.get("sla_state") == SLA_PAUSED:
        raise AppError(ERR_INVALID_SLA_STATE_TRANSITION,
                       "SLA is already paused.", 409)

    reason = require_enum(body, "reason", PAUSE_REASONS)
    check_version(body, d)

    # Adjacency check: must not start at exactly ended_at_minute of immediately preceding closed pause
    pauses = [p for p in db.all_rows("sla_pauses") if p["defect_id"] == defect_id
              and p.get("ended_at_minute") is not None]
    if pauses:
        pauses.sort(key=lambda p: (p["ended_at_minute"], p.get("_seq", 0)))
        last_end = pauses[-1]["ended_at_minute"]
        if project["clock_minute"] == last_end:
            raise AppError(ERR_SLA_PAUSE_ADJACENT,
                           "New pause adjacent to previous pause's end.", 409)

    # Open pause check (already handled by sla_state check above, but be safe)
    open_pauses = [p for p in db.all_rows("sla_pauses")
                   if p["defect_id"] == defect_id and p.get("ended_at_minute") is None]
    if open_pauses:
        raise AppError(ERR_INVALID_SLA_STATE_TRANSITION,
                       "An open pause already exists.", 409)

    pause_row = db.insert("sla_pauses", {
        "defect_id": defect_id,
        "started_at_minute": project["clock_minute"],
        "ended_at_minute": None,
        "reason": reason,
        "paused_by": g.user_id,
    })
    db.update("defects", defect_id, {"sla_state": SLA_PAUSED}, bump=True)
    append_audit(
        defect_id=defect_id,
        event_type="SLA_PAUSE",
        actor_id=g.user_id,
        from_value=SLA_RUNNING,
        to_value=SLA_PAUSED,
        at_minute=project["clock_minute"],
    )
    return success(defect_dto(db.find_by_id("defects", defect_id)))


@bp.post("/defects/<defect_id>/resume-sla")
def resume_sla(defect_id):
    require_role(ROLE_DEVELOPER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if d.get("assignee_id") != g.user_id:
        raise AppError(ERR_INVALID_SLA_STATE_TRANSITION,
                       "Only the assigned developer may resume.", 409)

    if d.get("sla_state") != SLA_PAUSED:
        raise AppError(ERR_INVALID_SLA_STATE_TRANSITION,
                       "SLA is not paused.", 409)

    open_pauses = [p for p in db.all_rows("sla_pauses")
                   if p["defect_id"] == defect_id and p.get("ended_at_minute") is None]
    if not open_pauses:
        raise AppError(ERR_INVALID_SLA_STATE_TRANSITION,
                       "No open pause to resume.", 409)
    check_version(body, d)

    pause = open_pauses[0]
    end_min = project["clock_minute"]
    pause["ended_at_minute"] = end_min
    # in-memory mutation persists; also call update
    delta = end_min - pause["started_at_minute"]
    new_total = d.get("total_paused_minutes", 0) + max(0, delta)
    db.update("defects", defect_id, {
        "sla_state": SLA_RUNNING,
        "total_paused_minutes": new_total,
    }, bump=True)
    append_audit(
        defect_id=defect_id,
        event_type="SLA_RESUME",
        actor_id=g.user_id,
        from_value=SLA_PAUSED,
        to_value=SLA_RUNNING,
        at_minute=end_min,
    )
    return success(defect_dto(db.find_by_id("defects", defect_id)))


# ---------------------------------------------------------------------------
# Fix records & verification records listings
# ---------------------------------------------------------------------------
@bp.get("/defects/<defect_id>/fix-records")
def list_fix_records(defect_id):
    require_role(ROLE_ANY)
    find_defect_or_404(defect_id)
    limit, offset = parse_pagination(request.args)
    from services.serializers import fix_record_dto
    rows, total = db.query("fix_records", filters={"defect_id": defect_id},
                           limit=limit, offset=offset)
    return success_list([fix_record_dto(r) for r in rows], total, limit, offset)


@bp.get("/defects/<defect_id>/verification-records")
def list_verification_records(defect_id):
    require_role(ROLE_ANY)
    find_defect_or_404(defect_id)
    limit, offset = parse_pagination(request.args)
    from services.serializers import verification_record_dto
    rows, total = db.query("verification_records", filters={"defect_id": defect_id},
                           limit=limit, offset=offset)
    return success_list([verification_record_dto(r) for r in rows], total, limit, offset)
