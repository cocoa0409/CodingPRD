"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

# Campaign windows that contain the default logical clock reading
# (2026-08-01T00:00:00Z, PRD §2.5) so plain setups are always in-window.
DEFAULT_SUBMISSION_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_SUBMISSION_WINDOW_END = "2026-08-31T23:59:59Z"
DEFAULT_CONTENT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_CONTENT_WINDOW_END = "2026-09-30T23:59:59Z"

_creator_seq = {"n": 0}
_brand_seq = {"n": 0}


def create_creator_payload(**overrides) -> dict:
    _creator_seq["n"] += 1
    n = _creator_seq["n"]
    defaults = {
        "handle": f"creator-{n}",
        "email": f"creator-{n}@example.com",
        "niche": "OTHER",
        "primary_platform": "YOUTUBE",
        "followers": 50000,
        "avg_views_30d": 40000,
        "engagement_rate_bps": 250,
    }
    defaults.update(overrides)
    return defaults


def create_brand_payload(**overrides) -> dict:
    _brand_seq["n"] += 1
    defaults = {"name": f"Brand-{_brand_seq['n']}", "industry": "CPG"}
    defaults.update(overrides)
    return defaults


def create_brief_payload(brand_id: str, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "title": "Campaign Brief",
        "niche": "OTHER",
        "min_followers": 1000,
        "min_engagement_bps": 50,
        "slots_total": 1,
        "budget_cents": 100000000,
        "deliverables_per_slot": 1,
        "usage_rights_days": 45,
        "exclusivity_category": "NONE",
        "exclusivity_days": 0,
        "whitelisting_required": False,
        "revision_rounds_included": 2,
        "submission_window_start": DEFAULT_SUBMISSION_WINDOW_START,
        "submission_window_end": DEFAULT_SUBMISSION_WINDOW_END,
        "content_window_start": DEFAULT_CONTENT_WINDOW_START,
        "content_window_end": DEFAULT_CONTENT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_pitch_payload(
    creator_id: str, expected_brief_version: int, **overrides
) -> dict:
    defaults = {
        "creator_id": creator_id,
        "proposed_fee_cents": 100000,
        "concept_note": "concept",
        "expected_brief_version": expected_brief_version,
    }
    defaults.update(overrides)
    return defaults


def propose_terms_payload(fee_base_cents: int, expected_deal_version: int) -> dict:
    return {
        "fee_base_cents": fee_base_cents,
        "expected_deal_version": expected_deal_version,
    }


def create_deliverable_payload(**overrides) -> dict:
    defaults = {
        "platform": "YOUTUBE",
        "due_date": "2026-08-10T00:00:00Z",
        "scheduled_publish_date": "2026-08-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_performance_report_payload(
    expected_deal_version: int, **overrides
) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-15T00:00:00Z",
        "views": 100000,
        "likes": 1000,
        "comments": 0,
        "shares": 0,
        "expected_deal_version": expected_deal_version,
    }
    defaults.update(overrides)
    return defaults


def finalize_report_payload(audited_views: int, audited_engagements: int) -> dict:
    return {
        "audited_views": audited_views,
        "audited_engagements": audited_engagements,
    }


def disclosure_pass_checklist() -> dict:
    return {
        "action": "PASS",
        "has_ad_hashtag": True,
        "verbal_disclosure": True,
        "platform_tool_used": True,
    }


def disclosure_fail_payload(**checklist) -> dict:
    payload = {
        "action": "FAIL",
        "has_ad_hashtag": False,
        "verbal_disclosure": False,
        "platform_tool_used": False,
    }
    payload.update(checklist)
    return payload


def create_dispute_payload(**overrides) -> dict:
    defaults = {"reason": "OTHER", "note": "dispute note"}
    defaults.update(overrides)
    return defaults


def create_reshoot_payload(**overrides) -> dict:
    defaults = {"reason": "reshoot required"}
    defaults.update(overrides)
    return defaults
