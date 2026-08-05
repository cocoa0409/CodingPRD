"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "DISCHARGED")


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "ACCEPTED", "DECLINED")


def assert_clinician(data: dict):
    _assert_common(data)
    assert data["discipline"] in ("PT", "OT")


def assert_room(data: dict):
    _assert_common(data)
    assert data["room_type"] in ("BALANCE_GYM", "EXAM", "GAIT_LAB")


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")
    assert isinstance(data["screening_score"], int)
    if data["status"] == "FINALIZED":
        assert isinstance(data["clinical_score"], int)
        assert data["fall_risk_tier"] in ("LOW", "MODERATE", "HIGH")


def assert_care_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_REASSESSMENT", "DISCHARGED")
    assert data["fall_risk_tier"] in ("LOW", "MODERATE", "HIGH")
    assert isinstance(data["target_visits"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert data["patient_responsibility_cents"] >= 0


def assert_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")
    assert isinstance(data["visits_used"], int) and data["visits_used"] >= 0


def assert_session(data: dict):
    _assert_common(data)
    assert data["attendance_status"] in ("SCHEDULED", "ATTENDED", "NO_SHOW", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "BILLED", "REVERSED")
    assert isinstance(data["copay_cents"], int)


def assert_home_safety_evaluation(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")
    if data["status"] == "FINALIZED":
        assert isinstance(data["home_hazard_score"], int)
        assert data["hazard_tier"] in ("LOW", "MODERATE", "HIGH")


def assert_device_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "DECLINED", "DISPENSED")
    assert data["source"] in ("MANUAL", "AUTO_HAZARD")
    assert data["device_type"] in ("CANE", "WALKER", "ROLLATOR", "GRAB_BAR")


def assert_community_linkage(data: dict):
    _assert_common(data)
    assert data["status"] in ("REFERRED", "ENROLLED", "COMPLETED", "DECLINED", "WITHDRAWN")


def assert_reassessment(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")
