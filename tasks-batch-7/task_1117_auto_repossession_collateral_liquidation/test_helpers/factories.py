"""Payload factories — one per writable endpoint, input fields only.

Defaults follow the standard scenario used across the test suite: a
2,000,000c-principal loan at 1200 bps APR with 3 missed installments of
45,000c, 60,000c accrued interest, and 12,000c late fees; a GOOD-grade
vehicle appraised at 1,500,000c trade-in with a 900,000c auction guide low.
"""


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Borrower",
        "state_code": "CA",
        "email": "borrower@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_loan_account_payload(borrower_id: str, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "vin": "1HGCM82633A004352",
        "governing_state_code": "CA",
        "principal_balance_cents": 2_000_000,
        "apr_bps": 1200,
        "monthly_payment_cents": 45_000,
        "missed_installments": 3,
        "accrued_interest_cents": 60_000,
        "late_fees_cents": 12_000,
    }
    defaults.update(overrides)
    return defaults


def create_recovery_case_payload(loan_account_id: str, **overrides) -> dict:
    defaults = {
        "loan_account_id": loan_account_id,
        "default_reason": "90 days delinquent",
    }
    defaults.update(overrides)
    return defaults


def create_cure_notice_payload(expected_recovery_case_version: int, **overrides) -> dict:
    defaults = {"expected_recovery_case_version": expected_recovery_case_version}
    defaults.update(overrides)
    return defaults


def create_cure_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(kind: str, amount_cents: int, **overrides) -> dict:
    defaults = {"kind": kind, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_repo_agent_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Recovery Agent",
        "license_number": "LIC-1",
        "licensed_state_codes": ["CA"],
        "max_active_assignments": 5,
    }
    defaults.update(overrides)
    return defaults


def create_repo_assignment_payload(**overrides) -> dict:
    defaults = {
        "field_window_start": "2026-05-16T00:00:00Z",
        "field_window_end": "2026-05-18T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def report_secured_payload(**overrides) -> dict:
    defaults = {
        "odometer": 65_000,
        "condition_grade": "GOOD",
        "trade_in_value_cents": 1_500_000,
        "auction_guide_low_cents": 900_000,
    }
    defaults.update(overrides)
    return defaults


def create_property_item_payload(**overrides) -> dict:
    defaults = {"description": "personal item"}
    defaults.update(overrides)
    return defaults


def create_redemption_quote_payload(quote_type: str, expected_recovery_case_version: int, **overrides) -> dict:
    defaults = {
        "quote_type": quote_type,
        "expected_recovery_case_version": expected_recovery_case_version,
    }
    defaults.update(overrides)
    return defaults


def accept_quote_payload(payment_amount_cents: int, **overrides) -> dict:
    defaults = {"payment_amount_cents": payment_amount_cents}
    defaults.update(overrides)
    return defaults


def create_auction_house_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Auction House",
        "fee_bps": 500,
        "transport_fee_cents": 15_000,
    }
    defaults.update(overrides)
    return defaults


def create_consignment_payload(auction_house_id: str, **overrides) -> dict:
    defaults = {"auction_house_id": auction_house_id}
    defaults.update(overrides)
    return defaults


def listing_window_payload(listing_start: str, listing_end: str, **overrides) -> dict:
    defaults = {"listing_start": listing_start, "listing_end": listing_end}
    defaults.update(overrides)
    return defaults


def report_sale_payload(gross_sale_cents: int, **overrides) -> dict:
    defaults = {"gross_sale_cents": gross_sale_cents}
    defaults.update(overrides)
    return defaults


def revise_deficiency_payload(adjustment_cents: int, reason: str = "adjustment", **overrides) -> dict:
    defaults = {"adjustment_cents": adjustment_cents, "reason": reason}
    defaults.update(overrides)
    return defaults


def record_deficiency_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    defaults = {
        "category": "WRONGFUL_REPOSSESSION",
        "description": "the recovery was wrongful",
    }
    defaults.update(overrides)
    return defaults


def resolve_complaint_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults
