"""Promotion pricing clamp, per-category concurrent-slot capacity, the promotable-vs-slot
precedence, and cancellation windows.

Queue-A depth: promotion_price_clamp_mode_a, promotion_category_slot_aggregate_overlap,
safety_beats_slot_capacity_on_promote.
Queue-B breadth: cancel_promotion_after_window_start_not_cancellable,
promotion_window_end_before_start_validation.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    register_member, publish_petition, create_draft_petition,
    create_promotion, setup_category_two_overlapping_promotions,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
GUEST = TEST_USERS["guest_headers"]


# ── combinatorial_formula / promotion_price_clamp_mode_a ─────────────────────
def test_promotion_price_clamps_before_listing_fee(api):
    """PRD §3.7: "The clamped subtotal is rounded half-up to whole cents, and only then is
    a flat listing fee of 1500 cents added to produce price_cents. The evaluation order is
    pinned — the clamp is applied before the listing fee is added — so the listing fee is
    never clamped away."

    Design: Difficulty/combinatorial_formula/promotion_price_clamp_mode_a
    """
    ctx = publish_petition(category="POLITICS", goal=100)
    promo = create_promotion(ctx["petition_id"], ctx["author_id"], "SPOTLIGHT",
                             "2026-04-01T00:00:00Z", "2026-04-11T00:00:00Z")
    assert promo["price_cents"] == 201500


def test_promotion_duration_days_is_ceiling_of_window(api):
    """PRD §3.7: "duration_days is the length of the window in whole days, computed as the
    ceiling of the elapsed time — the difference between window_end and window_start, in
    seconds, divided by 86400 seconds per day — rounded up to the next whole day."

    Design: Difficulty/combinatorial_formula/promotion_price_clamp_mode_a
    """
    ctx = publish_petition(category="POLITICS", goal=100)
    promo = create_promotion(ctx["petition_id"], ctx["author_id"], "SPOTLIGHT",
                             "2026-04-01T00:00:00Z", "2026-04-11T00:00:00Z")
    assert promo["duration_days"] == 10


# ── resource_temporal_overlap / promotion_category_slot_aggregate_overlap ────
def test_third_overlapping_category_promotion_rejected(api):
    """PRD §3.7: "The purchase is rejected with ERR_PROMO_SLOT_UNAVAILABLE only when 2 or
    more other promotions in the same category, each in SCHEDULED or ACTIVE status, already
    overlap the requested window."

    Design: Difficulty/resource_temporal_overlap/promotion_category_slot_aggregate_overlap
    """
    setup_category_two_overlapping_promotions(category="ENVIRONMENT")
    petE = publish_petition(category="ENVIRONMENT", goal=100)
    resp = api.create_promotion(
        {"petition_id": petE["petition_id"], "placement_tier": "STANDARD",
         "window_start": "2026-04-03T00:00:00Z", "window_end": "2026-04-04T00:00:00Z"},
        make_member_headers(petE["author_id"]))
    validate_error(resp, ApiErrorId.ERR_PROMO_SLOT_UNAVAILABLE.value, expected_status=409)


def test_second_overlapping_category_promotion_allowed(api):
    """PRD §3.7: "Featured slots are capacity-limited per category to 2 concurrent
    placements."
    PRD §3.7: "The purchase is rejected with ERR_PROMO_SLOT_UNAVAILABLE only when 2 or more
    other promotions in the same category, each in SCHEDULED or ACTIVE status, already
    overlap the requested window."

    Design: Difficulty/resource_temporal_overlap/promotion_category_slot_aggregate_overlap
    """
    petB = publish_petition(category="ENVIRONMENT", goal=100)
    create_promotion(petB["petition_id"], petB["author_id"], "STANDARD",
                     "2026-04-01T00:00:00Z", "2026-04-05T00:00:00Z")
    petE = publish_petition(category="ENVIRONMENT", goal=100)
    promo = create_promotion(petE["petition_id"], petE["author_id"], "STANDARD",
                             "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
    assert promo["status"] == "SCHEDULED"


# ── priority_pair_validation_conflict / safety_beats_slot_capacity_on_promote ─
def test_promote_unpromotable_draft_into_full_window_reports_not_promotable(api):
    """PRD §3.7: "Promotion is a safety-gated privilege: the petition must be promotable,
    meaning its moderation_status is APPROVED and its status is PUBLISHED, or the purchase
    is rejected with ERR_PETITION_NOT_PROMOTABLE."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_slot_capacity_on_promote
    """
    setup_category_two_overlapping_promotions(category="ENVIRONMENT")
    author = register_member()
    draft = create_draft_petition(author["id"], category="ENVIRONMENT", goal=100)
    resp = api.create_promotion(
        {"petition_id": draft["id"], "placement_tier": "STANDARD",
         "window_start": "2026-04-03T00:00:00Z", "window_end": "2026-04-04T00:00:00Z"},
        make_member_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_PROMOTABLE.value, expected_status=403)


def test_promote_unpromotable_draft_rejected_in_isolation(api):
    """PRD §3.7: "Promotion is a safety-gated privilege: the petition must be promotable,
    meaning its moderation_status is APPROVED and its status is PUBLISHED, or the purchase
    is rejected with ERR_PETITION_NOT_PROMOTABLE."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_slot_capacity_on_promote
    """
    author = register_member()
    draft = create_draft_petition(author["id"], category="ENVIRONMENT", goal=100)
    resp = api.create_promotion(
        {"petition_id": draft["id"], "placement_tier": "STANDARD",
         "window_start": "2026-04-03T00:00:00Z", "window_end": "2026-04-04T00:00:00Z"},
        make_member_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_PROMOTABLE.value, expected_status=403)


# ── Corner instances ─────────────────────────────────────────────────────────
def test_cancel_promotion_after_window_start_rejected(api):
    """PRD §3.7: "A promotion that is not SCHEDULED, or whose window has already started,
    cannot be cancelled and the attempt is rejected with ERR_PROMO_NOT_CANCELLABLE."

    Design: Corner/state_machines/cancel_promotion_after_window_start_not_cancellable
    """
    ctx = publish_petition(category="OTHER", goal=10)
    promo = create_promotion(ctx["petition_id"], ctx["author_id"], "STANDARD",
                             "2026-04-01T00:00:00Z", "2026-04-05T00:00:00Z")
    api.set_clock("2026-04-02T00:00:00Z", ADMIN)
    resp = api.cancel_promotion(promo["id"], make_member_headers(ctx["author_id"]))
    validate_error(resp, ApiErrorId.ERR_PROMO_NOT_CANCELLABLE.value, expected_status=409)


def test_promotion_window_end_not_after_start_rejected(api):
    """PRD §2.5: "well-formedness of the request body — required fields present, enums
    within their allowed set, integers within their declared bounds, and every window_end
    strictly greater than its window_start (ERR_VALIDATION, 422)."

    Design: Corner/validations/promotion_window_end_before_start_validation
    """
    ctx = publish_petition(category="OTHER", goal=10)
    resp = api.create_promotion(
        {"petition_id": ctx["petition_id"], "placement_tier": "STANDARD",
         "window_start": "2026-04-05T00:00:00Z", "window_end": "2026-04-05T00:00:00Z"},
        make_member_headers(ctx["author_id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)
