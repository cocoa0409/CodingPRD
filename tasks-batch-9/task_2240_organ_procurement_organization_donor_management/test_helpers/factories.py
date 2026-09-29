"""Payload builders with valid defaults for every create/action endpoint.

Each builder produces the minimal admissible body and accepts overrides, so a
test can name only the field it is actually varying.  Sentinel ``OMIT`` removes
a defaulted key entirely, which is how a test exercises a declared default.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_TIMELY_WINDOW_MINUTES,
)

OMIT = object()

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short monotonically increasing token for unique-code fields."""
    return f"{next(_counter):04d}"


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------
def hospital_partner_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Mercy General",
        "hospital_code": f"MRC{unique_suffix()}",
        "timely_referral_window_minutes": DEFAULT_TIMELY_WINDOW_MINUTES,
    }
    return _apply(payload, overrides)


def recovery_team_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "team_code": f"TM{unique_suffix()}",
        "specialty": "MULTIORGAN",
    }
    return _apply(payload, overrides)


def transport_asset_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "asset_code": f"AS{unique_suffix()}",
        "mode": "GROUND",
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Referral intake
# ---------------------------------------------------------------------------
def death_referral_payload(
    hospital_partner_id: str,
    trigger_event_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hospital_partner_id": hospital_partner_id,
        "patient_mrn": f"MRN-{unique_suffix()}",
        "age_years": 40,
        "ventilated": True,
        "gcs_score": 3,
        "cause_of_death_category": "ANOXIA",
        "trigger_event_at": trigger_event_at,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
def risk_assessment_payload(
    expected_screening_version: int,
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "risk_factors": list(risk_factors or []),
        "informant_reliability": informant_reliability,
        "expected_screening_version": expected_screening_version,
    }
    return _apply(payload, overrides)


def screening_decision_payload(decision: str = "CLEARED", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    return _apply(payload, overrides)


def serology_result_payload(
    marker: str,
    result: str,
    resulted_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "marker": marker,
        "result": result,
        "resulted_at": resulted_at,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def registry_authorization_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "registry_hit": True,
        "registry_document_ref": f"REG-{unique_suffix()}",
    }
    return _apply(payload, overrides)


def nok_authorization_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"registry_hit": False}
    return _apply(payload, overrides)


def nok_contact_payload(
    relationship: str, response: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"relationship": relationship, "response": response}
    return _apply(payload, overrides)


def document_payload(document_type: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"document_type": document_type}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Donor case
# ---------------------------------------------------------------------------
def donor_case_payload(
    referral_id: str, authorization_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "referral_id": referral_id,
        "authorization_id": authorization_id,
        "donor_code": f"D-{unique_suffix()}",
    }
    return _apply(payload, overrides)


def observation_payload(
    recorded_at: str,
    map_mmhg: int = 75,
    pao2_fio2_ratio: int = 320,
    sodium: int = 140,
    urine_output_ml_per_kg_hr: float = 1.0,
    pressor_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recorded_at": recorded_at,
        "map_mmhg": map_mmhg,
        "pao2_fio2_ratio": pao2_fio2_ratio,
        "sodium": sodium,
        "urine_output_ml_per_kg_hr": urine_output_ml_per_kg_hr,
        "pressor_count": pressor_count,
    }
    return _apply(payload, overrides)


def optimized_observation_payload(recorded_at: str, **overrides: Any) -> Dict[str, Any]:
    """Vitals that score an index of 70 -- oxygenation 40, haemo 25, metabolic 5."""
    payload = observation_payload(
        recorded_at,
        map_mmhg=65,
        pao2_fio2_ratio=300,
        sodium=130,
        urine_output_ml_per_kg_hr=0.4,
        pressor_count=0,
    )
    return _apply(payload, overrides)


def decompensating_observation_payload(
    recorded_at: str, **overrides: Any
) -> Dict[str, Any]:
    """Vitals that score an index of 35 -- oxygenation 15, haemo 10, metabolic 10."""
    payload = observation_payload(
        recorded_at,
        map_mmhg=55,
        pao2_fio2_ratio=150,
        sodium=130,
        urine_output_ml_per_kg_hr=0.6,
        pressor_count=0,
    )
    return _apply(payload, overrides)


def cardiac_arrest_observation_payload(
    recorded_at: str, **overrides: Any
) -> Dict[str, Any]:
    payload = observation_payload(
        recorded_at,
        map_mmhg=40,
        pao2_fio2_ratio=90,
        sodium=160,
        urine_output_ml_per_kg_hr=0.0,
        pressor_count=3,
        cardiac_arrest=True,
    )
    return _apply(payload, overrides)


def organ_payload(organ_type: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"organ_type": organ_type}
    return _apply(payload, overrides)


def organ_evaluation_payload(decision: str = "ALLOCATABLE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
def match_run_payload(
    expected_organ_version: int,
    candidates: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_organ_version": expected_organ_version,
        "candidates": candidates,
    }
    return _apply(payload, overrides)


def offer_response_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "DECLINE":
        payload["decline_reason"] = "RECIPIENT_UNAVAILABLE"
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Recovery and transport
# ---------------------------------------------------------------------------
def recovery_operation_payload(
    recovery_team_id: str, or_start_at: str, or_end_at: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recovery_team_id": recovery_team_id,
        "or_start_at": or_start_at,
        "or_end_at": or_end_at,
    }
    return _apply(payload, overrides)


def transport_payload(
    transport_asset_id: str,
    transport_depart_at: str,
    transport_arrive_at: str,
    transport_mode: str = "GROUND",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "transport_asset_id": transport_asset_id,
        "transport_mode": transport_mode,
        "transport_depart_at": transport_depart_at,
        "transport_arrive_at": transport_arrive_at,
    }
    return _apply(payload, overrides)


def disposition_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    return _apply(payload, overrides)
