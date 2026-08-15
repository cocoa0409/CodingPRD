"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating an optional 'Z' suffix."""
    assert isinstance(value, str), f"Expected ISO-8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected: str):
    """Two ISO-8601 instants denote the same point in time."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """Ingest-side records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_show(data: dict):
    assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["content_category"] in [
        "TECHNOLOGY", "BUSINESS", "COMEDY", "NEWS", "HEALTH", "SPORTS",
    ]
    assert isinstance(data["avg_downloads_30d"], int) and data["avg_downloads_30d"] >= 0
    assert isinstance(data["blocked_advertiser_categories"], list)
    assert data["brand_safety_tier"] in ["CLEAR", "FLAGGED", "SUSPENDED"]
    assert isinstance(data["forecast_impressions"], int)
    assert isinstance(data["reserved_impressions"], int)
    assert isinstance(data["available_impressions"], int)
    assert data["available_impressions"] == (
        data["forecast_impressions"] - data["reserved_impressions"]
    ), "available_impressions must equal forecast_impressions - reserved_impressions"


def assert_episode(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("show_id", "")), "show_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["measurement_window_days"], int)
    assert 1 <= data["measurement_window_days"] <= 90
    assert isinstance(data["slot_capacity"], int)
    assert 1 <= data["slot_capacity"] <= 5
    assert data["status"] in ["SCHEDULED", "PUBLISHED", "MEASURED"]
    assert isinstance(data["provisional_download_count"], int)
    assert data.get("measured_download_count") is None or isinstance(
        data["measured_download_count"], int
    )
    assert isinstance(data["slots_in_use"], int)


def assert_agency(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["commission_bps"], int)
    assert 0 <= data["commission_bps"] <= 5000


def assert_advertiser(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in [
        "AUTOMOTIVE", "CPG_FOOD", "FINTECH", "GAMBLING",
        "ALCOHOL", "HEALTH_PHARMA", "TECHNOLOGY",
    ]
    assert data.get("agency_id") is None or is_valid_uuid(data["agency_id"])
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_campaign(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("advertiser_id", "")), "advertiser_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert _parse_instant(data["flight_end"]) > _parse_instant(data["flight_start"])
    assert isinstance(data["booked_impressions"], int) and data["booked_impressions"] > 0
    assert isinstance(data["cpm_cents"], int) and data["cpm_cents"] > 0
    assert data["billing_model"] in ["ACTUAL_DELIVERY", "BOOKED_GROSS"]
    assert data["status"] in [
        "DRAFT", "ACTIVE", "PAUSED", "ENDED", "RECONCILED", "CANCELLED",
    ]
    assert isinstance(data["delivered_impressions"], int)
    assert data["delivered_impressions"] >= 0


def assert_line_item(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    targets = [t for t in (data.get("show_id"), data.get("episode_id")) if t is not None]
    assert len(targets) == 1, "exactly one of show_id / episode_id must be set"
    assert data["ad_format"] in ["HOST_READ", "PRODUCED_SPOT"]
    assert data["position"] in ["PRE_ROLL", "MID_ROLL", "POST_ROLL"]
    assert isinstance(data["reserved_impressions"], int)
    assert data["reserved_impressions"] > 0
    assert isinstance(data["priority"], int)
    assert is_valid_uuid(data.get("ad_copy_id", "")), "ad_copy_id must be a UUID"
    assert data["status"] in ["DRAFT", "ACTIVE", "PAUSED", "ENDED"]


def assert_ad_copy(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    assert data["kind"] in ["HOST_READ_SCRIPT", "PRODUCED_AUDIO"]
    if data["kind"] == "HOST_READ_SCRIPT":
        assert is_valid_uuid(data.get("show_id", "")), (
            "HOST_READ_SCRIPT copy must name its show_id"
        )
    assert isinstance(data["script_text"], str)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "WITHDRAWN",
    ]


def assert_download(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("episode_id", "")), "episode_id must be a UUID"
    assert isinstance(data["listener_key"], str) and data["listener_key"]
    assert data["user_agent_class"] in ["HUMAN", "BOT", "UNKNOWN"]
    assert isinstance(data["qualified_provisional"], bool)
    assert data.get("qualified_final") is None or isinstance(data["qualified_final"], bool)


def assert_impression(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("download_id", "")), "download_id must be a UUID"
    assert is_valid_uuid(data.get("line_item_id", "")), "line_item_id must be a UUID"
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    assert data["position"] in ["PRE_ROLL", "MID_ROLL", "POST_ROLL"]
    assert isinstance(data["billable_provisional"], bool)
    assert data.get("billable_final") is None or isinstance(data["billable_final"], bool)


def assert_attribution_event(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    assert data["kind"] in ["PROMO_CODE", "PIXEL"]
    if data["kind"] == "PROMO_CODE":
        assert isinstance(data.get("promo_code"), str) and data["promo_code"]
    assert isinstance(data["attributed"], bool)


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    assert data["billing_model"] in ["ACTUAL_DELIVERY", "BOOKED_GROSS"]
    assert isinstance(data["delivered_impressions_billed"], int)
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line.get("line_item_id", "")), "line_item_id must be a UUID"
        assert line["position"] in ["PRE_ROLL", "MID_ROLL", "POST_ROLL"]
        assert isinstance(line["billable_impressions"], int)
        assert isinstance(line["line_cents"], int)
    for field in (
        "gross_cents", "shortfall_impressions", "make_good_credit_cents",
        "agency_commission_cents", "net_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in ["DRAFT", "ISSUED", "DISPUTED", "PAID"]


def assert_make_good(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    assert is_valid_uuid(data.get("invoice_id", "")), "invoice_id must be a UUID"
    assert isinstance(data["granted_impressions"], int)
    assert data.get("baseline_delivered_impressions") is None or isinstance(
        data["baseline_delivered_impressions"], int
    )
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "FULFILLED", "EXPIRED"]


def assert_invoice_invariants(data: dict):
    """PRD §3.7: net_cents + agency_commission_cents + make_good_credit_cents == gross_cents."""
    assert (
        data["net_cents"]
        + data["agency_commission_cents"]
        + data["make_good_credit_cents"]
        == data["gross_cents"]
    ), (
        f"Invoice invariant broken: net {data['net_cents']} + commission "
        f"{data['agency_commission_cents']} + credit {data['make_good_credit_cents']} "
        f"!= gross {data['gross_cents']}"
    )
    assert data["shortfall_impressions"] >= 0
