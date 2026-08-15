"""Payload factories — one per entity, input fields only (PRD §3/§4).

Optional fields with server-side defaults (planned_sellout_months,
absorption_method, control_transfer_pct_bp) are omitted unless the caller
overrides them, so default-application behavior stays observable.
"""
from .constants import TEST_DEFAULTS


def create_parcel_payload(**overrides) -> dict:
    payload = {
        "parcel_name": TEST_DEFAULTS["PARCEL_NAME"],
        "county": TEST_DEFAULTS["COUNTY"],
        "earnest_money_cents": TEST_DEFAULTS["EARNEST_MONEY_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_phase_payload(parcel_id: str, sequence_number: int = 1, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "phase_name": "PH",
        "sequence_number": sequence_number,
        "planned_lot_count": 3,
        "selling_window_start": TEST_DEFAULTS["SELLING_WINDOW_START"],
        "selling_window_end": TEST_DEFAULTS["SELLING_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def submit_plat_payload(plat_lot_count: int = 3, lot_type: str = "STANDARD",
                        **overrides) -> dict:
    payload = {"plat_lot_count": plat_lot_count, "lot_type": lot_type}
    payload.update(overrides)
    return payload


def create_bond_payload(phase_id: str, **overrides) -> dict:
    payload = {
        "phase_id": phase_id,
        "engineer_estimate_cents": TEST_DEFAULTS["ENGINEER_ESTIMATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_builder_payload(**overrides) -> dict:
    payload = {
        "builder_name": "Test Builder Co",
        "license_number": "LIC-1",
        "contact_email": "builder@example.com",
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(parcel_id: str, builder_id: str, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "builder_id": builder_id,
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
        "base_lot_price_cents": TEST_DEFAULTS["BASE_LOT_PRICE_CENTS"],
        "escalator_rate_bp_per_quarter": TEST_DEFAULTS["ESCALATOR_RATE_BP_PER_QUARTER"],
        "price_cap_bp": TEST_DEFAULTS["PRICE_CAP_BP"],
        "min_lots_per_quarter": TEST_DEFAULTS["MIN_LOTS_PER_QUARTER"],
        "scheduled_lot_count": 3,
    }
    payload.update(overrides)
    return payload


def create_closing_payload(lot_id: str, agreement_id: str, **overrides) -> dict:
    payload = {"lot_id": lot_id, "agreement_id": agreement_id}
    payload.update(overrides)
    return payload


def create_loan_payload(parcel_id: str, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "commitment_amount_cents": TEST_DEFAULTS["COMMITMENT_AMOUNT_CENTS"],
        "release_price_floor_bp": TEST_DEFAULTS["RELEASE_PRICE_FLOOR_BP"],
    }
    payload.update(overrides)
    return payload


def create_draw_payload(loan_id: str, amount_cents: int = 100000, **overrides) -> dict:
    payload = {
        "loan_id": loan_id,
        "line_items": [{"description": "site work", "amount_cents": amount_cents}],
    }
    payload.update(overrides)
    return payload


def create_hoa_payload(parcel_id: str, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "hoa_name": "Test HOA",
        "statutory_control_end": "2030-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_provider_payload(**overrides) -> dict:
    payload = {
        "provider_name": "City Water",
        "utility_type": "WATER",
        "max_connections_per_day": 4,
    }
    payload.update(overrides)
    return payload


def create_connection_payload(lot_id: str, provider_id: str,
                              scheduled_date: str = "2026-08-20T00:00:00Z",
                              **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "provider_id": provider_id,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload
