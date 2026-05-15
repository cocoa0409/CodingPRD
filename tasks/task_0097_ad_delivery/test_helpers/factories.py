"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body. Tests pass overrides for the values they want to control.
Only PRD-declared input fields are produced.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits
(e.g. "2025-05-24T10:30:00.123Z"). PRD §2.9: monetary amounts are
integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def iso_date_offset(*, days: int = 0,
                    base: Optional[date] = None) -> str:
    base = base or date.today()
    return (base + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Random suffix for uniqueness.
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


# ===========================================================================
# Test harness (PRD §3.9)
# ===========================================================================
def advance_clock_payload(seconds: int = 1) -> Dict[str, Any]:
    return {"seconds": seconds}


# ===========================================================================
# Advertiser (PRD §3.1)
# ===========================================================================
def create_advertiser_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /advertisers payload.

    Required: account_type, legal_name, business_license_number,
    industry_category, billing_mode.
    Optional: parent_account_id, credit_line_cents,
    low_balance_threshold_cents, tax_rate_bps.
    """
    suffix = random_suffix(8)
    payload: Dict[str, Any] = {
        "account_type": "INDEPENDENT",
        "legal_name": f"Test Advertiser {suffix}",
        "business_license_number": f"BL-{suffix}",
        "industry_category": "GENERAL",
        "billing_mode": "PREPAY",
    }
    payload.update(overrides)
    return payload


def update_advertiser_payload(**overrides: Any) -> Dict[str, Any]:
    """PUT /advertisers/{id} payload — credit_line_cents,
    low_balance_threshold_cents, tax_rate_bps."""
    return dict(overrides)


# ===========================================================================
# Qualification (PRD §3.1)
# ===========================================================================
def upload_qualification_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /advertisers/{id}/qualifications payload.

    Required: doc_type, doc_url, expiry_date.
    """
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "doc_type": "BUSINESS_LICENSE",
        "doc_url": f"https://example.com/docs/{suffix}.pdf",
        "expiry_date": iso_offset(days=365),
    }
    payload.update(overrides)
    return payload


