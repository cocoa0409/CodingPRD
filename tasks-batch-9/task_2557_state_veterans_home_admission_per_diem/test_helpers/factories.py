"""Payload builders for every write endpoint.

Each builder returns a payload that satisfies the request shape described in the
PRD and accepts `**overrides` so a test can vary exactly the one field under
examination. Defaults describe an unremarkable, fully eligible nursing applicant
at a recognised home, because most scenarios only care about the deviation.
"""

from typing import Any, Dict, Optional

_home_counter = {"n": 0}
_unit_counter = {"n": 0}
_applicant_counter = {"n": 0}


def veterans_home_payload(**overrides: Any) -> Dict[str, Any]:
    _home_counter["n"] += 1
    payload: Dict[str, Any] = {
        "name": f"Willow Creek State Veterans Home {_home_counter['n']}",
        "state_code": "MN",
        "recognition_effective_date": "2026-07-01",
    }
    payload.update(overrides)
    return payload


def recognition_payload(
    action: str,
    effective_date: str,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "effective_date": effective_date}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def care_unit_payload(
    care_level: str = "NURSING",
    licensed_bed_count: int = 2,
    out_of_service_bed_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    _unit_counter["n"] += 1
    payload: Dict[str, Any] = {
        "unit_name": f"Unit {_unit_counter['n']}",
        "care_level": care_level,
        "licensed_bed_count": licensed_bed_count,
        "out_of_service_bed_count": out_of_service_bed_count,
    }
    payload.update(overrides)
    return payload


def applicant_payload(veterans_home_id: str, **overrides: Any) -> Dict[str, Any]:
    _applicant_counter["n"] += 1
    payload: Dict[str, Any] = {
        "veterans_home_id": veterans_home_id,
        "full_name": f"Applicant {_applicant_counter['n']}",
        "date_of_birth": "1950-01-01",
        "service_days": 900,
        "discharge_character": "HONORABLE",
        "wartime_service": True,
        "service_connected_disability_pct": 80,
        "nursing_care_for_service_connected": False,
        "state_residency_years": 6,
        "requested_care_level": "NURSING",
        "application_received_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def waitlist_entry_payload(applicant_id: str, care_unit_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"applicant_id": applicant_id, "care_unit_id": care_unit_id}
    payload.update(overrides)
    return payload


def clinical_assessment_payload(
    assessed_care_level: str = "NURSING",
    adl_dependency_count: int = 4,
    cognitive_impairment: bool = True,
    behavioral_risk_flag: bool = False,
    skilled_nursing_hours_per_day: float = 3.00,
    assessment_date: str = "2026-08-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "assessed_care_level": assessed_care_level,
        "adl_dependency_count": adl_dependency_count,
        "cognitive_impairment": cognitive_impairment,
        "behavioral_risk_flag": behavioral_risk_flag,
        "skilled_nursing_hours_per_day": skilled_nursing_hours_per_day,
        "assessment_date": assessment_date,
    }
    payload.update(overrides)
    return payload


def admission_decision_payload(
    care_unit_id: str,
    clinical_assessment_id: str,
    expected_care_unit_version: int,
    admission_date: str = "2026-08-01",
    decision: str = "APPROVED",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "care_unit_id": care_unit_id,
        "clinical_assessment_id": clinical_assessment_id,
        "expected_care_unit_version": expected_care_unit_version,
        "admission_date": admission_date,
    }
    payload.update(overrides)
    return payload


def income_record_payload(
    income_type: str = "SSA",
    monthly_amount_cents: int = 150000,
    effective_month: str = "2026-08",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "income_type": income_type,
        "monthly_amount_cents": monthly_amount_cents,
        "effective_month": effective_month,
    }
    payload.update(overrides)
    return payload


def income_verification_payload(decision: str = "VERIFIED", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def cost_share_payload(
    expected_resident_version: int,
    variant: str = "PROVISIONAL",
    effective_month: str = "2026-08",
    declared_medical_expense_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "variant": variant,
        "effective_month": effective_month,
        "expected_resident_version": expected_resident_version,
    }
    if declared_medical_expense_cents is not None:
        payload["declared_medical_expense_cents"] = declared_medical_expense_cents
    payload.update(overrides)
    return payload


def care_plan_payload(
    care_level: str = "NURSING",
    adl_support_level: str = "HIGH",
    plan_date: str = "2026-08-01",
    supersedes_care_plan_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "care_level": care_level,
        "adl_support_level": adl_support_level,
        "plan_date": plan_date,
    }
    if supersedes_care_plan_id is not None:
        payload["supersedes_care_plan_id"] = supersedes_care_plan_id
    payload.update(overrides)
    return payload


def transfer_payload(target_care_unit_id: str, effective_date: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_care_unit_id": target_care_unit_id,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def hospitalization_payload(hospitalization_start_date: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"hospitalization_start_date": hospitalization_start_date}
    payload.update(overrides)
    return payload


def readmission_payload(readmission_date: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"readmission_date": readmission_date}
    payload.update(overrides)
    return payload


def discharge_payload(
    discharge_date: str, discharge_reason: str = "VOLUNTARY", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "discharge_date": discharge_date,
        "discharge_reason": discharge_reason,
    }
    payload.update(overrides)
    return payload


def trust_fund_payload(
    txn_type: str,
    amount_cents: int,
    effective_date: str,
    memo: str = "test posting",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "memo": memo,
    }
    payload.update(overrides)
    return payload


def reversal_payload(memo: str = "posted to wrong resident", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"memo": memo}
    payload.update(overrides)
    return payload


def per_diem_claim_payload(
    veterans_home_id: str,
    care_unit_id: str,
    claim_month: str = "2026-08",
    basis: str = "AUDITED_BASIS",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "veterans_home_id": veterans_home_id,
        "care_unit_id": care_unit_id,
        "claim_month": claim_month,
        "basis": basis,
    }
    payload.update(overrides)
    return payload


def adjudication_payload(
    outcome: str = "PAID",
    adjudication_note: str = "reviewed",
    rejection_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "adjudication_note": adjudication_note}
    if rejection_code is not None:
        payload["rejection_code"] = rejection_code
    payload.update(overrides)
    return payload


def correction_payload(expected_claim_version: int, correction_note: str = "rate audit rerun", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_claim_version": expected_claim_version,
        "correction_note": correction_note,
    }
    payload.update(overrides)
    return payload


def survey_result_payload(
    survey_date: str,
    deficiencies: Any = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "survey_date": survey_date,
        "deficiencies": deficiencies if deficiencies is not None else [],
    }
    payload.update(overrides)
    return payload


def deficiency(scope: str, severity: str) -> Dict[str, Any]:
    return {"scope": scope, "severity": severity}


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def census_run_payload(through_date: str, veterans_home_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"through_date": through_date}
    if veterans_home_id is not None:
        payload["veterans_home_id"] = veterans_home_id
    return payload
