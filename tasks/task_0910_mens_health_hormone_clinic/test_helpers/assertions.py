"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_clinician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npi"], str)
    assert isinstance(data["dea_number"], str)


def assert_pharmacist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["sex"] in ("MALE", "OTHER")
    assert isinstance(data["email"], str)


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("CORE", "PLUS", "ELITE")
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["cycle_days"], int)


def assert_membership(data: dict):
    _assert_common(data)
    assert data["subscription_status"] in ("TRIAL", "ACTIVE", "CANCELLED")
    assert data["payment_status"] in ("CURRENT", "DELINQUENT")
    assert isinstance(data["lab_draw_credits_remaining"], int)


def assert_lab_panel(data: dict):
    _assert_common(data)
    assert data["panel_type"] in ("BASELINE", "MONITORING")
    assert data["status"] in ("ORDERED", "DRAWN", "RESULTED", "REVIEWED")


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "TITRATION_PENDING", "MONITORING_HOLD", "SUSPENDED")
    assert data["protocol_type"] in ("TRT_INJECTION", "TRT_TOPICAL", "ED_THERAPY")


def assert_prescription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "SUSPENDED", "REVOKED", "EXHAUSTED")
    assert isinstance(data["refills_remaining"], int)


def assert_refill_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_REVIEW", "DISPENSED", "CANCELLED", "REVERSED")


def assert_adverse_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("REPORTED", "MILD_LOGGED", "SEVERE_ESCALATED", "RESOLVED")
