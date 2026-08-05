"""Payload factories — one per creatable resource, input fields only.

Field names are exactly the names the PRD uses in its request narratives.
"""

import itertools
from typing import Any, Dict

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for program-unique inputs (mrn, asset_tag, serial_number,
    unit_code)."""
    return f"{next(_counter):04d}"


def create_patient_payload(**overrides: Any) -> Dict[str, Any]:
    """Registration payload.  ``diet_restriction``, ``broadband_verified`` and
    ``caregiver_present`` are optional at registration and are therefore only
    included when a caller supplies them."""
    payload: Dict[str, Any] = {
        "mrn": f"MRN-{unique_suffix()}",
        "full_name": "Test Patient",
        "home_distance_km": 5.0,
        "primary_diagnosis_code": "CHF_EXAC",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "origin": "ED",
        "qualifying_condition_code": "CHF_EXAC",
        "acuity": "STANDARD",
        "referring_physician_user_id": "phys-1",
    }
    payload.update(overrides)
    return payload


def create_eligibility_assessment_payload(
    referral_id: str, in_person_eval_at: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "referral_id": referral_id,
        "in_person_eval_at": in_person_eval_at,
        "home_safety_outcome": "PASS",
        "broadband_check": "PASS",
        "caregiver_present_confirmed": True,
        "consent_signed": True,
        "assessor_user_id": "phys-1",
    }
    payload.update(overrides)
    return payload


def create_episode_payload(
    patient_id: str, referral_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "referral_id": referral_id,
        "program_track": "CMS_WAIVER",
    }
    payload.update(overrides)
    return payload


def create_visit_payload(
    episode_id: str,
    service_date: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "visit_type": "RN_IN_PERSON",
        "staff_user_id": "rn-1",
        "service_date": service_date,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "distance_km": 5.0,
    }
    payload.update(overrides)
    return payload


def create_device_kit_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"asset_tag": f"KIT-{unique_suffix()}"}
    payload.update(overrides)
    return payload


def create_device_component_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "component_type": "TABLET",
        "serial_number": f"SN-{unique_suffix()}",
        "replacement_cost_usd": 450.00,
    }
    payload.update(overrides)
    return payload


def create_monitoring_lapse_payload(
    episode_id: str, gap_start_at: str, gap_end_at: str, **overrides: Any
) -> Dict[str, Any]:
    """``cause`` is optional and defaults to ``UNKNOWN`` when omitted, so it is
    only sent when a caller supplies it."""
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "gap_start_at": gap_start_at,
        "gap_end_at": gap_end_at,
    }
    payload.update(overrides)
    return payload


def create_delivery_order_payload(episode_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "order_kind": "MEDICATION",
        "is_controlled": False,
        "cold_chain_required": False,
        "weight_kg": 1.0,
        "requested_by_user_id": "log-1",
    }
    payload.update(overrides)
    return payload


def create_meal_plan_payload(episode_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "diet_code": "NONE",
        "daily_delivery_count": 2,
    }
    payload.update(overrides)
    return payload


def create_escalation_event_payload(episode_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "reason": "VITALS_OUT_OF_RANGE",
        "opened_by_user_id": "rn-1",
    }
    payload.update(overrides)
    return payload


def create_inpatient_unit_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "unit_code": f"UNIT-{unique_suffix()}",
        "total_beds": 2,
    }
    payload.update(overrides)
    return payload


def create_bed_reservation_payload(
    unit_id: str, episode_id: str, expected_unit_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "episode_id": episode_id,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def create_billing_claim_payload(
    episode_id: str, expected_episode_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "expected_episode_version": expected_episode_version,
    }
    payload.update(overrides)
    return payload


def deploy_kit_payload(
    episode_id: str, expected_kit_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "expected_kit_version": expected_kit_version,
    }
    payload.update(overrides)
    return payload
