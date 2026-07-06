"""Cancellation settlement (couple- vs service-initiated), deposit-money
conservation, and officiant reputation (displayed vs internal means, empty-set
null) (PRD Sections 2.6, 3.8, 3.9).
"""
import pytest

from test_helpers import (
    fixtures as fx,
    validate_success,
    assert_deposit_conserved,
    make_coordinator_headers, make_couple_headers,
)

COORD = make_coordinator_headers()

# A CONFIRMED booking with travel 100km + UNITY_CANDLE has deposit_due 83190.
_BOOKING_83190 = {
    "travel_distance_km": 100,
    "addon_codes": ["UNITY_CANDLE"],
    "ceremony_start": "2026-09-01T15:00:00Z",
    "ceremony_end": "2026-09-01T16:00:00Z",
}


def test_couple_initiated_cancel_at_60_days_refunds_50_percent(api):
    """PRD §3.8: "The refund fraction is 100 percent when at least 90 days remain,
    50 percent when at least 30 but fewer than 90 days remain, and 0 percent when
    fewer than 30 days remain. `refund_issued_cents` is the captured deposit
    `deposit_captured_cents` multiplied by that fraction, rounded half-up to a whole
    cent, and `forfeit_retained_cents` is the captured deposit minus the refund, so
    the two always sum back to the captured deposit."

    Design: Difficulty/dual_variant_calc/cancellation_settlement_couple_vs_service
    """
    ctx = fx.setup_confirmed_booking(api, deposit_amount_cents=83190, booking_overrides=_BOOKING_83190)
    fx.set_clock(api, "2026-07-03T15:00:00Z")  # ceremony is 60 days out
    resp = api.cancel_booking(
        ctx.booking["id"], {"cancel_reason": "COUPLE_REQUEST"}, make_couple_headers(ctx.couple["id"])
    )
    data = validate_success(resp, 200)
    assert data["refund_issued_cents"] == 41595
    assert data["forfeit_retained_cents"] == 41595
    assert data["cancel_initiator"] == "COUPLE"


def test_service_initiated_cancel_refunds_full_deposit_plus_goodwill(api):
    """PRD §3.8: "A goodwill amount is computed as the booking's
    `quoted_subtotal_cents` multiplied by 10 percent, rounded half-up to a whole
    cent. `refund_issued_cents` is the full captured deposit plus that goodwill
    amount, and `forfeit_retained_cents` is 0."

    Design: Difficulty/dual_variant_calc/cancellation_settlement_couple_vs_service
    """
    ctx = fx.setup_confirmed_booking(api, deposit_amount_cents=83190, booking_overrides=_BOOKING_83190)
    fx.set_clock(api, "2026-07-03T15:00:00Z")
    resp = api.cancel_booking(ctx.booking["id"], {"cancel_reason": "OTHER"}, COORD)  # coordinator -> SERVICE
    data = validate_success(resp, 200)
    assert data["refund_issued_cents"] == 106690
    assert data["forfeit_retained_cents"] == 0
    assert data["cancel_initiator"] == "SERVICE"


def test_deposit_money_conserved_across_confirm_and_cancel(api):
    """PRD §3.8: "`forfeit_retained_cents` is the captured deposit minus the refund,
    so the two always sum back to the captured deposit."

    Design: Difficulty/compensating_invariant/deposit_money_conserved_on_cancel
    """
    ctx = fx.setup_confirmed_booking(api, deposit_amount_cents=83190, booking_overrides=_BOOKING_83190)
    fx.set_clock(api, "2026-07-03T15:00:00Z")
    resp = api.cancel_booking(
        ctx.booking["id"], {"cancel_reason": "COUPLE_REQUEST"}, make_couple_headers(ctx.couple["id"])
    )
    data = validate_success(resp, 200)
    assert data["deposit_captured_cents"] == 83190
    assert data["refund_issued_cents"] == 41595
    assert data["forfeit_retained_cents"] == 41595
    assert_deposit_conserved(data)


