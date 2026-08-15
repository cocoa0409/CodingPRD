"""Payload factories — one per creatable resource, input fields only.

Identifiers (account_number, routing_number, item_reference) are suffixed with
a process-wide counter so multiple resources created inside one test never
collide on the PRD's uniqueness rules.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_account_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "customer_name": f"Customer {n}",
        "account_number": f"ACCT-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_clearing_bank_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Clearing Bank {n}",
        "routing_number": f"9{n:08d}"[:9],
        "claim_window_business_days": TEST_DEFAULTS["CLAIM_WINDOW_BUSINESS_DAYS"],
        "warranty_window_days": TEST_DEFAULTS["WARRANTY_WINDOW_DAYS"],
        "daily_claim_capacity": TEST_DEFAULTS["DAILY_CLAIM_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_check_item_payload(depositor_account_id: str, clearing_bank_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "depositor_account_id": depositor_account_id,
        "clearing_bank_id": clearing_bank_id,
        "item_reference": f"ITM-{n:06d}",
        "amount_cents": 100000,
        "encoded_amount_cents": 100000,
        "image_quality_score": 90,
        "capture_channel": "BRANCH",
    }
    defaults.update(overrides)
    return defaults


def create_freeze_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-05-04T00:00:00Z",
        "end_at": "2026-05-08T00:00:00Z",
        "reason": "freeze window",
    }
    defaults.update(overrides)
    return defaults


def create_hold_decision_payload(**overrides) -> dict:
    defaults = {
        "hold_until": "2026-05-07T00:00:00Z",
        "reason": "supplementary review",
    }
    defaults.update(overrides)
    return defaults


def create_decide_payload(**overrides) -> dict:
    defaults = {"decision": "RELEASE_FUNDS"}
    defaults.update(overrides)
    return defaults


def create_code_payload(**overrides) -> dict:
    defaults = {"reason_code": "NSF"}
    defaults.update(overrides)
    return defaults


def create_assign_payload(assigned_analyst_id: str, expected_adjustment_case_version: int, **overrides) -> dict:
    defaults = {
        "assigned_analyst_id": assigned_analyst_id,
        "expected_adjustment_case_version": expected_adjustment_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_resolve_payload(**overrides) -> dict:
    defaults = {"disposition": "NO_ACTION"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {"claimed_amount_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {"claimed_amount_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_recredit_payload(depositor_account_id: str, check_item_id: str, **overrides) -> dict:
    defaults = {
        "depositor_account_id": depositor_account_id,
        "check_item_id": check_item_id,
        "claimed_amount_cents": 1000,
        "reason": "recredit request",
    }
    defaults.update(overrides)
    return defaults
