"""Payload factories — one per entity, input fields only."""
from .constants import (
    STD_LAND_CENTS, STD_IMPROVEMENTS_CENTS,
    STD_SEVERANCE_CENTS, STD_SPECIAL_BENEFITS_CENTS,
)

DEFAULTS = {
    "PROJECT_NAME": "Right-of-Way Program",
    "AGENCY_NAME": "DOT",
    "BUDGET_CENTS": 100_000_000,
    "APPRAISER_NAME": "AX",
    "HOLDER_NAME": "Owner",
}


def create_project_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROJECT_NAME"],
        "agency_name": DEFAULTS["AGENCY_NAME"],
        "total_budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_parcel_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "apn": "APN-1",
        "total_area_sqft": 10_000,
        "take_area_sqft": 5_000,
        "take_type": "PARTIAL",
    }
    payload.update(overrides)
    return payload


def create_ownership_interest_payload(interest_type, holder_name, **overrides) -> dict:
    payload = {
        "interest_type": interest_type,
        "holder_name": holder_name,
    }
    payload.update(overrides)
    return payload


def create_appraisal_payload(expected_parcel_version, **overrides) -> dict:
    payload = {
        "appraiser_name": DEFAULTS["APPRAISER_NAME"],
        "land_value_cents": STD_LAND_CENTS,
        "improvements_value_cents": STD_IMPROVEMENTS_CENTS,
        "severance_damages_cents": STD_SEVERANCE_CENTS,
        "special_benefits_cents": STD_SPECIAL_BENEFITS_CENTS,
        "expected_parcel_version": expected_parcel_version,
    }
    payload.update(overrides)
    return payload


def create_inspection_appointment_payload(appraiser_name, start_at, end_at) -> dict:
    return {
        "appraiser_name": appraiser_name,
        "start_at": start_at,
        "end_at": end_at,
    }


def create_negotiation_payload(initial_offer_cents, **overrides) -> dict:
    payload = {"initial_offer_cents": initial_offer_cents}
    payload.update(overrides)
    return payload


def create_round_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_relocation_benefit_payload(claimant_name, occupant_type, **overrides) -> dict:
    payload = {
        "claimant_name": claimant_name,
        "occupant_type": occupant_type,
    }
    payload.update(overrides)
    return payload


def create_utility_relocation_payload(utility_type="WATER") -> dict:
    return {"utility_type": utility_type}


def create_escrow_payload(source="NEGOTIATED") -> dict:
    return {"source": source}
