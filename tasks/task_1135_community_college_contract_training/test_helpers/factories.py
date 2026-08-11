"""Payload factories — one per entity, input fields only."""

DEFAULT_MODULE = {"code": "T-1", "hours": 2, "required_credential_codes": []}


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer",
        "industry_code": "111110",
        "contact_email": "hr@example.test",
    }
    defaults.update(overrides)
    return defaults


def create_needs_assessment_payload(**overrides) -> dict:
    defaults = {
        "title": "Assessment",
        "skill_gaps": ["gap"],
        "target_roles": ["role"],
        "curriculum_modules": [dict(DEFAULT_MODULE)],
    }
    defaults.update(overrides)
    return defaults


def create_training_agreement_payload(needs_assessment_id, **overrides) -> dict:
    defaults = {
        "needs_assessment_id": needs_assessment_id,
        "pricing_model": "FLAT_COHORT",
        "delivery_mode": "ON_SITE",
        "est_participant_count": 2,
        "est_delivery_hours": 2,
        "target_start_date": "2026-06-15T00:00:00Z",
        "max_cohorts": 2,
    }
    defaults.update(overrides)
    return defaults


def create_grant_program_payload(**overrides) -> dict:
    defaults = {
        "code": "GP-DEFAULT",
        "name": "State Training Grant",
        "appropriation_cents": 1000000,
        "max_share_pct": 0.5,
        "cap_per_trainee_cents": 50000,
        "application_window_end": "2026-06-30T23:59:59Z",
        "claim_deadline_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_grant_application_payload(program_id, requested_cents, expected_cohort_version) -> dict:
    return {
        "program_id": program_id,
        "requested_cents": requested_cents,
        "expected_cohort_version": expected_cohort_version,
    }


def create_instructor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Instructor",
        "credentials": [],
        "hourly_rate_cents": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Venue",
        "kind": "EMPLOYER_SITE",
        "capacity": 10,
        "hourly_cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(**overrides) -> dict:
    defaults = {
        "delivery_mode": "ON_SITE",
        "min_enrollment": 1,
        "start_date": "2026-06-15T00:00:00Z",
        "end_date": "2026-06-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "start_at": "2026-06-15T09:00:00Z",
        "end_at": "2026-06-15T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_instructor_assignment_payload(instructor_id) -> dict:
    return {"instructor_id": instructor_id}


def create_participant_payload(external_employee_ref, **overrides) -> dict:
    defaults = {
        "external_employee_ref": external_employee_ref,
        "full_name": "Participant " + str(external_employee_ref),
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(variant="FINAL") -> dict:
    return {"variant": variant}


def create_outcome_report_payload(**overrides) -> dict:
    defaults = {
        "completers_employed_90d": 1,
        "satisfaction_avg": 4.5,
        "follow_on_opportunity_cents": 0,
    }
    defaults.update(overrides)
    return defaults
