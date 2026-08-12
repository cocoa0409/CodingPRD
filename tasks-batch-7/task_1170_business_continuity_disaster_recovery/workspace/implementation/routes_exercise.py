"""Exercises and findings (PRD §3.6)."""
from flask import Blueprint

from calc import (capability_targets, create_gap, exercise_result,
                  record_validation_run, refresh_process_capability_freshness)
from core import (ALL_ROLES, DB, actor, apply_filters, as_dt, as_enum, as_int,
                  as_str, body, bump, fail, not_found, ok, opt_str, paginate,
                  req, sorted_by_created, stamp_new, validation)
from routes_registry import get_process_or_404
from serializers import exercise_view, finding_view, gap_view, run_view

bp = Blueprint("exercise", __name__)

EXERCISE_TYPES = ["TABLETOP", "FAILOVER"]
OUTCOMES = ["MET", "MISSED", "PARTIAL"]
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def get_exercise_or_404(exercise_id):
    e = DB.exercises.get(exercise_id)
    if e is None:
        not_found("ERR_EXERCISE_NOT_FOUND", "Exercise")
    return e


def get_finding_or_404(finding_id):
    f = DB.findings.get(finding_id)
    if f is None:
        not_found("ERR_FINDING_NOT_FOUND", "Finding")
    return f


def _failover_window_conflict(process_id, start, end, exclude_id=None):
    """FAILOVER windows of one process are strictly disjoint under
    closed-interval semantics: touching endpoints count as overlap."""
    for e in DB.exercises.values():
        if (e["process_id"] == process_id and e["exercise_type"] == "FAILOVER"
                and e["status"] != "CANCELLED" and e["id"] != exclude_id):
            if start <= e["scheduled_end"] and e["scheduled_start"] <= end:
                return True
    return False


def _require_plan_approved_for_exercise(plan):
    if plan["status"] != "APPROVED":
        fail("ERR_PLAN_NOT_APPROVED_FOR_EXERCISE", 409,
             "The referenced plan must be APPROVED")


# --------------------------------------------------------------------------
# Exercises
# --------------------------------------------------------------------------

@bp.post("/resilience/exercises")
def create_exercise():
    actor(["ExerciseOfficer"])
    payload = body()
    process_id = req(payload, "process_id")
    process = DB.processes.get(process_id)
    if process is None:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    plan_id = req(payload, "plan_id")
    plan = DB.plans.get(plan_id)
    if plan is None:
        not_found("ERR_PLAN_NOT_FOUND", "Plan")
    ex_type = as_enum(req(payload, "exercise_type"), "exercise_type",
                      EXERCISE_TYPES)
    start = as_dt(req(payload, "scheduled_start"), "scheduled_start")
    end = as_dt(req(payload, "scheduled_end"), "scheduled_end")
    if end <= start:
        validation("scheduled_end must be strictly after scheduled_start")
    if process["status"] != "ACTIVE":
        fail("ERR_PROCESS_NOT_ACTIVE", 409,
             "The referenced process must be ACTIVE")
    _require_plan_approved_for_exercise(plan)
    if ex_type == "FAILOVER" and _failover_window_conflict(process_id, start,
                                                           end):
        fail("ERR_EXERCISE_WINDOW_OVERLAP", 409,
             "FAILOVER windows of a process must be strictly disjoint")
    if plan["process_id"] != process_id:
        validation("The plan must belong to the exercise's process")
    e = {"process_id": process_id, "plan_id": plan_id,
         "exercise_type": ex_type, "scheduled_start": start,
         "scheduled_end": end, "completion_outcome": None,
         "achieved_rto_hours": None, "achieved_rpo_hours": None,
         "result": None,
         "requires_capability_check": ex_type == "FAILOVER",
         "validation_run_id": None, "status": "SCHEDULED"}
    stamp_new(e)
    DB.exercises[e["id"]] = e
    return ok(exercise_view(e), status=201)


