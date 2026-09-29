"""Request-payload builders.

Each builder returns a complete, valid payload for one create operation and
accepts ``**overrides`` so a caller can vary exactly the field under test.
Passing ``None`` for a key sets it to null; to remove a key entirely, pop it
from the returned dict.
"""
from typing import Any, Dict, List, Optional

from .constants import (
    JURISDICTION_IL,
    JURISDICTION_IN,
    JURISDICTION_KY,
    REGISTRATION_YEAR,
    WEIGHT_GROUP_W80,
    DECLARED_WEIGHT_W80_LBS,
)


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

def jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(JURISDICTION_IL)
    payload.update(overrides)
    return payload


def jurisdiction_payload_for(code: str, **overrides: Any) -> Dict[str, Any]:
    source = {
        "IL": JURISDICTION_IL,
        "IN": JURISDICTION_IN,
        "KY": JURISDICTION_KY,
    }[code]
    payload = dict(source)
    payload.update(overrides)
    return payload


def weight_group_fee_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "jurisdiction_code": "IL",
        "weight_group_code": WEIGHT_GROUP_W80,
        "declared_weight_lbs": DECLARED_WEIGHT_W80_LBS,
        "annual_fee_amount": 2790.00,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Carrier and fleet
# --------------------------------------------------------------------------

def carrier_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "legal_name": "Baseline Freight Lines LLC",
        "usdot_number": "USDOT-2637000",
        "base_jurisdiction_code": "IL",
        "bond_ceiling_amount": 5000.00,
    }
    payload.update(overrides)
    return payload


def driver_payload(carrier_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "carrier_id": carrier_id,
        "full_name": "Casey Nolan",
        "cdl_number": "CDL-IL-900001",
    }
    payload.update(overrides)
    return payload


def vehicle_payload(carrier_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "carrier_id": carrier_id,
        "unit_number": "U-100",
        "vin": "1FUJGLDR0LSAA0100",
        "weight_group_code": WEIGHT_GROUP_W80,
        "factory_price_amount": 160000.00,
        "registration_year": REGISTRATION_YEAR,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Mileage
# --------------------------------------------------------------------------

def leg(jurisdiction_code: str, leg_miles: float) -> Dict[str, Any]:
    """One element of a ``legs`` or ``reconstructed_legs`` array."""
    return {"jurisdiction_code": jurisdiction_code, "leg_miles": leg_miles}


def trip_record_payload(
    carrier_id: str,
    vehicle_id: str,
    trip_start_utc: str = "2026-04-10T06:00:00Z",
    trip_end_utc: str = "2026-04-10T18:00:00Z",
    start_odometer: float = 100000.0,
    end_odometer: float = 100600.0,
    legs: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "trip_start_utc": trip_start_utc,
        "trip_end_utc": trip_end_utc,
        "start_odometer": start_odometer,
        "end_odometer": end_odometer,
        "legs": legs if legs is not None else [leg("IL", 600.0)],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Fuel
# --------------------------------------------------------------------------

def fuel_purchase_payload(
    carrier_id: str,
    vehicle_id: str,
    jurisdiction_code: str = "IL",
    purchase_date: str = "2026-04-11",
    gallons: float = 175.000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "jurisdiction_code": jurisdiction_code,
        "purchase_date": purchase_date,
        "gallons": gallons,
        "tax_paid_flag": True,
        "receipt_reference": "RCPT-IL-0001",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Quarterly returns
# --------------------------------------------------------------------------

def fuel_tax_return_payload(
    carrier_id: str,
    filing_year: int = REGISTRATION_YEAR,
    filing_quarter: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "carrier_id": carrier_id,
        "filing_year": filing_year,
        "filing_quarter": filing_quarter,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

def registration_application_payload(
    carrier_id: str,
    registration_year: int = REGISTRATION_YEAR,
    distance_basis: str = "ACTUAL_DISTANCE_BASIS",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "carrier_id": carrier_id,
        "registration_year": registration_year,
        "weight_group_code": WEIGHT_GROUP_W80,
        "distance_basis": distance_basis,
    }
    payload.update(overrides)
    return payload


def distance_schedule_line_payload(
    jurisdiction_code: str, reported_distance_miles: float, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "jurisdiction_code": jurisdiction_code,
        "reported_distance_miles": reported_distance_miles,
    }
    payload.update(overrides)
    return payload


def fleet_change_request_payload(
    registration_application_id: str,
    vehicle_id: str,
    change_type: str,
    effective_date: str,
    expected_registration_application_version: int,
    replaced_vehicle_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "registration_application_id": registration_application_id,
        "vehicle_id": vehicle_id,
        "replaced_vehicle_id": replaced_vehicle_id,
        "change_type": change_type,
        "effective_date": effective_date,
        "expected_registration_application_version": (
            expected_registration_application_version
        ),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------

def audit_selection_payload(
    carrier_id: str,
    selection_year: int = REGISTRATION_YEAR,
    selection_quarter: int = 2,
    late_filing_count: int = 0,
    retention_deficiency_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "carrier_id": carrier_id,
        "selection_year": selection_year,
        "selection_quarter": selection_quarter,
        "late_filing_count": late_filing_count,
        "retention_deficiency_count": retention_deficiency_count,
    }
    payload.update(overrides)
    return payload
