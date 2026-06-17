"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    ARRIVAL_UTC,
    DEPARTURE_UTC_1_NIGHT,
    DEFAULT_BASE_PRICE_CENTS_PER_GAL,
    DEFAULT_TANKERING_FEE_CENTS_PER_GAL,
    DEFAULT_MTOW_MID,
)


def create_operator_payload(**overrides) -> dict:
    """Operator: legal_name, contact_email (PRD §3.1)."""
    defaults = {"legal_name": "Aero Ops", "contact_email": "ops@aero.test"}
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(operator_id: str, **overrides) -> dict:
    """Aircraft: operator_id, tail_number, fuel_type, mtow_lb (PRD §3.1)."""
    defaults = {
        "operator_id": operator_id,
        "tail_number": "N100AA",
        "fuel_type": "JET_A",
        "mtow_lb": DEFAULT_MTOW_MID,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_contract_payload(operator_id: str, **overrides) -> dict:
    """FuelContract: operator_id, product, base_price_cents_per_gal, tankering_fee_cents_per_gal (PRD §3.2)."""
    defaults = {
        "operator_id": operator_id,
        "product": "JET_A",
        "base_price_cents_per_gal": DEFAULT_BASE_PRICE_CENTS_PER_GAL,
        "tankering_fee_cents_per_gal": DEFAULT_TANKERING_FEE_CENTS_PER_GAL,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(operator_id: str, aircraft_id: str, **overrides) -> dict:
    """ServiceVisit: operator_id, aircraft_id, arrival_utc, departure_utc (PRD §3.3)."""
    defaults = {
        "operator_id": operator_id,
        "aircraft_id": aircraft_id,
        "arrival_utc": ARRIVAL_UTC,
        "departure_utc": DEPARTURE_UTC_1_NIGHT,
    }
    defaults.update(overrides)
    return defaults


def create_parking_spot_payload(**overrides) -> dict:
    """ParkingSpot: label, spot_type, max_weight_class (PRD §3.4)."""
    defaults = {"label": "TD-1", "spot_type": "TIE_DOWN", "max_weight_class": "HEAVY"}
    defaults.update(overrides)
    return defaults


def create_parking_assignment_payload(service_visit_id: str, spot_id: str, **overrides) -> dict:
    """ParkingAssignment: service_visit_id, spot_id, occupy_start_utc, occupy_end_utc (PRD §3.4)."""
    defaults = {
        "service_visit_id": service_visit_id,
        "spot_id": spot_id,
        "occupy_start_utc": ARRIVAL_UTC,
        "occupy_end_utc": DEPARTURE_UTC_1_NIGHT,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_order_payload(service_visit_id: str, aircraft_id: str, fuel_contract_id: str,
                              **overrides) -> dict:
    """FuelOrder: service_visit_id, aircraft_id, fuel_contract_id, product, ordered_gallons, tankering? (PRD §3.6)."""
    defaults = {
        "service_visit_id": service_visit_id,
        "aircraft_id": aircraft_id,
        "fuel_contract_id": fuel_contract_id,
        "product": "JET_A",
        "ordered_gallons": 6000,
        "tankering": False,
    }
    defaults.update(overrides)
    return defaults


def create_into_plane_ticket_payload(fuel_order_id: str, delivered_gallons: int, **overrides) -> dict:
    """IntoPlaneTicket: fuel_order_id, delivered_gallons (PRD §3.6)."""
    defaults = {"fuel_order_id": fuel_order_id, "delivered_gallons": delivered_gallons}
    defaults.update(overrides)
    return defaults


def create_ramp_service_payload(service_visit_id: str, service_type: str = "GPU", **overrides) -> dict:
    """RampService: service_visit_id, service_type, plus de-ice fields for DE_ICE (PRD §3.8)."""
    defaults = {"service_visit_id": service_visit_id, "service_type": service_type}
    defaults.update(overrides)
    return defaults


def create_deice_service_payload(service_visit_id: str, deice_fluid_gallons: int,
                                 deice_fluid_type: str, deice_holdover_minutes: int,
                                 **overrides) -> dict:
    """DE_ICE RampService with required de-ice fields (PRD §3.8)."""
    defaults = {
        "service_visit_id": service_visit_id,
        "service_type": "DE_ICE",
        "deice_fluid_gallons": deice_fluid_gallons,
        "deice_fluid_type": deice_fluid_type,
        "deice_holdover_minutes": deice_holdover_minutes,
    }
    defaults.update(overrides)
    return defaults


def create_ramp_slot_payload(service_visit_id: str, pad_id: str,
                             window_start_utc: str, window_end_utc: str, **overrides) -> dict:
    """RampSlot: service_visit_id, pad_id, window_start_utc, window_end_utc (PRD §3.9)."""
    defaults = {
        "service_visit_id": service_visit_id,
        "pad_id": pad_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    defaults.update(overrides)
    return defaults


def pay_invoice_payload(payment_cents: int, expected_invoice_version: int, **overrides) -> dict:
    """Invoice payment: payment_cents, expected_invoice_version (PRD §3.7, §2.7)."""
    defaults = {"payment_cents": payment_cents, "expected_invoice_version": expected_invoice_version}
    defaults.update(overrides)
    return defaults


def occupy_payload(expected_assignment_version: int, **overrides) -> dict:
    """Occupy payload: expected_assignment_version (PRD §2.7, §3.4)."""
    defaults = {"expected_assignment_version": expected_assignment_version}
    defaults.update(overrides)
    return defaults
