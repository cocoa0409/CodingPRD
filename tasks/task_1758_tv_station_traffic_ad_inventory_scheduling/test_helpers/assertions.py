"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AvailWeekStatus,
    CopyInstructionStatus,
    DaypartCode,
    LogDayStatus,
    OrderLineStatus,
    OrderStatus,
    PreemptReason,
    ProductCategory,
    SpotClass,
    SpotStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_advertiser(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["agency_name"], str)
    assert data["product_category"] in [c.value for c in ProductCategory]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["daypart_code"] in [d.value for d in DaypartCode]
    assert isinstance(data["airs_weekday"], int) and 1 <= data["airs_weekday"] <= 7
    assert isinstance(data["start_time_local"], str)
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 5
    assert data["rating_estimate"] >= 0
    assert isinstance(data["is_political_window"], bool)


def assert_avail_week(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["week_start_date"], str)
    assert data["status"] in [s.value for s in AvailWeekStatus]


def assert_avail_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["avail_week_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["air_date"], str)
    assert isinstance(data["break_position"], int) and data["break_position"] >= 1
    assert isinstance(data["total_seconds"], int) and data["total_seconds"] > 0
    assert isinstance(data["reserved_political_seconds"], int)
    assert 0 <= data["reserved_political_seconds"] <= data["total_seconds"]
    assert isinstance(data["booked_commercial_seconds"], int)
    assert isinstance(data["booked_political_seconds"], int)


def assert_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["advertiser_id"], str)
    assert isinstance(data["flight_start_date"], str)
    assert isinstance(data["flight_end_date"], str)
    assert data["status"] in [s.value for s in OrderStatus]
    assert isinstance(data["gross_budget_cents"], int) and data["gross_budget_cents"] >= 0
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 0


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["weeks_requested"], int) and data["weeks_requested"] >= 1
    assert isinstance(data["spots_per_week"], int) and data["spots_per_week"] >= 1
    assert data["spot_length_seconds"] in (15, 30, 60, 120)
    assert isinstance(data["gross_rate_cents"], int) and data["gross_rate_cents"] > 0
    assert data["guaranteed_rating"] >= 0
    assert data["status"] in [s.value for s in OrderLineStatus]


def assert_copy_instruction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["advertiser_id"], str)
    assert data["length_seconds"] in (15, 30, 60, 120)
    assert isinstance(data["rotation_weight"], int) and data["rotation_weight"] >= 1
    assert data["status"] in [s.value for s in CopyInstructionStatus]


def assert_spot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_line_id"], str)
    assert data["status"] in [s.value for s in SpotStatus]
    assert data["spot_class"] in [c.value for c in SpotClass]
    assert data["preempt_reason"] in [r.value for r in PreemptReason]


def assert_log_day(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["avail_week_id"], str)
    assert isinstance(data["log_date"], str)
    assert data["status"] in [s.value for s in LogDayStatus]


def assert_as_run_entry(data: dict):
    """Append-only record: id and created_at only — updated_at/version absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "as-run entries carry no updated_at"
    assert "version" not in data, "as-run entries carry no version"
    assert isinstance(data["log_day_id"], str)
    assert isinstance(data["spot_id"], str)
    assert isinstance(data["aired"], bool)


def assert_post_buy_report(data: dict):
    assert isinstance(data["order_id"], str)
    assert isinstance(data["lines"], list)
    for key in ("discrepancy_credit_cents", "shortfall_credit_cents", "order_credit_cents"):
        assert isinstance(data[key], int) and data[key] >= 0, f"{key} must be integer cents"
    assert data["order_credit_cents"] == (
        data["discrepancy_credit_cents"] + data["shortfall_credit_cents"]
    ), "order credit must equal the sum of the discrepancy and shortfall buckets"


def assert_week_booked_seconds(units: list, expected_total: int):
    """Domain invariant: the summed booked seconds across a week's units."""
    total = sum(u["booked_commercial_seconds"] + u["booked_political_seconds"] for u in units)
    assert total == expected_total, (
        f"week booked-second total must be {expected_total}, got {total}"
    )
