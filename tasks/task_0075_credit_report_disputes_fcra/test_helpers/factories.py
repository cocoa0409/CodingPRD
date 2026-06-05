"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_consumer_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "email": f"consumer{n}@example.com",
        "full_name": f"Consumer {n}",
        "ssn_last4": f"{n % 10000:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_furnisher_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "name": f"Furnisher {n}",
        "furnisher_type": "BANK",
    }
    defaults.update(overrides)
    return defaults


def create_credit_file_payload(consumer_id, **overrides) -> dict:
    defaults = {
        "consumer_id": consumer_id,
        "bureau_code": "EQUIFAX",
    }
    defaults.update(overrides)
    return defaults


def create_tradeline_payload(credit_file_id, furnisher_id, **overrides) -> dict:
    defaults = {
        "credit_file_id": credit_file_id,
        "furnisher_id": furnisher_id,
        "account_type": "REVOLVING",
        "balance_cents": 50000,
        "date_of_first_delinquency": "2021-01-01T00:00:00.000Z",
        "reported_delinquency_date": "2021-01-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(credit_file_id, tradeline_id, expected_credit_file_version, **overrides) -> dict:
    defaults = {
        "credit_file_id": credit_file_id,
        "tradeline_id": tradeline_id,
        "dispute_reason": "NOT_MINE",
        "clock_mode": "CALENDAR",
        "expected_credit_file_version": expected_credit_file_version,
    }
    defaults.update(overrides)
    return defaults


def create_reverification_payload(dispute_id, furnisher_id, **overrides) -> dict:
    defaults = {
        "dispute_id": dispute_id,
        "furnisher_id": furnisher_id,
    }
    defaults.update(overrides)
    return defaults


def respond_reverification_payload(response_type, **overrides) -> dict:
    defaults = {"response_type": response_type}
    defaults.update(overrides)
    return defaults


def create_security_freeze_payload(credit_file_id, expected_credit_file_version, **overrides) -> dict:
    defaults = {
        "credit_file_id": credit_file_id,
        "freeze_type": "FREEZE",
        "effective_at": "2026-01-05T00:00:00.000Z",
        "expected_credit_file_version": expected_credit_file_version,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(dispute_id, **overrides) -> dict:
    defaults = {
        "dispute_id": dispute_id,
        "narrative": "The dispute outcome was mishandled.",
    }
    defaults.update(overrides)
    return defaults
