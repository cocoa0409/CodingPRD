"""Payload factories — one per resource, input fields only."""
from .constants import VALID_VIN


# Canonical CA fee-schedule defaults used across the suite. use_tax_rate_bps=625
# (6.25%), with trade-in credit allowed.
CA_SCHEDULE_DEFAULTS = {
    "state_code": "CA",
    "title_fee_cents": 2000,
    "registration_fee_cents": 8500,
    "transfer_fee_cents": 1500,
    "lien_recording_fee_cents": 1000,
    "use_tax_rate_bps": 625,
    "trade_in_credit_allowed": True,
}


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = dict(CA_SCHEDULE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_type": "RETAIL",
        "legal_name": "Test Account",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(account_id: str, transaction_type: str = "REGISTRATION",
                               vin: str = VALID_VIN, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "transaction_type": transaction_type,
        "vin": vin,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(transaction_id: str, checklist_code: str,
                            file_ref: str = "file-ref-1", **overrides) -> dict:
    defaults = {
        "transaction_id": transaction_id,
        "checklist_code": checklist_code,
        "file_ref": file_ref,
    }
    defaults.update(overrides)
    return defaults


def create_runner_trip_payload(dmv_office_code: str = "CA-DMV-01", capacity: int = 5,
                               window_start_at: str = "2026-04-01T09:00:00Z",
                               window_end_at: str = "2026-04-01T12:00:00Z",
                               **overrides) -> dict:
    defaults = {
        "dmv_office_code": dmv_office_code,
        "capacity": capacity,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    defaults.update(overrides)
    return defaults


def create_lien_packet_payload(transaction_id: str, lender_name: str = "First Bank",
                               lien_amount_cents: int = 500000, **overrides) -> dict:
    defaults = {
        "transaction_id": transaction_id,
        "lender_name": lender_name,
        "lien_amount_cents": lien_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(transaction_id: str, amount_cents: int,
                           kind: str = "CHARGE", **overrides) -> dict:
    defaults = {
        "transaction_id": transaction_id,
        "amount_cents": amount_cents,
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults
