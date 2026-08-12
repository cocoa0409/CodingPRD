"""Calculations and cascades (PRD §3, SCAFFOLD §1.3).

Dual-variant scores, blast radius, utilization, exercise/validation results,
attestation readiness, gap pressure, freshness, and the cascade machinery.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import DB, add_months, bump, fmt_dt, new_id, next_seq, now_dt, stamp_new, tick_dt

TIER1_UPLIFT = Decimal("0.15")
EVENT_DRIVEN_DISCOUNT = 15
FRESHNESS_MONTHS = 12
SIGN_THRESHOLD = 70

IMPACT_MAP = {"NONE": 0, "LOW": 1, "HIGH": 2}
SEVERITY_WEIGHT = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

REQUIRED_SECTION_TYPES = {"RECOVERY_STRATEGY", "DEPENDENCY_MAP", "COMMS_PLAN"}

SEV_CRITERIA = {
    "SEV1": {"CRITERION_A", "CRITERION_B"},
    "SEV2": {"CRITERION_A"},
    "SEV3": set(),
}


# --------------------------------------------------------------------------
# BIA criticality score (calculations.bia_criticality_score)
# --------------------------------------------------------------------------

def bia_raw_score(bia):
    impact_score = Decimal(str(bia["impact_financial_per_hour"])) / Decimal(10000)
    reg_score = IMPACT_MAP[bia["impact_regulatory"]]
    peak_score = 1 if bia["peak_period_flag"] else 0
    ops_score = IMPACT_MAP[bia["impact_operational"]]
    return (impact_score * 45 + reg_score * 25 + peak_score * 20 + ops_score * 10)


def bia_score(bia, final=False):
    raw = bia_raw_score(bia)
    if final:
        process = DB.processes.get(bia["process_id"])
        if process and process["criticality_tier"] == "TIER_1":
            raw = raw * (1 + TIER1_UPLIFT)
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# BIA / plan lookups
# --------------------------------------------------------------------------

def bias_of_process(process_id):
    return [b for b in DB.bias.values() if b["process_id"] == process_id]


def latest_bia(process_id, status):
    """Latest BIA of a process in a status: updated_at DESC, created_at DESC."""
    rows = [b for b in bias_of_process(process_id) if b["status"] == status]
    if not rows:
        return None
    rows.sort(key=lambda b: (b["updated_at"], b["created_at"], b.get("_seq", 0)),
              reverse=True)
    return rows[0]


def approved_bia(process_id):
    return latest_bia(process_id, "APPROVED")


def plans_of_process(process_id):
    return [p for p in DB.plans.values() if p["process_id"] == process_id]


def approved_plan(process_id):
    rows = [p for p in plans_of_process(process_id) if p["status"] == "APPROVED"]
    if not rows:
        return None
    rows.sort(key=lambda p: (p["updated_at"], p["created_at"], p.get("_seq", 0)),
              reverse=True)
    return rows[0]


def pin_target_bia(process_id):
    """Adoption rule: latest APPROVED BIA, else latest SUBMITTED, else None."""
    bia = approved_bia(process_id)
    if bia is None:
        bia = latest_bia(process_id, "SUBMITTED")
    return bia["id"] if bia else None


# --------------------------------------------------------------------------
# Vendor continuity score (calculations.vendor_continuity_score)
# --------------------------------------------------------------------------

def assessment_targets(assessment):
    """(required_rto, required_rpo): latest APPROVED BIA else fallback inputs."""
    bia = approved_bia(assessment["process_id"])
    if bia is not None:
        return bia["rto_target_hours"], bia["rpo_target_hours"]
    return assessment["rto_required_hours"], assessment["rpo_required_hours"]


def clamp(value, low, high):
    return max(low, min(high, value))


def assessment_provisional_score(assessment):
    req_rto, req_rpo = assessment_targets(assessment)
    rto_component = clamp(100 - max(0, assessment["assessed_rto_hours"] - req_rto) * 10,
                          0, 100)
    rpo_component = clamp(100 - max(0, assessment["assessed_rpo_hours"] - req_rpo) * 5,
                          0, 100)
    # floor(0.6*rto + 0.4*rpo) computed exactly with integers
    return (6 * rto_component + 4 * rpo_component) // 10


def assessment_compute(assessment, final=False):
    """Recompute continuity_score + meets_required_rto in place."""
    req_rto, _ = assessment_targets(assessment)
    provisional = assessment_provisional_score(assessment)
    if final and assessment["assessment_type"] == "EVENT_DRIVEN":
        score = max(0, provisional - EVENT_DRIVEN_DISCOUNT)
    else:
        score = provisional
    assessment["continuity_score"] = score
    assessment["meets_required_rto"] = assessment["assessed_rto_hours"] <= req_rto


# --------------------------------------------------------------------------
# Dependency graph / blast radius (calculations.dependency_blast_radius)
# --------------------------------------------------------------------------

def would_cycle(from_id, to_id):
    """True if adding from_id -> to_id closes a directed cycle, i.e. from_id
    is already reachable from to_id following from->to edges."""
    stack = [to_id]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur == from_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        for edge in DB.dependencies.values():
            if edge["from_process_id"] == cur:
                stack.append(edge["to_process_id"])
    return False


def blast_radius(process_id):
    """BFS from the target along from->to; discovery order by edge created_at."""
    adjacency = {}
    for edge in sorted_by_edge_created():
        adjacency.setdefault(edge["from_process_id"], []).append(edge)
    discovered = {}   # process_id -> created_at of discovery edge
    order = []
    queue = [process_id]
    visited = {process_id}
    while queue:
        cur = queue.pop(0)
        for edge in adjacency.get(cur, []):
            nxt = edge["to_process_id"]
            if nxt in visited:
                continue
            visited.add(nxt)
            discovered[nxt] = edge
            order.append(nxt)
            queue.append(nxt)
    # order already follows BFS with edges sorted by created_at; the discovery
    # edge ordering requirement is exactly this traversal order.
    return order


def sorted_by_edge_created():
    return sorted(DB.dependencies.values(),
                  key=lambda e: (e["created_at"], e.get("_seq", 0)))


# --------------------------------------------------------------------------
# Site capacity utilization (calculations.site_capacity_utilization)
# --------------------------------------------------------------------------

def site_utilization(site, probe_at):
    capacity = site["capacity_seats"]
    occupants = [
        r for r in DB.reservations.values()
        if r["site_id"] == site["id"] and r["status"] == "CONFIRMED"
        and r["starts_at"] <= probe_at < r["ends_at"]
    ]
    reserved_seats = sum(r["seats_reserved"] for r in occupants)
    pct = Decimal(0)
    for r in occupants:
        per = (Decimal(r["seats_reserved"]) / Decimal(capacity) * 100)
        pct += per.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    pct = pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return reserved_seats, float(pct)


# --------------------------------------------------------------------------
# Exercise result (calculations.exercise_result)
# --------------------------------------------------------------------------

def exercise_result(exercise, plan, outcome, ach_rto, ach_rpo):
    rto_ok = ach_rto <= plan["rto_committed_hours"]
    rpo_ok = ach_rpo <= plan["rpo_committed_hours"]
    if not (rto_ok and rpo_ok):
        return "MISSED"
    if outcome == "MET":
        return "MET"
    return outcome  # PARTIAL or MISSED as declared


# --------------------------------------------------------------------------
# Validation run result + capability cascade (calculations.validation_run_result)
# --------------------------------------------------------------------------

def capability_targets(capability):
    """(rto, rpo) targets for a capability's process, or None.

    Latest APPROVED BIA, else the APPROVED plan, else unresolvable.
    """
    process_id = capability["process_id"]
    bia = approved_bia(process_id)
    if bia is not None:
        return bia["rto_target_hours"], bia["rpo_target_hours"]
    plan = approved_plan(process_id)
    if plan is not None:
        return plan["rto_committed_hours"], plan["rpo_committed_hours"]
    return None


def run_result(measured_rto, measured_rpo, targets):
    rto, rpo = targets
    if measured_rto > rto or measured_rpo > rpo:
        return "GAP_IDENTIFIED"
    return "VALIDATED"


def create_gap(process_id, capability_id, finding_id, severity, description, due_date):
    gap = {
        "process_id": process_id,
        "capability_id": capability_id,
        "finding_id": finding_id,
        "gap_type": "FINDING" if finding_id else "CAPABILITY",
        "severity": severity,
        "description": description,
        "due_date": due_date,
        "closed_by_contact_id": None,
        "status": "OPEN",
    }
    stamp_new(gap)
    DB.gaps[gap["id"]] = gap
    return gap


def record_validation_run(capability, measured_rto, measured_rpo, method,
                          evidence_ref, exercise_id=None):
    """Create a run, supersede the prior RECORDED run, fire the cascade.

    Caller must have resolved targets already (None -> do not call).
    Returns the run.
    """
    targets = capability_targets(capability)
    result = run_result(measured_rto, measured_rpo, targets)
    run = {
        "capability_id": capability["id"],
        "exercise_id": exercise_id,
        "measured_rto_hours": measured_rto,
        "measured_rpo_hours": measured_rpo,
        "method": method,
        "evidence_ref": evidence_ref,
        "result": result,
        "gap_created_id": None,
        "status": "RECORDED",
    }
    stamp_new(run)
    DB.runs[run["id"]] = run

    # Supersede the prior RECORDED run: updated_at refresh only, no version bump.
    for other in DB.runs.values():
        if (other["capability_id"] == capability["id"] and other["id"] != run["id"]
                and other["status"] == "RECORDED"):
            other["status"] = "SUPERSEDED"
            other["updated_at"] = tick_dt()

    capability["last_validation_run_id"] = run["id"]
    if result == "VALIDATED":
        capability["status"] = "VALIDATED"
        capability["proven_rto_hours"] = measured_rto
        capability["proven_rpo_hours"] = measured_rpo
    else:
        capability["status"] = "GAP_IDENTIFIED"
        gap = create_gap(
            process_id=capability["process_id"],
            capability_id=capability["id"],
            finding_id=None,
            severity="HIGH",
            description=(f"Validation run {run['id']} identified a recovery "
                         f"gap for capability {capability['id']}"),
            due_date=now_dt() + timedelta(days=90),
        )
        run["gap_created_id"] = gap["id"]
    bump(capability)
    return run


# --------------------------------------------------------------------------
# Capability derived fields (computed on read; PRD §3.7)
# --------------------------------------------------------------------------

def capability_meets_bia(capability):
    if capability.get("proven_rto_hours") is None or capability.get("proven_rpo_hours") is None:
        return False
    bia = approved_bia(capability["process_id"])
    if bia is None:
        return False
    return (capability["proven_rto_hours"] <= bia["rto_target_hours"]
            and capability["proven_rpo_hours"] <= bia["rpo_target_hours"])


def capability_overdue_gap_exists(capability):
    now = now_dt()
    for gap in DB.gaps.values():
        if (gap.get("capability_id") == capability["id"]
                and gap["status"] in ("OPEN", "IN_PROGRESS")
                and now > gap["due_date"]):
            return True
    return False


def capability_freshness(capability):
    runs = [r for r in DB.runs.values() if r["capability_id"] == capability["id"]]
    if not runs:
        return "NEVER"
    latest_recorded = next(
        (r for r in runs if r["status"] == "RECORDED"), None)
    if latest_recorded is None:
        latest_recorded = max(runs, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    if now_dt() > add_months(latest_recorded["created_at"], FRESHNESS_MONTHS):
        return "STALE"
    if capability_overdue_gap_exists(capability):
        return "STALE"
    return "CURRENT"


def refresh_process_capability_freshness(process_id):
    """Gap-backlog aggregate refresh: recompute freshness for every capability
    of the process; bump the version of each whose label actually changes."""
    for cap in DB.capabilities.values():
        if cap["process_id"] != process_id:
            continue
        new_value = capability_freshness(cap)
        if cap.get("validation_freshness") != new_value:
            cap["validation_freshness"] = new_value
            bump(cap)


# --------------------------------------------------------------------------
# Gap backlog pressure (calculations.gap_backlog_pressure)
# --------------------------------------------------------------------------

def gap_is_overdue(gap):
    return gap["status"] in ("OPEN", "IN_PROGRESS") and now_dt() > gap["due_date"]


def gap_pressure(process_id):
    open_gaps = [g for g in DB.gaps.values()
                 if g["process_id"] == process_id
                 and g["status"] in ("OPEN", "IN_PROGRESS")]
    pressure = 0
    overdue_count = 0
    any_critical_overdue = False
    for gap in open_gaps:
        overdue = gap_is_overdue(gap)
        if overdue:
            overdue_count += 1
        w = SEVERITY_WEIGHT[gap["severity"]]
        pressure += w * (2 if overdue else 1)
        if overdue and gap["severity"] == "CRITICAL":
            any_critical_overdue = True
    if any_critical_overdue:
        pressure *= 2
    return {
        "pressure_score": pressure,
        "open_gap_count": len(open_gaps),
        "overdue_gap_count": overdue_count,
    }


# --------------------------------------------------------------------------
# Attestation readiness (calculations.attestation_readiness) — pinned order
# --------------------------------------------------------------------------

def attestation_readiness(process_id):
    now = now_dt()
    gaps = [g for g in DB.gaps.values()
            if g["process_id"] == process_id and g["status"] in ("OPEN", "IN_PROGRESS")]
    overdue = {g["id"]: now > g["due_date"] for g in gaps}

    plan_points = 40 if approved_plan(process_id) is not None else 0

    caps = [c for c in DB.capabilities.values() if c["process_id"] == process_id]
    capability_base = 0
    if caps and all(c["status"] in ("VALIDATED", "REMEDIATED") for c in caps):
        capability_base = 25
    overdue_count = sum(1 for v in overdue.values() if v)
    capability_points = max(0, capability_base - 10 * overdue_count)

    completed = [e for e in DB.exercises.values()
                 if e["process_id"] == process_id and e["status"] == "COMPLETED"]
    exercise_points = 0
    latest_exercise = None
    if completed:
        completed.sort(key=lambda e: (e["scheduled_end"], e["created_at"],
                                      e.get("_seq", 0)), reverse=True)
        latest_exercise = completed[0]
        if latest_exercise["scheduled_end"] >= now - timedelta(days=365):
            if latest_exercise.get("result") == "MET":
                exercise_points = 25
            elif latest_exercise.get("result") in ("PARTIAL", "MISSED"):
                exercise_points = 10

    subtotal = plan_points + capability_points + exercise_points
    open_count = sum(1 for g in gaps if not overdue[g["id"]])
    multiplier = Decimal("0.8") if open_count > 0 else Decimal("1.0")
    score_decimal = Decimal(subtotal) * multiplier
    if score_decimal > 100:
        score_decimal = Decimal(100)
    score = int(score_decimal)  # floor at the final step only (values >= 0)

    snapshot_inputs = {
        "plan_points": plan_points,
        "capability_points": capability_points,
        "exercise_points": exercise_points,
        "overdue_gap_count": overdue_count,
        "open_gap_count": open_count,
        "latest_exercise": latest_exercise,
    }
    return score, snapshot_inputs


def attestation_snapshot(attestation, score, inputs):
    """Immutable readiness evidence captured at signing (PRD §3.9)."""
    process_id = attestation["process_id"]
    plan = approved_plan(process_id)
    caps = [c for c in DB.capabilities.values() if c["process_id"] == process_id]
    ex = inputs.get("latest_exercise")
    return {
        "process_id": process_id,
        "readiness_score": score,
        "approved_plan_id": plan["id"] if plan else None,
        "approved_plan_version_no": plan["approved_version_no"] if plan else None,
        "capability_states": [
            {"capability_id": c["id"], "status": c["status"]}
            for c in sorted(caps, key=lambda c: (c["created_at"], c.get("_seq", 0)))
        ],
        "open_gap_count": inputs["open_gap_count"],
        "overdue_gap_count": inputs["overdue_gap_count"],
        "latest_completed_exercise_id": ex["id"] if ex else None,
        "latest_completed_exercise_result": ex.get("result") if ex else None,
        "latest_completed_exercise_scheduled_end": fmt_dt(ex["scheduled_end"]) if ex else None,
        "captured_at": fmt_dt(now_dt()),
    }


# --------------------------------------------------------------------------
# Activation fan-out helpers (PRD §3.8)
# --------------------------------------------------------------------------

def tree_nodes_in_order(tree_label):
    """Active nodes of the tree in fan-out order: BFS, siblings order_index ASC."""
    nodes = [n for n in DB.nodes.values() if n["tree_label"] == tree_label]
    active = [n for n in nodes if n["active_flag"]]
    children = {}
    for n in active:
        children.setdefault(n.get("parent_node_id"), []).append(n)
    for kids in children.values():
        kids.sort(key=lambda n: (n["order_index"], n["created_at"], n.get("_seq", 0)))
    ordered = []
    roots = children.get(None, [])
    queue = list(roots)
    seen = set(n["id"] for n in queue)
    while queue:
        cur = queue.pop(0)
        ordered.append(cur)
        for kid in children.get(cur["id"], []):
            if kid["id"] not in seen:
                seen.add(kid["id"])
                queue.append(kid)
    # Safety net: any active node unreachable from the root still fans out.
    for n in sorted(active, key=lambda n: (n["created_at"], n.get("_seq", 0))):
        if n["id"] not in seen:
            ordered.append(n)
            seen.add(n["id"])
    return ordered


def activation_coverage(activation):
    expected = activation["expected_notifications"]
    if expected == 0:
        return 0
    pct = Decimal(activation["acked_count"]) / Decimal(expected) * 100
    return int(pct.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
