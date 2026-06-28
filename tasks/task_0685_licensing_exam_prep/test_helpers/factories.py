"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields with PRD-declared defaults
(ce_bundle_id, financed, pass_guarantee, guarantee_refund_pct, includes_ce)
are only emitted when the caller overrides them, except where the factory's
canonical shape sets a sensible base value.
"""


def create_license_program_payload(**overrides) -> dict:
    """POST /license-programs inputs: license_code, title, passing_scaled_score, domain_weights."""
    defaults = {
        "license_code": "CPA-FAR",
        "title": "Test Program",
        "passing_scaled_score": 75,
        "domain_weights": [{"domain_code": "A", "weight": 1.00}],
    }
    defaults.update(overrides)
    return defaults


def create_question_item_payload(**overrides) -> dict:
    """POST /license-programs/{id}/items inputs: domain_code, difficulty, correct_choice."""
    defaults = {
        "domain_code": "A",
        "difficulty": "EASY",
        "correct_choice": "A",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    """POST /subscription-plans inputs."""
    defaults = {
        "tier": "BASIC",
        "total_price_cents": 30000,
        "down_payment_pct": 0.00,
        "financing_months": 1,
        "included_mock_credits": 3,
        "pass_guarantee": False,
        "guarantee_refund_pct": 0.0,
        "includes_ce": False,
    }
    defaults.update(overrides)
    return defaults


def create_ce_bundle_payload(license_program_id, **overrides) -> dict:
    """POST /ce-bundles inputs: license_program_id, ce_credits_total, modules_total."""
    defaults = {
        "license_program_id": license_program_id,
        "ce_credits_total": 12,
        "modules_total": 4,
    }
    defaults.update(overrides)
    return defaults


def create_learner_payload(**overrides) -> dict:
    """POST /learners inputs: email, full_name."""
    defaults = {
        "email": "learner@x.com",
        "full_name": "Test Learner",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(learner_id, license_program_id, subscription_plan_id, **overrides) -> dict:
    """POST /enrollments inputs: learner_id, license_program_id, subscription_plan_id, financed, ce_bundle_id?."""
    defaults = {
        "learner_id": learner_id,
        "license_program_id": license_program_id,
        "subscription_plan_id": subscription_plan_id,
        "financed": False,
    }
    defaults.update(overrides)
    return defaults


def create_practice_session_payload(**overrides) -> dict:
    """POST /enrollments/{id}/practice-sessions inputs: domain_code, answered_count, correct_count."""
    defaults = {
        "domain_code": "A",
        "answered_count": 10,
        "correct_count": 8,
    }
    defaults.update(overrides)
    return defaults


def create_mock_exam_payload(**overrides) -> dict:
    """POST /enrollments/{id}/mock-exams inputs: raw_score, item_count."""
    defaults = {
        "raw_score": 70,
        "item_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_ce_award_payload(**overrides) -> dict:
    """POST /enrollments/{id}/ce-awards inputs: modules_completed."""
    defaults = {"modules_completed": 1}
    defaults.update(overrides)
    return defaults


def create_pass_guarantee_claim_payload(enrollment_id, **overrides) -> dict:
    """POST /pass-guarantee-claims inputs: enrollment_id, remedy."""
    defaults = {
        "enrollment_id": enrollment_id,
        "remedy": "MONEY_BACK",
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(license_program_id, **overrides) -> dict:
    """POST /cohorts inputs: license_program_id, title, capacity."""
    defaults = {
        "license_program_id": license_program_id,
        "title": "Test Cohort",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_cohort_session_payload(**overrides) -> dict:
    """POST /cohorts/{id}/sessions inputs: topic, session_start_utc, session_end_utc."""
    defaults = {
        "topic": "Test Session",
        "session_start_utc": "2026-06-05T10:00:00Z",
        "session_end_utc": "2026-06-05T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cohort_membership_payload(enrollment_id, **overrides) -> dict:
    """POST /cohorts/{id}/memberships inputs: enrollment_id, session_start_utc, session_end_utc."""
    defaults = {
        "enrollment_id": enrollment_id,
        "session_start_utc": "2026-06-01T10:00:00Z",
        "session_end_utc": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults
