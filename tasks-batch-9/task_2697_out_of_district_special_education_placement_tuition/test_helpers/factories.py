"""
Payload factories: valid-by-default request bodies with keyword overrides.

Every monetary field is produced as a Python int so that it serialises to a JSON
integer - a monetary amount supplied as a decimal string or as a floating-point
number is a malformed request. Service-hour fields are produced as floats in
quarter-hour increments.

Each factory returns a fresh dict, so a test may mutate the result freely. Unique
natural keys (state_student_id, account_code, route_code) are suffixed from a
process-local counter to keep repeated calls inside one test distinct.
"""

import itertools
from typing import Any, Dict, List

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ─── Fiscal accounts ──────────────────────────────────────────────────────────
def fiscal_account_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fiscal_year": 2027,
        "account_code": "OOD-TUITION-2027",
        "authorized_cents": 100000000,
    }
    payload.update(overrides)
    return payload


# ─── Students ─────────────────────────────────────────────────────────────────
def student_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_student_id": f"SS-{_seq():05d}",
        "full_name": "Amara Okonkwo",
        "district_of_residence": "Northvale USD",
        "disability_category": "AUTISM",
        "iep_effective_date": "2026-08-15",
        "lre_current_setting": "RESOURCE_40_79",
    }
    payload.update(overrides)
    return payload


def medicaid_consent_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "medicaid_eligible": True,
        "medicaid_consent_on_file": True,
    }
    payload.update(overrides)
    return payload


# ─── Private schools ──────────────────────────────────────────────────────────
def private_school_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Harbor Academy",
        "state_approval_id": f"SA-{7000 + _seq()}",
        "approval_status": "APPROVED",
        "residential_capable": True,
        "medicaid_provider_number": "MP-4410",
    }
    payload.update(overrides)
    return payload


def approval_status_payload(approval_status: str) -> Dict[str, Any]:
    return {"approval_status": approval_status}


# ─── Tuition rate schedules ───────────────────────────────────────────────────
def rate_schedule_payload(
    school_id: str, expected_school_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "fiscal_year": 2027,
        "day_rate_cents": 32000,
        "residential_rate_cents": 51500,
        "service_hourly_rate_cents": 11000,
        "effective_from": "2026-07-01",
        "effective_to": "2027-06-30",
        "approval_state": "STATE_APPROVED",
        "expected_school_version": expected_school_version,
    }
    payload.update(overrides)
    return payload


# ─── Placement decisions ──────────────────────────────────────────────────────
DAY_LRE_JUSTIFICATION = (
    "Two quarters of in-district resource room support produced no measurable "
    "progress on the communication goals."
)

RESIDENTIAL_LRE_JUSTIFICATION = (
    "Medical and behavioral supports require a 24-hour therapeutic milieu that no "
    "day option on the continuum can provide."
)

DAY_CONTINUUM_OPTIONS: List[Dict[str, str]] = [
    {"setting": "GENERAL_EDUCATION_WITH_SUPPORTS", "rejected_reason": "No progress."},
    {"setting": "RESOURCE_ROOM", "rejected_reason": "Insufficient intensity."},
    {"setting": "SELF_CONTAINED_CLASS", "rejected_reason": "No certified program."},
]

RESIDENTIAL_CONTINUUM_OPTIONS: List[Dict[str, str]] = [
    {"setting": "SELF_CONTAINED_CLASS", "rejected_reason": "No overnight nursing."},
    {
        "setting": "OUT_OF_DISTRICT_DAY",
        "rejected_reason": "Regression across non-school hours.",
    },
    {"setting": "HOME_HOSPITAL", "rejected_reason": "No peer access."},
]


def placement_decision_payload(student_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "recommended_placement_type": "DAY",
        "lre_justification": DAY_LRE_JUSTIFICATION,
        "continuum_options_considered": [dict(o) for o in DAY_CONTINUUM_OPTIONS],
    }
    payload.update(overrides)
    return payload


def residential_decision_payload(student_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "recommended_placement_type": "RESIDENTIAL",
        "lre_justification": RESIDENTIAL_LRE_JUSTIFICATION,
        "continuum_options_considered": [
            dict(o) for o in RESIDENTIAL_CONTINUUM_OPTIONS
        ],
    }
    payload.update(overrides)
    return payload


def reviewer_notes_payload(notes: str = "Approved.") -> Dict[str, Any]:
    return {"reviewer_notes": notes}


# ─── Placements ───────────────────────────────────────────────────────────────
def placement_payload(
    student_id: str,
    school_id: str,
    decision_id: str,
    rate_schedule_id: str,
    fiscal_account_id: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "school_id": school_id,
        "decision_id": decision_id,
        "rate_schedule_id": rate_schedule_id,
        "fiscal_account_id": fiscal_account_id,
        "placement_type": "DAY",
        "start_date": "2026-09-01",
        "end_date": "2027-06-15",
        "contracted_instructional_days": 180,
        "contracted_residential_nights": 0,
        "transportation_required": False,
    }
    payload.update(overrides)
    return payload


def termination_payload(reason: str = "Family relocated out of district.") -> Dict[str, Any]:
    return {"termination_reason": reason}


