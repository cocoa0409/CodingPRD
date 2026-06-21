"""Payload factories — one per entity, input fields only (PRD-declared inputs)."""


DEFAULTS = {
    "AGENCY_NAME": "Acme Title",
    "REMIT_SPLIT_PCT": 0.82,
    "PARCEL_ID": "APN-1",
    "COUNTY": "King",
    "EFFECTIVE_DATE": "2026-01-05T00:00:00Z",
    "EXPIRY_DATE": "2026-07-05T00:00:00Z",
    "INSURED_AMOUNT_CENTS": 25_000_000,
    "COVERAGE_AMOUNT_CENTS": 25_000_000,
    "SALES_PRICE_CENTS": 25_000_000,
}


def create_agency_payload(**overrides) -> dict:
    """PRD §3.1: name + remit_split_pct (0..1 inclusive)."""
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "remit_split_pct": DEFAULTS["REMIT_SPLIT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_plant_record_payload(**overrides) -> dict:
    """PRD §3.1: parcel_id, county, instrument_type, recorded_date, sequence_no,
    grantor, grantee."""
    defaults = {
        "parcel_id": DEFAULTS["PARCEL_ID"],
        "county": DEFAULTS["COUNTY"],
        "instrument_type": "DEED",
        "recorded_date": "2020-01-01T00:00:00Z",
        "sequence_no": 1,
        "grantor": "A",
        "grantee": "B",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(agency_id, **overrides) -> dict:
    """PRD §3.2: agency_id, parcel_id, county, transaction_type, sales_price_cents,
    loan_amount_cents."""
    defaults = {
        "agency_id": agency_id,
        "parcel_id": DEFAULTS["PARCEL_ID"],
        "county": DEFAULTS["COUNTY"],
        "transaction_type": "PURCHASE",
        "sales_price_cents": DEFAULTS["SALES_PRICE_CENTS"],
        "loan_amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_title_search_payload(**overrides) -> dict:
    """PRD §3.3: searched_parcel_id, effective_date."""
    defaults = {
        "searched_parcel_id": DEFAULTS["PARCEL_ID"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(expected_order_version, **overrides) -> dict:
    """PRD §3.4 / §2.7: effective_date, expiry_date, schedule_a_estate,
    insured_amount_cents, expected_order_version."""
    defaults = {
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
        "schedule_a_estate": "FEE_SIMPLE",
        "insured_amount_cents": DEFAULTS["INSURED_AMOUNT_CENTS"],
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_exception_payload(**overrides) -> dict:
    """PRD §3.5: exception_type, description, optional curative_required."""
    defaults = {
        "exception_type": "STANDARD",
        "description": "Pre-printed Schedule B exception",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(commitment_id, **overrides) -> dict:
    """PRD §3.6: commitment_id, policy_type, coverage_amount_cents, optional
    is_reissue / co_issued_with_owner."""
    defaults = {
        "commitment_id": commitment_id,
        "policy_type": "OWNER",
        "coverage_amount_cents": DEFAULTS["COVERAGE_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(**overrides) -> dict:
    """PRD §3.6: form_code, charge_pct (0 < charge_pct <= 1)."""
    defaults = {
        "form_code": "ZONING",
        "charge_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    """PRD §3.7: amount_cents (> 0), source_ref."""
    defaults = {
        "amount_cents": 100_000,
        "source_ref": "WIRE-IN-1",
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(expected_order_version, **overrides) -> dict:
    """PRD §3.7 / §2.7: payee, amount_cents (> 0), purpose, wire_window_start,
    wire_window_end, expected_order_version."""
    defaults = {
        "payee": "Seller",
        "amount_cents": 100_000,
        "purpose": "SELLER_PROCEEDS",
        "wire_window_start": "2026-01-20T09:00:00Z",
        "wire_window_end": "2026-01-20T10:00:00Z",
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    """PRD §3.9: claim_type, estimated_loss_cents (>= 0)."""
    defaults = {
        "claim_type": "UNDISCLOSED_LIEN",
        "estimated_loss_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_curative_action_payload(subject_type, subject_id, **overrides) -> dict:
    """PRD §3.5: subject_type, subject_id, action_type."""
    defaults = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action_type": "PAYOFF",
    }
    defaults.update(overrides)
    return defaults
