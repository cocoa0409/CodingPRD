"""Resource serializers — produce the exact public field set per entity."""

from db import fmt_dt


def _strip(rec, fields):
    out = {}
    for f in fields:
        v = rec.get(f)
        out[f] = v
    return out


CHANNEL_FIELDS = [
    "id", "name", "genre", "timezone", "loop_duration_seconds",
    "refresh_cadence_days", "ad_separation_window_seconds",
    "avg_slot_impressions", "channel_status", "channel_posture",
    "ops_run_index", "last_published_on", "created_at", "updated_at",
    "version",
]

CONTENT_FIELDS = [
    "id", "title", "content_type", "runtime_seconds", "rating", "genre",
    "content_status", "created_at", "updated_at", "version",
]

GRANT_FIELDS = [
    "id", "channel_id", "content_id", "window_start_utc", "window_end_utc",
    "max_plays", "plays_used", "grant_status", "created_at", "updated_at",
    "version",
]

LOOP_FIELDS = [
    "id", "channel_id", "broadcast_date", "loop_status", "used_seconds",
    "validated_at", "published_at", "supersedes_loop_id", "created_at",
    "updated_at", "version",
]

ENTRY_FIELDS = [
    "id", "loop_id", "content_id", "sequence_index", "start_offset_seconds",
    "end_offset_seconds", "created_at", "updated_at", "version",
]

BREAK_FIELDS = [
    "id", "loop_id", "duration_seconds", "after_entry_index",
    "sequence_index", "start_offset_seconds", "break_status", "slots",
    "direct_seconds", "house_seconds", "slate_seconds", "created_at",
    "updated_at", "version",
]

DECISION_FIELDS = [
    "id", "break_id", "slot_index", "slots_spanned", "fill_type",
    "creative_id", "campaign_id", "house_ad_id", "expected_impressions",
    "committed_cost_cents", "actual_impressions", "reconciled_cost_cents",
    "decision_status", "created_at", "updated_at", "version",
]

CAMPAIGN_FIELDS = [
    "id", "advertiser_name", "iab_category", "total_budget_cents",
    "daily_budget_cents", "cpm_cents", "flight_start_date",
    "flight_end_date", "priority", "spent_cents", "campaign_status",
    "created_at", "updated_at", "version",
]

CREATIVE_FIELDS = [
    "id", "campaign_id", "brand", "iab_category", "duration_seconds",
    "creative_status", "created_by_user_id", "reviewed_by_user_id",
    "rejection_reason", "created_at", "updated_at", "version",
]

HOUSE_AD_FIELDS = [
    "id", "name", "channel_id", "duration_seconds", "priority_weight",
    "daily_impression_cap", "house_ad_status", "created_at", "updated_at",
    "version",
]

PLATFORM_FIELDS = [
    "id", "name", "reporting_tier", "platform_status", "created_at",
    "updated_at", "version",
]

AGREEMENT_FIELDS = [
    "id", "channel_id", "platform_id", "rev_share_bps_below",
    "rev_share_bps_above", "tier_threshold_cents", "minimum_guarantee_cents",
    "effective_start_date", "effective_end_date", "agreement_status",
    "locked_rev_share_bps_below", "locked_rev_share_bps_above",
    "locked_tier_threshold_cents", "locked_minimum_guarantee_cents",
    "created_at", "updated_at", "version",
]

REPORT_FIELDS = [
    "id", "channel_id", "platform_id", "agreement_id", "period_month",
    "report_status", "calculation_variant", "gross_revenue_cents",
    "platform_share_cents", "net_revenue_cents", "dispute_round",
    "generated_by_user_id", "finalized_by_user_id", "dispute_reason",
    "created_at", "updated_at", "version",
]

SNAPSHOT_FIELDS = [
    "id", "channel_id", "snapshot_date", "watch_seconds",
    "peak_concurrent_viewers", "ad_impressions", "direct_sold_impressions",
    "capacity_seconds", "direct_seconds", "house_seconds",
    "direct_fill_rate", "effective_fill_rate", "direct_revenue_cents",
    "ecpm_cents", "performance_score", "computed_at", "created_at",
    "updated_at", "version",
]


def ser_channel(r):
    return _strip(r, CHANNEL_FIELDS)


def ser_content(r):
    return _strip(r, CONTENT_FIELDS)


def ser_grant(r):
    return _strip(r, GRANT_FIELDS)


def ser_loop(r):
    return _strip(r, LOOP_FIELDS)


def ser_entry(r):
    return _strip(r, ENTRY_FIELDS)


def ser_break(r):
    return _strip(r, BREAK_FIELDS)


def ser_decision(r):
    return _strip(r, DECISION_FIELDS)


def ser_campaign(r):
    return _strip(r, CAMPAIGN_FIELDS)


def ser_creative(r):
    return _strip(r, CREATIVE_FIELDS)


def ser_house_ad(r):
    return _strip(r, HOUSE_AD_FIELDS)


def ser_platform(r):
    return _strip(r, PLATFORM_FIELDS)


def ser_agreement(r):
    return _strip(r, AGREEMENT_FIELDS)


def ser_report(r):
    return _strip(r, REPORT_FIELDS)


def ser_snapshot(r):
    out = _strip(r, SNAPSHOT_FIELDS)
    # Fill rates are scale-4 fixed-point numbers.
    for f in ("direct_fill_rate", "effective_fill_rate"):
        if out[f] is not None:
            out[f] = float(out[f])
    return out


def ser_event(r):
    return {
        "id": r["id"],
        "channel_id": r["channel_id"],
        "platform_id": r["platform_id"],
        "event_type": r["event_type"],
        "break_id": r["break_id"],
        "decision_id": r["decision_id"],
        "content_id": r["content_id"],
        "viewer_session_id": r["viewer_session_id"],
        "occurred_at_utc": r["occurred_at_utc"],
        "watch_seconds": r["watch_seconds"],
        "quantity": r["quantity"],
        "created_at": r["created_at"],
    }
