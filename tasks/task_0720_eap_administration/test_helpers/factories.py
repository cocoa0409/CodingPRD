"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "EMPLOYER_NAME": "Test Employer",
    "SESSIONS_PER_ISSUE": 2,
    "ANNUAL_SESSION_CAP": 10,
    "SESSION_RATE_CENTS": 12000,
    "CRISIS_SLA_MINUTES": 15,
    "ANNUAL_REIMBURSEMENT_BUDGET_CENTS": 1_000_000,
    "REPORTING_MIN_COHORT": 2,
    "PLAN_NAME": "Std",
    "COPAY_CENTS": 2000,
    "WORKLIFE_REFERRALS_PER_YEAR": 3,
    "DURATION_MINUTES": 50,
}


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "employer_name": DEFAULTS["EMPLOYER_NAME"],
        "sessions_per_issue": DEFAULTS["SESSIONS_PER_ISSUE"],
        "annual_session_cap": DEFAULTS["ANNUAL_SESSION_CAP"],
        "session_rate_cents": DEFAULTS["SESSION_RATE_CENTS"],
        "annual_reimbursement_budget_cents": DEFAULTS["ANNUAL_REIMBURSEMENT_BUDGET_CENTS"],
        "crisis_sla_minutes": DEFAULTS["CRISIS_SLA_MINUTES"],
        "reporting_min_cohort": DEFAULTS["REPORTING_MIN_COHORT"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "name": DEFAULTS["PLAN_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(contract_id, plan_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "plan_id": plan_id,
        "full_name": "Test Employee",
        "external_ref": "EXT1",
    }
    defaults.update(overrides)
    return defaults


def create_dependent_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "full_name": "Test Dependent",
        "relationship": "CHILD",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(contract_id, employee_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "employee_id": employee_id,
        "presenting_issue": "STRESS",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(provider_id, scheduled_for, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "scheduled_for": scheduled_for,
        "duration_minutes": DEFAULTS["DURATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Provider",
        "network_status": "IN_NETWORK",
        "specialties": ["STRESS"],
        "accepting": True,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(employee_id, required_specialty, referral_type="WORKLIFE",
                            **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "referral_type": referral_type,
        "required_specialty": required_specialty,
    }
    defaults.update(overrides)
    return defaults


def create_crisis_contact_payload(contract_id, severity="MODERATE", **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(contract_id, session_id, billed_cents=12000, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "session_id": session_id,
        "billed_cents": billed_cents,
    }
    defaults.update(overrides)
    return defaults


def create_wellness_activity_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "activity_type": "WEBINAR",
        "points": 10,
        "completed_on": "2026-03-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
