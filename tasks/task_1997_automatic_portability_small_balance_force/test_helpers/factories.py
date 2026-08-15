"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "RECORDKEEPER_CODE": "RK-A",
    "LEGAL_NAME": "Recordkeeper A",
    "PLAN_NAME": "Plan X",
    "SPONSOR_EIN": "11-1111111",
    "SSN_HASH": "hash-a",
    "FULL_NAME": "Ann A",
    "DATE_OF_BIRTH": "1980-01-01",
    "MAILING_ADDRESS_LINE1": "1 Main St",
    "MAILING_CITY": "Springfield",
    "MAILING_STATE": "IL",
    "MAILING_ZIP": "62701",
    "SEPARATION_DATE": "2026-07-15T00:00:00Z",
    "EMPLOYMENT_START_DATE": "2026-08-10",
}


def create_recordkeeper_payload(**overrides) -> dict:
    defaults = {
        "recordkeeper_code": DEFAULTS["RECORDKEEPER_CODE"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": DEFAULTS["PLAN_NAME"],
        "sponsor_ein": DEFAULTS["SPONSOR_EIN"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "ssn_hash": DEFAULTS["SSN_HASH"],
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "mailing_address_line1": DEFAULTS["MAILING_ADDRESS_LINE1"],
        "mailing_city": DEFAULTS["MAILING_CITY"],
        "mailing_state": DEFAULTS["MAILING_STATE"],
        "mailing_zip": DEFAULTS["MAILING_ZIP"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_batch_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_distribution_case_payload(**overrides) -> dict:
    defaults = {
        "separation_date": DEFAULTS["SEPARATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_election_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_safe_harbor_ira_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_check_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_match_search_payload(**overrides) -> dict:
    defaults = {
        "employment_start_date": DEFAULTS["EMPLOYMENT_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_fiduciary_review_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults
