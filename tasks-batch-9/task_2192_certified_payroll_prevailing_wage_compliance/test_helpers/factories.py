"""Payload factories — one per resource, input fields only."""
import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:10].upper()


def reporting_portal_payload(**overrides) -> dict:
    payload = {
        "portal_code": f"LCP{_suffix()}",
        "submission_format": "WH347_PDF",
        "cutoff_offset_days": 7,
        "grace_hours": 0,
        "requires_notarized_statement": False,
    }
    payload.update(overrides)
    return payload


def wage_determination_payload(**overrides) -> dict:
    payload = {
        "decision_number": f"CA2026{_suffix()}",
        "modification_number": 0,
        "locality_code": TEST_DEFAULTS["LOCALITY_CODE"],
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
    }
    payload.update(overrides)
    return payload


def wage_rate_payload(**overrides) -> dict:
    payload = {
        "classification_code": TEST_DEFAULTS["CLASSIFICATION_CODE"],
        "trade_code": TEST_DEFAULTS["TRADE_CODE"],
        "zone_code": "BASE",
        "base_hourly_rate_cents": TEST_DEFAULTS["BASE_HOURLY_RATE_CENTS"],
        "fringe_hourly_rate_cents": TEST_DEFAULTS["FRINGE_HOURLY_RATE_CENTS"],
        "zone_adjustment_cents": 0,
        "apprentice_scale_pct": [50, 60, 70, 80],
    }
    payload.update(overrides)
    return payload


def apprentice_program_payload(**overrides) -> dict:
    payload = {
        "registration_number": f"PROG-{_suffix()}",
        "sponsor_name": "Joint Apprenticeship Committee",
        "trade_code": TEST_DEFAULTS["TRADE_CODE"],
        "registration_status": "REGISTERED",
        "allowed_apprentice_hours_per_100_journey": 25,
        "period_count": 4,
    }
    payload.update(overrides)
    return payload


def contractor_payload(**overrides) -> dict:
    payload = {
        "legal_name": f"Contractor {_suffix()} Inc",
        "dir_registration_number": f"DIR-{_suffix()}",
    }
    payload.update(overrides)
    return payload


def staff_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Staff Member {_suffix()}",
        "capability": "BOTH",
    }
    payload.update(overrides)
    return payload


def fringe_plan_payload(**overrides) -> dict:
    payload = {
        "plan_name": f"Health Trust {_suffix()}",
        "plan_type": "BONA_FIDE_TRUST",
        "annual_contribution_cents": 1_000_000,
        "annual_total_hours": 2000.00,
        "annual_public_works_hours": 1000.00,
    }
    payload.update(overrides)
    return payload


def project_payload(wage_determination_id: str, reporting_portal_id: str, **overrides) -> dict:
    payload = {
        "project_name": f"Public Works {_suffix()}",
        "awarding_agency": "City of Testville",
        "locality_code": TEST_DEFAULTS["LOCALITY_CODE"],
        "zone_code": "BASE",
        "wage_determination_id": wage_determination_id,
        "reporting_portal_id": reporting_portal_id,
        "funding_source": "FEDERAL_DAVIS_BACON",
        "contract_award_date": TEST_DEFAULTS["CONTRACT_AWARD_DATE"],
    }
    payload.update(overrides)
    return payload


def contract_assignment_payload(contractor_id: str, **overrides) -> dict:
    payload = {
        "contractor_id": contractor_id,
        "subcontract_amount_cents": 10_000_000,
    }
    payload.update(overrides)
    return payload


def worker_payload(employer_contractor_id: str, **overrides) -> dict:
    payload = {
        "employer_contractor_id": employer_contractor_id,
        "worker_number": f"W-{_suffix()}",
        "full_name": f"Worker {_suffix()}",
        "default_classification_code": TEST_DEFAULTS["CLASSIFICATION_CODE"],
    }
    payload.update(overrides)
    return payload


def payroll_submission_payload(
    contract_assignment_id: str,
    prepared_by_staff_id: str,
    expected_contract_assignment_version: int,
    **overrides,
) -> dict:
    payload = {
        "contract_assignment_id": contract_assignment_id,
        "week_ending_date": TEST_DEFAULTS["WEEK_ENDING_DATE"],
        "prepared_by_staff_id": prepared_by_staff_id,
        "expected_contract_assignment_version": expected_contract_assignment_version,
    }
    payload.update(overrides)
    return payload


def payroll_line_payload(worker_id: str, **overrides) -> dict:
    payload = {
        "worker_id": worker_id,
        "classification_code": TEST_DEFAULTS["CLASSIFICATION_CODE"],
        "straight_hours": 40.00,
        "overtime_hours": 0.00,
        "base_rate_paid_cents": TEST_DEFAULTS["BASE_HOURLY_RATE_CENTS"],
        "overtime_rate_paid_cents": 0,
        "fringe_cash_paid_cents": TEST_DEFAULTS["FRINGE_HOURLY_RATE_CENTS"],
        "reported_as_apprentice": False,
    }
    payload.update(overrides)
    return payload


def finding_payload(project_id: str, payroll_submission_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "payroll_submission_id": payroll_submission_id,
        "finding_type": "MISCLASSIFICATION",
        "severity": "MINOR",
        "restitution_required_cents": 0,
    }
    payload.update(overrides)
    return payload


def restitution_payment_payload(worker_id: str, amount_cents: int = 1000, **overrides) -> dict:
    payload = {"worker_id": worker_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def interview_payload(
    project_id: str, contract_assignment_id: str, worker_id: str,
    window_start: str, window_end: str, **overrides,
) -> dict:
    payload = {
        "project_id": project_id,
        "contract_assignment_id": contract_assignment_id,
        "worker_id": worker_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload
