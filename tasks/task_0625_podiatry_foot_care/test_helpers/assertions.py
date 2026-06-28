"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_practice(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["npi"], str)
    assert isinstance(data["routine_care_min_interval_days"], int)
    assert isinstance(data["fee_split_medicare_pct"], (int, float))


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role_type"] in ("PODIATRIST", "NP_PA")
    assert isinstance(data["is_active"], bool)


def assert_modality(data: dict):
    _assert_common(data)
    assert data["modality_type"] in ("XRAY", "ULTRASOUND", "MRI")
    assert isinstance(data["cleanup_buffer_minutes"], int)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["diabetic_foot_risk_category"], int)
    assert 0 <= data["diabetic_foot_risk_category"] <= 3


def assert_prior_authorization(data: dict):
    _assert_common(data)
    assert data["service_category"] in ("DME", "ORTHOTIC", "IMAGING")
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "EXHAUSTED", "EXPIRED")
    assert isinstance(data["authorized_units"], int)
    assert isinstance(data["units_consumed"], int)
    assert isinstance(data["remaining_units"], int)
    assert data["remaining_units"] >= 0, "remaining_units floored at zero"


def assert_encounter(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "EXAM_DONE", "CODED", "SUBMITTED", "ADJUDICATED", "VOIDED")
    assert isinstance(data["total_medicare_pays_cents"], int)
    assert isinstance(data["total_patient_resp_cents"], int)


def assert_procedure(data: dict):
    _assert_common(data)
    assert data["procedure_kind"] in (
        "ROUTINE_NAIL_DEBRIDEMENT", "ROUTINE_CALLUS_PARING",
        "WOUND_DEBRIDEMENT", "NAIL_AVULSION")
    assert data["coverage_decision"] in (
        "PENDING", "COVERED", "DENIED_FREQUENCY", "DENIED_NO_QUALIFYING_DX")
    assert isinstance(data["is_routine"], bool)


def assert_orthotic_rx(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PENDING_PA", "APPROVED", "FULFILLED", "CANCELLED")
    assert data["foot_side"] in ("LEFT", "RIGHT", "BILATERAL")


def assert_lab_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUEUED", "SHIPPED", "RECEIVED", "CANCELLED")
    assert isinstance(data["total_cents"], int)


def assert_dme_dispense(data: dict):
    _assert_common(data)
    assert data["status"] in ("DISPENSED", "RETURNED")
    assert data["acquisition_mode"] in ("PURCHASE", "RENTAL")
    assert isinstance(data["this_period_charge_cents"], int)
    assert isinstance(data["cumulative_rental_paid_cents"], int)


def assert_imaging_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_referral(data: dict):
    _assert_common(data)
    assert data["specialty"] in (
        "VASCULAR", "ENDOCRINOLOGY", "ORTHOPEDIC_SURGERY", "WOUND_CARE")
    assert data["status"] == "SENT"


def assert_recall(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "COMPLETED", "CANCELLED")
    assert isinstance(data["interval_days"], int)


def assert_pa_units_invariant(data: dict):
    """remaining_units == authorized_units - units_consumed, never negative (PRD §3.6)."""
    assert data["remaining_units"] == data["authorized_units"] - data["units_consumed"], (
        f"remaining_units {data['remaining_units']} must equal "
        f"authorized_units {data['authorized_units']} - units_consumed {data['units_consumed']}"
    )
    assert data["remaining_units"] >= 0
