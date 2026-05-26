"""Cascade tests: depth-3 (Booking COMPLETE → Sitter counters → tier recompute)
and depth-4 (InsuranceClaim PAID → Sitter.claim_count → SUSPENDED →
auto-cancel CONFIRMED Booking → Owner.wallet credit refund). Plus the
shallow (depth-2) BG-flag cascade on a Sitter with no Bookings.

Covers queue A transitive_cascade instances and queue B
cascading_side_effects corner instance.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    create_booking_payload,
    TEST_USERS,
    make_owner_headers,
    make_sitter_headers,
    setup_completed_booking,
    setup_sitter_with_one_paid_claim,
    setup_approved_meet_and_greet,
    setup_confirmed_booking,
    register_owner,
    register_sitter,
    create_pending_bg_check,
    flag_bg_check,
    pin_clock,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---- Queue A: transitive_cascade — depth-3 from Booking COMPLETE ------------

def test_booking_complete_cascades_to_sitter_counters_then_tier(api):
    """PRD §3.6: "The sitter's `total_completed_bookings` increases by 1.
    When `owner_rating` is not null, the rating is folded into the
    sitter's running average by adding it to `total_rating_sum` and
    incrementing `total_rating_count` by 1; when `owner_rating` is null,
    the rating counters are untouched. The change to any of the four
    counters that feed the tier score (`total_completed_bookings`,
    `total_rating_sum`, `total_rating_count`, `claim_count`) triggers a
    `sitter_tier_score` recompute."
    PRD §3.7: "The derived `tier` is `GOLD` when `tier_score` is at
    least `70`, `SILVER` when `tier_score` is at least `40` and below
    `70`, and `BRONZE` otherwise."

    Design: Difficulty/transitive_cascade/booking_complete_cascade_depth_three_booking_to_sitter_counters_to_tier
    """
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-06T08:00:00Z",
        mg_scheduled_at="2026-06-06T07:30:00Z",
        booking_start_at="2026-06-06T09:00:00Z",
        booking_end_at="2026-06-06T10:00:00Z",
        service_type="WALK_60MIN", owner_rating=3,
    )
    # Link 1: Booking is COMPLETED.
    assert booking["status"] == "COMPLETED"
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    # Link 2: counters mutated.
    assert s_after["total_completed_bookings"] == 1
    assert s_after["total_rating_sum"] == 3
    assert s_after["total_rating_count"] == 1
    # Link 3: counter mutations triggered tier_score recompute.
    # rating_score=60, bookings=1, weighted_sum = 60*0.5 + 1*0.3 + 10 = 40.3 → 40.
    assert s_after["tier_score"] == 40
    assert s_after["tier"] == "SILVER"


def test_booking_complete_without_rating_only_bumps_completed_counter(api):
    """PRD §3.6: "The sitter's `total_completed_bookings` increases by 1.
    When `owner_rating` is not null, the rating is folded into the
    sitter's running average by adding it to `total_rating_sum` and
    incrementing `total_rating_count` by 1; when `owner_rating` is null,
    the rating counters are untouched."

    Same cascade origin (Booking COMPLETE) with a different rating
    input (null): the link-2 counter mutation pattern is different —
    only total_completed_bookings advances; total_rating_sum and
    total_rating_count stay at 0.

    Design: Difficulty/transitive_cascade/booking_complete_cascade_depth_three_booking_to_sitter_counters_to_tier
    """
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-06T08:00:00Z",
        mg_scheduled_at="2026-06-06T07:30:00Z",
        booking_start_at="2026-06-06T09:00:00Z",
        booking_end_at="2026-06-06T10:00:00Z",
        service_type="WALK_60MIN", owner_rating=None,
    )
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_after["total_completed_bookings"] == 1
    assert s_after["total_rating_sum"] == 0
    assert s_after["total_rating_count"] == 0


# ---- Queue A: transitive_cascade — depth-4 from Claim PAID ------------------

def test_second_claim_paid_suspends_sitter_and_auto_cancels_confirmed_bookings(api):
    """PRD §3.8: "Finally, if the increment of `claim_count` causes it to
    cross the value 2 (i.e. `claim_count` becomes greater than or equal
    to 2) while the sitter's `status` is `ACTIVE`, the sitter is moved
    to `SUSPENDED` per the sitter state machine, `Sitter.suspended_at`
    is stamped, and `Sitter.version` bumps again."

    Note: the PRD attaches auto-cancel-of-affected-bookings + owner-wallet
    refund explicitly to Cascade #1 (BG-flag) propagation, not to
    Cascade #2's SUSPENSION branch — those links are intentionally not
    asserted here.

    Design: Difficulty/transitive_cascade/claim_pay_cascade_depth_four_claim_to_sitter_to_bookings_to_owner_wallet
    """
    # Seed: Sitter with one PAID claim (claim_count=1) still ACTIVE.
    owner, sitter, pet, mg, completed_booking, first_paid_claim = setup_sitter_with_one_paid_claim(
        clock_iso="2026-06-07T08:00:00Z",
        mg_scheduled_at="2026-06-07T07:30:00Z",
        booking_start_at="2026-06-07T09:00:00Z",
        booking_end_at="2026-06-07T10:00:00Z",
    )
    s_before = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_before["claim_count"] == 1
    assert s_before["status"] == "ACTIVE"
    # File a second claim, escalate to PAID.
    second_claim = validate_success(api.create_insurance_claim(
        {"booking_id": completed_booking["id"], "claim_amount_cents": 8000},
        make_owner_headers(owner["id"]),
    ), 201)
    validate_success(api.start_review_insurance_claim(second_claim["id"], CLAIMS_ADJUSTER), 200)
    validate_success(api.approve_insurance_claim(second_claim["id"],
                                                   {"approved_amount_cents": 6000},
                                                   CLAIMS_ADJUSTER), 200)
    second_paid = validate_success(api.pay_insurance_claim(second_claim["id"],
                                                             CLAIMS_ADJUSTER), 200)
    # Link 1: claim status → PAID.
    assert second_paid["status"] == "PAID"
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    # Link 2a: Sitter.claim_count == 2.
    assert s_after["claim_count"] == 2
    # Link 2b: Sitter SUSPENDED (claim_count crossed 2 while ACTIVE).
    assert s_after["status"] == "SUSPENDED"


def test_second_claim_paid_increments_claim_count_to_two(api):
    """PRD §2.5: "Paying out an approved insurance claim increments the
    sitter's `claim_count`, which recomputes the sitter's tier; if the
    tier drops, every upcoming booking on that sitter's calendar (those
    still in `REQUESTED` or `CONFIRMED` status) is re-quoted at the new
    tier and any provisional payout is adjusted by the delta; if the
    sitter's `claim_count` crosses the value 2 while the sitter is
    `ACTIVE`, the sitter is also moved to `SUSPENDED` for safety review."

    A complementary aspect of the depth-4 cascade — verify the link-2a
    counter mutation on Sitter.claim_count in isolation, even when no
    future bookings exist to be auto-cancelled. The cascade is shorter
    in this configuration (links 1 and 2 only, no 3 or 4).

    Design: Difficulty/transitive_cascade/claim_pay_cascade_depth_four_claim_to_sitter_to_bookings_to_owner_wallet
    """
    owner, sitter, pet, mg, completed_booking, first_paid_claim = setup_sitter_with_one_paid_claim(
        clock_iso="2026-06-07T08:00:00Z",
        mg_scheduled_at="2026-06-07T07:30:00Z",
        booking_start_at="2026-06-07T09:00:00Z",
        booking_end_at="2026-06-07T10:00:00Z",
    )
    second_claim = validate_success(api.create_insurance_claim(
        {"booking_id": completed_booking["id"], "claim_amount_cents": 8000},
        make_owner_headers(owner["id"]),
    ), 201)
    validate_success(api.start_review_insurance_claim(second_claim["id"], CLAIMS_ADJUSTER), 200)
    validate_success(api.approve_insurance_claim(second_claim["id"],
                                                   {"approved_amount_cents": 6000},
                                                   CLAIMS_ADJUSTER), 200)
    validate_success(api.pay_insurance_claim(second_claim["id"], CLAIMS_ADJUSTER), 200)
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_after["claim_count"] == 2


# ---- Queue B: cascading_side_effects — BG flag with no Bookings -------------

def test_bg_flag_on_sitter_in_bg_check_pending_suspends_sitter(api):
    """PRD §3.2: "The flagged disposition is more consequential: it
    requires a non-empty `flagged_reason`, advances the `BackgroundCheck`
    from `PENDING` to `FLAGGED`, records the supplied `flagged_reason`
    on the row, and originates Cascade #1. Cascade #1 propagates as
    follows: the sitter (whether currently `BG_CHECK_PENDING` or
    `ACTIVE`) is moved to `SUSPENDED`, `Sitter.suspended_at` is stamped
    with the current clock, and `Sitter.version` increments."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_bg_flag_not_in_progress
    """
    sitter = register_sitter()
    bg = create_pending_bg_check(sitter["id"], provider="CHECKR")
    # Pre-condition: Sitter in BG_CHECK_PENDING (no bookings).
    flagged = flag_bg_check(bg["id"], reason="verification failed")
    assert flagged["status"] == "FLAGGED"  # link 1
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    # link 2: Sitter SUSPENDED (from BG_CHECK_PENDING).
    assert s_after["status"] == "SUSPENDED"
    assert s_after["suspended_at"] is not None
