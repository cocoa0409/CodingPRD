"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_staff_user_payload(role, **overrides) -> dict:
    payload = {
        "role": role,
        "full_name": "Test Staff",
        "email": "staff@example.com",
    }
    payload.update(overrides)
    return payload


def create_client_payload(account_manager_id, **overrides) -> dict:
    payload = {
        "name": "West Health",
        "region": "West",
        "account_manager_id": account_manager_id,
        "contingency_pct": TEST_DEFAULTS["CONTINGENCY_PCT"],
        "min_fee_cents": TEST_DEFAULTS["MIN_FEE_CENTS"],
        "guarantee_days": TEST_DEFAULTS["GUARANTEE_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_job_opening_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "specialty": "CARDIOLOGY",
        "region": "West",
        "region_state": "CA",
        "comp_min_cents": TEST_DEFAULTS["COMP_MIN_CENTS"],
        "comp_max_cents": TEST_DEFAULTS["COMP_MAX_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_candidate_payload(recruiter_id, **overrides) -> dict:
    payload = {
        "recruiter_id": recruiter_id,
        "full_name": "Dr Vale",
        "specialty": "CARDIOLOGY",
        "home_region": "West",
        "license_states": ["CA"],
        "desired_comp_cents": 26_000_000,
    }
    payload.update(overrides)
    return payload


def create_application_payload(candidate_id, opening_id, **overrides) -> dict:
    payload = {"candidate_id": candidate_id, "opening_id": opening_id}
    payload.update(overrides)
    return payload


def create_site_visit_payload(application_id, interviewer_user_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "interviewer_user_id": interviewer_user_id,
        "scheduled_start": TEST_DEFAULTS["SITE_VISIT_START"],
        "scheduled_end": TEST_DEFAULTS["SITE_VISIT_END"],
        "location": "HQ",
    }
    payload.update(overrides)
    return payload


def create_offer_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "base_salary_cents": TEST_DEFAULTS["BASE_SALARY_CENTS"],
        "start_date": TEST_DEFAULTS["START_DATE"],
        "expires_at": TEST_DEFAULTS["EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_relocation_expense_payload(category, amount_cents, **overrides) -> dict:
    payload = {"category": category, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_credential_item_payload(item_type, **overrides) -> dict:
    payload = {"item_type": item_type}
    payload.update(overrides)
    return payload


def create_guarantee_claim_payload(placement_id, fell_out_date, **overrides) -> dict:
    payload = {
        "placement_id": placement_id,
        "fell_out_date": fell_out_date,
        "reason": "left practice",
    }
    payload.update(overrides)
    return payload
