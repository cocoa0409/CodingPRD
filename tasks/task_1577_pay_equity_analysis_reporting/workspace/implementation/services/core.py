"""Core shared services: record lifecycle, derived aggregates (PRD §2.10),
auto-transitions (finding resolution, plan commitment/completion, study
auto-monitoring), and the scheduled-transition sweep (PRD §2.4)."""
from decimal import Decimal

from db import db, next_seq
from util import new_id, clock_now_ts, parse_date, clock_today, D


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    # System-stamped timestamps read from the logical clock (PRD §2.4/§2.5).
    ts = clock_now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Any mutation refreshes updated_at and increments version (PRD §2.5)."""
    rec["updated_at"] = clock_now_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_study(study_id):
    return db["pay_equity_studies"].get(study_id)


def get_group(group_id):
    return db["comparator_groups"].get(group_id)


def get_plan(plan_id):
    return db["remediation_plans"].get(plan_id)


def get_finding(finding_id):
    return db["gap_findings"].get(finding_id)


def snapshots_of_study(study_id):
    return [s for s in db["employee_snapshots"].values() if s["study_id"] == study_id]


def snapshots_of_group(group_id):
    return [s for s in db["employee_snapshots"].values()
            if s.get("comparator_group_id") == group_id]


def groups_of_study(study_id):
    return [g for g in db["comparator_groups"].values() if g["study_id"] == study_id]


def runs_of_group(group_id):
    return [r for r in db["model_runs"].values() if r["comparator_group_id"] == group_id]


def runs_of_study(study_id):
    return [r for r in db["model_runs"].values() if r["study_id"] == study_id]


def findings_of_study(study_id):
    return [f for f in db["gap_findings"].values() if f["study_id"] == study_id]


def plans_of_study(study_id):
    return [p for p in db["remediation_plans"].values() if p["study_id"] == study_id]


def adjustments_of_plan(plan_id):
    return [a for a in db["adjustments"].values() if a["plan_id"] == plan_id]


def adjustments_of_finding(finding_id):
    return [a for a in db["adjustments"].values() if a["gap_finding_id"] == finding_id]


def cycles_of_study(study_id):
    return [c for c in db["monitoring_cycles"].values() if c["study_id"] == study_id]


# ---------------------------------------------------------------------------
# Actionability (PRD §3.3) — both comparisons INCLUSIVE, on stored 4dp values
# ---------------------------------------------------------------------------

def compute_is_actionable(study, adjusted_gap_pct, p_value) -> bool:
    gap = D(adjusted_gap_pct)
    p = D(p_value)
    return (gap >= D(study["actionable_gap_pct"])
            and p <= D(study["significance_threshold"]))


# ---------------------------------------------------------------------------
# Derived aggregates (PRD §2.10) — each recomputation mutates the owner
# ---------------------------------------------------------------------------

def recompute_study_aggregates(study_id):
    study = db["pay_equity_studies"].get(study_id)
    if study is None:
        return
    snaps = snapshots_of_study(study_id)
    findings = findings_of_study(study_id)
    study["snapshot_count"] = len(snaps)
    study["assigned_snapshot_count"] = sum(
        1 for s in snaps if s.get("comparator_group_id") is not None)
    study["unresolved_finding_count"] = sum(
        1 for f in findings if f["status"] in ("FLAGGED", "TARGETED"))
    study["actionable_finding_count"] = sum(
        1 for f in findings if f["is_actionable"] and f["status"] != "DISMISSED")
    touch(study)


def recompute_member_count(group_id):
    group = db["comparator_groups"].get(group_id)
    if group is None:
        return
    group["member_count"] = len(snapshots_of_group(group_id))
    touch(group)


def recompute_plan(plan_id):
    """Recompute committed/remaining (PRD §2.10); does NOT run state transitions."""
    plan = db["remediation_plans"].get(plan_id)
    if plan is None:
        return
    committed = sum(
        a["approved_increase_cents"] or 0
        for a in adjustments_of_plan(plan_id)
        if a["status"] in ("APPROVED", "EFFECTIVE")
    )
    plan["committed_cents"] = committed
    plan["remaining_cents"] = plan["total_budget_cents"] - committed
    touch(plan)


# ---------------------------------------------------------------------------
# Auto-transitions
# ---------------------------------------------------------------------------

def plan_ready_for_monitoring(study_id) -> bool:
    """The study's non-COMPLETED plan (if any) is FULLY_COMMITTED or COMPLETED;
    a plan must exist (PRD §3.4)."""
    plans = plans_of_study(study_id)
    if not plans:
        return False
    live = [p for p in plans if p["status"] != "COMPLETED"]
    if live:
        return live[0]["status"] == "FULLY_COMMITTED"
    return True  # all plans COMPLETED


def check_study_auto_monitoring(study_id):
    """REMEDIATION_OPEN -> MONITORING when unresolved == 0 and the plan is
    FULLY_COMMITTED or COMPLETED (PRD §3.3/§3.4)."""
    study = db["pay_equity_studies"].get(study_id)
    if study is None or study["status"] != "REMEDIATION_OPEN":
        return
    if study["unresolved_finding_count"] != 0:
        return
    if not plan_ready_for_monitoring(study_id):
        return
    study["status"] = "MONITORING"
    touch(study)


def check_finding_resolution(finding_id, visited=None):
    """TARGETED -> RESOLVED when no referencing adjustment remains PROPOSED or
    APPROVED and at least one referencing adjustment is EFFECTIVE (PRD §3.4).
    Re-evaluated on every adjustment EFFECTIVE/REJECTED/REVERSED transition."""
    finding = db["gap_findings"].get(finding_id)
    if finding is None or finding["status"] != "TARGETED":
        return
    adjs = adjustments_of_finding(finding_id)
    if not adjs:
        return
    open_count = sum(1 for a in adjs if a["status"] in ("PROPOSED", "APPROVED"))
    effective_count = sum(1 for a in adjs if a["status"] == "EFFECTIVE")
    if open_count == 0 and effective_count >= 1:
        finding["status"] = "RESOLVED"
        touch(finding)
        recompute_study_aggregates(finding["study_id"])
        check_study_auto_monitoring(finding["study_id"])


def check_plan_transitions(plan_id, visited=None):
    """Automatic plan transitions (PRD §3.4):
    EXECUTING -> FULLY_COMMITTED when committed == total;
    EXECUTING/FULLY_COMMITTED -> COMPLETED when no PROPOSED/APPROVED remain and
    at least one adjustment is EFFECTIVE."""
    plan = db["remediation_plans"].get(plan_id)
    if plan is None:
        return
    if plan["status"] == "EXECUTING" and plan["committed_cents"] == plan["total_budget_cents"]:
        plan["status"] = "FULLY_COMMITTED"
        touch(plan)
        # Full-commitment runs the study auto-monitoring check (PRD §3.4)
        check_study_auto_monitoring(plan["study_id"])
        return
    if plan["status"] in ("EXECUTING", "FULLY_COMMITTED"):
        adjs = adjustments_of_plan(plan_id)
        open_count = sum(1 for a in adjs if a["status"] in ("PROPOSED", "APPROVED"))
        effective_count = sum(1 for a in adjs if a["status"] == "EFFECTIVE")
        if open_count == 0 and effective_count >= 1:
            plan["status"] = "COMPLETED"
            touch(plan)
            # Completion runs the study auto-monitoring check (PRD §3.4)
            check_study_auto_monitoring(plan["study_id"])


# ---------------------------------------------------------------------------
# Scheduled-transition sweep (PRD §2.4) — pinned order
# ---------------------------------------------------------------------------

def run_sweep(new_dt):
    """On every clock set, in this pinned order:
    1. APPROVED adjustments with effective_date <= new clock UTC date -> EFFECTIVE
       (ties: effective_date ASC, then created_at ASC)
    2. GapFinding resolution re-check for affected findings
    3. Plan completion / FULLY_COMMITTED checks
    4. Study auto-monitoring check
    5. SCHEDULED MonitoringCycles with due_date <= new clock UTC date -> DUE
    """
    new_date = new_dt.date()

    # 1. effectivation sweep
    due_adjustments = [
        a for a in db["adjustments"].values()
        if a["status"] == "APPROVED" and parse_date(a["effective_date"]) <= new_date
    ]
    due_adjustments.sort(key=lambda a: (a["effective_date"], a["created_at"], a["_seq"]))
    for adj in due_adjustments:
        adj["status"] = "EFFECTIVE"
        touch(adj)

    # 2. finding resolution re-check for affected findings (adjustment order, deduped)
    seen_findings = []
    for adj in due_adjustments:
        fid = adj["gap_finding_id"]
        if fid not in seen_findings:
            seen_findings.append(fid)
    for fid in seen_findings:
        check_finding_resolution(fid)

    # 3. plan completion / full-commitment checks (affected plans, adjustment order)
    seen_plans = []
    for adj in due_adjustments:
        pid = adj["plan_id"]
        if pid not in seen_plans:
            seen_plans.append(pid)
    for pid in seen_plans:
        plan = get_plan(pid)
        if plan is not None:
            recompute_plan(pid)
            check_plan_transitions(pid)

    # 4. study auto-monitoring check (affected studies)
    seen_studies = []
    for adj in due_adjustments:
        sid = adj["study_id"]
        if sid not in seen_studies:
            seen_studies.append(sid)
    for sid in seen_studies:
        check_study_auto_monitoring(sid)

    # 5. cycles SCHEDULED -> DUE
    for cyc in db["monitoring_cycles"].values():
        if cyc["status"] == "SCHEDULED" and parse_date(cyc["due_date"]) <= new_date:
            cyc["status"] = "DUE"
            touch(cyc)
