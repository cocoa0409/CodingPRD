"""Payload factories — one per create/action endpoint, input fields only.

Defaults follow the canonical scenario timeline: admission 2026-08-01T08:00Z,
expected discharge 2026-08-03T10:00Z (exactly two midnight crossings, so the
PROVISIONAL benchmark is MET at intake), and a clinical summary comfortably
past the 50-character completeness gate (PRD §3.3).
"""
from .constants import (
    ADMIT_AT,
    EXPECTED_DISCHARGE_AT,
    LONG_CLINICAL_SUMMARY,
    LONG_CLINICAL_UPDATE,
    TEST_DEFAULTS,
)

DEFAULTS = {
    "PAYER_NAME": "Medicare FFS",
    "PLAN_CLASS": "MEDICARE",
    "ATTRIBUTION": "FIRST_CAUSE",
    "PHYSICIAN_NAME": "Dr. Attend",
    "PHYSICIAN_SPECIALTY": "Internal Medicine",
    "ADVISOR_NAME": "Dr. Advisor",
    "ADVISOR_SPECIALTY": "Utilization Medicine",
    "PATIENT_MRN": "MRN-0001",
    "ADMISSION_STATUS": "INPATIENT",
    "LEVEL_OF_CARE": "INPATIENT",
    "REQUESTED_DAYS": 3,
    "CC44_RATIONALE": "Inpatient criteria not met; reclassify to observation.",
    "APPEAL_ARGUMENT": "Denial contradicts documented severity indicators.",
}


def create_payer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PAYER_NAME"],
        "plan_class": DEFAULTS["PLAN_CLASS"],
        "requires_inpatient_auth": True,
        "concurrent_review_cadence_hours": TEST_DEFAULTS["CADENCE_HOURS"],
        "p2p_window_hours": TEST_DEFAULTS["P2P_WINDOW_HOURS"],
        "appeal_deadline_days": TEST_DEFAULTS["APPEAL_DEADLINE_DAYS"],
        "bed_day_budget_per_case": TEST_DEFAULTS["BED_DAY_BUDGET"],
        "avoidable_attribution_method": DEFAULTS["ATTRIBUTION"],
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PHYSICIAN_NAME"],
        "specialty": DEFAULTS["PHYSICIAN_SPECIALTY"],
        "is_advisor": False,
    }
    defaults.update(overrides)
    return defaults


def create_utilization_case_payload(payer_id: str, attending_physician_id: str,
                                    **overrides) -> dict:
    defaults = {
        "patient_mrn": DEFAULTS["PATIENT_MRN"],
        "payer_id": payer_id,
        "attending_physician_id": attending_physician_id,
        "admit_at": ADMIT_AT,
        "expected_discharge_at": EXPECTED_DISCHARGE_AT,
        "requested_admission_status": DEFAULTS["ADMISSION_STATUS"],
    }
    defaults.update(overrides)
    return defaults


def discharge_payload(discharge_at: str) -> dict:
    return {"discharge_at": discharge_at}


def create_admission_review_payload(**overrides) -> dict:
    defaults = {
        "criteria_set": "INTERQUAL",
        "severity_of_illness_points": 2,
        "intensity_of_service_points": 2,
        "comorbidity_count": 0,
        "two_midnight_attestation": False,
    }
    defaults.update(overrides)
    return defaults


def advisor_review_payload(advisor_decision: str, **overrides) -> dict:
    payload = {"advisor_decision": advisor_decision}
    payload.update(overrides)
    return payload


def create_authorization_request_payload(expected_case_version: int,
                                         **overrides) -> dict:
    defaults = {
        "level_of_care": DEFAULTS["LEVEL_OF_CARE"],
        "requested_day_count": DEFAULTS["REQUESTED_DAYS"],
        "clinical_summary": LONG_CLINICAL_SUMMARY,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def auth_payer_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resubmit_payload(clinical_summary: str) -> dict:
    return {"clinical_summary": clinical_summary}


def create_concurrent_review_payload(**overrides) -> dict:
    defaults = {
        "clinical_update": LONG_CLINICAL_UPDATE,
        "requested_additional_day_count": 2,
    }
    defaults.update(overrides)
    return defaults


def concurrent_review_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_p2p_payload(advisor_physician_id: str, scheduled_start_at: str,
                       scheduled_end_at: str) -> dict:
    return {
        "advisor_physician_id": advisor_physician_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }


def reschedule_p2p_payload(scheduled_start_at: str, scheduled_end_at: str) -> dict:
    return {
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }


def complete_p2p_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_cc44_payload(expected_case_version: int, **overrides) -> dict:
    defaults = {
        "rationale": DEFAULTS["CC44_RATIONALE"],
        "service_lines": [
            {"description": "Room", "charge_cents": 200000, "rate_milli": 500},
        ],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def cc44_concurrence_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def cc44_committee_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def cc44_rescind_payload(rescind_reason: str) -> dict:
    return {"rescind_reason": rescind_reason}


def create_avoidable_day_payload(day_date: str, barrier_code: str,
                                 barrier_weight: int) -> dict:
    return {
        "day_date": day_date,
        "barrier_code": barrier_code,
        "barrier_weight": barrier_weight,
    }


def mitigate_payload(mitigation_note: str) -> dict:
    return {"mitigation_note": mitigation_note}


def resolve_escalation_payload(resolution_note: str) -> dict:
    return {"resolution_note": resolution_note}


def apply_credit_payload(credit_days: int) -> dict:
    return {"credit_days": credit_days}


def file_appeal_payload(appeal_level: int = 1, **overrides) -> dict:
    defaults = {
        "appeal_level": appeal_level,
        "argument_summary": DEFAULTS["APPEAL_ARGUMENT"],
    }
    defaults.update(overrides)
    return defaults


def appeal_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
