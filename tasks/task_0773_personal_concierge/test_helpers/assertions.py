"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_MEMBER_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED"]
_MEMBERSHIP_STATUSES = ["ACTIVE", "PAUSED", "CANCELLED"]
_VIP_TIERS = ["STANDARD", "SILVER", "GOLD", "PLATINUM"]
_CYCLE_STATUSES = ["OPEN", "CLOSED"]
_REQUEST_STATUSES = ["SUBMITTED", "IN_PROGRESS", "ON_HOLD", "FULFILLED", "CANCELLED"]
_CATEGORIES = ["ERRAND", "BOOKING", "TRAVEL", "GIFT"]
_ENGAGEMENT_STATUSES = ["PROPOSED", "CONFIRMED", "RECONCILED", "VOID"]
_TIME_ENTRY_STATUSES = ["FINALIZED", "REVERSED"]
_EXPENSE_STATUSES = ["RECONCILED", "DISPUTED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in _MEMBER_STATUSES, f"unexpected member status {data['status']}"
    assert isinstance(data["lifetime_billed_cents"], int)


def assert_retainer_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["monthly_retainer_cents"], int)
    assert isinstance(data["included_hours"], int)
    assert isinstance(data["overage_rate_cents_per_hour"], int)
    assert isinstance(data["max_pass_through_cents"], int)
    assert isinstance(data["default_markup_pct"], (int, float))


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["vip_tier"] in _VIP_TIERS
    assert data["status"] in _MEMBERSHIP_STATUSES
    assert isinstance(data["current_cycle_index"], int)
    assert isinstance(data["hour_bank_remaining_minutes"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["membership_id"])
    assert isinstance(data["cycle_index"], int)
    assert isinstance(data["included_minutes"], int)
    assert isinstance(data["consumed_minutes"], int)
    assert isinstance(data["overage_minutes"], int)
    assert isinstance(data["overage_charge_cents"], int)
    assert data["status"] in _CYCLE_STATUSES


def assert_service_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["membership_id"])
    assert data["category"] in _CATEGORIES
    assert isinstance(data["title"], str)
    assert data["status"] in _REQUEST_STATUSES
    assert isinstance(data["priority_score"], int)


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in _CATEGORIES
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_vendor_engagement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert data["billing_mode"] in ["MARKUP", "PASS_THROUGH"]
    assert data["status"] in _ENGAGEMENT_STATUSES
    assert isinstance(data["client_charge_cents"], int)


def assert_time_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert is_valid_uuid(data["billing_cycle_id"])
    assert isinstance(data["minutes"], int) and data["minutes"] > 0
    assert data["status"] in _TIME_ENTRY_STATUSES


def assert_expense(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vendor_engagement_id"])
    assert is_valid_uuid(data["membership_id"])
    assert isinstance(data["estimated_cents"], int)
    assert isinstance(data["actual_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["status"] in _EXPENSE_STATUSES


def assert_satisfaction_rating(data: dict):
    # common_fields: false — only id + created_at; no version / updated_at.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["service_request_id"])
    assert is_valid_uuid(data["membership_id"])
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5
    assert isinstance(data["sequence_no"], int)
