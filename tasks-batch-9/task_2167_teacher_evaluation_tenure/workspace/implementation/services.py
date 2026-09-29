"""Domain services: derived quantities, ledgers, cascades and serializers."""
from decimal import Decimal

import calc
from store import (S, D, add_days, clock_date, fmt_date, fmt_dt, new_record, now,
                   num, order_key, parse_date, round_half_up, sorted_records, touch)

COUNTED_OBS = ("SUBMITTED", "ACCEPTED")
ACTIVE_OBS = ("CONDUCTED", "SCORED", "SUBMITTED", "RETURNED", "ACCEPTED")
PENDING_OBS = ("SCHEDULED", "CONDUCTED", "SCORED", "RETURNED")
OPEN_PLAN = ("ACTIVE", "EXTENDED")


# ------------------------------------------------------------------- lookups
def policy_of_cycle(cycle):
    return S.policies.get(cycle["policy_id"])


def observations_of_cycle(cycle_id):
    return sorted_records([o for o in S.observations.values() if o["cycle_id"] == cycle_id])


def observations_of_evaluator(evaluator_id):
    return sorted_records([o for o in S.observations.values()
                           if o["evaluator_id"] == evaluator_id])


def artifacts_of_observation(observation_id):
    return sorted_records([a for a in S.artifacts.values()
                           if a["observation_id"] == observation_id])


def rubric_scores_of_observation(observation_id):
    return sorted_records([r for r in S.rubric_scores.values()
                           if r["observation_id"] == observation_id])


def growth_measures_of_cycle(cycle_id):
    return sorted_records([m for m in S.growth_measures.values() if m["cycle_id"] == cycle_id])


def plans_of_cycle(cycle_id):
    return sorted_records([p for p in S.plans.values() if p["cycle_id"] == cycle_id])


def plans_of_educator(educator_id):
    return sorted_records([p for p in S.plans.values() if p["educator_id"] == educator_id])


def cycles_of_educator(educator_id):
    return sorted_records([c for c in S.cycles.values() if c["educator_id"] == educator_id])


def calibrations_of_evaluator(evaluator_id):
    return sorted_records([r for r in S.calibrations.values()
                           if r["evaluator_id"] == evaluator_id])


def school_of_cycle(cycle):
    educator = S.educators.get(cycle["educator_id"])
    if educator is None:
        return None
    return S.schools.get(educator["school_id"])


# ------------------------------------------------------------ cycle derived
def recompute_cycle_counts(cycle):
    formal = 0
    informal = 0
    for obs in observations_of_cycle(cycle["id"]):
        if obs["status"] in COUNTED_OBS:
            if obs["observation_type"] == "FORMAL":
                formal += 1
            else:
                informal += 1
    cycle["completed_formal_count"] = formal
    cycle["completed_informal_count"] = informal


def recompute_cycle_evidence(cycle):
    total = 0
    for obs in observations_of_cycle(cycle["id"]):
        if obs["status"] != "VOIDED":
            total += int(obs["evidence_count"])
    cycle["evidence_artifact_count"] = total


def compute_observation_component(cycle, variant="PROVISIONAL"):
    policy = policy_of_cycle(cycle)
    if policy is None:
        return None
    counted = [o for o in observations_of_cycle(cycle["id"]) if o["status"] in COUNTED_OBS]
    formals = [o for o in counted if o["observation_type"] == "FORMAL"]
    informals = [o for o in counted if o["observation_type"] == "INFORMAL"]
    taken_formals = formals[:int(policy["required_formal_count"])]
    taken_informals = informals[:int(policy["required_informal_count"])]
    formal_scores = [o["weighted_score"] for o in taken_formals if o["weighted_score"] is not None]
    informal_scores = [o["weighted_score"] for o in taken_informals
                       if o["weighted_score"] is not None]
    return calc.observation_component(formal_scores, informal_scores, policy, variant)


def recompute_observation_component(cycle, variant="PROVISIONAL"):
    cycle["observation_component"] = compute_observation_component(cycle, variant)
    return cycle["observation_component"]


