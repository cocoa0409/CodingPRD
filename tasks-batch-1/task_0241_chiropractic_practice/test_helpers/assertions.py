"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape against the PRD's wire
contract. common_fields:true entities must carry id/created_at/updated_at/
version; LedgerEntry carries only id + created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npi"], str)
    assert isinstance(data["license_state"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["room_type"] in ("ADJUSTMENT", "IMAGING")
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["turnover_buffer_minutes"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert data["visit_type"] in ("ADJUSTMENT", "EXAM", "RE_EXAM", "X_RAY", "THERAPY")
    assert isinstance(data["cash_rate_cents"], int) and data["cash_rate_cents"] >= 0
    assert isinstance(data["billed_amount_cents"], int) and data["billed_amount_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_wellness_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["included_adjustments_per_month"], int)
    assert 0.0 <= data["overage_discount_pct"] <= 1.0
    assert data["status"] == "ACTIVE"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["payer_mode"] in ("INSURANCE", "CASH", "WELLNESS")
    assert isinstance(data["no_show_strike_count"], int) and data["no_show_strike_count"] >= 0
    assert isinstance(data["ledger_balance_cents"], int)
    assert isinstance(data["is_dismissed"], bool)
    assert data["status"] in ("ACTIVE", "DISMISSED")


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert isinstance(data["carrier_name"], str)
    assert isinstance(data["annual_visit_cap"], int) and data["annual_visit_cap"] >= 0
    assert isinstance(data["visits_reserved"], int) and data["visits_reserved"] >= 0
    assert isinstance(data["visits_committed"], int) and data["visits_committed"] >= 0
    assert isinstance(data["deductible_total_cents"], int)
    assert isinstance(data["deductible_met_cents"], int)
    assert 0.0 <= data["coinsurance_pct"] <= 1.0
    assert isinstance(data["allowed_amount_cents"], int)
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_exam(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["exam_type"] in ("INITIAL", "RE_EXAM")
    assert isinstance(data["imaging_ordered"], bool)
    assert 1 <= data["severity_score"] <= 10
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("exam_record_id", ""))
    assert data["current_phase"] in ("ACUTE", "CORRECTIVE", "MAINTENANCE")
    assert isinstance(data["total_planned_visits"], int)
    assert isinstance(data["visits_delivered"], int)
    assert data["status"] in ("PROPOSED", "ACTIVE", "COMPLETED", "DISCONTINUED")


def assert_plan_phase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("treatment_plan_id", ""))
    assert data["phase_type"] in ("ACUTE", "CORRECTIVE", "MAINTENANCE")
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 0
    assert 1 <= data["visits_per_week"] <= 7
    assert data["planned_visit_count"] >= 1
    assert isinstance(data["visits_completed"], int)
    assert data["status"] in ("PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_appointment_series(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("treatment_plan_id", ""))
    assert is_valid_uuid(data.get("plan_phase_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("treatment_room_id", ""))
    assert isinstance(data["weekday_pattern"], list)
    assert 0 <= data["start_time_minutes"] < 1440
    assert 1 <= data["duration_minutes"] <= 240
    assert isinstance(data["generated_count"], int)
    assert data["status"] in ("SCHEDULED", "REGENERATED", "CANCELLED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("treatment_room_id", ""))
    assert data["visit_type"] in ("ADJUSTMENT", "EXAM", "RE_EXAM", "X_RAY", "THERAPY")
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert 1 <= data["duration_minutes"] <= 240
    assert isinstance(data["counts_against_cap"], bool)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert isinstance(data["insurance_paid_cents"], int)
    assert isinstance(data["no_show_fee_cents"], int)
    assert data["attendance_status"] in (
        "BOOKED", "CHECKED_IN", "ATTENDED", "NO_SHOW", "CANCELLED", "LATE_CANCEL",
    )
    assert data["billing_status"] in ("UNBILLED", "POSTED", "ADJUDICATED", "WRITTEN_OFF")


def assert_soap_note(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    for sec in ("subjective", "objective", "assessment", "plan"):
        assert sec in data
    assert data["status"] in ("DRAFT", "SIGNED")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only (id + created_at only; no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data["entry_type"] in (
        "CHARGE", "INSURANCE_PAYMENT", "PATIENT_PAYMENT", "NO_SHOW_FEE", "WRITE_OFF",
    )
    assert isinstance(data["amount_cents"], int)
