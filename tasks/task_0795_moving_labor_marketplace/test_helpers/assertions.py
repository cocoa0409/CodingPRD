"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

JOB_STATUSES = ["DRAFT", "QUOTED", "BOOKED", "IN_PROGRESS", "COMPLETED", "SETTLED", "CANCELLED"]
QUOTE_STATUSES = ["ACTIVE", "ACCEPTED", "SUPERSEDED"]
ASSIGNMENT_STATUSES = ["ASSIGNED", "CHECKED_IN", "CHECKED_OUT", "RELEASED", "NO_SHOW"]
CLAIM_STATUSES = ["FILED", "UNDER_REVIEW", "APPROVED", "DENIED"]
PAYOUT_STATUSES = ["RELEASED", "REVERSED"]
VETTING_STATUSES = ["PENDING_REVIEW", "APPROVED", "REJECTED", "SUSPENDED"]


def _parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating a trailing 'Z' and optional fractions."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def same_instant(a: str, b: str) -> bool:
    """True when two ISO-8601 strings denote the same UTC instant, ignoring formatting."""
    return _parse_instant(a) == _parse_instant(b)


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full-common-field entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_reference_fields(data: dict):
    """id + created_at ONLY for immutable reference data (RateCard, InsurancePolicy)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "reference data must not carry updated_at"
    assert "version" not in data, "reference data must not carry version"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0


def assert_helper(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["base_hourly_rate_cents"], int)
    assert data["vetting_status"] in VETTING_STATUSES
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0
    assert isinstance(data["lifetime_payout_cents"], int) and data["lifetime_payout_cents"] >= 0


def assert_job(data: dict):
    assert_common_fields(data)
    assert data["status"] in JOB_STATUSES
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert data["job_type"] in ["LOAD", "UNLOAD", "MOVE"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["cancellation_fee_cents"], int)


def assert_quote(data: dict):
    assert_common_fields(data)
    assert data["status"] in QUOTE_STATUSES
    for field in (
        "base_labor_cents", "truck_fee_cents", "addons_total_cents",
        "subtotal_cents", "service_fee_cents", "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_addon(data: dict):
    assert_common_fields(data)
    assert data["addon_type"] in ["PACKING_MATERIALS", "HEAVY_ITEM", "STAIRS", "LONG_CARRY", "ASSEMBLY"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_total_cents"], int)


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ASSIGNMENT_STATUSES
    assert data["role"] in ["LEAD", "CREW"]
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["helper_id"])


def assert_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in CLAIM_STATUSES
    assert isinstance(data["claimed_amount_cents"], int)


def assert_rating(data: dict):
    assert_common_fields(data)
    assert isinstance(data["stars"], int) and 1 <= data["stars"] <= 5
    assert isinstance(data["tip_cents"], int)


def assert_payout(data: dict):
    assert_common_fields(data)
    assert data["status"] in PAYOUT_STATUSES
    for field in ("base_pay_cents", "tip_cents", "bonus_cents", "total_payout_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"
    assert data["total_payout_cents"] == data["base_pay_cents"] + data["tip_cents"] + data["bonus_cents"], (
        "total_payout_cents must equal base_pay_cents + tip_cents + bonus_cents"
    )