def compute_growth_component(cycle):
    certified = [m for m in growth_measures_of_cycle(cycle["id"]) if m["status"] == "CERTIFIED"]
    return calc.growth_component(certified)


def recompute_growth_component(cycle):
    cycle["growth_component"] = compute_growth_component(cycle)
    return cycle["growth_component"]


def cycle_has_active_observation(cycle_id):
    for obs in observations_of_cycle(cycle_id):
        if obs["status"] in ACTIVE_OBS:
            return True
    return False


def maybe_bubble_down(cycle):
    """SCORING -> SCHEDULING when no observation remains in the active set."""
    if cycle["status"] != "SCORING":
        return False
    if cycle_has_active_observation(cycle["id"]):
        return False
    cycle["status"] = "SCHEDULING"
    if cycle["completed_formal_count"] == 0 and cycle["completed_informal_count"] == 0:
        cycle["observation_component"] = None
    touch(cycle)
    return True


# ----------------------------------------------------------- stipend ledger
def commit_stipend(cycle, amount):
    school = school_of_cycle(cycle)
    if school is None:
        return
    school["evaluation_budget_committed_cents"] += int(amount)
    touch(school)


def release_stipend(cycle, amount):
    school = school_of_cycle(cycle)
    if school is None:
        return
    school["evaluation_budget_committed_cents"] -= int(amount)
    touch(school)


# --------------------------------------------------------- educator derived
def educator_history(educator_id):
    history = [c for c in S.cycles.values()
               if c["educator_id"] == educator_id and c["status"] in ("FINALIZED", "CLOSED")]
    return sorted(history, key=lambda c: (c["school_year"], c["created_at"], c["_seq"]))


def consecutive_effective_years(educator_id):
    run = 0
    for cycle in reversed(educator_history(educator_id)):
        if cycle["composite_rating"] in ("EFFECTIVE", "HIGHLY_EFFECTIVE"):
            run += 1
        else:
            break
    return run


def latest_rating(educator_id):
    history = educator_history(educator_id)
    if not history:
        return None
    return history[-1]["composite_rating"]


def tenure_track_hold(educator):
    if educator["tenure_status"] == "NON_RENEWED":
        return False
    for plan in plans_of_educator(educator["id"]):
        if plan["status"] in OPEN_PLAN:
            return True
    return False


def completed_service_years(educator):
    start = parse_date(educator["service_start_date"])
    if start is None:
        return 0
    return calc.service_years(start, clock_date())


def recompute_educator_rating(educator):
    """Refresh the stored last_composite_rating (PRD 3.9)."""
    if educator is None:
        return
    new_rating = latest_rating(educator["id"])
    if educator.get("last_composite_rating") != new_rating:
        educator["last_composite_rating"] = new_rating
        touch(educator)


def policy_for_educator(educator_id):
    cycles = sorted([c for c in S.cycles.values() if c["educator_id"] == educator_id],
                    key=lambda c: (c["school_year"], c["created_at"], c["_seq"]))
    if not cycles:
        return None
    return S.policies.get(cycles[-1]["policy_id"])


# ----------------------------------------------------------------- cascades
def void_open_plans_of_cycle(cycle):
    """Appeal MODIFIED / REMANDED and sustained grievance cascades."""
    touched = False
    for plan in plans_of_cycle(cycle["id"]):
        if plan["status"] in OPEN_PLAN:
            plan["status"] = "VOIDED"
            touch(plan)
            touched = True
    if touched:
        educator = S.educators.get(cycle["educator_id"])
        recompute_educator_rating(educator)
    return touched


def revert_cycle_to_scoring(cycle):
    """FINALIZED -> SCORING reversion (appeal REMANDED / grievance RATING_VACATED)."""
    cycle["status"] = "SCORING"
    cycle["composite_score"] = None
    cycle["composite_rating"] = None
    cycle["composite_variant"] = None
    cycle["evidence_adjustment"] = Decimal("0.00")
    cycle["finalized_at"] = None
    cycle["appeal_deadline"] = None
    void_open_plans_of_cycle(cycle)
    recompute_educator_rating(S.educators.get(cycle["educator_id"]))


