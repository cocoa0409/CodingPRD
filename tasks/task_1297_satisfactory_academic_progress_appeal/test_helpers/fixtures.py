"""Composite setup helpers.

Every helper builds its world through the public API only. The server is
restarted with an empty database before each test, so helpers never assume any
pre-existing row and every test re-creates whatever it needs. Setup calls use
the lenient `get_success_data` validator so a setup failure surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import FAILING_HALF_TERM, STANDARD_TERMS
from .factories import (
    amend_payload, appeal_payload, checkpoint_payload, decide_payload,
    document_payload, enrollment_payload, plan_payload, post_grades_payload,
    program_payload, student_payload, term_payload,
)
from .test_users import (
    AID_ADMIN, AID_OFFICER, AUDITOR, COMMITTEE, REGISTRAR, make_student_headers,
)


# ==========================================================================
# Tier 0 -- single-call primitives
# ==========================================================================

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, AID_ADMIN))


def create_program(**overrides) -> dict:
    return get_success_data(api_client.create_program(program_payload(**overrides), REGISTRAR))


def create_term(seq: int, start_date: str = None, end_date: str = None, **overrides) -> dict:
    """Create one term. Defaults come from the standard academic calendar."""
    std = next(t for t in STANDARD_TERMS if t["seq"] == seq)
    payload = term_payload(
        seq,
        start_date or std["start_date"],
        end_date or std["end_date"],
        **overrides,
    )
    return get_success_data(api_client.create_term(payload, REGISTRAR))


def create_standard_terms(count: int = 5) -> dict:
    """Create the first `count` standard terms. Returns {seq: term}."""
    return {seq: create_term(seq) for seq in range(1, count + 1)}


def create_student(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_student(student_payload(program_id, **overrides), REGISTRAR))


def create_enrollment(student_id: str, term_id: str, attempted_credits: int) -> dict:
    return get_success_data(api_client.create_enrollment(
        enrollment_payload(student_id, term_id, attempted_credits), REGISTRAR))


def post_grades(enrollment_id: str, earned_credits: int, quality_points: float,
                gpa_hours: int) -> dict:
    return get_success_data(api_client.post_enrollment(
        enrollment_id, post_grades_payload(earned_credits, quality_points, gpa_hours),
        REGISTRAR))


def amend_grades(enrollment_id: str, earned_credits: int, quality_points: float,
                 gpa_hours: int, amendment_reason: str = "Grade correction") -> dict:
    return get_success_data(api_client.amend_enrollment(
        enrollment_id,
        amend_payload(earned_credits, quality_points, gpa_hours, amendment_reason),
        REGISTRAR))


def close_grading(term_id: str) -> dict:
    return get_success_data(api_client.close_grading(term_id, REGISTRAR))


def evaluate_term(term_id: str) -> dict:
    return get_success_data(api_client.evaluate_term(term_id, AID_OFFICER))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, AID_OFFICER))


def student_version(student_id: str) -> int:
    return get_student(student_id)["version"]


def list_evaluations(params: dict) -> list:
    data, _meta = validate_paginated(api_client.list_evaluations(
        AID_OFFICER, params={"limit": 100, **params}))
    return data


def official_evaluation(student_id: str, term_id: str) -> dict:
    """The single OFFICIAL evaluation row for (student, term)."""
    rows = list_evaluations(
        {"student_id": student_id, "term_id": term_id, "status": "OFFICIAL"})
    assert len(rows) == 1, f"expected exactly one OFFICIAL evaluation, got {len(rows)}"
    return rows[0]


def list_notifications(params: dict) -> list:
    data, _meta = validate_paginated(api_client.list_notifications(
        AID_OFFICER, params={"limit": 100, **params}))
    return data


def list_audit_events(params: dict) -> list:
    data, _meta = validate_paginated(api_client.list_audit_events(
        AUDITOR, params={"limit": 100, **params}))
    return data


def dispatch_notifications() -> dict:
    return get_success_data(api_client.dispatch_notifications(AID_OFFICER))


# ==========================================================================
# Tier 1 -- enrollment lifecycle shortcuts
# ==========================================================================

def create_posted_enrollment(student_id: str, term_id: str, attempted_credits: int,
                             earned_credits: int, quality_points: float,
                             gpa_hours: int) -> dict:
    """Create an enrollment and post its grades. Returns the POSTED row."""
    enrollment = create_enrollment(student_id, term_id, attempted_credits)
    return post_grades(enrollment["id"], earned_credits, quality_points, gpa_hours)


def close_and_evaluate(term_id: str) -> dict:
    """Close grading then run the evaluation pipeline. Returns the summary."""
    close_grading(term_id)
    return evaluate_term(term_id)


# ==========================================================================
# Tier 2 -- standing worlds
# ==========================================================================

def setup_warned_student(num_terms: int = 2, program_overrides: dict = None,
                         term_stats: dict = None):
    """Program + terms + one student evaluated once into WARNING.

    The default grade line (attempted 6, earned 3, GPA 1.0) fails both the
    pace and GPA standards on a first evaluation: GOOD_STANDING -> WARNING.

    Returns dict(program, terms, student, evaluation).
    """
    stats = dict(FAILING_HALF_TERM)
    if term_stats:
        stats.update(term_stats)
    program = create_program(**(program_overrides or {}))
    terms = create_standard_terms(num_terms)
    student = create_student(program["id"])
    create_posted_enrollment(
        student["id"], terms[1]["id"], stats["attempted_credits"],
        stats["earned_credits"], stats["quality_points"], stats["gpa_hours"])
    close_and_evaluate(terms[1]["id"])
    evaluation = official_evaluation(student["id"], terms[1]["id"])
    return {"program": program, "terms": terms,
            "student": get_student(student["id"]), "evaluation": evaluation}


def setup_suspended_student(num_terms: int = 5, program_overrides: dict = None,
                            t1_stats: dict = None, t2_stats: dict = None):
    """Program + terms + one student evaluated twice into SUSPENSION.

    Two consecutive failing terms walk the student GOOD_STANDING -> WARNING
    -> SUSPENSION under default policy thresholds. The T2 OFFICIAL evaluation
    is the suspension row an appeal cites.

    Returns dict(program, terms, student, evaluation, student_version).
    """
    s1 = dict(FAILING_HALF_TERM)
    if t1_stats:
        s1.update(t1_stats)
    s2 = dict(FAILING_HALF_TERM)
    if t2_stats:
        s2.update(t2_stats)
    program = create_program(**(program_overrides or {}))
    terms = create_standard_terms(num_terms)
    student = create_student(program["id"])

    create_posted_enrollment(
        student["id"], terms[1]["id"], s1["attempted_credits"],
        s1["earned_credits"], s1["quality_points"], s1["gpa_hours"])
    close_and_evaluate(terms[1]["id"])

    create_posted_enrollment(
        student["id"], terms[2]["id"], s2["attempted_credits"],
        s2["earned_credits"], s2["quality_points"], s2["gpa_hours"])
    close_and_evaluate(terms[2]["id"])

    evaluation = official_evaluation(student["id"], terms[2]["id"])
    refreshed = get_student(student["id"])
    assert refreshed["sap_status"] == "SUSPENSION", (
        f"setup invariant broken: student is {refreshed['sap_status']}, expected SUSPENSION")
    return {
        "program": program, "terms": terms, "student": refreshed,
        "evaluation": evaluation, "student_version": refreshed["version"],
    }


# ==========================================================================
# Tier 3 -- appeal lifecycle shortcuts
# ==========================================================================

def submit_appeal(student_id: str, evaluation_id: str, expected_student_version: int,
                  **overrides) -> dict:
    """Submit an appeal as the owning student. Returns the SUBMITTED appeal."""
    headers = make_student_headers(student_id)
    payload = appeal_payload(evaluation_id, expected_student_version, **overrides)
    return get_success_data(api_client.create_appeal(payload, headers))


def setup_submitted_appeal(**world_kwargs) -> dict:
    """Suspended student + one SUBMITTED appeal against the T2 evaluation."""
    world = setup_suspended_student(**world_kwargs)
    appeal = submit_appeal(
        world["student"]["id"], world["evaluation"]["id"], world["student_version"])
    world["appeal"] = appeal
    return world


def setup_appeal_under_review(**world_kwargs) -> dict:
    """Suspended student + appeal screened into UNDER_REVIEW."""
    world = setup_submitted_appeal(**world_kwargs)
    world["appeal"] = get_success_data(
        api_client.screen_appeal(world["appeal"]["id"], AID_OFFICER))
    return world


def decide_appeal(appeal_id: str, decision: str, **overrides) -> dict:
    """Committee decision on an appeal. Returns the decided appeal row."""
    return get_success_data(
        api_client.decide_appeal(appeal_id, decide_payload(decision, **overrides), COMMITTEE))


def setup_approved_appeal(resolution: str = "WITH_PLAN", **world_kwargs) -> dict:
    """Suspended student + appeal APPROVED with the given resolution.

    After WITH_PLAN the student stands PLAN_PENDING; after PROBATION_ONLY the
    student stands PROBATION.
    """
    world = setup_appeal_under_review(**world_kwargs)
    world["appeal"] = decide_appeal(
        world["appeal"]["id"], "APPROVED", resolution=resolution)
    world["student"] = get_student(world["student"]["id"])
    return world


# ==========================================================================
# Tier 4 -- academic plan worlds
# ==========================================================================

def create_plan(student_id: str, appeal_id: str, start_term_id: str,
                total_required_credits: int, checkpoints: list) -> dict:
    return get_success_data(api_client.create_plan(
        plan_payload(student_id, appeal_id, start_term_id,
                     total_required_credits, checkpoints),
        AID_OFFICER))


def setup_plan_active(checkpoint_credits=(12, 12), checkpoint_terms=(3, 4),
                      required_term_gpa: float = 2.0,
                      required_term_pace_pct: float = 67.0,
                      **world_kwargs) -> dict:
    """Suspended student + APPROVED WITH_PLAN appeal + ACTIVE academic plan.

    By default the plan covers the two terms after the suspension term with
    one checkpoint each (credit budget == sum of checkpoint floors).

    Returns the world dict plus `plan` and the plan's checkpoint rows.
    """
    world = setup_approved_appeal(resolution="WITH_PLAN", **world_kwargs)
    assert world["student"]["sap_status"] == "PLAN_PENDING", (
        f"setup invariant broken: student is {world['student']['sap_status']}")
    checkpoints = [
        checkpoint_payload(world["terms"][seq]["id"], credits,
                           required_term_gpa=required_term_gpa,
                           required_term_pace_pct=required_term_pace_pct)
        for seq, credits in zip(checkpoint_terms, checkpoint_credits)
    ]
    total = sum(checkpoint_credits)
    plan = create_plan(world["student"]["id"], world["appeal"]["id"],
                       world["terms"][checkpoint_terms[0]]["id"], total, checkpoints)
    assert plan["status"] == "ACTIVE", f"setup invariant broken: plan is {plan['status']}"
    world["plan"] = plan
    world["student"] = get_student(world["student"]["id"])
    return world
