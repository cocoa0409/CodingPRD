"""Payload builders.

Each builder returns a minimally valid request body for one endpoint and
accepts keyword overrides so a test can perturb exactly one field.
"""

from .constants import (
    FORM_W9,
    METHODOLOGY_PRO_RATA,
    MIN_FOLLOWERS,
    MIN_WATCH_MINUTES_365D,
    PRODUCT_TYPE_TIPS,
)


def _merge(base, overrides):
    payload = dict(base)
    for key, value in overrides.items():
        payload[key] = value
    return {key: value for key, value in payload.items() if value is not _OMIT}


class _Omit:
    """Sentinel that removes a key from a generated payload."""

    def __repr__(self):
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


def creator_payload(**overrides):
    """A channel that already meets both audience minimums."""
    return _merge(
        {
            "display_name": "Nova Channel",
            "country_code": "GB",
            "follower_count": MIN_FOLLOWERS,
            "watch_time_minutes_365d": MIN_WATCH_MINUTES_365D,
        },
        overrides,
    )


def metrics_payload(**overrides):
    return _merge({"follower_count": MIN_FOLLOWERS}, overrides)


def policy_strike_payload(**overrides):
    return _merge({"reason": "Repeated advertiser-policy violation."}, overrides)


def payout_settings_payload(**overrides):
    return _merge({"payout_method": "CHECK"}, overrides)


def tax_profile_payload(creator_id, expected_creator_version, **overrides):
    return _merge(
        {
            "creator_id": creator_id,
            "form_type": FORM_W9,
            "country_code": "US",
            "tin_provided": True,
            "treaty_claimed": False,
            "expected_creator_version": expected_creator_version,
        },
        overrides,
    )


def verify_payload(**overrides):
    return _merge({"decision": "VERIFY"}, overrides)


def reject_payload(**overrides):
    return _merge(
        {"decision": "REJECT", "rejection_reason": "Name does not match the TIN."},
        overrides,
    )


def revise_payload(**overrides):
    return _merge({"tin_provided": True}, overrides)


def product_payload(**overrides):
    """A tips product with a whole share split and no minimum."""
    return _merge(
        {
            "product_type": PRODUCT_TYPE_TIPS,
            "name": "Tips Flat",
            "creator_share_bps": 5000,
            "platform_fee_bps": 5000,
            "min_payable_cents": 0,
        },
        overrides,
    )


def content_item_payload(creator_id, **overrides):
    return _merge(
        {
            "creator_id": creator_id,
            "title": "Studio Session",
            "published_at": "2026-07-01T00:00:00Z",
        },
        overrides,
    )


def rate_payload(rating, **overrides):
    return _merge(
        {"suitability_rating": rating, "rating_source": "MANUAL"}, overrides
    )


def revenue_event_payload(creator_id, product_id, **overrides):
    return _merge(
        {
            "creator_id": creator_id,
            "product_id": product_id,
            "gross_amount_cents": 10000,
            "occurred_at": "2026-07-05T00:00:00Z",
        },
        overrides,
    )


def appeal_payload(content_item_id, **overrides):
    return _merge(
        {
            "content_item_id": content_item_id,
            "requested_rating": "GREEN",
            "statement_text": "The clip is licensed and advertiser safe.",
        },
        overrides,
    )


def request_info_payload(**overrides):
    return _merge({"info_request": "Please attach the licence."}, overrides)


def respond_payload(**overrides):
    return _merge({"response_statement": "Licence attached."}, overrides)


def decide_appeal_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


def period_payload(**overrides):
    return _merge(
        {
            "label": "2026-07",
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-08-01T00:00:00Z",
        },
        overrides,
    )


def dispute_payload(claimed_amount_cents, **overrides):
    return _merge(
        {
            "dispute_reason": "Two tips from the fifth were mine.",
            "dispute_claimed_amount_cents": claimed_amount_cents,
        },
        overrides,
    )


def resolve_dispute_payload(decision, adjustment_cents, **overrides):
    return _merge(
        {"decision": decision, "adjustment_cents": adjustment_cents}, overrides
    )


def payout_payload(creator_id, **overrides):
    return _merge({"creator_id": creator_id}, overrides)


def settlement_payload(outcome, **overrides):
    return _merge({"outcome": outcome}, overrides)


def investigation_payload(creator_id, **overrides):
    return _merge(
        {
            "creator_id": creator_id,
            "scope": "Advertiser complaint about July revenue.",
            "violation_window_start": "2026-07-01T00:00:00Z",
            "violation_window_end": "2026-07-31T00:00:00Z",
        },
        overrides,
    )


def substantiate_payload(**overrides):
    return _merge({"finding": "Violation confirmed by the review board."}, overrides)


def clear_payload(**overrides):
    return _merge({"finding": "Complaint withdrawn; no violation found."}, overrides)


def fund_payload(period_id, **overrides):
    return _merge(
        {
            "name": "Creator Fund",
            "period_id": period_id,
            "total_pool_cents": 100000,
            "methodology": METHODOLOGY_PRO_RATA,
            "min_watch_time_minutes": 0,
        },
        overrides,
    )


def allocate_payload(expected_fund_version, **overrides):
    return _merge({"expected_fund_version": expected_fund_version}, overrides)


def void_allocations_payload(expected_fund_version, **overrides):
    return _merge(
        {
            "expected_fund_version": expected_fund_version,
            "reason": "Programme cancelled by Finance.",
        },
        overrides,
    )


def clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}