def create_improvement_plan(cycle, educator_id, trigger_reason, escalation_level, prior_plan_id):
    policy = policy_of_cycle(cycle)
    started = now()
    remediation_days = int(policy["remediation_days"]) if policy else 90
    plan = new_record(
        cycle_id=cycle["id"],
        educator_id=educator_id,
        prior_plan_id=prior_plan_id,
        status="ACTIVE",
        trigger_reason=trigger_reason,
        started_at=started,
        due_at=add_days(started, remediation_days),
        extension_days_used=0,
        escalation_level=escalation_level,
    )
    S.plans[plan["id"]] = plan
    return plan


def suspend_evaluator_cascade(evaluator):
    """Every SCHEDULED/CONDUCTED/SCORED/RETURNED observation of the evaluator voids."""
    for obs in observations_of_evaluator(evaluator["id"]):
        if obs["status"] not in ("SCHEDULED", "CONDUCTED", "SCORED", "RETURNED"):
            continue
        obs["status"] = "VOIDED"
        obs["void_reason"] = "EVALUATOR_SUSPENDED"
        touch(obs)
        cycle = S.cycles.get(obs["cycle_id"])
        if cycle is None:
            continue
        recompute_cycle_evidence(cycle)
        maybe_bubble_down(cycle)


# -------------------------------------------------------------- serializers
POLICY_FIELDS = (
    "school_year", "observation_weight_pct", "growth_weight_pct", "planning_weight_pct",
    "environment_weight_pct", "instruction_weight_pct", "professionalism_weight_pct",
    "required_formal_count", "required_informal_count", "unannounced_multiplier",
    "informal_cap", "highly_effective_threshold", "effective_threshold",
    "developing_threshold", "evidence_min_artifacts", "remediation_days",
    "max_plan_extension_days", "appeal_window_days", "tenure_required_years",
    "tenure_min_consecutive_effective", "min_days_between_formals",
    "calibration_drift_tolerance", "calibration_max_consecutive_failures",
    "observation_stipend_cents",
)


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_policy(rec):
    out = _common(rec)
    for field in POLICY_FIELDS:
        out[field] = num(rec[field])
    return out


def ser_school(rec):
    out = _common(rec)
    allocated = int(rec["evaluation_budget_allocated_cents"])
    committed = int(rec["evaluation_budget_committed_cents"])
    out.update({
        "name": rec["name"],
        "code": rec["code"],
        "level": rec["level"],
        "evaluation_budget_allocated_cents": allocated,
        "evaluation_budget_committed_cents": committed,
        "evaluation_budget_remaining_cents": allocated - committed,
    })
    return out


def ser_educator(rec):
    out = _common(rec)
    out.update({
        "school_id": rec["school_id"],
        "employee_number": rec["employee_number"],
        "full_name": rec["full_name"],
        "service_start_date": rec["service_start_date"],
        "tenure_status": rec["tenure_status"],
        "completed_service_years": completed_service_years(rec),
        "consecutive_effective_years": consecutive_effective_years(rec["id"]),
        "tenure_track_hold": tenure_track_hold(rec),
        "last_composite_rating": rec["last_composite_rating"],
        "tenure_recommended_by_user_id": rec["tenure_recommended_by_user_id"],
    })
    return out


def ser_evaluator(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "certification_status": rec["certification_status"],
        "certification_expires_on": rec["certification_expires_on"],
        "consecutive_failed_calibrations": rec["consecutive_failed_calibrations"],
        "passed_calibration_count": rec["passed_calibration_count"],
        "calibration_drift_rolling": num(rec["calibration_drift_rolling"]),
        "calibration_drift_anchor": num(rec["calibration_drift_anchor"]),
    })
    return out


