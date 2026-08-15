"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_jurisdiction_profile_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "base_fee_cents": TEST_DEFAULTS["CA_BASE_FEE_CENTS"],
        "per_additional_debtor_fee_cents": TEST_DEFAULTS["CA_PER_ADDITIONAL_DEBTOR_FEE_CENTS"],
        "county_surcharge_cents": TEST_DEFAULTS["CA_COUNTY_SURCHARGE_CENTS"],
        "county_filing_collateral_classes": list(TEST_DEFAULTS["CA_COUNTY_COLLATERAL_CLASSES"]),
        "county_names": list(TEST_DEFAULTS["CA_COUNTY_NAMES"]),
        "individual_name_rule": TEST_DEFAULTS["CA_NAME_RULE"],
        "expedited_daily_capacity": TEST_DEFAULTS["CA_EXPEDITED_DAILY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_client_account_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["CLIENT_NAME"]}
    defaults.update(overrides)
    return defaults


def create_debtor_payload(**overrides) -> dict:
    defaults = {
        "debtor_type": "ORGANIZATION",
        "legal_name": TEST_DEFAULTS["ORG_LEGAL_NAME"],
        "jurisdiction_of_formation": TEST_DEFAULTS["ORG_JURISDICTION"],
    }
    defaults.update(overrides)
    # A None value means "omit this optional field from the body".
    return {k: v for k, v in defaults.items() if v is not None}


def create_secured_party_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["SECURED_PARTY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_filing_request_payload(**overrides) -> dict:
    defaults = {
        "kind": "NEW_UCC1",
        "jurisdiction_code": "CA",
        "collateral_class": "GENERAL",
        "fee_authorization_cents": TEST_DEFAULTS["FEE_AUTHORIZATION_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_attempt_payload(**overrides) -> dict:
    defaults = {
        "debtor_name_on_filing": TEST_DEFAULTS["ORG_LEGAL_NAME"],
        "collateral_text": TEST_DEFAULTS["COLLATERAL_TEXT"],
    }
    defaults.update(overrides)
    # A None value means "omit this optional field from the body".
    return {k: v for k, v in defaults.items() if v is not None}


def create_lien_search_payload(**overrides) -> dict:
    defaults = {
        "purpose": "PRE_FILING",
        "jurisdiction_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_hit_payload(**overrides) -> dict:
    defaults = {
        "found_debtor_name": TEST_DEFAULTS["ORG_LEGAL_NAME"],
        "found_filing_number": _unique("CA-FOUND"),
        "found_filed_at": "2020-01-15T00:00:00Z",
        "secured_party_name": "Other Bank",
    }
    defaults.update(overrides)
    return defaults


def record_results_payload(**overrides) -> dict:
    defaults = {
        "through_date": TEST_DEFAULTS["CLOCK_START_ISO"],
        "hits": [],
    }
    defaults.update(overrides)
    return defaults


def create_perfection_report_payload(**overrides) -> dict:
    defaults = {
        "mode": "AS_OF_NOW",
        "horizon_days": 90,
    }
    defaults.update(overrides)
    return defaults
