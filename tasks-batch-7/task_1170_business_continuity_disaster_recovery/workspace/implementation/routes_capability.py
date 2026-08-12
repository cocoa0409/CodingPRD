"""Recovery capabilities, validation runs, gaps (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

from calc import (capability_freshness, capability_meets_bia,
                  capability_targets, create_gap, record_validation_run,
                  refresh_process_capability_freshness)
from core import (ALL_ROLES, DB, actor, apply_filters, as_dt, as_enum, as_int,
                  as_str, body, bump, fail, not_found, now_dt, ok, opt_str,
                  paginate, req, sorted_by_created, stamp_new, validation)
from serializers import capability_view, gap_view, run_view

bp = Blueprint("capability", __name__)

CAPABILITY_TYPES = ["SITE", "WORKFORCE", "DATA_RESTORE", "VENDOR_FAILOVER"]
RUN_METHODS = ["FAILOVER", "SIMULATION", "COMPONENT_TEST"]
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
CAP_TERMINAL_GAP_STATES = ("CLOSED", "ACCEPTED_RISK")


def get_capability_or_404(capability_id):
    c = DB.capabilities.get(capability_id)
    if c is None:
        not_found("ERR_CAPABILITY_NOT_FOUND", "Recovery capability")
    return c


def get_run_or_404(run_id):
    r = DB.runs.get(run_id)
    if r is None:
        not_found("ERR_RUN_NOT_FOUND", "Validation run")
    return r


def get_gap_or_404(gap_id):
    g = DB.gaps.get(gap_id)
    if g is None:
        not_found("ERR_GAP_NOT_FOUND", "Gap")
    return g


# --------------------------------------------------------------------------
# Recovery capabilities
# --------------------------------------------------------------------------

@bp.post("/resilience/recovery-capabilities")
def create_capability():
    actor(["PlanAuthor"])
    payload = body()
    process_id = req(payload, "process_id")
    if process_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    cap_type = as_enum(req(payload, "capability_type"), "capability_type",
                       CAPABILITY_TYPES)
    ref_id = req(payload, "capability_ref_id")
    ref_id = as_str(ref_id, "capability_ref_id")
    # Cross-reference consistency (PRD §2.10 layer 14, 422 on this route)
    if cap_type == "SITE" and ref_id not in DB.sites:
        validation("capability_ref_id must reference an existing alternate "
                   "site for capability_type SITE", status=422)
    if cap_type == "VENDOR_FAILOVER" and ref_id not in DB.third_parties:
        validation("capability_ref_id must reference an existing third party "
                   "for capability_type VENDOR_FAILOVER", status=422)
    c = {"process_id": process_id, "capability_type": cap_type,
         "capability_ref_id": ref_id, "proven_rto_hours": None,
         "proven_rpo_hours": None, "meets_bia": False,
         "last_validation_run_id": None, "validation_freshness": "NEVER",
         "status": "UNPROVEN"}
    stamp_new(c)
    DB.capabilities[c["id"]] = c
    return ok(capability_view(c), status=201)


@bp.get("/resilience/recovery-capabilities")
def list_capabilities():
    actor(ALL_ROLES)
    items = list(DB.capabilities.values())
    # Refresh computed labels before filtering on them.
    for c in items:
        c["meets_bia"] = capability_meets_bia(c)
        c["validation_freshness"] = capability_freshness(c)
    items = apply_filters(items, [
        ("process_id", "process_id"),
        ("capability_type", "capability_type"),
        ("status", "status"),
        ("validation_freshness", "validation_freshness"),
        ("capability_ref_id", "capability_ref_id"),
        ("last_validation_run_id", "last_validation_run_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([capability_view(c) for c in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/recovery-capabilities/<capabilityId>")
def get_capability(capabilityId):
    actor(ALL_ROLES)
    return ok(capability_view(get_capability_or_404(capabilityId)))


@bp.post("/resilience/recovery-capabilities/<capabilityId>/mark-remediated")
def mark_remediated(capabilityId):
    actor(["PlanAuthor"])
    c = get_capability_or_404(capabilityId)
    if c["status"] != "GAP_IDENTIFIED":
        fail("ERR_INVALID_STATE", 409,
             "A capability may be marked remediated only from GAP_IDENTIFIED")
    if any(g.get("capability_id") == capabilityId
           and g["status"] not in CAP_TERMINAL_GAP_STATES
           for g in DB.gaps.values()):
        fail("ERR_CAPABILITY_HAS_OPEN_GAPS", 409,
             "The capability still has non-terminal gaps")
    c["status"] = "REMEDIATED"
    bump(c)
    c["validation_freshness"] = capability_freshness(c)
    return ok(capability_view(c))


@bp.get("/resilience/recovery-capabilities/<capabilityId>/validation-runs")
def capability_runs(capabilityId):
    actor(ALL_ROLES)
    get_capability_or_404(capabilityId)
    items = [r for r in DB.runs.values() if r["capability_id"] == capabilityId]
    page, meta = paginate(sorted_by_created(items))
    return ok([run_view(r) for r in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/recovery-capabilities/<capabilityId>/gaps")
def capability_gaps(capabilityId):
    actor(ALL_ROLES)
    get_capability_or_404(capabilityId)
    items = [g for g in DB.gaps.values()
             if g.get("capability_id") == capabilityId]
    page, meta = paginate(sorted_by_created(items))
    return ok([gap_view(g) for g in page], response_type="array",
              pagination=meta)


# --------------------------------------------------------------------------
# Validation runs
# --------------------------------------------------------------------------

@bp.post("/resilience/validation-runs")
def create_run():
    actor(["ExerciseOfficer"])
    payload = body()
    capability_id = req(payload, "capability_id")
    capability = DB.capabilities.get(capability_id)
    if capability is None:
        not_found("ERR_CAPABILITY_NOT_FOUND", "Recovery capability")
    measured_rto = as_int(req(payload, "measured_rto_hours"),
                          "measured_rto_hours", minv=0)
    measured_rpo = as_int(req(payload, "measured_rpo_hours"),
                          "measured_rpo_hours", minv=0)
    method = as_enum(req(payload, "method"), "method", RUN_METHODS)
    evidence_ref = as_str(req(payload, "evidence_ref"), "evidence_ref")
    if capability_targets(capability) is None:
        fail("ERR_CAPABILITY_TARGETS_UNKNOWN", 422,
             "The capability's process has neither an APPROVED BIA nor an "
             "APPROVED plan")
    run = record_validation_run(capability, measured_rto, measured_rpo,
                                method, evidence_ref)
    return ok(run_view(run), status=201)


@bp.get("/resilience/validation-runs")
def list_runs():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.runs.values()), [
        ("capability_id", "capability_id"),
        ("exercise_id", "exercise_id"),
        ("result", "result"),
        ("status", "status"),
        ("gap_created_id", "gap_created_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([run_view(r) for r in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/validation-runs/<runId>")
def get_run(runId):
    actor(ALL_ROLES)
    return ok(run_view(get_run_or_404(runId)))


# --------------------------------------------------------------------------
# Gaps
# --------------------------------------------------------------------------

@bp.post("/resilience/gaps")
def create_manual_gap():
    actor(["PlanAuthor"])
    payload = body()
    process_id = req(payload, "process_id")
    if process_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    finding_id = payload.get("finding_id")
    if finding_id is not None and finding_id not in DB.findings:
        not_found("ERR_FINDING_NOT_FOUND", "Finding")
    severity = as_enum(req(payload, "severity"), "severity", SEVERITIES)
    description = as_str(req(payload, "description"), "description")
    due_date = as_dt(req(payload, "due_date"), "due_date")
    gap = create_gap(process_id=process_id, capability_id=None,
                     finding_id=finding_id, severity=severity,
                     description=description, due_date=due_date)
    refresh_process_capability_freshness(process_id)
    return ok(gap_view(gap), status=201)


@bp.get("/resilience/gaps")
def list_gaps():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.gaps.values()), [
        ("process_id", "process_id"),
        ("capability_id", "capability_id"),
        ("finding_id", "finding_id"),
        ("status", "status"),
        ("severity", "severity"),
        ("closed_by_contact_id", "closed_by_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([gap_view(g) for g in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/gaps/<gapId>")
def get_gap(gapId):
    actor(ALL_ROLES)
    return ok(gap_view(get_gap_or_404(gapId)))


def _gap_transition(gapId, from_states, to_state):
    actor(["PlanAuthor"])
    g = get_gap_or_404(gapId)
    if g["status"] not in from_states:
        fail("ERR_INVALID_STATE", 409,
             f"Gap must be in {' or '.join(from_states)}")
    g["status"] = to_state
    bump(g)
    return g


@bp.post("/resilience/gaps/<gapId>/start")
def start_gap(gapId):
    return ok(gap_view(_gap_transition(gapId, ["OPEN"], "IN_PROGRESS")))


@bp.post("/resilience/gaps/<gapId>/reopen")
def reopen_gap(gapId):
    return ok(gap_view(_gap_transition(gapId, ["IN_PROGRESS"], "OPEN")))


def _gap_resolve(gapId, to_state):
    who = actor(["RiskCommittee"])
    g = get_gap_or_404(gapId)
    if g["status"] not in ("OPEN", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", 409,
             "Gap must be in OPEN or IN_PROGRESS")
    g["status"] = to_state
    if to_state == "CLOSED":
        g["closed_by_contact_id"] = who["id"]
    bump(g)
    # Aggregate refresh (PRD §3.7): capabilities of the process recompute
    # validation_freshness (bumped when the label actually changes).
    refresh_process_capability_freshness(g["process_id"])
    return g


@bp.post("/resilience/gaps/<gapId>/close")
def close_gap(gapId):
    return ok(gap_view(_gap_resolve(gapId, "CLOSED")))


@bp.post("/resilience/gaps/<gapId>/accept-risk")
def accept_risk_gap(gapId):
    return ok(gap_view(_gap_resolve(gapId, "ACCEPTED_RISK")))
