"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import RATE_CARD_2026_Q2


def create_rate_card_payload(**overrides) -> dict:
    """RateCard input fields (PRD §3.1). Defaults to the canonical 2026-Q2 card."""
    defaults = dict(RATE_CARD_2026_Q2)
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Customer input fields: full_name, email, fico_score (PRD §3.1)."""
    defaults = {
        "full_name": "Test Borrower",
        "email": "test@x.com",
        "fico_score": 760,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    """Vehicle input fields (PRD §3.1)."""
    defaults = {
        "vin": "VIN-TEST",
        "make_model": "Acme Sedan LX",
        "msrp_cents": 3_200_000,
        "sale_price_cents": 3_000_000,
        "residual_value_cents": 1_850_000,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(customer_id: str, vehicle_id: str, **overrides) -> dict:
    """Loan origination input fields (PRD §3.2). gap_insurance optional, defaults false."""
    defaults = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "down_payment_cents": 500_000,
        "term_months": 60,
        "gap_insurance": False,
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(customer_id: str, vehicle_id: str, **overrides) -> dict:
    """Lease origination input fields (PRD §3.5). gap_insurance optional, defaults false."""
    defaults = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "down_payment_cents": 0,
        "term_months": 36,
        "annual_mileage_allowance": 12_000,
        "per_mile_overage_rate_cents": 22.5,
        "disposition_fee_cents": 39_500,
        "purchase_option_fee_cents": 30_000,
        "gap_insurance": False,
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(amount_cents: int, kind: str = "SCHEDULED", **overrides) -> dict:
    """Payment input fields: amount_cents, kind (PRD §3.3)."""
    defaults = {"amount_cents": amount_cents, "kind": kind}
    defaults.update(overrides)
    return defaults


def declare_default_payload(insurance_settlement_cents: int, **overrides) -> dict:
    """Declare-default input fields: insurance_settlement_cents (PRD §3.3)."""
    defaults = {"insurance_settlement_cents": insurance_settlement_cents}
    defaults.update(overrides)
    return defaults


def payoff_payload(amount_cents: int, expected_loan_version: int, **overrides) -> dict:
    """Payoff input fields: amount_cents, expected_loan_version (PRD §3.4)."""
    defaults = {
        "amount_cents": amount_cents,
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(lease_id: str, election: str, odometer_miles: int,
                              expected_lease_version: int, **overrides) -> dict:
    """LeaseEndSettlement input fields (PRD §3.6). per_year_excess_miles / renew_term_months
    are election-dependent and supplied via overrides."""
    defaults = {
        "lease_id": lease_id,
        "election": election,
        "odometer_miles": odometer_miles,
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults
