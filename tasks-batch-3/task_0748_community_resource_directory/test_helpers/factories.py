"""Payload factories — one per entity, input fields only."""


DEFAULT_FUNDER_NAME = "Test Funder"
DEFAULT_FUNDER_FY_MONTH = 7
DEFAULT_FUNDER_GRANT = 100_000_000  # 1M USD in cents
DEFAULT_FUNDER_CURRENCY = "USD"

DEFAULT_PROVIDER_NAME = "Test Provider"
DEFAULT_PROVIDER_LAT = 40.00
DEFAULT_PROVIDER_LNG = -74.00
DEFAULT_PROVIDER_ACCESSIBILITY = ["WHEELCHAIR"]
DEFAULT_PROVIDER_LANGUAGES = ["EN"]

DEFAULT_PROGRAM_CATEGORY = "FOOD"
DEFAULT_PROGRAM_INCOME_MAX = 500_000
DEFAULT_PROGRAM_AGE_MIN = 18
DEFAULT_PROGRAM_AGE_MAX = 65
DEFAULT_PROGRAM_UNIT_COST = 10_000
DEFAULT_PROGRAM_CAPACITY = 5

DEFAULT_CLIENT_NAME = "Test Client"
DEFAULT_CLIENT_DOB = "1996-01-15"
DEFAULT_CLIENT_INCOME = 400_000
DEFAULT_CLIENT_LAT = 40.00
DEFAULT_CLIENT_LNG = -74.00
DEFAULT_CLIENT_LANG = "EN"

DEFAULT_INTAKE_NEEDS = ["FOOD"]
DEFAULT_INTAKE_URGENCY = "ROUTINE"


def create_funder_payload(**overrides) -> dict:
    return {
        "name": DEFAULT_FUNDER_NAME,
        "fiscal_year_start_month": DEFAULT_FUNDER_FY_MONTH,
        "grant_cents_total": DEFAULT_FUNDER_GRANT,
        "reporting_currency": DEFAULT_FUNDER_CURRENCY,
        **overrides,
    }


def create_provider_payload(**overrides) -> dict:
    return {
        "legal_name": DEFAULT_PROVIDER_NAME,
        "location_lat": DEFAULT_PROVIDER_LAT,
        "location_lng": DEFAULT_PROVIDER_LNG,
        "accessibility_features": list(DEFAULT_PROVIDER_ACCESSIBILITY),
        "languages_supported": list(DEFAULT_PROVIDER_LANGUAGES),
        **overrides,
    }


def create_program_payload(provider_id: str, funder_id: str, **overrides) -> dict:
    return {
        "provider_id": provider_id,
        "funder_id": funder_id,
        "category": DEFAULT_PROGRAM_CATEGORY,
        "eligibility_income_max_cents": DEFAULT_PROGRAM_INCOME_MAX,
        "eligibility_age_min": DEFAULT_PROGRAM_AGE_MIN,
        "eligibility_age_max": DEFAULT_PROGRAM_AGE_MAX,
        "unit_cost_cents": DEFAULT_PROGRAM_UNIT_COST,
        "capacity_slots_total": DEFAULT_PROGRAM_CAPACITY,
        **overrides,
    }


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULT_CLIENT_NAME,
        "date_of_birth": DEFAULT_CLIENT_DOB,
        "monthly_income_cents": DEFAULT_CLIENT_INCOME,
        "home_lat": DEFAULT_CLIENT_LAT,
        "home_lng": DEFAULT_CLIENT_LNG,
        "preferred_language": DEFAULT_CLIENT_LANG,
        "accessibility_needs": [],
    }
    payload.update(overrides)
    return payload


def create_intake_payload(**overrides) -> dict:
    return {
        "presenting_needs": list(DEFAULT_INTAKE_NEEDS),
        "urgency": DEFAULT_INTAKE_URGENCY,
        "household_size": 1,
        "disability_flag": False,
        **overrides,
    }


def create_consent_grant_payload(provider_id: str, **overrides) -> dict:
    return {"provider_id": provider_id, "scope": "BASIC_CONTACT", **overrides}


def create_referral_payload(program_id: str, consent_grant_id: str, **overrides) -> dict:
    return {
        "program_id": program_id,
        "consent_grant_id": consent_grant_id,
        "transport_mode": "CAR",
        **overrides,
    }


def create_transport_plan_payload(
    pickup_start_ts: str,
    pickup_end_ts: str,
    mode: str = "AGENCY_SHUTTLE",
    cost_cents: int = 500,
    **overrides,
) -> dict:
    return {
        "pickup_start_ts": pickup_start_ts,
        "pickup_end_ts": pickup_end_ts,
        "mode": mode,
        "cost_cents": cost_cents,
        **overrides,
    }


def create_availability_window_payload(
    start_ts: str, end_ts: str, max_slots: int = 3, **overrides
) -> dict:
    return {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "max_slots": max_slots,
        **overrides,
    }


def create_outcome_report_payload(
    outcome: str, service_hours: float, follow_up_needed: bool = False, **overrides
) -> dict:
    return {
        "outcome": outcome,
        "service_hours": service_hours,
        "follow_up_needed": follow_up_needed,
        **overrides,
    }


def create_funder_report_payload(
    reporting_period_start: str,
    reporting_period_end: str,
    rounding_variant: str = "SUM_THEN_ROUND",
    **overrides,
) -> dict:
    return {
        "reporting_period_start": reporting_period_start,
        "reporting_period_end": reporting_period_end,
        "rounding_variant": rounding_variant,
        **overrides,
    }
