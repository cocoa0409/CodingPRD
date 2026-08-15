"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from .constants import DISCLOSURE_VERSION, STANDARD_PROGRAM

_name_counter = itertools.count(1)


def create_program_payload(**overrides) -> dict:
    defaults = dict(STANDARD_PROGRAM)
    defaults["name"] = f"OD-Program-{next(_name_counter)}"
    defaults.update(overrides)
    return defaults


def create_account_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "holder_name": f"Holder-{next(_name_counter)}",
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(**overrides) -> dict:
    defaults = {
        "channel": "BRANCH",
        "disclosure_version": DISCLOSURE_VERSION,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "type": "DEBIT_ONE_TIME",
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(program_id, business_date, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "business_date": business_date,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_request_payload(account_id, fee_ids, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "fee_ids": list(fee_ids),
        "kind": "FULL",
        "reason_code": "GOODWILL",
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(program_id, expected_program_version, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "parameter": "FEE_AMOUNT",
        "new_value": "3600",
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(account_id, expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "offer_type": "COUNSELING",
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(program_id, period_start, period_end, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults
