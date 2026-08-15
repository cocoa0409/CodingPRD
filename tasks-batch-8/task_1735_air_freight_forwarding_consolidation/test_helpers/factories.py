"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import (
    STANDARD_AGREEMENT_VALID_FROM,
    STANDARD_AGREEMENT_VALID_TO,
    STANDARD_CUTOFF_UTC,
    STANDARD_DEPARTURE_UTC,
    STANDARD_DESTINATION,
    STANDARD_FUEL_PCT,
    STANDARD_MIN_CHARGE,
    STANDARD_ORIGIN,
    STANDARD_SECURITY_FEE,
    STANDARD_SPOT_PCT,
    STANDARD_WEIGHT_BREAKS,
)


def create_shipper_payload(**overrides) -> dict:
    defaults = {"name": "Acme Exports", "account_code": "ACME"}
    defaults.update(overrides)
    return defaults


def create_rate_agreement_payload(shipper_id: str, **overrides) -> dict:
    defaults = {
        "shipper_id": shipper_id,
        "origin_code": STANDARD_ORIGIN,
        "destination_code": STANDARD_DESTINATION,
        "weight_breaks": [dict(tier) for tier in STANDARD_WEIGHT_BREAKS],
        "min_charge_amount": STANDARD_MIN_CHARGE,
        "fuel_surcharge_pct": STANDARD_FUEL_PCT,
        "security_fee_amount": STANDARD_SECURITY_FEE,
        "spot_surcharge_pct": STANDARD_SPOT_PCT,
        "valid_from_utc": STANDARD_AGREEMENT_VALID_FROM,
        "valid_to_utc": STANDARD_AGREEMENT_VALID_TO,
    }
    defaults.update(overrides)
    return defaults


def create_flight_booking_payload(**overrides) -> dict:
    defaults = {
        "airline_code": "UA",
        "flight_number": "UA838",
        "origin_code": STANDARD_ORIGIN,
        "destination_code": STANDARD_DESTINATION,
        "scheduled_departure_utc": STANDARD_DEPARTURE_UTC,
        "cutoff_utc": STANDARD_CUTOFF_UTC,
        "booked_weight_kg": 500.0,
        "booked_volume_m3": 50.0,
    }
    defaults.update(overrides)
    return defaults


def create_master_waybill_payload(booking_id: str, **overrides) -> dict:
    defaults = {"booking_id": booking_id, "mawb_number": "180-12345675"}
    defaults.update(overrides)
    return defaults


def create_house_waybill_payload(shipper_id: str, **overrides) -> dict:
    defaults = {
        "shipper_id": shipper_id,
        "hwb_number": "HWB-A",
        "origin_code": STANDARD_ORIGIN,
        "destination_code": STANDARD_DESTINATION,
        "pieces": 5,
        "gross_weight_kg": 80.0,
        "declared_volume_m3": 0.60,
        "dg_flag": False,
    }
    defaults.update(overrides)
    return defaults


def consolidate_payload(hwb_id: str, expected_master_waybill_version: int) -> dict:
    return {
        "hwb_id": hwb_id,
        "expected_master_waybill_version": expected_master_waybill_version,
    }


def tender_payload(
    start: str = "2026-08-09T12:00:00Z", end: str = "2026-08-09T13:00:00Z"
) -> dict:
    return {"tender_window_start_utc": start, "tender_window_end_utc": end}


def measure_payload(measured_volume_m3: float) -> dict:
    return {"measured_volume_m3": measured_volume_m3}


def milestone_payload(event_code: str, event_time_utc: str, **overrides) -> dict:
    payload = {"event_code": event_code, "event_time_utc": event_time_utc}
    payload.update(overrides)
    return payload


def resolve_screening_payload(outcome: str, rejection_reason: str = None) -> dict:
    payload = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return payload


def create_customs_entry_payload(**overrides) -> dict:
    defaults = {"entry_type": "CONSUMPTION"}
    defaults.update(overrides)
    return defaults


def customs_transition_payload(target_status: str, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def create_claim_payload(hwb_id: str, **overrides) -> dict:
    defaults = {
        "hwb_id": hwb_id,
        "claim_type": "DAMAGE",
        "claimed_amount": 3000.00,
    }
    defaults.update(overrides)
    return defaults


def resolve_review_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload
