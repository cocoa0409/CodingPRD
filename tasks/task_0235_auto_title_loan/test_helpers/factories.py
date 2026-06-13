"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Each factory accepts **overrides for the values tests
need to control and supplies sensible defaults for everything else.
"""
import itertools

from .constants import (
    CA_PROFILE,
    DEFAULT_TRADE_IN_VALUE_CENTS,
    DEFAULT_AUCTION_VALUE_CENTS,
    DEFAULT_CONDITION_GRADE,
    DEFAULT_PRINCIPAL_CENTS,
    DEFAULT_CONTRACT_APR_BPS,
    DEFAULT_TERM_MONTHS,
)

# Monotonic counters so unique fields (email, vin, serial_number) never collide
# within a single test's setup chain.
_email_seq = itertools.count(1)
_vin_seq = itertools.count(1)
_serial_seq = itertools.count(1)


def unique_email() -> str:
    return f"borrower{next(_email_seq)}@example.com"


def unique_vin() -> str:
    return f"VIN{next(_vin_seq):011d}"[:17]


def unique_serial() -> str:
    return f"SER-{next(_serial_seq):08d}"


def create_regulatory_profile_payload(**overrides) -> dict:
    defaults = dict(CA_PROFILE)
    defaults.update(overrides)
    return defaults


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Borrower",
        "state_code": "CA",
        "monthly_income_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(borrower_id: str, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "vin": unique_vin(),
        "year": 2019,
        "make": "Mazda",
        "model": "6",
        "odometer_miles": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(vehicle_id: str, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "trade_in_value_cents": DEFAULT_TRADE_IN_VALUE_CENTS,
        "auction_value_cents": DEFAULT_AUCTION_VALUE_CENTS,
        "condition_grade": DEFAULT_CONDITION_GRADE,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(borrower_id: str, appraisal_id: str, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "appraisal_id": appraisal_id,
        "requested_principal_cents": DEFAULT_PRINCIPAL_CENTS,
        "contract_apr_bps": DEFAULT_CONTRACT_APR_BPS,
        "term_months": DEFAULT_TERM_MONTHS,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, payment_type: str = "REGULAR", **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "payment_type": payment_type,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_payload(expected_loan_version: int, new_term_months: int, **overrides) -> dict:
    defaults = {
        "expected_loan_version": expected_loan_version,
        "new_term_months": new_term_months,
    }
    defaults.update(overrides)
    return defaults


def create_title_lien_file_payload(dmv_reference: str = "DMV-TEST-1", **overrides) -> dict:
    defaults = {"dmv_reference": dmv_reference}
    defaults.update(overrides)
    return defaults


def create_repossession_order_payload(loan_id: str, **overrides) -> dict:
    defaults = {"loan_id": loan_id}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(agent_name: str, window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "agent_name": agent_name,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(sale_proceeds_cents: int, **overrides) -> dict:
    defaults = {"sale_proceeds_cents": sale_proceeds_cents}
    defaults.update(overrides)
    return defaults


def create_device_payload(vehicle_id: str, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "serial_number": unique_serial(),
    }
    defaults.update(overrides)
    return defaults


def create_device_command_payload(command_type: str, effective_start: str, effective_end: str, **overrides) -> dict:
    defaults = {
        "command_type": command_type,
        "effective_start": effective_start,
        "effective_end": effective_end,
    }
    defaults.update(overrides)
    return defaults
