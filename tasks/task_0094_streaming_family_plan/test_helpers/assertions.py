"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the system spine (id, timestamps, and — for
full-spine resources — version) plus the entity-specific fields. The three
write-once resources (SubscriptionPlan, Title, PlanChange) carry only id +
created_at and never an updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

RATING_VALUES = ["G", "PG", "PG13", "R", "NC17"]


def _assert_leaf_spine(data: dict):
    """id + created_at only (write-once configuration / audit resources)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "write-once resource must not carry updated_at"
    assert "version" not in data, "write-once resource must not carry version"


def _assert_full_spine(data: dict):
    """id + created_at + updated_at + version (mutable aggregates)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version must start at 1 and increment"


def assert_subscription_plan(data: dict):
    _assert_leaf_spine(data)
    assert data["tier"] in ["AD_SUPPORTED", "AD_FREE", "PREMIUM"]
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["max_profiles"], int) and data["max_profiles"] >= 1
    assert isinstance(data["concurrent_stream_cap"], int) and data["concurrent_stream_cap"] >= 1
    assert isinstance(data["max_registered_devices"], int) and data["max_registered_devices"] >= 1
    assert isinstance(data["download_quota_per_profile"], int) and data["download_quota_per_profile"] >= 0
    assert isinstance(data["ad_free"], bool)
    assert isinstance(data["hd_offline_allowed"], bool)


def assert_title(data: dict):
    _assert_leaf_spine(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["maturity_rating"] in RATING_VALUES
    assert isinstance(data["runtime_minutes"], int) and data["runtime_minutes"] >= 1
    assert isinstance(data["downloadable"], bool)
    assert isinstance(data["license_size_mb"], int) and data["license_size_mb"] >= 1


def assert_plan_change(data: dict):
    _assert_leaf_spine(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("to_plan_id", "")), "to_plan_id must be a UUID"
    assert data["direction"] in ["UPGRADE", "DOWNGRADE", "LATERAL"]


def assert_account(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["owner_email"], str) and len(data["owner_email"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["billing_anchor_day"], int) and 1 <= data["billing_anchor_day"] <= 28
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["billing_status"] in ["OPEN", "INVOICED"]
    assert isinstance(data["period_charge_cents"], int)
    assert isinstance(data["proration_adjustment_cents"], int)
    assert isinstance(data["active_stream_count"], int) and data["active_stream_count"] >= 0
    assert isinstance(data["registered_device_count"], int) and data["registered_device_count"] >= 0


def assert_profile(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["kind"] in ["ADULT", "TEEN", "KID"]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]
    assert data["max_rating_allowed"] in RATING_VALUES
    assert isinstance(data["daily_watch_minutes_used"], int) and data["daily_watch_minutes_used"] >= 0


def assert_parental_control(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("profile_id", "")), "profile_id must be a UUID"
    assert data["max_rating"] in RATING_VALUES
    assert isinstance(data["daily_watch_limit_minutes"], int) and data["daily_watch_limit_minutes"] >= 0
    assert isinstance(data["curfew_start_min"], int) and 0 <= data["curfew_start_min"] <= 1439
    assert isinstance(data["curfew_end_min"], int) and 0 <= data["curfew_end_min"] <= 1439


def assert_invite(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["invitee_email"], str) and len(data["invitee_email"]) > 0
    assert isinstance(data["token"], str) and len(data["token"]) > 0
    assert data["status"] in ["PENDING", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED"]
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert isinstance(data["hold_amount_cents"], int) and data["hold_amount_cents"] >= 0


def assert_device(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["device_label"], str) and len(data["device_label"]) > 0
    assert data["platform"] in ["TV", "MOBILE", "WEB", "TABLET"]
    assert data["status"] in ["REGISTERED", "DEREGISTERED"]
    assert isinstance(data["supports_hd"], bool)


def assert_stream_session(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("profile_id", "")), "profile_id must be a UUID"
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert is_valid_uuid(data.get("title_id", "")), "title_id must be a UUID"
    assert data["status"] in ["ACTIVE", "ENDED"]
    assert isinstance(data["started_at_min"], int) and 0 <= data["started_at_min"] <= 1439
    assert isinstance(data["minutes_watched"], int) and data["minutes_watched"] >= 0
    assert isinstance(data["ad_breaks_served"], int) and data["ad_breaks_served"] >= 0


def assert_download(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("profile_id", "")), "profile_id must be a UUID"
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert is_valid_uuid(data.get("title_id", "")), "title_id must be a UUID"
    assert data["status"] in ["DOWNLOADING", "READY", "EXPIRED", "DELETED"]
    assert data["quality"] in ["SD", "HD"]
    assert isinstance(data["size_mb"], int) and data["size_mb"] >= 1


def assert_watch_progress(data: dict):
    _assert_full_spine(data)
    assert is_valid_uuid(data.get("profile_id", "")), "profile_id must be a UUID"
    assert is_valid_uuid(data.get("title_id", "")), "title_id must be a UUID"
    assert isinstance(data["position_min"], int) and data["position_min"] >= 0
    assert is_valid_uuid(data.get("last_device_id", "")), "last_device_id must be a UUID"
    assert isinstance(data["completed"], bool)
