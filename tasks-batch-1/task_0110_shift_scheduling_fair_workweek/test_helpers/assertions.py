"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, validate_paginated,
)


# --- Common system-field checks ---
def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_location(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["time_zone"], str) and len(data["time_zone"]) > 0
    assert isinstance(data["predictability_pay_enabled"], bool)
    assert isinstance(data["advance_notice_days"], int)
    assert isinstance(data["min_rest_hours_between_shifts"], int)
    assert isinstance(data["overtime_cost_guardrail_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_worker(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["base_hourly_rate_cents"], int)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["role_name"], str)
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert isinstance(data["headcount_required"], int) and data["headcount_required"] >= 1
    assert isinstance(data["headcount_filled"], int) and data["headcount_filled"] >= 0
    assert data["status"] in ("DRAFT", "OPEN", "FULLY_STAFFED", "COMPLETED", "CANCELLED")
    assert isinstance(data["duration_hours"], (int, float))


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["shift_id"])
    assert is_valid_uuid(data["worker_id"])
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["source"] in ("DIRECT", "BID", "SWAP")
    assert isinstance(data["clopening_flag"], bool)
    assert isinstance(data["provisional_cost_cents"], int)


def assert_bid(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["shift_id"])
    assert is_valid_uuid(data["worker_id"])
    assert isinstance(data["seniority_score"], int)
    assert data["status"] in ("SUBMITTED", "AWARDED", "REJECTED", "WITHDRAWN")


def assert_swap(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["from_assignment_id"])
    assert is_valid_uuid(data["to_worker_id"])
    assert data["status"] in (
        "PROPOSED", "COUNTERED", "ACCEPTED", "MANAGER_APPROVED", "REJECTED", "CANCELLED",
    )


def assert_pay_period(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert data["status"] in ("OPEN", "LOCKED")
    assert isinstance(data["projected_labor_cost_cents"], int)


def assert_ledger_entry(data: dict):
    """PredictabilityLedgerEntry is append-only: id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["worker_id"])
    assert is_valid_uuid(data["shift_id"])
    assert data["reason"] in ("CLOPENING", "SHORT_NOTICE_POST", "SHORT_NOTICE_CANCEL")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


# --- Ledger query helpers (used by predictability / cascade tests) ---
def ledger_entries_for_shift(api, shift_id: str, headers, reason: str = None) -> list:
    """Return all PredictabilityLedgerEntry rows for a shift, optionally filtered by reason."""
    resp = api.list_predictability_ledger(headers, params={"shift_id": shift_id})
    entries, _meta = validate_paginated(resp)
    if reason is not None:
        entries = [e for e in entries if e["reason"] == reason]
    return entries
