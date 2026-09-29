"""Request-payload factories.

Each factory returns only the *input* fields the PRD marks as client-supplied, so
computed and system fields (segment, quota limit, status, snapshots, counters)
never leak into a create body.  Every factory accepts `**overrides`.
"""

import itertools
from typing import Any, Dict

from .constants import TEST_DEFAULTS
from .types import (
    AmendmentType,
    BasicCategory,
    CapItemAction,
    ChallengeType,
    CourtStatus,
    CurriculumCode,
    EvidenceType,
    ReviewAction,
    SelectionSource,
    UnitType,
)

_dot_seq = itertools.count(1000001)
_code_seq = itertools.count(1)
_report_seq = itertools.count(1)
_cdl_seq = itertools.count(1)
_vin_seq = itertools.count(1)
_citation_seq = itertools.count(77001)


def create_carrier_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /carriers body.  Defaults to a MEDIUM carrier with exposure 30.0."""
    payload = {
        "dot_number": str(next(_dot_seq)),
        "legal_name": "Buckeye Freight LLC",
        "average_power_units": TEST_DEFAULTS["medium_carrier_power_units"],
        "annual_vmt": TEST_DEFAULTS["medium_carrier_annual_vmt"],
    }
    payload.update(overrides)
    return payload


def create_driver_payload(carrier_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /drivers body.  employment_status is optional and defaults to ACTIVE."""
    payload = {
        "carrier_id": carrier_id,
        "cdl_number": f"OH-D-{99000 + next(_cdl_seq)}",
        "full_name": "Dana Reyes",
    }
    payload.update(overrides)
    return payload


def create_violation_code_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /violation-codes body."""
    n = next(_code_seq)
    payload = {
        "code": f"392.{n}S",
        "description": "Speeding 15 or more over the limit",
        "basic_category": BasicCategory.UNSAFE_DRIVING,
        "severity_weight": 5,
    }
    payload.update(overrides)
    return payload


def create_intervention_threshold_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /intervention-thresholds body."""
    payload = {
        "basic_category": BasicCategory.UNSAFE_DRIVING,
        "carrier_segment": "MEDIUM",
        "effective_from": TEST_DEFAULTS["threshold_effective_from"],
        "measure_at_p50": 0.5,
        "measure_at_p65": 1.0,
        "measure_at_p80": 2.0,
    }
    payload.update(overrides)
    return payload


def create_inspection_report_payload(carrier_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /inspection-reports body."""
    n = next(_report_seq)
    payload = {
        "report_number": f"OH2026070{n:03d}",
        "inspection_state": "OH",
        "inspection_level": 2,
        "inspection_start": TEST_DEFAULTS["inspection_start"],
        "inspection_end": TEST_DEFAULTS["inspection_end"],
        "vehicle_vin": f"1FUJA6CK21LK{next(_vin_seq):05d}",
        "attributed_carrier_id": carrier_id,
        "selection_source": SelectionSource.RANDOM,
    }
    payload.update(overrides)
    return payload


def create_violation_payload(violation_code_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /inspection-reports/{id}/violations body."""
    payload = {
        "violation_code_id": violation_code_id,
        "unit_type": UnitType.VEHICLE,
    }
    payload.update(overrides)
    return payload


def create_amendment_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /inspection-reports/{id}/amendments body."""
    payload = {
        "amendment_type": AmendmentType.VIOLATION_CODE_CORRECTION,
        "rationale": "State agency correction filed by the issuing officer.",
    }
    payload.update(overrides)
    return payload


def create_data_challenge_payload(report_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /data-challenges body."""
    payload = {
        "report_id": report_id,
        "challenge_type": ChallengeType.VIOLATION_NOT_SUPPORTED,
        "narrative": "The officer narrative does not describe a speeding event.",
    }
    payload.update(overrides)
    return payload


def create_evidence_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /data-challenges/{id}/evidence body."""
    payload = {
        "evidence_type": EvidenceType.ELD_RECORD,
        "document_uri": "s3://dataqs/evidence/eld.json",
        "description": "ELD trace covering the inspection window",
    }
    payload.update(overrides)
    return payload


def review_payload(action: str = ReviewAction.ASSIGN, **overrides: Any) -> Dict[str, Any]:
    """POST /data-challenges/{id}/review body."""
    payload: Dict[str, Any] = {
        "action": action,
        "review_note": "Recorded by the federal data review officer.",
    }
    payload.update(overrides)
    return payload


def create_citation_adjudication_payload(
    violation_id: str, expected_violation_version: int, **overrides: Any
) -> Dict[str, Any]:
    """POST /citation-adjudications body (OCC-guarded, PRD 2.6)."""
    payload = {
        "violation_id": violation_id,
        "citation_number": f"OH-CIT-{next(_citation_seq)}",
        "court_date": "2026-07-20T00:00:00Z",
        "expected_violation_version": expected_violation_version,
    }
    payload.update(overrides)
    return payload


def court_result_payload(
    court_status: str = CourtStatus.CONVICTED, **overrides: Any
) -> Dict[str, Any]:
    """POST /citation-adjudications/{id}/court-result body."""
    payload: Dict[str, Any] = {
        "court_status": court_status,
        "court_note": "Court outcome recorded by the issuing state agency.",
    }
    payload.update(overrides)
    return payload


def create_coaching_assignment_payload(
    driver_id: str, violation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """POST /coaching-assignments body."""
    payload = {
        "driver_id": driver_id,
        "violation_id": violation_id,
        "curriculum_code": CurriculumCode.UNSAFE_DRIVING_101,
        "session_start": "2026-08-10T14:00:00Z",
        "session_end": "2026-08-10T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_cap_payload(
    carrier_id: str, expected_carrier_version: int, **overrides: Any
) -> Dict[str, Any]:
    """POST /corrective-action-plans body (OCC-guarded, PRD 2.6)."""
    payload = {
        "carrier_id": carrier_id,
        "expected_carrier_version": expected_carrier_version,
        "narrative": "Remediation of the findings raised by the compliance review.",
    }
    payload.update(overrides)
    return payload


def create_cap_action_item_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /corrective-action-plans/{id}/action-items body."""
    payload = {
        "basic_category": BasicCategory.HOURS_OF_SERVICE,
        "description": "Retrain all drivers on the 11-hour rule.",
        "target_completion_date": "2026-09-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def cap_item_status_payload(
    action: str = CapItemAction.COMMIT, **overrides: Any
) -> Dict[str, Any]:
    """POST /cap-action-items/{id}/status body."""
    payload: Dict[str, Any] = {"action": action, "note": f"{action} recorded."}
    payload.update(overrides)
    return payload


def create_scoring_run_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /scoring-runs body.  The snapshot is taken from the logical clock."""
    payload = {
        "note": "Monthly scoring epoch checkpoint.",
    }
    payload.update(overrides)
    return payload
