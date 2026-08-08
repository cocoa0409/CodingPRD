"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_client(data: dict):
    _assert_common(data)
    assert data["status"] in ("INTAKE", "ACTIVE", "DISCHARGED")
    assert data["payer_type"] in ("INSURANCE", "SELF_PAY")
    assert isinstance(data["insurance_visits_used"], int)
    assert isinstance(data["insurance_visits_remaining"], int)


def assert_client_visit_conservation(data: dict):
    """used + remaining == authorized, an always-true invariant (PRD §3.1)."""
    assert (
        data["insurance_visits_used"] + data["insurance_visits_remaining"]
        == data["insurance_visits_authorized"]
    ), "insurance_visits_used + remaining must equal authorized"


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "ASSESSED", "CONVERTED", "DECLINED")


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_REVISION", "DISCHARGED", "SUPERSEDED")
    assert isinstance(data["revision_count"], int)


def assert_goal(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "MET", "DISCONTINUED")
    assert 0.0 <= data["progress_attendance"] <= 1.0
    assert 0.0 <= data["progress_rubric"] <= 1.0


def assert_material(data: dict):
    _assert_common(data)
    assert data["available_quantity"] >= 0, "available_quantity never negative"


def assert_material_conservation(data: dict):
    """reserved + available == on_hand, an always-true invariant (PRD §3.4)."""
    assert (
        data["reserved_quantity"] + data["available_quantity"] == data["on_hand_quantity"]
    ), "reserved + available must equal on_hand"


def assert_session(data: dict):
    _assert_common(data)
    assert data["scheduling_status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "BILLED", "ADJUDICATED")


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW", "CANCELLED")


def assert_progress_note(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SIGNED")


def assert_superbill(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "ADJUDICATED", "VOIDED")