def ser_cycle(rec):
    out = _common(rec)
    out.update({
        "educator_id": rec["educator_id"],
        "policy_id": rec["policy_id"],
        "school_year": rec["school_year"],
        "cycle_type": rec["cycle_type"],
        "status": rec["status"],
        "dispute_state": rec["dispute_state"],
        "completed_formal_count": rec["completed_formal_count"],
        "completed_informal_count": rec["completed_informal_count"],
        "evidence_artifact_count": rec["evidence_artifact_count"],
        "observation_component": num(rec["observation_component"]),
        "growth_component": num(rec["growth_component"]),
        "evidence_adjustment": num(rec["evidence_adjustment"]),
        "composite_score": num(rec["composite_score"]),
        "composite_rating": rec["composite_rating"],
        "composite_variant": rec["composite_variant"],
        "finalized_at": fmt_dt(rec["finalized_at"]),
        "appeal_deadline": fmt_dt(rec["appeal_deadline"]),
    })
    return out


def ser_observation(rec):
    out = _common(rec)
    out.update({
        "cycle_id": rec["cycle_id"],
        "evaluator_id": rec["evaluator_id"],
        "observation_type": rec["observation_type"],
        "announced": rec["announced"],
        "scheduled_start": fmt_dt(rec["scheduled_start"]),
        "scheduled_end": fmt_dt(rec["scheduled_end"]),
        "status": rec["status"],
        "scored_domain_count": rec["scored_domain_count"],
        "weighted_score": num(rec["weighted_score"]),
        "evidence_count": rec["evidence_count"],
        "stipend_cents": rec["stipend_cents"],
        "return_count": rec["return_count"],
        "return_reason": rec["return_reason"],
        "void_reason": rec["void_reason"],
    })
    return out


def ser_rubric_score(rec):
    out = _common(rec)
    out.update({
        "observation_id": rec["observation_id"],
        "domain_code": rec["domain_code"],
        "raw_score": rec["raw_score"],
        "weighted_contribution": num(rec["weighted_contribution"]),
        "superseded": rec["superseded"],
        "observation_version_after": rec["observation_version_after"],
        "scored_domain_count": rec["scored_domain_count"],
    })
    return out


def ser_artifact(rec):
    out = _common(rec)
    out.update({
        "observation_id": rec["observation_id"],
        "artifact_type": rec["artifact_type"],
        "title": rec["title"],
        "status": rec["status"],
        "submitted_by_role": rec["submitted_by_role"],
    })
    return out


def ser_growth_measure(rec):
    out = _common(rec)
    out.update({
        "cycle_id": rec["cycle_id"],
        "measure_code": rec["measure_code"],
        "index_value": num(rec["index_value"]),
        "coverage_pct": num(rec["coverage_pct"]),
        "status": rec["status"],
        "cycle_version_after": rec["cycle_version_after"],
    })
    return out


def ser_plan(rec):
    out = _common(rec)
    out.update({
        "cycle_id": rec["cycle_id"],
        "educator_id": rec["educator_id"],
        "prior_plan_id": rec["prior_plan_id"],
        "status": rec["status"],
        "trigger_reason": rec["trigger_reason"],
        "started_at": fmt_dt(rec["started_at"]),
        "due_at": fmt_dt(rec["due_at"]),
        "extension_days_used": rec["extension_days_used"],
        "escalation_level": rec["escalation_level"],
    })
    return out


def ser_appeal(rec):
    out = _common(rec)
    out.update({
        "cycle_id": rec["cycle_id"],
        "educator_id": rec["educator_id"],
        "grounds": rec["grounds"],
        "statement": rec["statement"],
        "status": rec["status"],
        "panelist_evaluator_id": rec["panelist_evaluator_id"],
        "adjusted_composite": num(rec["adjusted_composite"]),
        "decided_at": fmt_dt(rec["decided_at"]),
    })
    return out


def ser_grievance(rec):
    out = _common(rec)
    out.update({
        "appeal_id": rec["appeal_id"],
        "educator_id": rec["educator_id"],
        "article_code": rec["article_code"],
        "status": rec["status"],
        "remedy": rec["remedy"],
    })
    return out


def ser_calibration(rec):
    out = _common(rec)
    out.update({
        "evaluator_id": rec["evaluator_id"],
        "anchor_lesson_code": rec["anchor_lesson_code"],
        "anchor_score": num(rec["anchor_score"]),
        "evaluator_score": num(rec["evaluator_score"]),
        "deviation": num(rec["deviation"]),
        "outcome": rec["outcome"],
        "sequence_index": rec["sequence_index"],
    })
    return out
