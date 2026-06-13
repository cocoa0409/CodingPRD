"""Payload factories — one per entity, input fields only."""
from .constants import (
    TERM_START,
    TERM_END,
    ENROLL_OPEN,
    ENROLL_CLOSE,
)


def create_institution_payload(**overrides) -> dict:
    """Input fields for POST /institutions. currency and refund_policy optional."""
    defaults = {"name": "Test Institution", "currency": "USD"}
    defaults.update(overrides)
    return defaults


def create_term_payload(institution_id, **overrides) -> dict:
    """Input fields for POST /institutions/terms."""
    defaults = {
        "institution_id": institution_id,
        "code": "FALL2026",
        "term_start": TERM_START,
        "term_end": TERM_END,
        "enroll_open": ENROLL_OPEN,
        "enroll_close": ENROLL_CLOSE,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(institution_id, **overrides) -> dict:
    """Input fields for POST /institutions/students."""
    defaults = {
        "institution_id": institution_id,
        "external_ref": "S1",
        "full_name": "Test Student",
        "email": "student@example.edu",
    }
    defaults.update(overrides)
    return defaults


def create_plan_template_payload(institution_id, **overrides) -> dict:
    """Input fields for POST /institutions/plan-templates.
    late_fee_grace_days and autopay_required are optional with defaults."""
    defaults = {
        "institution_id": institution_id,
        "name": "4PAY",
        "installment_count": 4,
        "down_payment_pct": 0.20,
        "plan_fee_cents": 4500,
        "late_fee_grace_days": 3,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, term_id, plan_template_id, **overrides) -> dict:
    """Input fields for POST /institutions/enrollments. autopay_enabled optional."""
    defaults = {
        "student_id": student_id,
        "term_id": term_id,
        "plan_template_id": plan_template_id,
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(enrollment_id, **overrides) -> dict:
    """Input fields for POST /institutions/charges."""
    defaults = {
        "enrollment_id": enrollment_id,
        "kind": "TUITION",
        "amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_aid_payload(enrollment_id, **overrides) -> dict:
    """Input fields for POST /institutions/aids."""
    defaults = {
        "enrollment_id": enrollment_id,
        "source": "GRANT",
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(enrollment_id, purpose, amount_cents, installment_id=None, **overrides) -> dict:
    """Input fields for POST /institutions/payments. installment_id omitted for DOWN_PAYMENT."""
    payload = {
        "enrollment_id": enrollment_id,
        "purpose": purpose,
        "amount_cents": amount_cents,
    }
    if installment_id is not None:
        payload["installment_id"] = installment_id
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    """Input field for POST /institutions/{id}/_clock/set_current_utc."""
    return {"to_iso8601": to_iso8601}


def activate_payload(expected_enrollment_version) -> dict:
    """Input field for POST /institutions/enrollments/{id}/activate."""
    return {"expected_enrollment_version": expected_enrollment_version}


def withdraw_payload(effective_date, expected_enrollment_version) -> dict:
    """Input fields for POST /institutions/enrollments/{id}/withdraw."""
    return {
        "effective_date": effective_date,
        "expected_enrollment_version": expected_enrollment_version,
    }
