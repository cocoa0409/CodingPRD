"""Payload factories — one per creatable entity, input fields only."""

import itertools

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


DEFAULTS = {
    "BRANCH_NAME": "Main",
    "CUSTOMER_LEGAL_NAME": "Test Customer",
    "CUSTOMER_TYPE": "INDIVIDUAL",
    "CUSTOMER_TIN": "00-0000000",
    "ACCOUNT_OPENED_DATE": "2026-01-15T00:00:00Z",
    "OCCURRED_AT": "2026-08-01T08:00:00Z",
    "AMOUNT_CENTS": 100_000,
}


def create_branch_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BRANCH_NAME"],
        "branch_code": _seq("BR"),
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["CUSTOMER_LEGAL_NAME"],
        "customer_type": DEFAULTS["CUSTOMER_TYPE"],
        "account_opened_date": DEFAULTS["ACCOUNT_OPENED_DATE"],
        # PRD §3.1: tin is optional at creation but required before any CTR
        # for the customer can be validated (§3.5). Default to a non-null tin
        # so factory-built customers satisfy the validation precondition;
        # tests exercising the null-tin path pass tin=None explicitly.
        "tin": DEFAULTS["CUSTOMER_TIN"],
    }
    defaults.update(overrides)
    return defaults


def create_cash_transaction_payload(customer_id: str, branch_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "branch_id": branch_id,
        "direction": "CASH_IN",
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "occurred_at": DEFAULTS["OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_instrument_sale_payload(customer_id: str, branch_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "branch_id": branch_id,
        "instrument_type": "CASHIERS_CHECK",
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "occurred_at": DEFAULTS["OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_exemption_designation_payload(**overrides) -> dict:
    defaults = {"phase": "PHASE_I"}
    defaults.update(overrides)
    return defaults


def create_structuring_alert_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "window_start_date": "2026-07-27",
        "window_end_date": "2026-07-31",
        "note": "manual tip",
    }
    defaults.update(overrides)
    return defaults


def create_examination_case_payload(**overrides) -> dict:
    defaults = {
        "regulator": "FINCEN",
        "case_number": _seq("CASE"),
        "scope_start_date": "2025-01-01",
        "scope_end_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(target_type: str, target_id: str, **overrides) -> dict:
    defaults = {
        "severity": "DEFICIENCY",
        "target_type": target_type,
        "target_id": target_id,
        "description": "finding narrative",
    }
    defaults.update(overrides)
    return defaults
