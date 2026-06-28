"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1 int"


def assert_patient(data: dict):
    _versioned(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["is_minor_at_intake"], bool)


def assert_clinician(data: dict):
    _versioned(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_state_codes"], list) and len(data["license_state_codes"]) >= 1
    assert data["role_type"] in ("DENTIST", "ORTHODONTIST")
    assert isinstance(data["active"], bool)


def assert_treatment_case(data: dict):
    _versioned(data)
    assert isinstance(data["patient_id"], str)
    assert data["intake_channel"] in ("IMPRESSION_KIT", "IN_OFFICE_SCAN")
    assert data["status"] in (
        "INTAKE_PENDING", "UNDER_REVIEW", "DECLINED", "PLAN_APPROVED",
        "ACTIVE", "REFINEMENT", "COMPLETED", "REFUNDED",
    )
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["total_contracted_cents"], int)
    assert isinstance(data["amount_collected_cents"], int)
    assert isinstance(data["refund_issued_cents"], int)
    assert isinstance(data["refinement_count"], int)
    assert isinstance(data["planned_step_count"], int)
    assert isinstance(data["guardian_consent"], bool)


def assert_intake_record(data: dict):
    _versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["channel"] in ("IMPRESSION_KIT", "IN_OFFICE_SCAN")
    assert is_iso8601_timestamp(data.get("captured_at", "")), "captured_at must be ISO 8601"
    assert 0.0 <= data["quality_score"] <= 1.0


def assert_treatment_plan(data: dict):
    _versioned(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["author_clinician_id"], str)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "ELIGIBILITY_DECLINED",
    )
    assert isinstance(data["proposed_step_count"], int) and data["proposed_step_count"] >= 1
    assert isinstance(data["weeks_per_step"], int) and data["weeks_per_step"] >= 1


def assert_aligner_step(data: dict):
    _versioned(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["step_index"], int) and data["step_index"] >= 1
    assert data["status"] in ("PLANNED", "IN_PRODUCTION", "MANUFACTURED", "SHIPPED", "VOID")


def assert_shipment(data: dict):
    _versioned(data)
    assert isinstance(data["step_id"], str)
    assert data["carrier_code"] in ("GROUND", "EXPRESS")
    assert data["status"] in ("BOOKED", "IN_TRANSIT", "DELIVERED", "CANCELLED")


def assert_progress_checkin(data: dict):
    """ProgressCheckin is append-only: id + created_at ONLY, no version/updated_at."""
    _common(data)
    assert "version" not in data, "ProgressCheckin must not carry version"
    assert "updated_at" not in data, "ProgressCheckin must not carry updated_at"
    assert isinstance(data["case_id"], str)
    assert isinstance(data["reported_step_index"], int) and data["reported_step_index"] >= 1
    assert 0.0 <= data["photo_quality_score"] <= 1.0
    assert data["tracking_assessment"] in ("PENDING", "ON_TRACK", "OFF_TRACK")


def assert_refinement_request(data: dict):
    _versioned(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["triggering_checkin_id"], str)
    assert isinstance(data["additional_step_count"], int) and data["additional_step_count"] >= 1
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED")
    assert isinstance(data["is_billable"], bool)


def assert_financing_plan(data: dict):
    _versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["term_months"] in (12, 24, 36)
    assert isinstance(data["down_payment_cents"], int)
    assert isinstance(data["apr_bps"], int)
    assert data["billing_state"] in ("PENDING_ACTIVATION", "ACTIVE", "PAID_OFF", "CANCELLED")
    assert data["delinquency_state"] in ("CURRENT", "DELINQUENT", "DEFAULTED")
    assert isinstance(data["financed_principal_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)


def assert_installment(data: dict):
    _versioned(data)
    assert isinstance(data["financing_plan_id"], str)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["principal_portion_cents"], int)
    assert data["status"] in ("SCHEDULED", "POSTED", "LATE", "WAIVED")


def assert_retainer_subscription(data: dict):
    _versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["cadence"] in ("QUARTERLY", "SEMIANNUAL")
    assert isinstance(data["per_shipment_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_refund_request(data: dict):
    _versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["reason"] in ("ELIGIBILITY_DECLINE", "PATIENT_CANCEL", "GOODWILL")
    assert data["status"] in ("OPEN", "APPROVED", "SETTLED", "REJECTED")
    assert isinstance(data["computed_refund_cents"], int)
    assert isinstance(data["restocking_fee_cents"], int)
