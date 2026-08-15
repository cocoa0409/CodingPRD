"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DISTRICT_NAME": "Test District",
    "METHODOLOGY": "PER_PARCEL",
    "INTEREST_METHOD": "SIMPLE",
    "SEASON_START": "03-01",
    "SEASON_END": "11-30",
    "OWNER_NAME": "Test Owner",
    "OWNER_ADDRESS": "1 Main St",
    "PARCEL_NUMBER": "P-001",
    "FRONTAGE_FT": 100.0,
    "CONTRACT_PRICE_CENTS": 100000,
    "CONTINGENCY_CENTS": 0,
    "HEARING_DATE": "2026-08-15T00:00:00Z",
    "VENUE": "City Hall Room A",
    "GROUNDS": "objection grounds",
    "PHASE_NAME": "PH1",
    "CREW_NAME": "Alpha",
    "PHASE_START": "2026-09-10",
    "PHASE_END": "2026-10-10",
    "PHASE_COST_CENTS": 50000,
    "CHANGE_ORDER_DESCRIPTION": "overrun",
    "PAYMENT_METHOD": "ACH",
}


def create_district_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DISTRICT_NAME"],
        "methodology": DEFAULTS["METHODOLOGY"],
        "interest_method": DEFAULTS["INTEREST_METHOD"],
        "season_start_mmdd": DEFAULTS["SEASON_START"],
        "season_end_mmdd": DEFAULTS["SEASON_END"],
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["OWNER_NAME"],
        "email": "owner@x.test",
        "mailing_address": DEFAULTS["OWNER_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(**overrides) -> dict:
    defaults = {
        "district_id": "",
        "owner_id": "",
        "parcel_number": DEFAULTS["PARCEL_NUMBER"],
        "frontage_ft": DEFAULTS["FRONTAGE_FT"],
    }
    defaults.update(overrides)
    return defaults


def create_petition_payload(**overrides) -> dict:
    defaults = {"district_id": ""}
    defaults.update(overrides)
    return defaults


def create_signature_payload(**overrides) -> dict:
    defaults = {"petition_id": "", "parcel_id": ""}
    defaults.update(overrides)
    return defaults


def create_cost_estimate_payload(**overrides) -> dict:
    defaults = {
        "district_id": "",
        "expected_district_version": 0,
        "contract_price_cents": DEFAULTS["CONTRACT_PRICE_CENTS"],
        "contingency_cents": DEFAULTS["CONTINGENCY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(**overrides) -> dict:
    defaults = {
        "district_id": "",
        "hearing_date": DEFAULTS["HEARING_DATE"],
        "venue": DEFAULTS["VENUE"],
    }
    defaults.update(overrides)
    return defaults


def create_objection_payload(**overrides) -> dict:
    defaults = {"hearing_id": "", "parcel_id": "", "grounds": DEFAULTS["GROUNDS"]}
    defaults.update(overrides)
    return defaults


def create_resolution_payload(**overrides) -> dict:
    defaults = {
        "district_id": "",
        "expected_district_version": 0,
        "motion": "APPROVE",
        "votes_for": 3,
        "votes_against": 0,
    }
    defaults.update(overrides)
    return defaults


def create_payment_option_payload(**overrides) -> dict:
    defaults = {"option": "INSTALLMENTS", "term_years": 5}
    defaults.update(overrides)
    return defaults


def create_phase_payload(**overrides) -> dict:
    defaults = {
        "district_id": "",
        "name": DEFAULTS["PHASE_NAME"],
        "crew_name": DEFAULTS["CREW_NAME"],
        "start_date": DEFAULTS["PHASE_START"],
        "end_date": DEFAULTS["PHASE_END"],
        "estimated_cost_cents": DEFAULTS["PHASE_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {
        "district_id": "",
        "description": DEFAULTS["CHANGE_ORDER_DESCRIPTION"],
        "amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "parcel_assessment_id": "",
        "expected_parcel_assessment_version": 0,
        "amount_cents": 0,
        "method": DEFAULTS["PAYMENT_METHOD"],
    }
    defaults.update(overrides)
    return defaults
