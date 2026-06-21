"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the POST body for creating that entity. Only
`source: input` fields appear; system/computed fields are never sent. Optional
fields with PRD defaults are omitted unless overridden.
"""


def create_cap_table_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Test Co",
        "authorized_shares": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_security_class_payload(cap_table_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "name": "Common",
        "class_type": "COMMON",
        "original_issue_price_cents": 0,
        "liquidation_pref_multiple": 0,
    }
    defaults.update(overrides)
    return defaults


def create_shareholder_payload(cap_table_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "legal_name": "Test Holder",
        "holder_type": "EMPLOYEE",
        "email": "holder@test.com",
    }
    defaults.update(overrides)
    return defaults


def create_share_issuance_payload(cap_table_id, security_class_id, shareholder_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "security_class_id": security_class_id,
        "shareholder_id": shareholder_id,
        "share_count": 1000,
        "price_paid_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_valuation_payload(cap_table_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "fmv_per_share_cents": 100,
        "valuation_date": "2025-01-01T00:00:00Z",
        "expires_at": "2025-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_option_pool_payload(cap_table_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "authorized_shares": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_option_grant_payload(cap_table_id, option_pool_id, shareholder_id,
                                security_class_id, valuation_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "option_pool_id": option_pool_id,
        "shareholder_id": shareholder_id,
        "security_class_id": security_class_id,
        "valuation_id": valuation_id,
        "share_count": 1000,
        "strike_price_cents": 100,
        "grant_date": "2025-01-01T00:00:00Z",
        "vesting_months": 48,
        "cliff_months": 12,
    }
    defaults.update(overrides)
    return defaults


def create_exercise_payload(cap_table_id, option_grant_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "option_grant_id": option_grant_id,
        "share_count": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_section_83b_election_payload(cap_table_id, exercise_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "exercise_id": exercise_id,
        "filed_date": "2025-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_safe_note_payload(cap_table_id, shareholder_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "shareholder_id": shareholder_id,
        "instrument_type": "SAFE",
        "principal_cents": 1_000_000,
        "issue_date": "2025-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_liquidation_event_payload(cap_table_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "total_proceeds_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(cap_table_id, **overrides) -> dict:
    defaults = {
        "cap_table_id": cap_table_id,
        "reason": "PRE_EARNINGS",
        "starts_at": "2025-01-01T00:00:00Z",
        "ends_at": "2025-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