def test_couple_refund_credit_increases_by_refund_amount(api):
    """PRD §3.8: "After settlement, the couple's `refund_credit_cents` increases by
    `refund_issued_cents`, and the officiant's `escrow_balance_cents` decreases by
    the captured deposit minus the retained forfeit".

    Design: Difficulty/compensating_invariant/deposit_money_conserved_on_cancel
    """
    ctx = fx.setup_confirmed_booking(api, deposit_amount_cents=83190, booking_overrides=_BOOKING_83190)
    fx.set_clock(api, "2026-07-03T15:00:00Z")
    fx.cancel_booking(api, ctx.booking, ctx.couple)
    couple = fx.get_success_data(api.get_couple(ctx.couple["id"], make_couple_headers(ctx.couple["id"])))
    assert couple["refund_credit_cents"] == 41595


# --- Officiant reputation over a fixed review population ---

def _officiant_with_published_4_and_submitted_2(api) -> str:
    ref = fx.setup_reference(api)
    b1 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-04-01T15:00:00Z", ceremony_end="2026-04-01T16:00:00Z")
    fx.place_hold(api, b1, ref.couple, ref.officiant["version"])
    v2 = fx.current_officiant_version(api, ref.officiant["id"])
    b2 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-04-08T15:00:00Z", ceremony_end="2026-04-08T16:00:00Z")
    fx.place_hold(api, b2, ref.couple, v2)
    fx.confirm_booking(api, b1, ref.couple, 70800)
    fx.confirm_booking(api, b2, ref.couple, 70800)
    fx.set_clock(api, "2026-04-09T00:00:00Z")
    fx.complete_booking(api, b1, ref.officiant)
    fx.complete_booking(api, b2, ref.officiant)
    review1 = fx.create_review(api, b1, ref.couple, rating=4, text="Wonderful")
    fx.create_review(api, b2, ref.couple, rating=2, text="Okay")
    fx.moderate_review(api, review1, "PUBLISH")
    return ref.officiant["id"]


def test_displayed_rating_is_mean_of_published_reviews_only(api):
    """PRD §3.9: "The public `displayed_rating` is the mean `rating` over the
    officiant's reviews whose status is `PUBLISHED`. ... The officiant's
    `published_review_count` is the number of the officiant's reviews in `PUBLISHED`."

    Design: Difficulty/dual_variant_calc/officiant_reputation_displayed_vs_internal
    """
    off_id = _officiant_with_published_4_and_submitted_2(api)
    officiant = fx.get_officiant(api, off_id)
    assert officiant["displayed_rating"] == pytest.approx(4.00, abs=0.001)
    assert officiant["published_review_count"] == 1


def test_internal_rating_is_mean_of_submitted_and_published_reviews(api):
    """PRD §3.9: "The operations-facing `internal_rating` is the mean `rating` over
    the officiant's reviews whose status is `SUBMITTED` or `PUBLISHED`."

    Design: Difficulty/dual_variant_calc/officiant_reputation_displayed_vs_internal
    """
    off_id = _officiant_with_published_4_and_submitted_2(api)
    officiant = fx.get_officiant(api, off_id)
    assert officiant["internal_rating"] == pytest.approx(3.00, abs=0.001)


def test_displayed_rating_null_with_no_published_reviews(api):
    """PRD §2.6: "`displayed_rating` and `internal_rating` are decimal numbers
    rounded to two decimal places, also round-half-up, and are `null` when there
    are no qualifying reviews."

    Design: Difficulty/boundary_precision_check/reputation_empty_published_set_is_null
    """
    officiant = fx.create_active_officiant(api)
    fetched = fx.get_officiant(api, officiant["id"])
    assert fetched["displayed_rating"] is None


def test_internal_rating_null_and_published_count_zero_with_no_reviews(api):
    """PRD §3.9: "The officiant's `published_review_count` is the number of the
    officiant's reviews in `PUBLISHED`."
    PRD §2.6: "`displayed_rating` and `internal_rating` ... are `null` when there
    are no qualifying reviews."

    Design: Difficulty/boundary_precision_check/reputation_empty_published_set_is_null
    """
    officiant = fx.create_active_officiant(api)
    fetched = fx.get_officiant(api, officiant["id"])
    assert fetched["internal_rating"] is None
    assert fetched["published_review_count"] == 0
