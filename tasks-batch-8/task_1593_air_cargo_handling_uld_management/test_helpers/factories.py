"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""
from .constants import (
    DEFAULT_ARRIVAL,
    DEFAULT_BUILD_END,
    DEFAULT_BUILD_START,
    DEFAULT_DEPARTURE,
)

_flight_seq = {"n": 100}
_uld_seq = {"n": 1}


def _next_flight_number() -> str:
    _flight_seq["n"] += 1
    return f"CA{_flight_seq['n']}"


def _next_uld_code() -> str:
    _uld_seq["n"] += 1
    return f"AKE{_uld_seq['n']:05d}CA"


def create_flight_payload(**overrides) -> dict:
    defaults = {
        "flight_number": _next_flight_number(),
        "origin": "SFO",
        "destination": "NRT",
        "scheduled_departure": DEFAULT_DEPARTURE,
        "scheduled_arrival": DEFAULT_ARRIVAL,
        "max_payload_kg": 1000,
        "max_volume_m3": 10,
        "uld_position_count": 2,
        "dg_certified": True,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(flight_id: str, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "shipper_ref": "SHP-1",
        "commodity_code": "GEN",
        "pieces": 1,
        "gross_weight_kg": 100,
        "volume_m3": 1,
    }
    defaults.update(overrides)
    return defaults


def create_uld_type_payload(**overrides) -> dict:
    defaults = {
        "type_code": "AKE",
        "tare_weight_kg": 100,
        "max_gross_weight_kg": 500,
        "internal_volume_m3": 4.5,
    }
    defaults.update(overrides)
    return defaults


def create_uld_payload(uld_type_id: str, **overrides) -> dict:
    defaults = {
        "uld_code": _next_uld_code(),
        "uld_type_id": uld_type_id,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(
    flight_id: str, uld_id: str, expected_flight_version: int, **overrides
) -> dict:
    defaults = {
        "flight_id": flight_id,
        "uld_id": uld_id,
        "build_start": DEFAULT_BUILD_START,
        "build_end": DEFAULT_BUILD_END,
        "expected_flight_version": expected_flight_version,
    }
    defaults.update(overrides)
    return defaults


def create_assign_payload(booking_id: str, expected_build_up_plan_version: int) -> dict:
    return {
        "booking_id": booking_id,
        "expected_build_up_plan_version": expected_build_up_plan_version,
    }


def create_weight_restriction_payload(restricted_payload_kg: float) -> dict:
    return {"restricted_payload_kg": restricted_payload_kg}


def create_rebook_payload(flight_id: str) -> dict:
    return {"flight_id": flight_id}


def create_dg_declaration_payload(**overrides) -> dict:
    defaults = {
        "un_number": "UN1263",
        "dg_class": "3",
        "packing_group": "II",
        "declaration_doc_ref": "DGD-1",
    }
    defaults.update(overrides)
    return defaults


def create_dg_rejection_payload(rejection_reason: str = "paperwork incomplete") -> dict:
    return {"rejection_reason": rejection_reason}


def create_temperature_log_payload(recorded_at: str, temperature_c: float) -> dict:
    return {"recorded_at": recorded_at, "temperature_c": temperature_c}


def create_customs_hold_payload(reason_code: str = "DOC_CHECK") -> dict:
    return {"reason_code": reason_code}


def create_hold_release_payload(release_note: str = "cleared") -> dict:
    return {"release_note": release_note}


def create_claim_payload(booking_id: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "claim_type": "DAMAGE",
        "claimed_amount": 100,
        "items": [{"weight_kg": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_settle_payload(settlement_ref: str = "PAY-1001") -> dict:
    return {"settlement_ref": settlement_ref}


def create_claim_reject_payload(reason: str = "insufficient evidence") -> dict:
    return {"reason": reason}


def create_report_damage_payload(**overrides) -> dict:
    defaults = {
        "damage_description": "torn net and dented base",
        "repair_cost_estimate": 300,
    }
    defaults.update(overrides)
    return defaults


def create_complete_repair_payload(final_repair_cost: float = 275.5) -> dict:
    return {"final_repair_cost": final_repair_cost}


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
