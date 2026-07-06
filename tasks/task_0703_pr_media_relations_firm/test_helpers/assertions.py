"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["industry"] in ["TECH", "HEALTH", "FINANCE", "CONSUMER", "NONPROFIT"]
    assert isinstance(data["monthly_retainer_cents"], int) and data["monthly_retainer_cents"] >= 0
    assert data["monthly_hours_cap"] > 0
    assert isinstance(data["overage_rate_cents"], int) and data["overage_rate_cents"] >= 0
    assert data["account_tier"] in ["STANDARD", "PREMIUM", "ENTERPRISE"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["lifetime_earned_media_cents"], int)


def assert_outlet(data: dict):
    # common_fields: false — only id + created_at, no version/updated_at.
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier"] in ["NATIONAL", "REGIONAL", "TRADE", "BLOG"]
    assert isinstance(data["monthly_unique_visitors"], int) and data["monthly_unique_visitors"] >= 0
    assert 0 <= data["domain_authority"] <= 100


def assert_journalist(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("outlet_id", "")), "outlet_id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["beat"] in ["TECH", "HEALTH", "FINANCE", "CONSUMER", "POLITICS"]
    assert data["status"] in ["ACTIVE", "BLOCKLISTED"]


def assert_campaign(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["objective"] in ["LAUNCH", "THOUGHT_LEADERSHIP", "CRISIS", "AWARENESS"]
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert data["target_beat"] in ["TECH", "HEALTH", "FINANCE", "CONSUMER", "POLITICS"]
    assert data["status"] in ["DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "ARCHIVED"]
    assert isinstance(data["earned_media_value_cents"], int)
    assert isinstance(data["cost_basis_cents"], int)
    assert data["roi_ratio"] is None or isinstance(data["roi_ratio"], (int, float))


def assert_retainer_period(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["period_month"], str)
    assert data["hours_cap"] > 0
    assert isinstance(data["overage_rate_cents"], int) and data["overage_rate_cents"] >= 0
    assert isinstance(data["hours_consumed"], (int, float))
    assert isinstance(data["provisional_total_cents"], int)
    assert data["final_total_cents"] is None or isinstance(data["final_total_cents"], int)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_spokesperson(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["title"], str)
    assert isinstance(data["prep_buffer_minutes"], int) and data["prep_buffer_minutes"] >= 0
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_media_list(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["journalist_ids"], list)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "EXHAUSTED", "ARCHIVED"]


def assert_pitch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a valid UUID"
    assert is_valid_uuid(data.get("media_list_id", "")), "media_list_id must be a valid UUID"
    assert is_valid_uuid(data.get("journalist_id", "")), "journalist_id must be a valid UUID"
    assert isinstance(data["angle"], str)
    assert isinstance(data["is_exclusive"], bool)
    assert data["status"] in ["DRAFT", "SENT", "RESPONDED", "ACCEPTED", "REJECTED", "DECLINED", "CANCELLED"]


def assert_press_release(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a valid UUID"
    assert isinstance(data["headline"], str)
    assert isinstance(data["embargo_until"], str)
    assert data["status"] in ["DRAFT", "SCHEDULED", "RELEASED", "WITHDRAWN"]


def assert_distribution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("press_release_id", "")), "press_release_id must be a valid UUID"
    assert is_valid_uuid(data.get("journalist_id", "")), "journalist_id must be a valid UUID"
    assert data["status"] in ["QUEUED", "DELIVERED", "BOUNCED"]


def assert_coverage(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a valid UUID"
    assert is_valid_uuid(data.get("journalist_id", "")), "journalist_id must be a valid UUID"
    assert isinstance(data["headline"], str)
    assert isinstance(data["published_at"], str)
    assert data["sentiment"] in ["POSITIVE", "NEUTRAL", "NEGATIVE"]
    assert data["prominence"] in ["FEATURE", "MENTION", "PASSING"]
    assert isinstance(data["estimated_media_value_cents"], int)
    assert isinstance(data["media_value_cents"], int)
    assert data["status"] in ["DRAFT", "VERIFIED", "RETRACTED"]


def assert_interview(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a valid UUID"
    assert is_valid_uuid(data.get("spokesperson_id", "")), "spokesperson_id must be a valid UUID"
    assert is_valid_uuid(data.get("journalist_id", "")), "journalist_id must be a valid UUID"
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert data["status"] in ["REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"]


def assert_crisis_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["summary"], str)
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["severity_status"] in ["ASSESSING", "CONTAINED", "ESCALATED"]
    assert data["response_status"] in ["DRAFTING", "APPROVED", "PUBLISHED"]


def assert_time_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("retainer_period_id", "")), "retainer_period_id must be a valid UUID"
    assert isinstance(data["staff_id"], str)
    assert data["work_type"] in ["STRATEGY", "WRITING", "OUTREACH", "MONITORING", "CRISIS"]
    assert data["billable_hours"] > 0
    assert isinstance(data["cost_cents"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "VOID"]