@bp.get("/resilience/exercises")
def list_exercises():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.exercises.values()), [
        ("process_id", "process_id"),
        ("plan_id", "plan_id"),
        ("status", "status"),
        ("exercise_type", "exercise_type"),
        ("validation_run_id", "validation_run_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([exercise_view(e) for e in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/exercises/<exerciseId>")
def get_exercise(exerciseId):
    actor(ALL_ROLES)
    return ok(exercise_view(get_exercise_or_404(exerciseId)))


@bp.put("/resilience/exercises/<exerciseId>")
def reschedule_exercise(exerciseId):
    actor(["ExerciseOfficer"])
    e = get_exercise_or_404(exerciseId)
    payload = body()
    expected = as_int(req(payload, "expected_exercise_version"),
                      "expected_exercise_version")
    start = e["scheduled_start"]
    end = e["scheduled_end"]
    if "scheduled_start" in payload and payload["scheduled_start"] is not None:
        start = as_dt(payload["scheduled_start"], "scheduled_start")
    if "scheduled_end" in payload and payload["scheduled_end"] is not None:
        end = as_dt(payload["scheduled_end"], "scheduled_end")
    if end <= start:
        validation("scheduled_end must be strictly after scheduled_start")
    if e["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", 409,
             "An exercise may be rescheduled only while SCHEDULED")
    plan = DB.plans.get(e["plan_id"])
    if plan is not None:
        _require_plan_approved_for_exercise(plan)
    if e["exercise_type"] == "FAILOVER" and _failover_window_conflict(
            e["process_id"], start, end, exclude_id=e["id"]):
        fail("ERR_EXERCISE_WINDOW_OVERLAP", 409,
             "FAILOVER windows of a process must be strictly disjoint")
    if expected != e["version"]:
        fail("ERR_STALE_VERSION", 412,
             "expected_exercise_version does not match the current version")
    e["scheduled_start"] = start
    e["scheduled_end"] = end
    bump(e)
    return ok(exercise_view(e))


@bp.post("/resilience/exercises/<exerciseId>/start")
def start_exercise(exerciseId):
    actor(["ExerciseOfficer"])
    e = get_exercise_or_404(exerciseId)
    if e["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", 409,
             "An exercise may be started only from SCHEDULED")
    e["status"] = "IN_PROGRESS"
    bump(e)
    return ok(exercise_view(e))


@bp.post("/resilience/exercises/<exerciseId>/complete")
def complete_exercise(exerciseId):
    actor(["ExerciseOfficer"])
    e = get_exercise_or_404(exerciseId)
    payload = body()
    outcome = as_enum(req(payload, "completion_outcome"), "completion_outcome",
                      OUTCOMES)
    ach_rto = as_int(req(payload, "achieved_rto_hours"), "achieved_rto_hours",
                     minv=0)
    ach_rpo = as_int(req(payload, "achieved_rpo_hours"), "achieved_rpo_hours",
                     minv=0)
    if e["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", 409,
             "An exercise may be completed only from IN_PROGRESS")
    plan = DB.plans.get(e["plan_id"])
    if plan is None:
        not_found("ERR_PLAN_NOT_FOUND", "Plan")
    _require_plan_approved_for_exercise(plan)
    e["completion_outcome"] = outcome
    e["achieved_rto_hours"] = ach_rto
    e["achieved_rpo_hours"] = ach_rpo
    e["result"] = exercise_result(e, plan, outcome, ach_rto, ach_rpo)
    e["status"] = "COMPLETED"
    bump(e)
    # FAILOVER validation cascade (PRD §3.6)
    if e["requires_capability_check"]:
        pool = [c for c in DB.capabilities.values()
                if c["process_id"] == e["process_id"]
                and c["capability_type"] == "SITE"
                and c["status"] in ("UNPROVEN", "VALIDATED", "GAP_IDENTIFIED")]
        pool.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))
        if pool:
            capability = pool[0]
            if capability_targets(capability) is not None:
                run = record_validation_run(
                    capability, ach_rto, ach_rpo, "FAILOVER", None,
                    exercise_id=e["id"])
                e["validation_run_id"] = run["id"]
    return ok(exercise_view(e))


@bp.post("/resilience/exercises/<exerciseId>/cancel")
def cancel_exercise(exerciseId):
    actor(["ExerciseOfficer"])
    e = get_exercise_or_404(exerciseId)
    if e["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", 409,
             "An exercise may be cancelled only from SCHEDULED or IN_PROGRESS")
    e["status"] = "CANCELLED"
    bump(e)
    return ok(exercise_view(e))


