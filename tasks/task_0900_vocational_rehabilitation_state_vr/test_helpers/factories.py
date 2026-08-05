"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "COUNSELOR_NAME": "Casey Counselor",
    "COUNSELOR_EMAIL": "casey@vr.gov",
    "COUNSELOR_UNIT": "U1",
    "SUPERVISOR_NAME": "Sam Supervisor",
    "SUPERVISOR_EMAIL": "sam@vr.gov",
    "PROVIDER_NAME": "Acme Services",
    "CONSUMER_NAME": "Al Ray",
    "CONSUMER_DOB": "1990-01-01",
    "REFERRAL_SOURCE": "DR",
    "EMPLOYMENT_GOAL": "Clerk",
    "EMPLOYER_NAME": "Acme",
}


def create_counselor_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["COUNSELOR_NAME"],
        "email": DEFAULTS["COUNSELOR_EMAIL"],
        "unit": DEFAULTS["COUNSELOR_UNIT"],
    }
    payload.update(overrides)
    return payload


def create_supervisor_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SUPERVISOR_NAME"],
        "email": DEFAULTS["SUPERVISOR_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_provider_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROVIDER_NAME"],
        "service_categories": ["TRAINING"],
        "max_concurrent_authorizations": 5,
    }
    payload.update(overrides)
    return payload


def create_priority_category_payload(**overrides) -> dict:
    payload = {
        "rank": 1,
        "label": "MSD",
        "slot_capacity": 5,
    }
    payload.update(overrides)
    return payload


def create_case_payload(**overrides) -> dict:
    payload = {
        "consumer_full_name": DEFAULTS["CONSUMER_NAME"],
        "consumer_dob": DEFAULTS["CONSUMER_DOB"],
        "disability_type": "PHYSICAL",
        "referral_source": DEFAULTS["REFERRAL_SOURCE"],
        "monthly_income_cents": 150000,
        "budget_allocated_cents": 500000,
    }
    payload.update(overrides)
    return payload


def create_ipe_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "employment_goal": DEFAULTS["EMPLOYMENT_GOAL"],
        "goal_wage_target_cents": 60000,
    }
    payload.update(overrides)
    return payload


def create_authorization_payload(case_id, ipe_id, provider_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "ipe_id": ipe_id,
        "provider_id": provider_id,
        "service_category": "TRAINING",
        "authorized_amount_cents": 100000,
        "comparable_benefit_cents": 0,
        "service_period_start": "2026-05-01",
        "service_period_end": "2026-05-31",
    }
    payload.update(overrides)
    return payload


def create_payment_payload(authorization_id, **overrides) -> dict:
    payload = {
        "authorization_id": authorization_id,
        "amount_cents": 100000,
    }
    payload.update(overrides)
    return payload


def create_placement_payload(case_id, ipe_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "ipe_id": ipe_id,
        "employer_name": DEFAULTS["EMPLOYER_NAME"],
        "placement_date": "2026-05-01",
        "weekly_wage_cents": 50000,
        "hours_per_week": 40,
        "employment_type": "COMPETITIVE_INTEGRATED",
    }
    payload.update(overrides)
    return payload


def create_progress_review_payload(placement_id, review_date, reported_weekly_wage_cents, **overrides) -> dict:
    payload = {
        "placement_id": placement_id,
        "review_date": review_date,
        "reported_weekly_wage_cents": reported_weekly_wage_cents,
    }
    payload.update(overrides)
    return payload
