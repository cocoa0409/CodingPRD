"""Payload factories — one per entity, input fields only.

Emails are made unique per call so a single test may register several
applicants against a fresh database without colliding on the unique email.
"""
import uuid


def _unique_email(prefix: str = "buyer") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": "Down-Payment Assistance",
        "ami_limit_pct": 80,
        "max_assistance_cents": 5_000_000,
        "recapture_model": "SHARED_APPRECIATION",
    }
    payload.update(overrides)
    return payload


def create_income_limit_payload(**overrides) -> dict:
    payload = {
        "household_size": 4,
        "ami_100_income_cents": 10_000_000,
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ann Buyer",
        "email": _unique_email(),
        "household_size": 4,
        "annual_income_cents": 8_000_000,
    }
    payload.update(overrides)
    return payload


def create_property_payload(**overrides) -> dict:
    payload = {
        "address": "1 Main St",
        "county_code": "K01",
        "purchase_price_cents": 30_000_000,
    }
    payload.update(overrides)
    return payload


def create_application_payload(**overrides) -> dict:
    payload = {
        "first_mortgage_amount_cents": 24_000_000,
        "buyer_contribution_cents": 500_000,
    }
    payload.update(overrides)
    return payload


def create_education_session_payload(**overrides) -> dict:
    payload = {
        "title": "Homebuyer Education 101",
        "start_at": "2026-07-02T09:00:00Z",
        "end_at": "2026-07-02T12:00:00Z",
        "capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_funding_source_payload(**overrides) -> dict:
    payload = {
        "name": "HOME Fund",
        "priority": 1,
        "total_appropriation_cents": 10_000_000,
    }
    payload.update(overrides)
    return payload


def create_funding_allocation_payload(**overrides) -> dict:
    payload = {
        "amount_cents": 5_000_000,
        "lien_position": 1,
    }
    payload.update(overrides)
    return payload


def create_closing_payload(**overrides) -> dict:
    payload = {
        "scheduled_date": "2026-08-01T00:00:00Z",
        "window_days": 7,
    }
    payload.update(overrides)
    return payload