def review_qualification_payload(outcome: str = "APPROVE",
                                 rejection_reason: Optional[str] = None,
                                 **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    payload.update(overrides)
    return payload


# ===========================================================================
# AccountUser (PRD §3.2)
# ===========================================================================
def create_account_user_payload(external_user_id: Optional[str] = None,
                                account_role: str = "OWNER",
                                **overrides: Any) -> Dict[str, Any]:
    """POST /advertisers/{id}/users payload.

    Required: external_user_id, account_role.
    """
    payload: Dict[str, Any] = {
        "external_user_id": external_user_id or f"user-{random_suffix(6)}",
        "account_role": account_role,
    }
    payload.update(overrides)
    return payload


def patch_account_user_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /advertisers/{id}/users/{userId} payload — account_role,
    status."""
    return dict(overrides)


# ===========================================================================
# Campaign (PRD §3.3)
# ===========================================================================
def create_campaign_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /advertisers/{id}/campaigns payload.

    Required: name, daily_budget_cents, pacing_strategy, start_date.
    Optional: lifetime_budget_cents, end_date.
    """
    payload: Dict[str, Any] = {
        "name": f"Test Campaign {random_suffix(6)}",
        "daily_budget_cents": 100000,
        "pacing_strategy": "STANDARD",
        "start_date": iso_date_offset(days=0),
    }
    payload.update(overrides)
    return payload


def update_campaign_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# ===========================================================================
# AdGroup (PRD §3.3)
# ===========================================================================
def create_ad_group_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /advertisers/{id}/campaigns/{id}/ad-groups payload.

    Required: name, bidding_strategy, bid_cents, targeting_geo.
    Optional: targeting_demographic, targeting_interest,
    targeting_behavior, targeting_device, targeting_dayparts,
    remarketing_audience_id, frequency_cap_per_user_per_day.
    """
    payload: Dict[str, Any] = {
        "name": f"Test AdGroup {random_suffix(6)}",
        "bidding_strategy": "CPC",
        "bid_cents": 500,
        "targeting_geo": ["US-CA"],
    }
    payload.update(overrides)
    return payload


def update_ad_group_payload(**overrides: Any) -> Dict[str, Any]:
    """PUT /advertisers/{id}/campaigns/{id}/ad-groups/{id} payload.

    Permitted (PRD §3.3): name, bid_cents, targeting_*, frequency cap,
    quality_score, predicted_ctr.
    """
    return dict(overrides)


# ===========================================================================
# Creative (PRD §3.4)
# ===========================================================================
def create_creative_payload(**overrides: Any) -> Dict[str, Any]:
    """POST .../creatives payload.

    Required: format, asset_url, headline, body_text, landing_url.
    Optional: required_disclaimer, parent_version_id.
    """
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "format": "IMAGE",
        "asset_url": f"https://cdn.example.com/{suffix}.png",
        "headline": "Buy our product now!",
        "body_text": "High quality, low price.",
        "landing_url": f"https://example.com/lp/{suffix}",
    }
    payload.update(overrides)
    return payload


def prescreen_payload(pre_screen_score: float,
                      outcome: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """POST /creatives/{id}/prescreen payload.

    Required: pre_screen_score. Optional: outcome (PASS|FAIL override).
    """
    payload: Dict[str, Any] = {"pre_screen_score": pre_screen_score}
    if outcome is not None:
        payload["outcome"] = outcome
    payload.update(overrides)
    return payload


def human_review_payload(outcome: str = "APPROVE",
                         rejection_codes: Optional[List[str]] = None,
                         notes: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if rejection_codes is not None:
        payload["rejection_codes"] = rejection_codes
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


def appeal_payload(notes: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


def appeal_decide_payload(outcome: str = "APPROVE",
                          rejection_codes: Optional[List[str]] = None,
                          notes: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if rejection_codes is not None:
        payload["rejection_codes"] = rejection_codes
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ===========================================================================
# Auction (PRD §3.5)
# ===========================================================================
def run_auction_payload(candidate_ad_group_ids: Optional[List[str]] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """POST /auctions payload.

    Required: exchange, pricing_rule, floor_price_cents, user_id, device,
    geo, candidate_ad_group_ids.
    """
    payload: Dict[str, Any] = {
        "exchange": "INTERNAL",
        "pricing_rule": "GSP",
        "floor_price_cents": 50,
        "user_id": f"end-user-{random_suffix(6)}",
        "device": "DESKTOP",
        "geo": "US-CA",
        "candidate_ad_group_ids": (
            list(candidate_ad_group_ids)
            if candidate_ad_group_ids is not None else []
        ),
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# BillingEvent (PRD §3.6)
# ===========================================================================
def create_billing_event_payload(auction_event_id: str,
                                 ad_group_id: str,
                                 event_type: str = "CLICK",
                                 dedup_key: Optional[str] = None,
                                 ivt_score: float = 0.0,
                                 **overrides: Any) -> Dict[str, Any]:
    """POST /billing-events payload.

    Required: event_type, auction_event_id, ad_group_id, dedup_key,
    ivt_score.
    """
    payload: Dict[str, Any] = {
        "event_type": event_type,
        "auction_event_id": auction_event_id,
        "ad_group_id": ad_group_id,
        "dedup_key": dedup_key or f"dedup-{random_suffix(8)}",
        "ivt_score": ivt_score,
    }
    payload.update(overrides)
    return payload


def reverse_billing_event_payload(
    reversal_reason: str = "late-ivt-detection",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /billing-events/{id}/reverse payload — reversal_reason."""
    payload: Dict[str, Any] = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


# ===========================================================================
# ConversionEvent (PRD §3.7)
# ===========================================================================
def create_conversion_payload(advertiser_id: str,
                              user_id: str,
                              source: str = "WEB_PIXEL",
                              conversion_type: str = "PURCHASE",
                              **overrides: Any) -> Dict[str, Any]:
    """POST /conversions payload.

    Required: source, user_id, advertiser_id, conversion_type.
    Optional: value_cents, attribution_window_days, attribution_model.
    """
    payload: Dict[str, Any] = {
        "source": source,
        "user_id": user_id,
        "advertiser_id": advertiser_id,
        "conversion_type": conversion_type,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# WalletTransaction (PRD §3.8)
# ===========================================================================
def create_wallet_tx_payload(tx_type: str,
                             amount_cents: int,
                             idempotency_key: Optional[str] = None,
                             reference_event_id: Optional[str] = None,
                             note: Optional[str] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """POST /advertisers/{id}/wallet/transactions payload.

    Required: tx_type, amount_cents, idempotency_key.
    Optional: reference_event_id, note (required for ADJUSTMENT).
    """
    payload: Dict[str, Any] = {
        "tx_type": tx_type,
        "amount_cents": amount_cents,
        "idempotency_key": (
            idempotency_key or f"idem-{random_suffix(10)}"
        ),
    }
    if reference_event_id is not None:
        payload["reference_event_id"] = reference_event_id
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def reverse_wallet_tx_payload(note: str = "operator-initiated reversal",
                              **overrides: Any) -> Dict[str, Any]:
    """POST /advertisers/{id}/wallet/transactions/{txId}/reverse —
    requires non-empty note per PRD §3.8.
    """
    payload: Dict[str, Any] = {"note": note}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "iso_date_offset",
    "random_suffix",
    "advance_clock_payload",
    "create_advertiser_payload",
    "update_advertiser_payload",
    "upload_qualification_payload",
    "review_qualification_payload",
    "create_account_user_payload",
    "patch_account_user_payload",
    "create_campaign_payload",
    "update_campaign_payload",
    "create_ad_group_payload",
    "update_ad_group_payload",
    "create_creative_payload",
    "prescreen_payload",
    "human_review_payload",
    "appeal_payload",
    "appeal_decide_payload",
    "run_auction_payload",
    "create_billing_event_payload",
    "reverse_billing_event_payload",
    "create_conversion_payload",
    "create_wallet_tx_payload",
    "reverse_wallet_tx_payload",
]
