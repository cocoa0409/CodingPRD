"""Payload factories — one per entity, PRD input fields only."""
from .constants import (
    DEFAULT_DEMURRAGE_TIERS,
    DEFAULTS,
    FCL_BOOKING_CONTAINER_COUNT,
    FCL_BOOKING_WEIGHT_KG,
    FCL_BOOKING_VOLUME_CBM,
    LCL_BOOKING_WEIGHT_KG,
    LCL_BOOKING_VOLUME_CBM,
)


def create_shipper_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "ACME SHIPPING CO",
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_tariff_payload(**overrides) -> dict:
    defaults = {
        "tariff_code": "T-LCL-1",
        "origin_port": DEFAULTS["LANE_ORIGIN"],
        "destination_port": DEFAULTS["LANE_DESTINATION"],
        "commodity_type": "GENERAL",
        "mode": "LCL",
        "rate_per_unit_cents": DEFAULTS["LCL_RATE_PER_UNIT_CENTS"],
        "minimum_charge_cents": DEFAULTS["LCL_MINIMUM_CHARGE_CENTS"],
        "effective_from": DEFAULTS["WINDOW_FROM"],
        "effective_to": DEFAULTS["WINDOW_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_fcl_tariff_payload(**overrides) -> dict:
    defaults = create_tariff_payload(
        tariff_code="T-FCL-1",
        mode="FCL",
        container_type=DEFAULTS["FCL_CONTAINER_TYPE"],
        rate_per_unit_cents=DEFAULTS["FCL_RATE_PER_UNIT_CENTS"],
    )
    defaults.pop("minimum_charge_cents", None)
    defaults.update(overrides)
    return defaults


def create_carrier_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_number": "CARR-1",
        "carrier_name": "MAERSK",
        "service_lane": DEFAULTS["LANE"],
        "container_rates": [
            {"container_type": "40HC", "rate_cents": 120000},
        ],
        "demurrage_free_days": DEFAULTS["DEMURRAGE_FREE_DAYS"],
        "detention_free_days": DEFAULTS["DETENTION_FREE_DAYS"],
        "demurrage_tiers": [dict(t) for t in DEFAULT_DEMURRAGE_TIERS],
        "detention_per_diem_cents": DEFAULTS["DETENTION_PER_DIEM_CENTS"],
        "service_start": DEFAULTS["CONTRACT_START"],
        "service_end": DEFAULTS["CONTRACT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_surety_bond_payload(**overrides) -> dict:
    defaults = {
        "bond_number": "BOND-1",
        "surety_company": "SURETYCO",
        "coverage_amount_cents": DEFAULTS["BOND_COVERAGE_CENTS"],
        "effective_from": DEFAULTS["CONTRACT_START"],
        "effective_to": DEFAULTS["WINDOW_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_voyage_payload(carrier_contract_id: str, **overrides) -> dict:
    defaults = {
        "vessel_name": "EVER GIVEN",
        "voyage_number": "EG101",
        "carrier_contract_id": carrier_contract_id,
        "origin_port": DEFAULTS["LANE_ORIGIN"],
        "destination_port": DEFAULTS["LANE_DESTINATION"],
        "etd": DEFAULTS["VOYAGE_ETD"],
        "eta": DEFAULTS["VOYAGE_ETA"],
    }
    defaults.update(overrides)
    return defaults


def create_lcl_booking_payload(voyage_id: str, tariff_id: str, **overrides) -> dict:
    defaults = {
        "voyage_id": voyage_id,
        "tariff_id": tariff_id,
        "rate_source": "CONTRACT",
        "mode": "LCL",
        "commodity_type": "GENERAL",
        "gross_weight_kg": LCL_BOOKING_WEIGHT_KG,
        "volume_cbm": LCL_BOOKING_VOLUME_CBM,
        "terms": "PREPAID",
    }
    defaults.update(overrides)
    return defaults


def create_fcl_booking_payload(voyage_id: str, tariff_id: str, **overrides) -> dict:
    defaults = {
        "voyage_id": voyage_id,
        "tariff_id": tariff_id,
        "rate_source": "CONTRACT",
        "mode": "FCL",
        "container_type": DEFAULTS["FCL_CONTAINER_TYPE"],
        "container_count": FCL_BOOKING_CONTAINER_COUNT,
        "commodity_type": "GENERAL",
        "gross_weight_kg": FCL_BOOKING_WEIGHT_KG,
        "volume_cbm": FCL_BOOKING_VOLUME_CBM,
        "terms": "COLLECT",
    }
    defaults.update(overrides)
    return defaults


def create_consolidation_payload(voyage_id: str, **overrides) -> dict:
    defaults = {
        "voyage_id": voyage_id,
        "cfs_location": "CFS-LAX-01",
        "container_type": DEFAULTS["FCL_CONTAINER_TYPE"],
        "max_weight_kg": 10000,
        "max_volume_cbm": 100.0,
        "stuffing_window_start": "2026-08-10T00:00:00Z",
        "stuffing_window_end": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_container_assignment_payload(booking_id: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "container_number": "MSKU1234567",
        "stuffed_weight_kg": FCL_BOOKING_WEIGHT_KG,
        "stuffed_volume_cbm": FCL_BOOKING_VOLUME_CBM,
    }
    defaults.update(overrides)
    return defaults


def create_bill_of_lading_payload(booking_id: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "bl_type": "HOUSE",
        "release_mode": "SEAWAY",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_filing_payload(booking_id: str, filing_type: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "filing_type": filing_type,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(booking_id: str, invoice_type: str = "FREIGHT", **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "invoice_type": invoice_type,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(booking_id: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "coverage_type": "ALL_RISK",
        "cargo_value_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "claim_type": "DAMAGE",
        "claimed_amount_cents": 400000,
    }
    defaults.update(overrides)
    return defaults
