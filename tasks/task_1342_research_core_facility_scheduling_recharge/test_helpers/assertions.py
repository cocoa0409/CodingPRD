"""Entity assertions and domain invariant checkers (PRD §2.2, §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_user(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["affiliation"] in ("INTERNAL", "EXTERNAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["is_pi"], bool)


def assert_instrument(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("AVAILABLE", "DOWN", "MAINTENANCE", "RETIRED")
    assert isinstance(data["requires_training"], bool)
    assert isinstance(data["booking_buffer_minutes"], int)


def assert_training_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "CERTIFIED", "EXPIRED", "REVOKED")
    assert isinstance(data["user_id"], str)
    assert isinstance(data["instrument_id"], str)


def assert_grant(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED", "CLOSED")
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["budget_encumbered_cents"], int)
    assert isinstance(data["budget_used_cents"], int)
    assert isinstance(data["budget_available_cents"], int)


def assert_grant_ledger_invariants(data: dict):
    """PRD §2.10: available == total - encumbered - used must always hold."""
    assert data["budget_available_cents"] == (
        data["budget_total_cents"]
        - data["budget_encumbered_cents"]
        - data["budget_used_cents"]
    ), f"grant ledger invariant violated: {data}"


def assert_rate_set(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "APPROVED", "EFFECTIVE", "SUPERSEDED")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["lines"], list)


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "IN_PROGRESS", "COMPLETED",
        "CANCELLED", "NO_SHOW", "PREEMPTED", "REJECTED",
    )
    assert data["priority"] in ("STANDARD", "PRIORITY")
    assert isinstance(data["user_id"], str)
    assert isinstance(data["instrument_id"], str)


def assert_usage_log(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "VALIDATED", "REJECTED")
    assert isinstance(data["booking_id"], str)


def assert_recharge_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "FINALIZED")
    assert isinstance(data["entry_count"], int)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["net_amount_cents"], int)


def assert_recharge_entry(data: dict):
    _assert_common(data)
    assert data["kind"] in ("USAGE", "PENALTY", "ADJUSTMENT")
    assert data["status"] in ("PENDING", "BILLED", "PAID", "DISPUTED", "WRITTEN_OFF")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["subsidy_offset_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert data["net_amount_cents"] == data["amount_cents"] - data["subsidy_offset_cents"], (
        f"net must equal amount minus offset: {data}"
    )


def assert_subsidy_application(data: dict):
    _assert_common(data)
    assert data["kind"] in ("STARTUP", "SUBSIDY")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "REJECTED",
    )


def assert_subsidy_award(data: dict):
    _assert_common(data)
    assert data["kind"] in ("STARTUP", "SUBSIDY")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED", "REVOKED")
    assert isinstance(data["awarded_amount_cents"], int)
    assert isinstance(data["remaining_amount_cents"], int)
    assert isinstance(data["conveys_priority"], bool)


def assert_maintenance_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXPIRED", "TERMINATED")
    assert isinstance(data["annual_cost_cents"], int)


def assert_downtime_event(data: dict):
    _assert_common(data)
    assert data["kind"] in ("UNSCHEDULED_FAILURE", "PREVENTIVE_MAINTENANCE", "CALIBRATION")
    assert data["status"] in ("REPORTED", "CONFIRMED", "RESOLVED", "CANCELLED")


def assert_publication(data: dict):
    _assert_common(data)
    assert data["status"] in ("REPORTED", "VERIFIED", "REJECTED")
    assert isinstance(data["acknowledges_core"], bool)
    assert isinstance(data["instrument_ids"], list)


def assert_fiscal_year_period(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["carryforward_in_cents"], int)
