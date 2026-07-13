"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["risk_score"], int), "risk_score must be an integer"
    assert data["risk_tier"] in ("LOW", "MODERATE", "HIGH")
    assert isinstance(data["consent_on_file"], bool)


def assert_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["available_budget_cents"], int)
    assert isinstance(data["committed_spend_cents"], int)
    assert isinstance(data["active_enrollment_count"], int)
    assert isinstance(data["remaining_slots"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DISCHARGED", "WITHDRAWN")
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["needs_review"], bool)


def assert_care_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_REVISION", "CLOSED")
    assert data["risk_level"] in ("LOW", "MODERATE", "HIGH")


def assert_home_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["billable"], bool)


def assert_telehealth_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["billable"], bool)


def assert_billing_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED")


def assert_ed_event(data: dict):
    """EDEvent is append-only: carries id + created_at only (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["is_readmission"], bool)


def assert_budget_conserved(program: dict, budget_cap_cents: int):
    """available_budget_cents + committed_spend_cents must equal budget_cap_cents."""
    total = program["available_budget_cents"] + program["committed_spend_cents"]
    assert total == budget_cap_cents, (
        f"budget invariant broken: available({program['available_budget_cents']}) + "
        f"committed({program['committed_spend_cents']}) = {total} != cap {budget_cap_cents}"
    )


def assert_slots_conserved(program: dict, enrollment_cap: int):
    """active_enrollment_count + remaining_slots must equal enrollment_cap."""
    total = program["active_enrollment_count"] + program["remaining_slots"]
    assert total == enrollment_cap, (
        f"slot invariant broken: active({program['active_enrollment_count']}) + "
        f"remaining({program['remaining_slots']}) = {total} != cap {enrollment_cap}"
    )