def return_to_district_payload(
    reason: str = "Student is ready to return to a district program.",
    receiving_lre_setting: str = "SEPARATE_CLASS_UNDER_40",
) -> Dict[str, Any]:
    return {
        "return_reason": reason,
        "receiving_lre_setting": receiving_lre_setting,
    }


# ─── Service addenda ──────────────────────────────────────────────────────────
def service_addendum_payload(placement_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "service_type": "SPEECH",
        "authorized_hours_per_week": 2.0,
        "contract_weeks": 36,
        "medicaid_billable": False,
    }
    payload.update(overrides)
    return payload


# ─── Transport routes and assignments ─────────────────────────────────────────
def transport_route_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "route_code": f"R-{_seq():03d}",
        "seat_capacity": 4,
        "daily_rate_cents": 6200,
        "service_window_start_min": 360,
        "service_window_end_min": 660,
    }
    payload.update(overrides)
    return payload


def transportation_assignment_payload(
    placement_id: str, route_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "route_id": route_id,
        "pickup_window_start_min": 420,
        "pickup_window_end_min": 450,
        "days_per_week": 5,
        "contract_weeks": 36,
    }
    payload.update(overrides)
    return payload


# ─── Attendance records ───────────────────────────────────────────────────────
def service_line(addendum_id: str, hours_delivered: float) -> Dict[str, Any]:
    return {"service_addendum_id": addendum_id, "hours_delivered": hours_delivered}


def attendance_record_payload(placement_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "period_start": "2026-10-05",
        "period_end": "2026-11-01",
        "days_enrolled": 20,
        "days_attended": 20,
        "days_absent_unexcused": 0,
        "residential_nights": 0,
        "service_delivery_lines": [],
    }
    payload.update(overrides)
    return payload


def verify_attendance_payload(
    decision: str = "ACCEPT", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def amend_attendance_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "days_enrolled": 20,
        "days_attended": 18,
        "days_absent_unexcused": 2,
        "residential_nights": 0,
        "service_delivery_lines": [],
    }
    payload.update(overrides)
    return payload


# ─── Tuition invoices ─────────────────────────────────────────────────────────
def tuition_invoice_payload(
    placement_id: str,
    attendance_record_id: str,
    submitted_amount_cents: int,
    expected_placement_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "attendance_record_id": attendance_record_id,
        "billing_period_start": "2026-10-05",
        "billing_period_end": "2026-11-01",
        "submitted_amount_cents": submitted_amount_cents,
        "transport_days_billed": 0,
        "expected_placement_version": expected_placement_version,
    }
    payload.update(overrides)
    return payload


def verify_invoice_payload(basis: str = "ENROLLMENT") -> Dict[str, Any]:
    return {"basis": basis}


def resubmit_invoice_payload(
    submitted_amount_cents: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"submitted_amount_cents": submitted_amount_cents}
    payload.update(overrides)
    return payload


# ─── Reimbursement claims ─────────────────────────────────────────────────────
def reimbursement_claim_payload(
    student_id: str, fiscal_account_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "fiscal_account_id": fiscal_account_id,
        "unilateral_school_name": "Lakeside Prep",
        "claimed_tuition_cents": 4500000,
        "claimed_transport_cents": 200000,
        "claimed_instructional_days": 150,
        "notice_date": "2026-08-25",
        "unilateral_start_date": "2026-09-01",
        "unilateral_end_date": "2027-06-15",
        "prior_district_offer_date": "2026-08-20",
        "parent_cooperation": True,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(
    award_basis: str = "strict_statutory", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"award_basis": award_basis}
    payload.update(overrides)
    return payload


def remand_payload(
    remand_reason: str = "Findings insufficient to support the statutory basis.",
) -> Dict[str, Any]:
    return {"remand_reason": remand_reason}


# ─── Progress reports ─────────────────────────────────────────────────────────
def progress_report_payload(placement_id: str, quarter: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "fiscal_year": 2027,
        "quarter": quarter,
        "goals_total": 8,
        "goals_met": 6,
        "goals_regressed": 1,
        "benchmark_scaled_score": 60.0,
        "attendance_rate_pct": 90.0,
    }
    payload.update(overrides)
    return payload


def accept_report_payload(decision: str = "ACCEPT") -> Dict[str, Any]:
    return {"decision": decision}


# ─── Return transition plans ──────────────────────────────────────────────────
def transition_plan_payload(placement_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "target_return_date": "2027-08-24",
        "receiving_program": "Northvale HS Therapeutic Support Center",
    }
    payload.update(overrides)
    return payload


DEFAULT_TRANSITION_SERVICES = [
    "Transition IEP meeting",
    "Two-week reverse mainstream trial",
]


def activate_plan_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "transition_services": list(DEFAULT_TRANSITION_SERVICES),
    }
    payload.update(overrides)
    return payload


# ─── Funding claims ───────────────────────────────────────────────────────────
def funding_claim_payload(
    placement_id: str, claim_type: str = "HIGH_COST_FUND", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "claim_type": claim_type,
        "fiscal_year": 2027,
    }
    payload.update(overrides)
    return payload


def submit_to_state_payload(
    state_claim_reference: str = "STATE-HC-0001",
) -> Dict[str, Any]:
    return {"state_claim_reference": state_claim_reference}
