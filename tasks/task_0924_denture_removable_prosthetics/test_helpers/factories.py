"""Payload factories — one per entity, input fields only."""

from .constants import DEFAULT_CLOCK_UTC, LAB_DEFAULT_INVOICE_AMOUNT

DEFAULTS = {
    "PATIENT_NAME": "Adaeze Fenwick",
    "PATIENT_DOB": "1957-03-14",
    "PATIENT_PHONE": "555-0142",
    "CARRIER_PRIMARY": "Meridian Dental",
    "CARRIER_SECONDARY": "Harborline Health",
    "LAB_NAME": "Northgate Dental Lab",
    "EFFECTIVE_DATE": "2024-01-01T00:00:00Z",
    "FIRST_DUE_DATE": "2026-06-01T00:00:00Z",
    "CLOCK": DEFAULT_CLOCK_UTC,
}


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["PATIENT_DOB"],
        "phone": DEFAULTS["PATIENT_PHONE"],
    }
    payload.update(overrides)
    return payload


def create_coverage_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "carrier_name": DEFAULTS["CARRIER_PRIMARY"],
        "rank": "PRIMARY",
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_lab_payload(**overrides) -> dict:
    payload = {
        "lab_name": DEFAULTS["LAB_NAME"],
        "bench_line_count": 3,
        "standard_turnaround_days": 10,
        "rush_turnaround_days": 4,
    }
    payload.update(overrides)
    return payload


def create_case_payload(patient_id, prosthesis_type="FLEXIBLE_PARTIAL", **overrides) -> dict:
    payload = {"patient_id": patient_id, "prosthesis_type": prosthesis_type}
    payload.update(overrides)
    return payload


def create_case_arch_payload(case_id, arch_position="MAXILLARY", **overrides) -> dict:
    payload = {"case_id": case_id, "arch_position": arch_position}
    payload.update(overrides)
    return payload


def create_impression_payload(case_arch_id, capture_method="DIGITAL_SCAN", **overrides) -> dict:
    payload = {"case_arch_id": case_arch_id, "capture_method": capture_method}
    payload.update(overrides)
    return payload


def review_impression_payload(quality_score, **overrides) -> dict:
    payload = {"quality_score": quality_score}
    payload.update(overrides)
    return payload


def create_try_in_payload(case_arch_id, milestone_kind, **overrides) -> dict:
    payload = {"case_arch_id": case_arch_id, "milestone_kind": milestone_kind}
    payload.update(overrides)
    return payload


def create_lab_case_payload(
    case_arch_id, dental_lab_id, expected_case_arch_version, **overrides
) -> dict:
    payload = {
        "case_arch_id": case_arch_id,
        "dental_lab_id": dental_lab_id,
        "bench_line": 1,
        "turnaround_class": "STANDARD",
        "unit_count": 1,
        "purpose": "FABRICATION",
        "expected_case_arch_version": expected_case_arch_version,
        "lab_invoice_amount": LAB_DEFAULT_INVOICE_AMOUNT,
    }
    payload.update(overrides)
    return payload


def create_prosthesis_payload(case_arch_id, **overrides) -> dict:
    payload = {"case_arch_id": case_arch_id}
    payload.update(overrides)
    return payload


def create_service_payload(
    prosthesis_id, service_type, expected_prosthesis_version, **overrides
) -> dict:
    payload = {
        "prosthesis_id": prosthesis_id,
        "service_type": service_type,
        "expected_prosthesis_version": expected_prosthesis_version,
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(prosthesis_id, reported_issue, **overrides) -> dict:
    payload = {"prosthesis_id": prosthesis_id, "reported_issue": reported_issue}
    payload.update(overrides)
    return payload


def create_remake_request_payload(case_arch_id, reason_code, **overrides) -> dict:
    payload = {"case_arch_id": case_arch_id, "reason_code": reason_code}
    payload.update(overrides)
    return payload


def create_predetermination_payload(case_id, coverage_id, **overrides) -> dict:
    payload = {"case_id": case_id, "coverage_id": coverage_id}
    payload.update(overrides)
    return payload


def create_claim_payload(case_id, coverage_id, **overrides) -> dict:
    payload = {"case_id": case_id, "coverage_id": coverage_id}
    payload.update(overrides)
    return payload


def create_payment_plan_payload(
    patient_id, case_id, expected_prosthesis_case_version, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "case_id": case_id,
        "installment_count": 3,
        "down_payment_amount": 240.00,
        "first_due_date": DEFAULTS["FIRST_DUE_DATE"],
        "frequency": "MONTHLY",
        "expected_prosthesis_case_version": expected_prosthesis_case_version,
        "pay_in_full": False,
    }
    payload.update(overrides)
    return payload


def pay_installment_payload(amount_paid, **overrides) -> dict:
    payload = {"amount_paid": amount_paid}
    payload.update(overrides)
    return payload
