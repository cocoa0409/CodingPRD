"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_generator_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "GenCo",
        "hq_state_code": "OH",
        "contact_email": "g@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_offtaker_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "OffCo",
        "hq_state_code": "PA",
        "receiving_state_codes": ["PA", "WV"],
    }
    defaults.update(overrides)
    return defaults


def create_stream_payload(generator_id, **overrides) -> dict:
    defaults = {
        "generator_id": generator_id,
        "material_type": "FLY_ASH",
        "declared_moisture_pct": 9.0,
        "expected_tons_per_month": 500,
    }
    defaults.update(overrides)
    return defaults


def create_characterization_payload(**overrides) -> dict:
    defaults = {
        "lab_name": "LabCo",
        "sampled_on": "2026-07-01",
        "ph": 7.2,
        "arsenic_ppm": 3.0,
        "lead_ppm": 2.0,
        "moisture_pct_measured": 9.5,
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["DESTINATION_STATE"],
        "use_case": "CEMENT_ADDITIVE",
        "valid_from": TEST_DEFAULTS["ELIGIBILITY_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["ELIGIBILITY_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_state_permit_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["DESTINATION_STATE"],
        "material_type": "FLY_ASH",
        "regime": "PERMIT",
        "permit_number": "PA-001",
        "issued_on": TEST_DEFAULTS["PERMIT_ISSUED_ON"],
        "expires_on": TEST_DEFAULTS["PERMIT_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_agreement_payload(generator_id, stream_id, **overrides) -> dict:
    defaults = {
        "generator_id": generator_id,
        "stream_id": stream_id,
        "committed_monthly_tons": 500,
        "revenue_share_pct_to_generator": 0.6,
        "freight_share_pct_to_generator": 0.25,
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_offtake_commitment_payload(offtaker_id, stream_id, **overrides) -> dict:
    defaults = {
        "offtaker_id": offtaker_id,
        "stream_id": stream_id,
        "destination_state_code": TEST_DEFAULTS["DESTINATION_STATE"],
        "committed_monthly_tons": 500,
        "max_moisture_pct": TEST_DEFAULTS["MAX_MOISTURE_PCT"],
        "max_arsenic_ppm": TEST_DEFAULTS["MAX_ARSENIC_PPM"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(
    supply_agreement_id,
    offtake_commitment_id,
    expected_supply_agreement_version,
    **overrides,
) -> dict:
    defaults = {
        "supply_agreement_id": supply_agreement_id,
        "offtake_commitment_id": offtake_commitment_id,
        "pickup_date": TEST_DEFAULTS["PICKUP_DATE"],
        "distance_miles": TEST_DEFAULTS["DISTANCE_MILES"],
        "gross_tons": 10,
        "loading_moisture_pct": TEST_DEFAULTS["LOADING_MOISTURE_PCT"],
        "expected_supply_agreement_version": expected_supply_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(**overrides) -> dict:
    defaults = {
        "destination_moisture_pct": TEST_DEFAULTS["DESTINATION_MOISTURE_PCT"],
        "destination_arsenic_ppm": TEST_DEFAULTS["DESTINATION_ARSENIC_PPM"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_facility_payload(**overrides) -> dict:
    defaults = {
        "state_code": "OH",
        "material_types_allowed": ["FLY_ASH"],
        "capacity_tons": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_storage_reservation_payload(facility_id, stream_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "stream_id": stream_id,
        "start_date": "2026-08-01",
        "end_date": "2026-08-10",
        "tons": 100,
    }
    defaults.update(overrides)
    return defaults


def create_price_index_payload(**overrides) -> dict:
    defaults = {
        "material_type": "FLY_ASH",
        "region_code": TEST_DEFAULTS["DESTINATION_STATE"],
        "effective_from": TEST_DEFAULTS["INDEX_EFFECTIVE_FROM"],
        "price_cents_per_ton": TEST_DEFAULTS["INDEX_PRICE_CENTS_PER_TON"],
    }
    defaults.update(overrides)
    return defaults
