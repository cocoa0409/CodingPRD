"""Payload factories — one per creatable entity, input fields only.

Every factory accepts **overrides so tests can steer the values that matter
(thresholds, amounts, dates, classifications) while sensible defaults fill
the rest.
"""
from .constants import (
    DEFAULT_MISC_REPORTABLE_THRESHOLD_CENTS,
    DEFAULT_NEC_REPORTABLE_THRESHOLD_CENTS,
    DEFAULT_PERIOD_END_EXCLUSIVE,
    DEFAULT_PERIOD_START,
    DEFAULT_RECIPIENT_COPY_DEADLINE,
    DEFAULT_TAX_YEAR,
)

_TIN_COUNTER = {"n": 100000000}


def next_tin() -> str:
    """Generate a distinct, valid 9-digit TIN per call."""
    _TIN_COUNTER["n"] += 1
    return str(_TIN_COUNTER["n"] % 1000000000).zfill(9)


def create_tax_year_payload(**overrides) -> dict:
    defaults = {
        "tax_year": DEFAULT_TAX_YEAR,
        "period_start": DEFAULT_PERIOD_START,
        "period_end_exclusive": DEFAULT_PERIOD_END_EXCLUSIVE,
        "recipient_copy_deadline": DEFAULT_RECIPIENT_COPY_DEADLINE,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Vendor",
        "entity_classification": "INDIVIDUAL_SOLE_PROP",
        "address_line1": "1 Main St",
        "address_city": "Austin",
        "address_state": "TX",
        "address_postal": "78701",
    }
    defaults.update(overrides)
    return defaults


def create_w9_submission_payload(**overrides) -> dict:
    defaults = {
        "submitted_legal_name": "Test Vendor",
        "submitted_tin": next_tin(),
        "submitted_tin_type": "SSN",
        "signature_name": "A. Signer",
    }
    defaults.update(overrides)
    return defaults


def record_match_result_payload(**overrides) -> dict:
    defaults = {"match_result": "MATCHED"}
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "vendor_id": None,
        "source_system": "AP_ERP",
        "payment_type": "SERVICE",
        "amount_cents": 100000,
        "payment_date": "2025-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(**overrides) -> dict:
    defaults = {"tax_year": DEFAULT_TAX_YEAR, "quarter": 1}
    defaults.update(overrides)
    return defaults


def generate_returns_payload(**overrides) -> dict:
    defaults = {"tax_year": DEFAULT_TAX_YEAR}
    defaults.update(overrides)
    return defaults


def correct_return_payload(expected_return_version: int, **overrides) -> dict:
    defaults = {"expected_return_version": expected_return_version}
    defaults.update(overrides)
    return defaults


def deliver_copy_payload(**overrides) -> dict:
    defaults = {"channel": "POSTAL"}
    defaults.update(overrides)
    return defaults


def create_transmittal_payload(**overrides) -> dict:
    defaults = {"tax_year": DEFAULT_TAX_YEAR, "form_type": "NEC"}
    defaults.update(overrides)
    return defaults


def submit_transmittal_payload(**overrides) -> dict:
    defaults = {"channel": "PAPER"}
    defaults.update(overrides)
    return defaults


def create_state_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": "TX",
        "participates_in_cfsf": False,
        "direct_reporting_threshold_cents": 50000,
        "effective_from": "2020-01-01T00:00:00Z",
        "effective_to": "2030-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_b_notice_payload(**overrides) -> dict:
    defaults = {"vendor_id": None, "notice_year": DEFAULT_TAX_YEAR}
    defaults.update(overrides)
    return defaults


def create_merge_request_payload(**overrides) -> dict:
    defaults = {
        "source_vendor_id": None,
        "target_vendor_id": None,
        "reason": "duplicate vendor record",
    }
    defaults.update(overrides)
    return defaults