@bp.get("/resilience/exercises/<exerciseId>/findings")
def exercise_findings(exerciseId):
    actor(ALL_ROLES)
    get_exercise_or_404(exerciseId)
    items = [f for f in DB.findings.values() if f["exercise_id"] == exerciseId]
    page, meta = paginate(sorted_by_created(items))
    return ok([finding_view(f) for f in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/exercises/<exerciseId>/validation-runs")
def exercise_validation_runs(exerciseId):
    actor(ALL_ROLES)
    get_exercise_or_404(exerciseId)
    items = [r for r in DB.runs.values() if r.get("exercise_id") == exerciseId]
    page, meta = paginate(sorted_by_created(items))
    return ok([run_view(r) for r in page], response_type="array",
              pagination=meta)


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

@bp.post("/resilience/findings")
def create_finding():
    actor(["ExerciseOfficer"])
    payload = body()
    exercise_id = req(payload, "exercise_id")
    exercise = DB.exercises.get(exercise_id)
    if exercise is None:
        not_found("ERR_EXERCISE_NOT_FOUND", "Exercise")
    process_id = req(payload, "process_id")
    if process_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    severity = as_enum(req(payload, "severity"), "severity", SEVERITIES)
    description = as_str(req(payload, "description"), "description")
    due_date = as_dt(req(payload, "due_date"), "due_date")
    root_cause = opt_str(payload, "root_cause")
    if exercise["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", 409,
             "Findings may be recorded only on a COMPLETED exercise")
    if process_id != exercise["process_id"]:
        validation("The finding's process must equal the exercise's process",
                   status=422)
    f = {"exercise_id": exercise_id, "process_id": process_id,
         "severity": severity, "description": description,
         "due_date": due_date, "root_cause": root_cause,
         "verified_by_contact_id": None, "rejected_reason": None,
         "status": "OPEN", "_rem_gap_id": None}
    stamp_new(f)
    DB.findings[f["id"]] = f
    return ok(finding_view(f), status=201)


@bp.get("/resilience/findings")
def list_findings():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.findings.values()), [
        ("exercise_id", "exercise_id"),
        ("process_id", "process_id"),
        ("severity", "severity"),
        ("status", "status"),
        ("verified_by_contact_id", "verified_by_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([finding_view(f) for f in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/findings/<findingId>")
def get_finding(findingId):
    actor(ALL_ROLES)
    return ok(finding_view(get_finding_or_404(findingId)))


@bp.post("/resilience/findings/<findingId>/remediate")
def remediate_finding(findingId):
    actor(["PlanAuthor"])
    f = get_finding_or_404(findingId)
    if f["status"] != "OPEN":
        fail("ERR_INVALID_STATE", 409,
             "A finding may be remediated only from OPEN")
    gap = create_gap(process_id=f["process_id"], capability_id=None,
                     finding_id=f["id"], severity=f["severity"],
                     description=f["description"], due_date=f["due_date"])
    f["_rem_gap_id"] = gap["id"]
    f["status"] = "REMEDIATING"
    bump(f)
    return ok(finding_view(f))


def _remediation_gap(f):
    gap = DB.gaps.get(f.get("_rem_gap_id") or "")
    if gap is None:
        # Fall back to any live finding-linked gap.
        gap = next((g for g in DB.gaps.values()
                    if g.get("finding_id") == f["id"]
                    and g["status"] in ("OPEN", "IN_PROGRESS")), None)
    return gap


@bp.post("/resilience/findings/<findingId>/verify")
def verify_finding(findingId):
    who = actor(["RiskCommittee"])
    f = get_finding_or_404(findingId)
    if f["status"] != "REMEDIATING":
        fail("ERR_INVALID_STATE", 409,
             "A finding may be verified only from REMEDIATING")
    f["verified_by_contact_id"] = who["id"]
    f["status"] = "VERIFIED"
    bump(f)
    gap = _remediation_gap(f)
    if gap is not None and gap["status"] in ("OPEN", "IN_PROGRESS"):
        gap["status"] = "CLOSED"
        gap["closed_by_contact_id"] = who["id"]
        bump(gap)
    refresh_process_capability_freshness(f["process_id"])
    return ok(finding_view(f))


@bp.post("/resilience/findings/<findingId>/reject")
def reject_finding(findingId):
    actor(["RiskCommittee"])
    f = get_finding_or_404(findingId)
    payload = body()
    reason = opt_str(payload, "rejected_reason")
    if f["status"] != "REMEDIATING":
        fail("ERR_INVALID_STATE", 409,
             "A finding may be rejected only from REMEDIATING")
    f["rejected_reason"] = reason
    f["status"] = "REJECTED"
    bump(f)
    gap = _remediation_gap(f)
    if gap is not None and gap["status"] in ("OPEN", "IN_PROGRESS"):
        gap["status"] = "ACCEPTED_RISK"
        bump(gap)
    refresh_process_capability_freshness(f["process_id"])
    return ok(finding_view(f))


@bp.get("/resilience/findings/<findingId>/gaps")
def finding_gaps(findingId):
    actor(ALL_ROLES)
    get_finding_or_404(findingId)
    items = [g for g in DB.gaps.values() if g.get("finding_id") == findingId]
    page, meta = paginate(sorted_by_created(items))
    return ok([gap_view(g) for g in page], response_type="array",
              pagination=meta)
