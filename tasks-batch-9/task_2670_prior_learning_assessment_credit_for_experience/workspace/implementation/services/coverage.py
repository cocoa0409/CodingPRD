"""Outcome coverage arithmetic (PRD 3.4 and 3.7)."""
from db import artifacts_of_portfolio, db, outcomes_of_course, scores_of_assignment
from util import DEFAULT_MASTERY_THRESHOLD_BP, DEFAULT_PASS_THRESHOLD_BP, RUBRIC_MAX_POINTS, rhu


def score_ratio_bp(points_awarded):
    return rhu(points_awarded * 10000, RUBRIC_MAX_POINTS)


def mastery_threshold(outcome):
    value = outcome.get("mastery_threshold_bp")
    return DEFAULT_MASTERY_THRESHOLD_BP if value is None else value


def pass_threshold(program):
    if program is None:
        return DEFAULT_PASS_THRESHOLD_BP
    value = program.get("pla_pass_threshold_bp")
    return DEFAULT_PASS_THRESHOLD_BP if value is None else value


def portfolio_provisional_coverage(portfolio, course):
    """PRIMARY mapping credits an outcome fully, SUPPORTING credits it half."""
    artifacts = artifacts_of_portfolio(portfolio["id"])
    best = {}
    for artifact in artifacts:
        for mapping in artifact.get("outcome_mappings") or []:
            outcome_id = mapping.get("learning_outcome_id")
            alignment = mapping.get("alignment")
            credit = 10000 if alignment == "PRIMARY" else 5000 if alignment == "SUPPORTING" else 0
            if credit > best.get(outcome_id, 0):
                best[outcome_id] = credit
    total = 0
    for outcome in outcomes_of_course(course["id"]):
        total += outcome["weight_bp"] * best.get(outcome["id"], 0)
    return rhu(total, 10000)


def crosswalk_provisional_coverage(rule, course):
    if course["credits"] <= 0:
        return 0
    return min(10000, rhu(rule["awarded_credits"] * 10000, course["credits"]))


def assignment_verified_coverage(assignment, course):
    total = 0
    by_outcome = {}
    for score in scores_of_assignment(assignment["id"]):
        by_outcome[score["learning_outcome_id"]] = score
    for outcome in outcomes_of_course(course["id"]):
        score = by_outcome.get(outcome["id"])
        if score is None:
            continue
        total += outcome["weight_bp"] * score["score_ratio_bp"]
    return rhu(total, 10000)
