"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "FULL_NAME": "Test Person",
    "EMAIL": "test.person@example.com",
    "DESIGNATION": "EMPLOYEE",
    "DEPARTMENT": "Engineering",
    "CODENAME": "PROJECTTEST",
    "DEAL_TYPE": "MERGER",
    "TICKER": "ACME",
    "TRADE_SIDE": "BUY",
    "QUANTITY": 100,
    "PROPOSED_TRADE_DATE": "2026-08-20T00:00:00Z",
    "PRICE": 10.00,
    "TRADE_DATE": "2026-08-01T10:00:00Z",
    "BROKER_REF": "BR-TEST",
    "HARDSHIP_REASON": "hardship",
    "TOTAL_QUANTITY": 300,
    "FIRST_TRADE_DATE": "2026-09-01T00:00:00Z",
    "VIOLATION_TYPE": "NO_PRECLEARANCE",
    "ATTESTATION_KIND": "POLICY_ACK",
    "PERIOD_YEAR": 2026,
    "DUE_DATE": "2026-12-31T00:00:00Z",
    "WINDOW_START": "2026-08-10T00:00:00Z",
    "WINDOW_END": "2026-08-20T00:00:00Z",
}


def create_covered_person_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
        "designation": DEFAULTS["DESIGNATION"],
        "department": DEFAULTS["DEPARTMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(**overrides) -> dict:
    defaults = {
        "codename": DEFAULTS["CODENAME"],
        "deal_type": DEFAULTS["DEAL_TYPE"],
        "security_ticker": DEFAULTS["TICKER"],
    }
    defaults.update(overrides)
    return defaults


def create_restricted_list_entry_payload(**overrides) -> dict:
    defaults = {"security_ticker": DEFAULTS["TICKER"]}
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(**overrides) -> dict:
    defaults = {
        "kind": "QUARTERLY",
        "fiscal_year": 2026,
        "fiscal_quarter": "Q3",
        "start_at": DEFAULTS["WINDOW_START"],
        "end_at": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_preclearance_request_payload(**overrides) -> dict:
    defaults = {
        "security_ticker": DEFAULTS["TICKER"],
        "trade_side": DEFAULTS["TRADE_SIDE"],
        "quantity": DEFAULTS["QUANTITY"],
        "proposed_trade_date": DEFAULTS["PROPOSED_TRADE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_exception_request_payload(**overrides) -> dict:
    defaults = {
        "security_ticker": DEFAULTS["TICKER"],
        "quantity": 1000,
        "hardship_reason": DEFAULTS["HARDSHIP_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_tenb5_plan_payload(**overrides) -> dict:
    defaults = {
        "security_ticker": DEFAULTS["TICKER"],
        "total_quantity": DEFAULTS["TOTAL_QUANTITY"],
        "first_trade_date": DEFAULTS["FIRST_TRADE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_confirmation_payload(**overrides) -> dict:
    defaults = {
        "security_ticker": DEFAULTS["TICKER"],
        "trade_side": DEFAULTS["TRADE_SIDE"],
        "quantity": DEFAULTS["QUANTITY"],
        "price": DEFAULTS["PRICE"],
        "trade_date": DEFAULTS["TRADE_DATE"],
        "broker_ref": DEFAULTS["BROKER_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_violation_case_payload(**overrides) -> dict:
    defaults = {"violation_type": DEFAULTS["VIOLATION_TYPE"]}
    defaults.update(overrides)
    return defaults


def create_attestation_payload(**overrides) -> dict:
    defaults = {
        "kind": DEFAULTS["ATTESTATION_KIND"],
        "period_year": DEFAULTS["PERIOD_YEAR"],
        "due_date": DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults
