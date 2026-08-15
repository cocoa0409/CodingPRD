"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3).

Entity asserts are deliberately permissive about nullable/computed fields —
they validate identity, timestamps, version counters, and enum membership,
the properties the PRD pins for every reader. Value-level assertions live in
the tests themselves.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Fields every non-audit resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def assert_project(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "CLOSING", "CLOSED")
    assert data["work_posture"] in ("CLEAR", "STOPPED")
    assert isinstance(data["approved_co_total_cents"], int)
    assert isinstance(data["contingency_cents"], int)
    assert isinstance(data["single_co_cap_cents"], int)


def assert_utility_owner(data: dict):
    _assert_common_fields(data)
    assert data["owner_type"] in ("WATER", "SEWER", "GAS", "ELECTRIC", "TELECOM")
    assert isinstance(data["committed_shutdown_minutes"], int)
    assert isinstance(data["min_notice_hours"], int)
    assert isinstance(data["max_shutdown_hours"], int)


def assert_locate_ticket(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACTIVE", "EXPIRED")
    assert isinstance(data["renew_count"], int)


def assert_pothole_verification(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PLANNED", "PERFORMED", "VERIFIED", "CONFLICT", "SUPERSEDED"
    )
    assert data["method"] in ("VACUUM", "HAND_DIG")


def assert_trench_safety_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "VOIDED")
    assert data["protective_system"] in (
        "SLOPING", "BENCHING", "SHORING", "TRENCH_BOX"
    )
    assert isinstance(data["revision"], int) and data["revision"] >= 1


def assert_pipe_segment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PLANNED", "READY", "INSTALLING", "INSTALLED", "BACKFILLING",
        "COMPLETE", "ON_HOLD",
    )
    assert data["hold_reason"] in ("NONE", "STOP_WORK", "DEWATERING")
    assert isinstance(data["lifts_required"], int) and data["lifts_required"] >= 1
    assert isinstance(data["lifts_satisfied"], int) and data["lifts_satisfied"] >= 0
    assert isinstance(data["tie_in_completed"], bool)


def assert_installation_inspection(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RECORDED", "CONFIRMED", "DISPUTED")
    assert data["result"] in ("PASS", "FAIL")


def assert_shutdown_window(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PROPOSED", "CONFIRMED", "ACTIVE", "COMPLETED", "MISSED",
        "REJECTED", "CANCELLED",
    )
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0


def assert_discharge_permit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ISSUED", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["exceedance_count"], int) and data["exceedance_count"] >= 0


def assert_discharge_reading(data: dict):
    _assert_common_fields(data)
    assert data["classification"] in (
        "NORMAL", "EXCEEDS_FLOW", "EXCEEDS_TURBIDITY", "EXCEEDS_VOLUME"
    )
    assert isinstance(data["volume_gal"], int)


def assert_compaction_test(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RECORDED", "ACCEPTED", "REJECTED")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["lift_number"], int) and data["lift_number"] >= 1


def assert_as_built_package(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["within_tolerance"], bool)


def assert_unforeseen_condition(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "MITIGATING", "RESOLVED", "CLOSED_NO_ACTION")
    assert data["condition_type"] in (
        "ROCK", "GROUNDWATER", "CONTAMINATED_SOIL", "CONFLICTING_UTILITY", "VOID"
    )
    assert isinstance(data["stop_work_required"], bool)


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "COMPLETED", "SUPERSEDED"
    )
    assert isinstance(data["direct_cost_cents"], int)
    assert isinstance(data["markup_cents"], int)
    assert isinstance(data["provisional_price_cents"], int)
    assert isinstance(data["revision"], int) and data["revision"] >= 1


def assert_audit_event(data: dict):
    """Audit events are append-only: id + created_at only from the common set
    (PRD §2.4 — no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "audit events carry no version (PRD §2.4)"
    assert "updated_at" not in data, "audit events carry no updated_at (PRD §2.4)"
    for field in (
        "project_id", "actor_role", "actor_user_id", "action",
        "entity_type", "entity_id", "detail",
    ):
        assert isinstance(data.get(field), str) and data[field], (
            f"audit event {field} must be a non-empty string"
        )
