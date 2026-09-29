"""Entity assertions, timestamp canonicalisation and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str) and value, f"expected a timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "timestamp"):
    """Compare two instants by value, so 12:00:00Z and 12:00:00.000Z match."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_date_at_midnight(value: str, label: str = "date field"):
    """Date-valued fields are returned as UTC instants at midnight."""
    instant = parse_instant(value)
    assert (
        instant.hour == 0
        and instant.minute == 0
        and instant.second == 0
        and instant.microsecond == 0
    ), f"{label} must sit at midnight UTC, got {value}"


# ---------------------------------------------------------------------------
# Common audit fields
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict, expected_version: Optional[int] = None):
    """id + created_at + updated_at + version, for every versioned entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_append_only_fields(data: dict):
    """Append-only ledger rows carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only rows must not carry updated_at"
    assert "version" not in data, "append-only rows must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_location(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["state_code"] in ("CA", "NY", "TX", "MA")
    assert isinstance(data["state_min_wage_cents"], int)
    assert isinstance(data["cash_wage_cents"], int)
    assert isinstance(data["tip_credit_enabled"], bool)
    assert data["cc_fee_policy"] in ("PROHIBITED", "ACTUAL_ONLY", "CAPPED_BPS")
    assert data["service_charge_treatment"] in ("WAGES", "TIPS")
    assert isinstance(data["applicable_min_wage_cents"], int)
    assert isinstance(data["max_tip_credit_per_hour_cents"], int)
    assert isinstance(data["pending_pool_cents"], int)
    assert data["pending_pool_cents"] >= 0


def assert_job_role(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"] == data["code"].upper()
    assert data["tip_status"] in ("TIPPED", "NON_TIPPED")
    assert isinstance(data["is_management"], bool)
    assert 0 <= data["pool_contribution_pct_bps"] <= 5000
    assert 0 <= data["pool_share_points"] <= 100
    assert isinstance(data["side_work_eligible"], bool)


def assert_employee(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["external_payroll_ref"], str)
    assert isinstance(data["monthly_tip_baseline_cents"], int)
    assert isinstance(data["trailing_pool_receipts_cents"], int)


def assert_role_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["job_role_id"])
    assert isinstance(data["is_primary"], bool)
    assert isinstance(data["dual_job"], bool)


