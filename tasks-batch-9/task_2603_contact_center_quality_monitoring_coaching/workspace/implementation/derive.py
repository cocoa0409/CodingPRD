"""Recompute helpers.

Every helper writes the derived fields of one row and bumps `version` /
`updated_at` only when at least one stored field actually changed (PRD 2.4,
2.10).
"""
import calc
from common import get, rows, touch


def apply_changes(row, updates):
    """Write `updates` onto `row`; bump version/updated_at when something moved."""
    changed = False
    for key, value in updates.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def force(row, updates):
    """Write `updates` and bump version/updated_at unconditionally."""
    row.update(updates)
    touch(row)


# --- Evaluator ------------------------------------------------------------

def recompute_evaluator(evaluator_id):
    evaluator = get("evaluators", evaluator_id)
    if evaluator is None:
        return None
    apply_changes(evaluator, {
        "open_assignment_count": calc.open_assignment_count(evaluator_id),
        "last_deviation_pct": calc.last_deviation_pct(evaluator_id),
    })
    return evaluator


# --- Interaction ----------------------------------------------------------

def recompute_interaction_sampled(interaction_id):
    interaction = get("interactions", interaction_id)
    if interaction is None:
        return None
    apply_changes(interaction, {
        "sampled_count": calc.interaction_sampled_count(interaction_id),
    })
    return interaction


# --- SamplePlan -----------------------------------------------------------

def recompute_plan(plan):
    if plan is None:
        return None
    apply_changes(plan, calc.sample_quota_attainment(plan))
    return plan


def recompute_plan_by_id(plan_id):
    return recompute_plan(get("plans", plan_id))


# --- Agent ----------------------------------------------------------------

def recompute_agent_indices(agent_id):
    agent = get("agents", agent_id)
    if agent is None:
        return None
    apply_changes(agent, {
        "quality_index_rolling": calc.quality_index_rolling(agent_id),
        "quality_index_period": calc.quality_index_period(agent_id),
    })
    return agent


def recompute_agent_streak(agent_id):
    agent = get("agents", agent_id)
    if agent is None:
        return None
    apply_changes(agent, {
        "consecutive_passing_evaluations": calc.consecutive_passing_evaluations(agent_id),
    })
    return agent


def recompute_agent_findings(agent_id):
    agent = get("agents", agent_id)
    if agent is None:
        return None
    apply_changes(agent, {
        "open_compliance_findings": calc.open_compliance_findings(agent_id),
    })
    return agent


def selection_has_evaluation(selection_id):
    return any(ev["selection_id"] == selection_id for ev in rows("evaluations"))
