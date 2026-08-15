"""Payload factories — one per entity, input fields only."""
from .constants import INITIAL_SEASON, TEST_DEFAULTS


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "display_name": TEST_DEFAULTS["VENUE_DISPLAY_NAME"],
        "city": TEST_DEFAULTS["VENUE_CITY"],
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["SPONSOR_LEGAL_NAME"],
        "display_name": TEST_DEFAULTS["SPONSOR_DISPLAY_NAME"],
        "industry_category": TEST_DEFAULTS["SPONSOR_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "name": TEST_DEFAULTS["ASSET_NAME"],
        "asset_class": TEST_DEFAULTS["ASSET_CLASS"],
        "rate_card_unit_cents": TEST_DEFAULTS["RATE_CARD_UNIT_CENTS"],
        "avg_impressions_per_unit": TEST_DEFAULTS["AVG_IMPRESSIONS_PER_UNIT"],
        "cpm_cents": TEST_DEFAULTS["CPM_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rights_window_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "holder": "LEAGUE",
        "category": TEST_DEFAULTS["SPONSOR_CATEGORY"],
        "first_season": INITIAL_SEASON,
        "last_season": INITIAL_SEASON,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(venue_id, sponsor_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "sponsor_id": sponsor_id,
        "title": "Stadium Naming Rights",
        "term_first_season": INITIAL_SEASON,
        "term_last_season": INITIAL_SEASON,
        "base_fee_cents": TEST_DEFAULTS["BASE_FEE_CENTS"],
        "escalator_pct": 0,
        "escalator_mode": "SIMPLE",
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "category": TEST_DEFAULTS["SPONSOR_CATEGORY"],
        "first_season": INITIAL_SEASON,
        "last_season": INITIAL_SEASON,
    }
    defaults.update(overrides)
    return defaults


def create_deliverable_payload(contract_id, asset_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "asset_id": asset_id,
        "season": INITIAL_SEASON,
        "unit_kind": "GAME_DISPLAY",
        "contracted_units": TEST_DEFAULTS["CONTRACTED_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_suite_deliverable_payload(contract_id, asset_id, checkin_date,
                                     checkout_date, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "asset_id": asset_id,
        "season": INITIAL_SEASON,
        "unit_kind": "SUITE_NIGHT",
        "contracted_units": 1,
        "checkin_date": checkin_date,
        "checkout_date": checkout_date,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(deliverable_id, **overrides) -> dict:
    defaults = {
        "deliverable_id": deliverable_id,
        "units_claimed": 1,
        "evidence_uri": TEST_DEFAULTS["EVIDENCE_URI"],
    }
    defaults.update(overrides)
    return defaults


def create_credit_payload(contract_id, deliverable_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "deliverable_id": deliverable_id,
        "requested_amount_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1,
        "method": TEST_DEFAULTS["PAYMENT_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(contract_id, season, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "season": season,
    }
    defaults.update(overrides)
    return defaults


def create_opportunity_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "proposed_fee_cents": 12_000_000,
    }
    defaults.update(overrides)
    return defaults
