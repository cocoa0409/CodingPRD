"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_channel(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["loop_duration_seconds"], int) and data["loop_duration_seconds"] > 0
    assert isinstance(data["refresh_cadence_days"], int) and data["refresh_cadence_days"] > 0
    assert isinstance(data["ad_separation_window_seconds"], int)
    assert isinstance(data["avg_slot_impressions"], int)
    assert data["channel_status"] in ["DRAFT", "LIVE", "SUSPENDED", "OFFLINE", "ARCHIVED"]
    assert data["channel_posture"] in ["ACTIVE", "GUARDED", "FROZEN"]
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0


def assert_content_asset(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["content_type"] in ["MOVIE", "EPISODE", "SHORT"]
    assert isinstance(data["runtime_seconds"], int) and data["runtime_seconds"] > 0
    assert data["rating"] in ["G", "PG", "PG13", "R", "TVMA"]
    assert data["content_status"] in [
        "INGESTING", "AVAILABLE", "PULLED", "WINDOW_EXPIRED", "ARCHIVED",
    ]


def assert_rights_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["content_id"])
    assert isinstance(data["max_plays"], int) and data["max_plays"] > 0
    assert isinstance(data["plays_used"], int) and data["plays_used"] >= 0
    assert data["grant_status"] in ["PENDING", "ACTIVE", "EXPIRED", "EXHAUSTED", "REVOKED"]


def assert_playlist_loop(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["channel_id"])
    assert isinstance(data["broadcast_date"], str) and len(data["broadcast_date"]) == 10
    assert data["loop_status"] in [
        "DRAFT", "VALIDATED", "LOCKED", "PUBLISHED", "SUPERSEDED", "ARCHIVED",
    ]
    assert isinstance(data["used_seconds"], int) and data["used_seconds"] >= 0


def assert_playlist_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loop_id"])
    assert is_valid_uuid(data["content_id"])
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 0
    assert isinstance(data["start_offset_seconds"], int) and data["start_offset_seconds"] >= 0
    assert isinstance(data["end_offset_seconds"], int)
    assert data["end_offset_seconds"] > data["start_offset_seconds"]


def assert_ad_break(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loop_id"])
    assert isinstance(data["duration_seconds"], int)
    assert data["duration_seconds"] % 30 == 0
    assert 30 <= data["duration_seconds"] <= 240
    assert data["break_status"] in ["MARKED", "DECIDED", "AIRED", "RECONCILED"]
    assert data["slots"] == data["duration_seconds"] // 30
    assert isinstance(data["direct_seconds"], int) and data["direct_seconds"] >= 0
    assert isinstance(data["house_seconds"], int) and data["house_seconds"] >= 0
    assert isinstance(data["slate_seconds"], int) and data["slate_seconds"] >= 0
    assert data["direct_seconds"] + data["house_seconds"] + data["slate_seconds"] == data[
        "duration_seconds"
    ], "fill accounting must partition the pod (PRD §3.6)"


def assert_fill_decision(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["break_id"])
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 0
    assert isinstance(data["slots_spanned"], int) and data["slots_spanned"] >= 1
    assert data["fill_type"] in ["DIRECT", "HOUSE"]
    if data["fill_type"] == "DIRECT":
        assert data.get("creative_id"), "DIRECT row carries creative_id (PRD §3.6)"
        assert data.get("campaign_id"), "DIRECT row carries campaign_id (PRD §3.6)"
        assert data.get("house_ad_id") in (None, ""), "DIRECT row leaves house reference unset"
    else:
        assert data.get("house_ad_id"), "HOUSE row carries house_ad_id (PRD §3.6)"
        assert data.get("creative_id") in (None, "")
        assert data.get("campaign_id") in (None, "")
        assert data["expected_impressions"] == 0
        assert data["committed_cost_cents"] == 0
    assert data["decision_status"] in ["PROVISIONAL", "COMMITTED", "RECONCILED", "VOIDED"]


def assert_ad_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["advertiser_name"], str) and data["advertiser_name"]
    assert isinstance(data["iab_category"], str) and data["iab_category"]
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] > 0
    assert isinstance(data["daily_budget_cents"], int) and data["daily_budget_cents"] > 0
    assert isinstance(data["cpm_cents"], int) and data["cpm_cents"] > 0
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0, (
        "spent_cents never goes negative (PRD §3.5)"
    )
    assert data["campaign_status"] in ["DRAFT", "ACTIVE", "PAUSED", "EXHAUSTED", "COMPLETED"]


def assert_ad_creative(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["brand"], str) and data["brand"]
    assert isinstance(data["iab_category"], str) and data["iab_category"]
    assert data["creative_status"] in ["PENDING_REVIEW", "APPROVED", "REJECTED", "RETIRED"]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_house_ad(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["duration_seconds"] == 30, "house ad is exactly one slot (PRD §3.5)"
    assert isinstance(data["priority_weight"], int)
    assert isinstance(data["daily_impression_cap"], int) and data["daily_impression_cap"] > 0
    assert data["house_ad_status"] in ["ACTIVE", "PAUSED", "RETIRED"]


def assert_distributor_platform(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["reporting_tier"] in ["STANDARD", "PREMIUM"]
    assert data["platform_status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED"]


def assert_distribution_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["platform_id"])
    assert 0 <= data["rev_share_bps_below"] <= 6000
    assert 0 <= data["rev_share_bps_above"] <= 6000
    assert isinstance(data["tier_threshold_cents"], int) and data["tier_threshold_cents"] >= 0
    assert isinstance(data["minimum_guarantee_cents"], int) and data["minimum_guarantee_cents"] >= 0
    assert data["agreement_status"] in ["NEGOTIATION", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_revenue_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["platform_id"])
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert data["report_status"] in ["DRAFT", "PROVISIONAL", "FINALIZED", "DISPUTED", "SETTLED"]
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0
    if data.get("gross_revenue_cents") is not None:
        assert data["net_revenue_cents"] == (
            data["gross_revenue_cents"] - data["platform_share_cents"]
        ), "net = gross - share (PRD §3.8)"
        assert data["platform_share_cents"] >= 0


def assert_viewership_event(data: dict):
    """Append-only record: id + created_at present; updated_at/version absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "viewership events carry no updated_at (PRD §2.5)"
    assert "version" not in data, "viewership events carry no version (PRD §2.5)"
    assert is_valid_uuid(data["channel_id"])
    assert data["event_type"] in [
        "SESSION_START", "SESSION_END", "CONTENT_WATCH", "AD_IMPRESSION", "AD_COMPLETE",
    ]


def assert_channel_day_snapshot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["channel_id"])
    assert isinstance(data["snapshot_date"], str) and len(data["snapshot_date"]) == 10
    assert isinstance(data["watch_seconds"], int) and data["watch_seconds"] >= 0
    assert isinstance(data["peak_concurrent_viewers"], int) and data["peak_concurrent_viewers"] >= 0
    assert isinstance(data["capacity_seconds"], int) and data["capacity_seconds"] >= 0
    assert 0 <= data["performance_score"] <= 100