def assert_tip_pool_policy(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert data["pool_type"] in ("TIPPED_ONLY", "ALL_NON_MANAGEMENT")
    assert data["contribution_basis"] in ("TIPS_RECEIVED_PCT", "GROSS_SALES_PCT")
    assert data["share_basis"] in ("POINTS_ONLY", "HOURS_WEIGHTED_POINTS")
    assert isinstance(data["cc_fee_pass_through"], bool)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_pay_period(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert data["status"] in ("OPEN", "COMPUTED", "APPROVED")
    assert data["compute_variant"] in (None, "WEEKLY_AGGREGATE", "PER_SHIFT")
    for field in (
        "total_credited_minutes",
        "total_tip_credit_cents",
        "total_topup_cents",
        "total_correction_cents",
        "gross_receipts_cents",
        "reported_tips_cents",
        "allocation_shortfall_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)}"
        )


def assert_pay_period_rollups_zero(data: dict):
    """Every money and minute rollup sits at zero."""
    for field in (
        "total_credited_minutes",
        "total_tip_credit_cents",
        "total_topup_cents",
        "total_correction_cents",
        "gross_receipts_cents",
        "reported_tips_cents",
        "allocation_shortfall_cents",
    ):
        assert data[field] == 0, f"{field} should be 0, got {data[field]}"


def assert_shift(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["job_role_id"])
    assert is_valid_uuid(data["pay_period_id"])
    assert data["time_status"] in ("OPEN", "CLOSED", "VOIDED")
    assert data["declaration_status"] in ("UNDECLARED", "DECLARED", "AMENDED")
    assert isinstance(data["scheduled_minutes"], int) and data["scheduled_minutes"] >= 0
    for field in (
        "side_work_minutes",
        "max_continuous_side_work_minutes",
        "non_tip_credit_minutes",
        "tip_credit_eligible_minutes",
        "gross_sales_cents",
        "charged_sales_cents",
        "cc_processing_fee_bps",
        "declared_cash_tips_cents",
        "declared_charged_tips_cents",
        "declaration_count",
        "pool_contribution_cents",
        "retained_tips_cents",
        "shift_tip_credit_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)}"
        )


def assert_service_charge(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert data["amount_cents"] > 0
    assert data["treatment"] in ("WAGES", "TIPS")
    assert data["status"] in ("RECORDED", "ALLOCATED", "VOIDED")


def assert_shift_tip_pool(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert data["contribution_status"] in ("CONTRIBUTED", "REVERSED")
    assert data["distribution_status"] in ("PENDING", "DISTRIBUTED", "REVERSED")
    for field in (
        "contributing_shift_count",
        "participant_count",
        "total_contributed_cents",
        "service_charge_tips_cents",
        "cc_fee_deducted_cents",
        "net_pool_cents",
        "total_share_weight",
        "distributed_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)}"
        )


def assert_pool_allocation(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data["shift_tip_pool_id"])
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["shift_id"])
    assert data["entry_type"] in ("DISTRIBUTION", "REVERSAL")
    assert isinstance(data["share_weight"], int)
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["remainder_cent_awarded"], bool)


def assert_pay_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["pay_period_id"])
    assert is_valid_uuid(data["employee_id"])
    assert data["variant"] in ("WEEKLY_AGGREGATE", "PER_SHIFT")
    assert data["status"] in ("DRAFT", "FINAL", "SUPERSEDED")
    assert isinstance(data["tipped_employee_qualified"], bool)
    for field in (
        "total_minutes",
        "tip_credit_eligible_minutes",
        "non_tip_credit_minutes",
        "regular_minutes",
        "overtime_minutes",
        "straight_cash_cents",
        "service_charge_wages_cents",
        "regular_rate_cents_per_hour",
        "overtime_premium_cents",
        "minimum_wage_obligation_cents",
        "tips_available_cents",
        "tip_credit_cents",
        "topup_cents",
        "total_gross_cents",
        "correction_applied_cents",
        "pending_correction_cents",
        "open_dispute_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)}"
        )


def assert_dispute(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["pay_line_id"])
    assert is_valid_uuid(data["raised_by_employee_id"])
    assert data["category"] in ("POOL_SHARE", "TIP_CREDIT", "CC_FEE", "SERVICE_CHARGE")
    assert data["status"] in (
        "OPEN",
        "UPHELD",
        "PARTIALLY_UPHELD",
        "DENIED",
        "CLOSED",
    )
    assert data["claimed_amount_cents"] > 0
    assert isinstance(data["adjudicated_amount_cents"], int)


def assert_back_wage_correction(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["pay_line_id"])
    assert data["amount_cents"] > 0
    assert data["reason_code"] in (
        "POOL_SHARE_SHORTFALL",
        "TIP_CREDIT_INVALID",
        "CC_FEE_OVERDEDUCTION",
        "SERVICE_CHARGE_MISCLASSIFIED",
        "SIDE_WORK_OVERAGE",
    )
    assert data["status"] in ("PENDING", "APPLIED", "VOIDED")
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_shift_minute_split(data: dict):
    """Credit-eligible and non-credit minutes partition the scheduled minutes."""
    if data["time_status"] == "CLOSED":
        assert (
            data["non_tip_credit_minutes"] + data["tip_credit_eligible_minutes"]
            == data["scheduled_minutes"]
        ), (
            "non_tip_credit_minutes + tip_credit_eligible_minutes must equal "
            f"scheduled_minutes, got {data['non_tip_credit_minutes']} + "
            f"{data['tip_credit_eligible_minutes']} != {data['scheduled_minutes']}"
        )


def assert_pool_money_identity(pool: dict):
    """net_pool_cents is what is left after the permitted card fee."""
    assert (
        pool["net_pool_cents"]
        == pool["total_contributed_cents"]
        + pool["service_charge_tips_cents"]
        - pool["cc_fee_deducted_cents"]
    ), (
        "net_pool_cents must equal contributions plus service-charge tips minus the "
        f"card fee, got {pool['net_pool_cents']}"
    )


def assert_allocations_sum_to(allocations: list, expected_total: int):
    total = sum(row["allocated_cents"] for row in allocations)
    assert total == expected_total, (
        f"allocated_cents must sum to {expected_total}, got {total}"
    )
