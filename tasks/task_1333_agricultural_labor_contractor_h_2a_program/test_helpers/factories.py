"""Payload factories — one per entity, input fields only (PRD 3.x).

Defaults follow the shared scenario literals in constants.py: the WD1 lettuce
determination and the J1 2026-09-01..2026-10-20 job order.
"""
from typing import Any, Dict, List, Optional

from .constants import J1, WD1


def set_clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def create_grower_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "legal_name": "Green Acres LLC",
        "fein": "12-3456789",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_wage_determination_payload(**overrides) -> Dict[str, Any]:
    """WD1: CA / LETTUCE / HARVEST / 2026, AEWR 1850, prevailing 1775, piece 450/BOX."""
    defaults: Dict[str, Any] = dict(WD1)
    defaults.update(overrides)
    return defaults


def create_hourly_only_determination_payload(**overrides) -> Dict[str, Any]:
    """CHILE determination with no surveyed piece rate (both piece fields null)."""
    defaults: Dict[str, Any] = {
        "state_code": "CA",
        "crop": "CHILE",
        "activity": "HARVEST",
        "effective_year": 2026,
        "aewr_hourly_cents": 700,
        "prevailing_hourly_cents": 710,
    }
    defaults.update(overrides)
    return defaults


def create_job_order_payload(grower_id: str, wage_determination_id: str, **overrides) -> Dict[str, Any]:
    """J1: 2026-09-01..2026-10-20, 8h days, 4 workers, offered 1800/400, transport 60000/75000."""
    defaults: Dict[str, Any] = {
        "grower_id": grower_id,
        "wage_determination_id": wage_determination_id,
        **J1,
    }
    defaults.update(overrides)
    return defaults


def patch_job_order_payload(expected_job_order_version: int, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"expected_job_order_version": expected_job_order_version}
    defaults.update(overrides)
    return defaults


def decide_application_payload(decision: str, qualification: str) -> Dict[str, Any]:
    return {"decision": decision, "qualification": qualification}


def create_domestic_application_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "applicant_name": "Dom Worker",
        "contact_phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": "Worker A",
        "passport_number": "P0001",
        "date_of_birth": "1990-01-01",
        "country_code": "MX",
    }
    defaults.update(overrides)
    return defaults


def create_visa_petition_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "receipt_code": "RCPT-1",
        "requested_worker_count": 1,
    }
    defaults.update(overrides)
    return defaults


def adjudicate_payload(decision: str, approved_worker_count: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if approved_worker_count is not None:
        payload["approved_worker_count"] = approved_worker_count
    return payload


def create_consular_appointment_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "consulate_code": "MEX-MTY",
        "appointment_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_housing_unit_payload(grower_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "grower_id": grower_id,
        "name": "Camp A",
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_housing_inspection_payload(inspected_on: str, result: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"inspected_on": inspected_on, "result": result}
    defaults.update(overrides)
    return defaults


def create_housing_assignment_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"move_in_date": "2026-09-01"}
    defaults.update(overrides)
    return defaults


def create_worker_assignment_payload(worker_id: str, job_order_id: str) -> Dict[str, Any]:
    return {"worker_id": worker_id, "job_order_id": job_order_id}


def end_assignment_payload(end_reason: str) -> Dict[str, Any]:
    return {"end_reason": end_reason}


def create_work_log_payload(worker_assignment_id: str, work_date: str, hours_worked: float, units_picked: int) -> Dict[str, Any]:
    return {
        "worker_assignment_id": worker_assignment_id,
        "work_date": work_date,
        "hours_worked": hours_worked,
        "units_picked": units_picked,
    }


def create_transfer_request_payload(worker_id: str, from_assignment_id: str, to_job_order_id: str, reason: str) -> Dict[str, Any]:
    return {
        "worker_id": worker_id,
        "from_assignment_id": from_assignment_id,
        "to_job_order_id": to_job_order_id,
        "reason": reason,
    }


def create_audit_case_payload(grower_id: str, trigger_source: str = "MANUAL", **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"grower_id": grower_id, "trigger_source": trigger_source}
    defaults.update(overrides)
    return defaults


def issue_findings_payload(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"findings": findings}


def finding(violation_code: str, count: int, willful: bool) -> Dict[str, Any]:
    return {"violation_code": violation_code, "count": count, "willful": willful}
