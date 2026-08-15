"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import TERM_T1, TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_term_payload(**overrides) -> dict:
    defaults = {
        "name": f"Term {_n()}",
        "start_date": TERM_T1["start_date"],
        "end_date": TERM_T1["end_date"],
    }
    defaults.update(overrides)
    return defaults


def create_break_payload(**overrides) -> dict:
    defaults = {
        "start_date": TERM_T1["break_start"],
        "end_date": TERM_T1["break_end"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "external_ref": f"EXT-{i}",
        "full_name": f"Test Student {i}",
        "email": f"student{i}@example.edu",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(term_id: str, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "institutional_charges_cents":
            TEST_DEFAULTS["INSTITUTIONAL_CHARGES_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {
        "program": "PELL_GRANT",
        "amount_cents": TEST_DEFAULTS["PELL_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_payload(**overrides) -> dict:
    defaults = {
        "withdrawal_type": "OFFICIAL",
        "notification_date": TERM_T1["day_63"],
    }
    defaults.update(overrides)
    return defaults


def create_recalculation_payload(expected_withdrawal_case_version: int,
                                 **overrides) -> dict:
    defaults = {
        "expected_withdrawal_case_version": expected_withdrawal_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_record_return_payload(amount_cents: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {
        "to_iso8601": to_iso8601,
    }
    defaults.update(overrides)
    return defaults
