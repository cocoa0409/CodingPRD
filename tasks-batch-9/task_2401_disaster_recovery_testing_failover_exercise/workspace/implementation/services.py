"""Derived-field calculations, posture derivation and the three cascades.

Every formula here traces to a named entry in SCAFFOLD.yaml `calculations` and to
the corresponding prose in PRD.md section 3.
"""

import math
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    CAPACITY_BY_TYPE,
    CAPACITY_WEIGHT,
    DECAY_HORIZON_DAYS,
    ESCALATION_FAILURE_THRESHOLD,
    FINDING_NON_TERMINAL,
    LEVEL_2_FLOOR,
    LEVEL_3_FLOOR,
    MANIFEST_HEADER_LINES,
    READINESS_FLOOR_FOR_SCOPING,
    RESERVING_EXECUTION_STATES,
    SURCHARGE_BY_LEVEL,
    TYPE_BASE,
)
from db import db, now, sort_key, touch

ZERO = Decimal("0.00")


def round2(value):
    """round_half_up to two decimal places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# small collection helpers
# --------------------------------------------------------------------------- #

def steps_of(runbook_id):
    return [s for s in db.runbook_steps.values() if s["runbook_id"] == runbook_id]


def runbooks_of(group_id):
    return [r for r in db.runbooks.values() if r["recovery_group_id"] == group_id]


def scope_items_of(exercise_id):
    return [i for i in db.scope_items.values() if i["exercise_id"] == exercise_id]


def step_executions_of(exercise_id):
    return [x for x in db.step_executions.values() if x["exercise_id"] == exercise_id]


def findings_of_group(group_id):
    return [f for f in db.findings.values() if f["recovery_group_id"] == group_id]


def in_scope_group_ids(exercise):
    return {item["recovery_group_id"] for item in scope_items_of(exercise["id"])}


def exercises_scoping_group(group_id):
    ids = {i["exercise_id"] for i in db.scope_items.values()
           if i["recovery_group_id"] == group_id}
    return [db.exercises[i] for i in ids if i in db.exercises]


# --------------------------------------------------------------------------- #
# calculations.runbook_readiness_score
# --------------------------------------------------------------------------- #

def compute_readiness_score(runbook):
    steps = steps_of(runbook["id"])
    total_weight = sum(s["weight"] for s in steps)
    if total_weight == 0:
        return ZERO
    current = now()
    accumulated = ZERO
    for step in sorted(steps, key=sort_key):
        if step["validation_status"] == "VALIDATED" and step["last_validated_at"]:
            elapsed = (current - step["last_validated_at"]).total_seconds()
            age_days = math.floor(elapsed / 86400.0)
            step_score = round2(
                Decimal(100) * (Decimal(1) - Decimal(age_days) / Decimal(DECAY_HORIZON_DAYS))
            )
            if step_score < ZERO:
                step_score = ZERO
        else:
            step_score = ZERO
        # PINNED ROUNDING ORDER: round each contribution first, then sum.
        accumulated += round2(step_score * Decimal(step["weight"]) / Decimal(total_weight))
    return accumulated


def refresh_readiness_score(runbook):
    if runbook is None:
        return None
    fresh = compute_readiness_score(runbook)
    if runbook["readiness_score"] != fresh:
        runbook["readiness_score"] = fresh
        touch(runbook)
    return fresh


# --------------------------------------------------------------------------- #
# calculations.recovery_group_open_finding_count
# --------------------------------------------------------------------------- #

def refresh_open_finding_count(group):
    count = sum(
        1 for f in findings_of_group(group["id"])
        if f["state"] in FINDING_NON_TERMINAL
    )
    if group["open_finding_count"] != count:
        group["open_finding_count"] = count
        touch(group)
    return count


# --------------------------------------------------------------------------- #
# calculations.projected_recovery_minutes_critical_path
# --------------------------------------------------------------------------- #

def refresh_projection(group):
    weights = {}
    keys = {}
    for app in db.applications.values():
        if app["recovery_group_id"] == group["id"]:
            weights[app["id"]] = app["rto_minutes"] if app["rto_minutes"] is not None else 0
            keys[app["id"]] = sort_key(app)
    for asset in db.assets.values():
        if asset["recovery_group_id"] == group["id"]:
            weights[asset["id"]] = asset["restore_minutes"]
            keys[asset["id"]] = sort_key(asset)

    adjacency = defaultdict(list)
    for edge in db.dependency_edges.values():
        if edge["edge_kind"] != "HARD":
            continue  # SOFT edges contribute exactly zero to any projection
        if edge["from_node_id"] in weights and edge["to_node_id"] in weights:
            adjacency[edge["from_node_id"]].append(edge["to_node_id"])

    best = None  # (total, tie_key_tuple, path)

    def candidate_better(cand, incumbent):
        if incumbent is None:
            return True
        if cand[0] != incumbent[0]:
            return cand[0] > incumbent[0]
        return cand[1] < incumbent[1]

    def walk(path, total):
        nonlocal best
        cand = (total, tuple(keys[n] for n in path), list(path))
        if candidate_better(cand, best):
            best = cand
        for nxt in sorted(adjacency[path[-1]], key=lambda n: keys[n]):
            if nxt in path:
                continue
            path.append(nxt)
            walk(path, total + weights[nxt])
            path.pop()

    for node_id in sorted(weights, key=lambda n: keys[n]):
        walk([node_id], weights[node_id])

    projected = best[0] if best else 0
    sequence = list(best[2]) if best else []

    changed = False
    if group["projected_recovery_minutes"] != projected:
        group["projected_recovery_minutes"] = projected
        changed = True
    if group["recovery_sequence"] != sequence:
        group["recovery_sequence"] = sequence
        changed = True
    if changed:
        touch(group)
    return projected


def groups_containing_both(node_a_id, node_b_id):
    """Recovery groups whose membership contains both endpoints of an edge."""
    group_of = {}
    for app in db.applications.values():
        group_of[app["id"]] = app["recovery_group_id"]
    for asset in db.assets.values():
        group_of[asset["id"]] = asset["recovery_group_id"]
    ga = group_of.get(node_a_id)
    gb = group_of.get(node_b_id)
    if ga and gb and ga == gb and ga in db.recovery_groups:
        return [db.recovery_groups[ga]]
    return []


# --------------------------------------------------------------------------- #
# calculations.site_reserved_capacity_units  (full recompute, never a delta)
# --------------------------------------------------------------------------- #

def refresh_site_reserved(site):
    if site is None:
        return
    total = sum(
        ex["required_capacity_units"] for ex in db.exercises.values()
        if ex["recovery_site_id"] == site["id"]
        and ex["execution_state"] in RESERVING_EXECUTION_STATES
    )
    if site["reserved_capacity_units"] != total:
        site["reserved_capacity_units"] = total
        touch(site)


def refresh_site_reserved_for(exercise):
    refresh_site_reserved(db.sites.get(exercise["recovery_site_id"]))


# --------------------------------------------------------------------------- #
# calculations.exercise_required_capacity_units
# --------------------------------------------------------------------------- #

def refresh_required_capacity(exercise):
    total = sum(i["capacity_units_contributed"] for i in scope_items_of(exercise["id"]))
    if exercise["required_capacity_units"] != total:
        exercise["required_capacity_units"] = total
        touch(exercise)
    return total


def capacity_units_for(exercise):
    return CAPACITY_BY_TYPE[exercise["exercise_type"]]


# --------------------------------------------------------------------------- #
# calculations.recovery_group_posture_derivation  (+ cascade fan-out)
# --------------------------------------------------------------------------- #

def derive_posture(group):
    escalated_open = any(
        f["escalated"] and f["state"] not in ("CLOSED", "WITHDRAWN")
        for f in findings_of_group(group["id"])
    )
    if escalated_open:
        return "FROZEN", "OPEN_CRITICAL_FINDING"
    if group["current_runbook_id"] is None:
        return "RESTRICTED", "NO_VALIDATED_RUNBOOK"
    runbook = db.runbooks.get(group["current_runbook_id"])
    if (runbook is None
            or runbook["status"] != "VALIDATED"
            or runbook["readiness_score"] < READINESS_FLOOR_FOR_SCOPING):
        return "RESTRICTED", "RUNBOOK_STALE"
    return "READY", "READY_ALL_CHECKS_PASSED"


def apply_posture(group):
    """Re-derive posture/posture_reason and fan out cascade A hop 5 / B hop 4-5."""
    previous = group["posture"]
    posture, reason = derive_posture(group)
    if group["posture"] != posture or group["posture_reason"] != reason:
        group["posture"] = posture
        group["posture_reason"] = reason
        touch(group)

    if posture == "FROZEN" and previous != "FROZEN":
        _cascade_freeze_exercises(group)
    elif previous == "READY" and posture != "READY":
        _revert_scheduled_exercises(group)
    return posture


def _revert_scheduled_exercises(group):
    """Cascade A hop 5 + hop 6."""
    for exercise in exercises_scoping_group(group["id"]):
        if exercise["execution_state"] == "SCHEDULED":
            exercise["execution_state"] = "SCOPED"
            exercise["closure_reason"] = "NONE"
            touch(exercise)
            refresh_site_reserved_for(exercise)


def _cascade_freeze_exercises(group):
    """Cascade B hop 4 + hop 5."""
    cancellable = ("SCOPED", "PENDING_IMPACT_APPROVAL", "APPROVED", "SCHEDULED")
    for exercise in exercises_scoping_group(group["id"]):
        if exercise["execution_state"] in cancellable:
            exercise["execution_state"] = "CANCELLED"
            exercise["closure_reason"] = "CANCELLED_GROUP_FROZEN"
            touch(exercise)
            # Full recompute for every cancelled exercise's site.  Only the
            # SCHEDULED source state actually held a reservation, so the others
            # leave the site's figure unchanged.
            refresh_site_reserved_for(exercise)


# --------------------------------------------------------------------------- #
# cascades A and C -- step invalidation driven staleness
# --------------------------------------------------------------------------- #

def invalidate_steps_and_stale_runbooks(step_predicate, stale_reason):
    """Hops 2-4 shared by cascade A (re-tier) and cascade C (owner suspended)."""
    affected_runbook_ids = set()
    for step in db.runbook_steps.values():
        if step["validation_status"] == "VALIDATED" and step_predicate(step):
            step["validation_status"] = "INVALIDATED"
            touch(step)
            affected_runbook_ids.add(step["runbook_id"])

    staled_group_ids = []
    for runbook_id in sorted(
        affected_runbook_ids,
        key=lambda rid: sort_key(db.runbooks[rid]) if rid in db.runbooks else (0, 0),
    ):
        runbook = db.runbooks.get(runbook_id)
        if runbook is None:
            continue
        if runbook["status"] == "VALIDATED":
            runbook["status"] = "STALE"
            runbook["stale_reason"] = stale_reason
            touch(runbook)
            refresh_readiness_score(runbook)
            staled_group_ids.append(runbook["recovery_group_id"])

    seen = set()
    for group_id in staled_group_ids:
        if group_id in seen:
            continue
        seen.add(group_id)
        group = db.recovery_groups.get(group_id)
        if group is not None:
            apply_posture(group)


def cascade_application_retiered(application):
    invalidate_steps_and_stale_runbooks(
        lambda step: step["covers_application_id"] == application["id"],
        "APPLICATION_RETIERED",
    )


def cascade_owner_suspended(stakeholder):
    invalidate_steps_and_stale_runbooks(
        lambda step: step["owner_id"] == stakeholder["id"],
        "STEP_OWNER_SUSPENDED",
    )


# --------------------------------------------------------------------------- #
# calculations.production_impact_score_with_governance_surcharge
# --------------------------------------------------------------------------- #

def level_of(score):
    if score >= LEVEL_3_FLOOR:
        return "LEVEL_3"
    if score >= LEVEL_2_FLOOR:
        return "LEVEL_2"
    return "LEVEL_1"


def compute_impact(exercise):
    group_ids = in_scope_group_ids(exercise)
    criticality = sum(
        app["criticality_weight"] for app in db.applications.values()
        if app["tier_agreement_status"] == "AGREED"
        and app["recovery_group_id"] in group_ids
    )
    site = db.sites.get(exercise["recovery_site_id"])
    usable = site["usable_capacity_units"] if site else 0
    if usable and usable > 0:
        capacity_component = round2(
            CAPACITY_WEIGHT * Decimal(exercise["required_capacity_units"]) / Decimal(usable)
        )
    else:
        capacity_component = ZERO

    provisional = round2(
        Decimal(TYPE_BASE[exercise["exercise_type"]])
        + Decimal(criticality)
        + capacity_component
    )
    # STEP 3 -- the surcharge is keyed on the PROVISIONAL band, and the band is
    # never re-derived a second time to grow the surcharge.
    surcharge = SURCHARGE_BY_LEVEL[level_of(provisional)]
    final = round2(provisional + Decimal(surcharge))
    # STEP 5 -- required_approval_level derived exactly once, from the FINAL score.
    return provisional, final, level_of(final)


# --------------------------------------------------------------------------- #
# calculations.exercise_objectives_baseline
# --------------------------------------------------------------------------- #

def baseline_applications(exercise):
    group_ids = in_scope_group_ids(exercise)
    return [
        app for app in db.applications.values()
        if app["tier_agreement_status"] == "AGREED"
        and app["recovery_group_id"] in group_ids
    ]


# --------------------------------------------------------------------------- #
# calculations.achieved_rto_minutes
# --------------------------------------------------------------------------- #

def compute_achieved_rto(exercise):
    if exercise["exercise_type"] == "FULL_SITE_FAILOVER":
        delta = (exercise["failover_completed_at"]
                 - exercise["execution_started_at"]).total_seconds()
        return int(math.ceil(delta / 60.0))
    return sum(
        x["elapsed_minutes"] for x in step_executions_of(exercise["id"])
        if x["outcome"] in ("PASSED", "PASSED_WITH_ISSUE", "FAILED")
    )


# --------------------------------------------------------------------------- #
# calculations.achieved_rpo_minutes
# --------------------------------------------------------------------------- #

def in_scope_data_stores(exercise):
    group_ids = in_scope_group_ids(exercise)
    return [
        asset for asset in db.assets.values()
        if asset["asset_kind"] == "DATA_STORE"
        and asset["recovery_group_id"] in group_ids
    ]


def latest_observation(asset_id, at_or_before):
    rows = [
        o for o in db.observations.values()
        if o["asset_id"] == asset_id and o["observed_at"] <= at_or_before
    ]
    if not rows:
        return None
    return max(rows, key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))


def compute_achieved_rpo(exercise):
    stores = in_scope_data_stores(exercise)
    cutoff = exercise["failover_completed_at"]
    uses_transaction_gap = any(s["replication_mode"] == "BATCH_SNAPSHOT" for s in stores)

    values = []
    for asset in stores:
        observation = latest_observation(asset["id"], cutoff)
        if observation is None:
            continue
        if uses_transaction_gap:
            rate = asset["expected_txn_rate_per_minute"]
            if not rate or rate <= 0:
                continue  # skipped entirely rather than dividing by zero
            values.append(int(math.ceil(observation["unreplicated_txn_count"] / float(rate))))
        else:
            values.append(int(math.ceil(observation["replication_lag_seconds"] / 60.0)))
    if not values:
        return 0
    return max(values)


# --------------------------------------------------------------------------- #
# calculations.finding_retest_escalation
# --------------------------------------------------------------------------- #

def apply_retest_failure(finding):
    finding["retest_failure_count"] = finding["retest_failure_count"] + 1
    if (finding["retest_failure_count"] >= ESCALATION_FAILURE_THRESHOLD
            and finding["severity"] == "CRITICAL"):
        finding["escalated"] = True


# --------------------------------------------------------------------------- #
# calculations.evidence_manifest_line_count
# --------------------------------------------------------------------------- #

def compute_manifest_line_count(package):
    exercise_id = package["exercise_id"]
    scope_count = len(scope_items_of(exercise_id))
    step_count = len(step_executions_of(exercise_id))
    finding_count = sum(
        1 for f in db.findings.values()
        if f["exercise_id"] == exercise_id and f["state"] != "WITHDRAWN"
    )
    return MANIFEST_HEADER_LINES + scope_count + step_count + finding_count


# --------------------------------------------------------------------------- #
# HARD-edge cycle detection
# --------------------------------------------------------------------------- #

def hard_edge_creates_cycle(from_node_id, to_node_id):
    """True when adding from->to closes a directed cycle among HARD edges."""
    if from_node_id == to_node_id:
        return True
    adjacency = defaultdict(list)
    for edge in db.dependency_edges.values():
        if edge["edge_kind"] == "HARD":
            adjacency[edge["from_node_id"]].append(edge["to_node_id"])
    # a cycle appears iff `to_node_id` can already reach `from_node_id`
    stack = [to_node_id]
    seen = set()
    while stack:
        node = stack.pop()
        if node == from_node_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, ()))
    return False


# --------------------------------------------------------------------------- #
# window helpers
# --------------------------------------------------------------------------- #

def half_open_intersects_closed(start, end, closed_start, closed_end):
    """[start, end) meets [closed_start, closed_end] ?

    The freeze interval is closed on both ends while the exercise window is
    half-open, and an exercise that merely touches a freeze endpoint DOES
    conflict -- so the exercise window's own end instant counts as touching.
    """
    if closed_start is None or closed_end is None:
        return False
    return start <= closed_end and closed_start <= end


def half_open_intersects(a_start, a_end, b_start, b_end):
    """[a_start, a_end) intersects [b_start, b_end) ?"""
    return a_start < b_end and b_start < a_end
