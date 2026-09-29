"""Payload factories — one per entity, carrying only client-supplied fields."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS
from .types import (
    AppealGrounds,
    CaseTriggerReason,
    DirectCareClass,
    NurseGroup,
    SupportType,
    VerificationOutcome,
    WorkerType,
)


def create_facility_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "ccn": TEST_DEFAULTS["FACILITY_CCN"],
        "name": TEST_DEFAULTS["FACILITY_NAME"],
        "state_code": TEST_DEFAULTS["FACILITY_STATE_CODE"],
        "certified_bed_count": TEST_DEFAULTS["FACILITY_BED_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_reporting_period_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "period_code": TEST_DEFAULTS["PERIOD_CODE"],
        "state_code": TEST_DEFAULTS["FACILITY_STATE_CODE"],
        "start_date": TEST_DEFAULTS["PERIOD_START"],
        "end_date": TEST_DEFAULTS["PERIOD_END"],
        "submission_deadline": TEST_DEFAULTS["PERIOD_DEADLINE"],
        "correction_window_end": TEST_DEFAULTS["PERIOD_CORRECTION_END"],
    }
    payload.update(overrides)
    return payload


def create_job_category_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": "RN",
        "cms_job_code": 5,
        "direct_care_class": DirectCareClass.DIRECT_CARE.value,
        "nurse_group": NurseGroup.RN.value,
        "direct_care_credit_pct": 1.00,
        "weekend_countable": True,
    }
    payload.update(overrides)
    return payload


def create_worker_payload(
    facility_id: str, primary_job_category_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_id": facility_id,
        "full_name": "Riley Nurse",
        "worker_type": WorkerType.EMPLOYEE.value,
        "primary_job_category_id": primary_job_category_id,
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "vendor_name": TEST_DEFAULTS["VENDOR_NAME"],
        "tax_id": TEST_DEFAULTS["VENDOR_TAX_ID"],
        "attestation_contact": TEST_DEFAULTS["VENDOR_CONTACT"],
    }
    payload.update(overrides)
    return payload


def create_payroll_record_payload(
    facility_id: str, worker_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "worker_id": worker_id,
        "pay_period_start": "2026-04-01",
        "pay_period_end": "2026-04-01",
        "paid_hours": 8.00,
        "support_type": SupportType.TIMECARD.value,
        "document_ref": "TC-20260401",
    }
    payload.update(overrides)
    return payload


def create_submission_payload(
    facility_id: str, reporting_period_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "reporting_period_id": reporting_period_id,
    }
    payload.update(overrides)
    return payload


def allocation_line(job_category_id: str, percent: float) -> Dict[str, Any]:
    return {"job_category_id": job_category_id, "percent": percent}


def create_hour_entry_payload(
    submission_id: str,
    worker_id: str,
    job_category_id: str,
    expected_submission_version: int,
    work_date: str = "2026-04-01",
    shift_start: str = "07:00",
    shift_end: str = "15:00",
    allocations: Optional[List[Dict[str, Any]]] = None,
    payroll_record_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "submission_id": submission_id,
        "worker_id": worker_id,
        "job_category_id": job_category_id,
        "work_date": work_date,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "allocations": (
            allocations
            if allocations is not None
            else [allocation_line(job_category_id, 100.00)]
        ),
        "expected_submission_version": expected_submission_version,
    }
    if payroll_record_id is not None:
        payload["payroll_record_id"] = payroll_record_id
    payload.update(overrides)
    return payload


def replace_allocations_payload(
    allocations: List[Dict[str, Any]], expected_submission_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "allocations": allocations,
        "expected_submission_version": expected_submission_version,
    }
    payload.update(overrides)
    return payload


def create_census_day_payload(
    submission_id: str,
    census_date: str = "2026-04-01",
    resident_count: int = 5,
    mds_resident_count: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "submission_id": submission_id,
        "census_date": census_date,
        "resident_count": resident_count,
    }
    if mds_resident_count is not None:
        payload["mds_resident_count"] = mds_resident_count
    payload.update(overrides)
    return payload


def vendor_batch_line(
    worker_id: str,
    job_category_id: str,
    work_date: str,
    shift_start: str = "07:00",
    shift_end: str = "15:00",
    allocations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "worker_id": worker_id,
        "job_category_id": job_category_id,
        "work_date": work_date,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "allocations": (
            allocations
            if allocations is not None
            else [allocation_line(job_category_id, 100.00)]
        ),
    }


def create_vendor_submission_payload(
    vendor_id: str,
    facility_id: str,
    reporting_period_id: str,
    lines: List[Dict[str, Any]],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "facility_id": facility_id,
        "reporting_period_id": reporting_period_id,
        "attested_by": TEST_DEFAULTS["VENDOR_ATTESTED_BY"],
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def verify_hour_entry_payload(
    outcome: str = VerificationOutcome.SUPPORTED.value, **overrides
) -> Dict[str, Any]:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_staffing_measure_payload(submission_id: str, **overrides) -> Dict[str, Any]:
    payload = {"submission_id": submission_id}
    payload.update(overrides)
    return payload


def create_discrepancy_case_payload(
    facility_id: str,
    submission_id: str,
    trigger_reason: str = CaseTriggerReason.CENSUS_MISMATCH.value,
    detail: str = "Reported census conflicts with the state register.",
    staffing_measure_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_id": facility_id,
        "submission_id": submission_id,
        "trigger_reason": trigger_reason,
        "detail": detail,
    }
    if staffing_measure_id is not None:
        payload["staffing_measure_id"] = staffing_measure_id
    payload.update(overrides)
    return payload


def create_rating_appeal_payload(
    staffing_measure_id: str,
    expected_measure_version: int,
    grounds: str = AppealGrounds.DATA_ENTRY_ERROR.value,
    narrative: str = "Two RN shifts were keyed against the wrong reporting period.",
    discrepancy_case_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "staffing_measure_id": staffing_measure_id,
        "grounds": grounds,
        "narrative": narrative,
        "expected_measure_version": expected_measure_version,
    }
    if discrepancy_case_id is not None:
        payload["discrepancy_case_id"] = discrepancy_case_id
    payload.update(overrides)
    return payload
