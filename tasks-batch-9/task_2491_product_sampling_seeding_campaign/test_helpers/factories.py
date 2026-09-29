"""Payload builders.

Each builder returns a valid request body for one creation endpoint, with
unique identifying strings so that repeated calls inside one test never collide.
Keyword overrides let a test change exactly the field it is probing.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    BADGE_DISCLOSURE_STATEMENT,
    CANONICAL_SEGMENT_CODE,
    CANONICAL_WINDOW_END,
    CANONICAL_WINDOW_START,
    CANONICAL_BUDGET_TOTAL_CENTS,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short, monotonically increasing token unique within one test process."""
    return str(next(_counter))


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------
def campaign_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "name": f"Spring Seeding {suffix}",
        "objective_type": "TRIAL_GENERATION",
        "target_segment_codes": [CANONICAL_SEGMENT_CODE],
        "syndication_retailer_ids": [],
        "sampling_window_start": CANONICAL_WINDOW_START,
        "sampling_window_end": CANONICAL_WINDOW_END,
        "budget_total_cents": CANONICAL_BUDGET_TOTAL_CENTS,
        "review_due_days": 21,
        "min_review_word_count": 10,
        "holdout_pct": 0.0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# KitLine
# ---------------------------------------------------------------------------
def kit_line_payload(campaign_id: str, **overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "component_sku": f"HERO-{suffix}",
        "component_role": "HERO_PRODUCT",
        "unit_cost_cents": 1417,
        "quantity_per_kit": 1,
        "component_discount_pct": 0.8,
    }
    payload.update(overrides)
    return payload


def canonical_kit_line_payloads(campaign_id: str) -> List[Dict[str, Any]]:
    """The three-line kit whose assembly cost is 454 cents over four units.

    HERO-1 costs 1417 for one unit at a 0.80 multiplier, extending to 283.
    ACC-2 costs 388 for two units at 0.85, extending to 116.
    INS-3 costs 554 for one unit at 0.90, extending to 55.
    """
    return [
        {
            "campaign_id": campaign_id,
            "component_sku": "HERO-1",
            "component_role": "HERO_PRODUCT",
            "unit_cost_cents": 1417,
            "quantity_per_kit": 1,
            "component_discount_pct": 0.8,
        },
        {
            "campaign_id": campaign_id,
            "component_sku": "ACC-2",
            "component_role": "ACCESSORY",
            "unit_cost_cents": 388,
            "quantity_per_kit": 2,
            "component_discount_pct": 0.85,
        },
        {
            "campaign_id": campaign_id,
            "component_sku": "INS-3",
            "component_role": "INSERT_CARD",
            "unit_cost_cents": 554,
            "quantity_per_kit": 1,
            "component_discount_pct": 0.9,
        },
    ]


# ---------------------------------------------------------------------------
# FulfillmentCenter / FulfillmentWave
# ---------------------------------------------------------------------------
def fulfillment_center_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "name": f"Central Hub {suffix}",
        "zone_code": "Z1",
        "daily_pick_capacity_units": 100,
        "freight_cents_per_kit": 300,
    }
    payload.update(overrides)
    return payload


def fulfillment_wave_payload(fulfillment_center_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fulfillment_center_id": fulfillment_center_id,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-02T00:00:00Z",
        "planned_capacity_units": 50,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Panelist
# ---------------------------------------------------------------------------
def panelist_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "email": f"panelist{suffix}@example.com",
        "display_name": f"Panelist {suffix}",
        "address_hash": f"H-{suffix}",
        "account_opened_at": "2026-01-01T00:00:00Z",
        "segment_code": CANONICAL_SEGMENT_CODE,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
def screening_answers(**overrides: Any) -> Dict[str, Any]:
    answers: Dict[str, Any] = {"household_size": 4}
    answers.update(overrides)
    return answers


def enrollment_payload(campaign_id: str, panelist_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "panelist_id": panelist_id,
        "screening_answers": screening_answers(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReviewSubmission
# ---------------------------------------------------------------------------
def review_payload(enrollment_id: str, **overrides: Any) -> Dict[str, Any]:
    """A submittable review.

    The disclosure carries the stricter badge phrase, which satisfies the
    submission gate and also every retailer that insists on the badge wording,
    so a default review can travel the whole road to a retailer feed.
    """
    payload: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "headline": "Great hero product",
        "body_text": (
            "This sampling kit arrived quickly and the hero product performed "
            "very well overall"
        ),
        "star_rating": 5,
        "disclosure_statement": BADGE_DISCLOSURE_STATEMENT,
        "honest_opinion_attested": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Retailer
# ---------------------------------------------------------------------------
def retailer_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "name": f"BigBox {suffix}",
        "feed_status": "ACCEPTING",
        "requires_disclosure_badge": True,
        "min_star_rating_accepted": 3,
        "max_reviews_per_panelist_per_month": 1,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DiversionCase
# ---------------------------------------------------------------------------
def diversion_case_payload(
    panelist_id: str, sample_shipment_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "panelist_id": panelist_id,
        "sample_shipment_id": sample_shipment_id,
        "signal_type": "RESALE_LISTING",
        "evidence_note": "Listing found on a resale marketplace",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PurchaseMatch
# ---------------------------------------------------------------------------
def purchase_match_payload(enrollment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "retailer_channel_code": "CH-ONLINE",
        "purchase_amount_cents": 2599,
        "purchased_at": "2026-08-10T00:00:00Z",
        "match_confidence": 0.9,
    }
    payload.update(overrides)
    return payload


def build_body_text(word_count: int) -> Optional[str]:
    """A body of exactly ``word_count`` whitespace-separated words."""
    if word_count <= 0:
        return ""
    return " ".join(f"word{index}" for index in range(1, word_count + 1))
