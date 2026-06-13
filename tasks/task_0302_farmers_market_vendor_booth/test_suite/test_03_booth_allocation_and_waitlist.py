"""Booth allocation, waitlist, promotion, completion cascades, and ledger
conservation.

Covers Difficulty rules transitive_cascade, compensating_invariant, and
resource_temporal_overlap, plus the corner waitlist/cascade instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_vendor_headers,
    TEST_USERS,
    create_market, create_booth, create_active_vendor, create_open_market_day,
    reserve_season_assignment, reserve_daily_assignment, waitlist_season_assignment,
    booth_version, create_booth_assignment_payload,
    setup_season_held_with_waitlister, setup_season_held_two_waitlisters,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade
# ---------------------------------------------------------------------------
def test_weather_cancel_cascades_to_assignment_and_ledger(api):
    """PRD 3.6: "every daily booth assignment on the day that is in REQUESTED,
    WAITLISTED, RESERVED, or ACTIVE is cancelled to CANCELLED. Where the reason is
    WEATHER, each such cancelled assignment has its fee_refunded_cents set by the
    refund rule below and, if it was holding a booth, frees that booth's slot;
    freeing a slot then recomputes the parent market's total_fees_collected_cents."
    PRD 3.6 also: "a daily assignment receives a full rebate — its
    fee_refunded_cents equals its fee_charged_cents." DAILY SINGLE fee 4000 ->
    refunded 4000, ledger back to 0.

    Design: Difficulty/transitive_cascade/weather_cancel_day_to_assignment_to_market_ledger
    """
    market = create_market()
    booth = create_booth(market["id"], label="B-01", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    assert asg["fee_charged_cents"] == 4000
    before = get_success_data(api.get_market(market["id"], ADMIN))
    assert before["total_fees_collected_cents"] == 4000

    cancelled_day = validate_success(
        api.cancel_market_day(day["id"], {"cancellation_reason": "WEATHER"}, ADMIN), 200)
    assert cancelled_day["status"] == "CANCELLED"
    assert cancelled_day["daily_fee_refundable"] is True

    asg_after = get_success_data(api.get_booth_assignment(asg["id"], ADMIN))
    assert asg_after["status"] == "CANCELLED"
    assert asg_after["fee_refunded_cents"] == 4000

    market_after = get_success_data(api.get_market(market["id"], ADMIN))
    assert market_after["total_fees_collected_cents"] == 0


def test_weather_cancel_marks_day_and_voids_assignment_status(api):
    """PRD 3.6: "On cancellation the system sets daily_fee_refundable to true
    exactly when the cancellation_reason is WEATHER" and "every daily booth
    assignment on the day that is in REQUESTED, WAITLISTED, RESERVED, or ACTIVE is
    cancelled to CANCELLED." Asserts the day-level and assignment-level hops of the
    cascade chain (distinct from the ledger hop).

    Design: Difficulty/transitive_cascade/weather_cancel_day_to_assignment_to_market_ledger
    """
    market = create_market()
    booth = create_booth(market["id"], label="B-02", grid_row=0, grid_col=2, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])

    cancelled_day = validate_success(
        api.cancel_market_day(day["id"], {"cancellation_reason": "WEATHER"}, ADMIN), 200)
    assert cancelled_day["status"] == "CANCELLED"
    assert cancelled_day["daily_fee_refundable"] is True

    asg_after = get_success_data(api.get_booth_assignment(asg["id"], ADMIN))
    assert asg_after["status"] == "CANCELLED"


def test_complete_season_frees_booth_status_then_reholds(api):
    """PRD 3.3: completion "sets the booth's status back to OPEN, clears
    season_holder_assignment_id ... Completion then promotes the rank-1 waitlisted
    assignment ... which itself runs the waitlist-to-reserved transition", and a
    season reservation "sets the booth's status to SEASON_HELD". After the promote
    the booth is SEASON_HELD again, held by the promoted assignment.

    Design: Difficulty/transitive_cascade/complete_season_to_booth_to_waitlist_promotion
    """
    s = setup_season_held_with_waitlister(corner=True)
    validate_success(api.complete_booth_assignment(s["asg1"]["id"], ADMIN), 200)

    booth_after = get_success_data(api.get_booth(s["booth"]["id"], ADMIN))
    assert booth_after["status"] == "SEASON_HELD"
    assert booth_after["season_holder_assignment_id"] == s["asg2"]["id"]


def test_complete_season_frees_booth_and_promotes_waitlister(api):
    """PRD 3.3: "For a season assignment, completion frees the booth: it sets the
    booth's status back to OPEN, clears season_holder_assignment_id ... Completion
    then promotes the rank-1 waitlisted assignment on the freed slot to RESERVED".
    The promoted SEASON assignment re-locks the CORNER fee 75000 and becomes the
    season holder.

    Design: Difficulty/transitive_cascade/complete_season_to_booth_to_waitlist_promotion
    """
    s = setup_season_held_with_waitlister(corner=True)

    completed = validate_success(api.complete_booth_assignment(s["asg1"]["id"], ADMIN), 200)
    assert completed["status"] == "COMPLETED"

    asg2_after = get_success_data(api.get_booth_assignment(s["asg2"]["id"], ADMIN))
    assert asg2_after["status"] == "RESERVED"
    assert asg2_after["fee_charged_cents"] == 75000

    booth_after = get_success_data(api.get_booth(s["booth"]["id"], ADMIN))
    assert booth_after["season_holder_assignment_id"] == s["asg2"]["id"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant
# ---------------------------------------------------------------------------
def test_complete_then_promote_conserves_fee_ledger(api):
    """PRD 3.3: "Because the occupancy ledger counts only RESERVED and ACTIVE rows,
    completing the holder drops its locked fee from the total and the promotion of
    the next waitlister re-adds an identical fee, leaving the ledger invariant
    across the complete-and-promote pair." Two SEASON CORNER assignments -> ledger
    invariant at 75000.

    Design: Difficulty/compensating_invariant/season_complete_then_promote_conserves_fee_ledger
    """
    s = setup_season_held_with_waitlister(corner=True)
    before = get_success_data(api.get_market(s["market"]["id"], ADMIN))
    assert before["total_fees_collected_cents"] == 75000

    completed = validate_success(api.complete_booth_assignment(s["asg1"]["id"], ADMIN), 200)
    assert completed["status"] == "COMPLETED"

    asg2_after = get_success_data(api.get_booth_assignment(s["asg2"]["id"], ADMIN))
    assert asg2_after["status"] == "RESERVED"
    assert asg2_after["fee_charged_cents"] == 75000

    market_after = get_success_data(api.get_market(s["market"]["id"], ADMIN))
    assert market_after["total_fees_collected_cents"] == 75000, (
        "ledger invariant across complete+promote pair (zero drift)"
    )


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_second_season_request_on_held_booth_waitlists(api):
    """PRD 3.3: "When instead the slot is already occupied by a RESERVED or ACTIVE
    assignment, the request takes the waitlist path: it moves from REQUESTED to
    WAITLISTED, its waitlist_rank is computed as one more than the count of existing
    waitlisted assignments on the same booth ... and its fee_charged_cents stays 0
    while it waits." A SEASON occupation holds the booth across the whole window.

    Design: Difficulty/resource_temporal_overlap/season_overlap_whole_window_waitlists
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    v1 = create_active_vendor(market["id"], "CRAFTS", "V1", "v1@x.com")
    v2 = create_active_vendor(market["id"], "FLOWERS", "V2", "v2@x.com")
    reserve_season_assignment(market["id"], booth["id"], v1["id"])

    asg2 = waitlist_season_assignment(market["id"], booth["id"], v2["id"])
    assert asg2["status"] == "WAITLISTED"
    assert asg2["waitlist_rank"] == 1
    assert asg2["fee_charged_cents"] == 0


def test_season_holder_keeps_booth_held_during_overlap(api):
    """PRD 3.3: "for a season request, the booth must be OPEN with no overlapping
    season or daily occupation across the season window" — the first SEASON holder
    keeps the booth SEASON_HELD across the whole window, which is precisely why the
    second SEASON request collides and waitlists rather than reserving.

    Design: Difficulty/resource_temporal_overlap/season_overlap_whole_window_waitlists
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    v1 = create_active_vendor(market["id"], "CRAFTS", "V1", "v1@x.com")
    v2 = create_active_vendor(market["id"], "FLOWERS", "V2", "v2@x.com")
    asg1 = reserve_season_assignment(market["id"], booth["id"], v1["id"])

    booth_held = get_success_data(api.get_booth(booth["id"], ADMIN))
    assert booth_held["status"] == "SEASON_HELD"
    assert booth_held["season_holder_assignment_id"] == asg1["id"]

    asg2 = waitlist_season_assignment(market["id"], booth["id"], v2["id"])
    assert asg2["status"] == "WAITLISTED", "collides with the whole-window occupation"
    asg1_after = get_success_data(api.get_booth_assignment(asg1["id"], ADMIN))
    assert asg1_after["status"] == "RESERVED"


def test_complete_then_promote_preserves_both_fee_halves(api):
    """PRD 3.3: "completing the holder drops its locked fee from the total and the
    promotion of the next waitlister re-adds an identical fee". Asserts the two
    per-assignment halves: the completed holder's locked fee equals the promoted
    waitlister's newly-locked fee (both 75000 SEASON CORNER), so they cancel.

    Design: Difficulty/compensating_invariant/season_complete_then_promote_conserves_fee_ledger
    """
    s = setup_season_held_with_waitlister(corner=True)
    dropped_fee = s["asg1"]["fee_charged_cents"]
    assert dropped_fee == 75000

    validate_success(api.complete_booth_assignment(s["asg1"]["id"], ADMIN), 200)
    asg2_after = get_success_data(api.get_booth_assignment(s["asg2"]["id"], ADMIN))
    assert asg2_after["status"] == "RESERVED"
    readded_fee = asg2_after["fee_charged_cents"]
    assert readded_fee == dropped_fee, (
        "promotion re-adds an identical fee to the one completion dropped"
    )


# ---------------------------------------------------------------------------
# Corner: state_machines (waitlist re-rank + daily collision)
# ---------------------------------------------------------------------------
def test_cancel_rank1_waitlister_reranks_survivor(api):
    """PRD 3.3: "If instead it was merely WAITLISTED, cancellation re-ranks the
    remaining waitlisted assignments, decrementing each higher rank by 1."
    Cancelling the rank-1 waitlister drops the rank-2 survivor to rank 1.

    Design: Corner/state_machines/cancel_waitlisted_reranks_survivors
    """
    s = setup_season_held_two_waitlisters()
    vh_v2 = make_vendor_headers(s["v2"]["id"])

    cancelled = validate_success(api.cancel_booth_assignment(s["asg2"]["id"], vh_v2), 200)
    assert cancelled["status"] == "CANCELLED"

    asg3_after = get_success_data(api.get_booth_assignment(s["asg3"]["id"], ADMIN))
    assert asg3_after["status"] == "WAITLISTED"
    assert asg3_after["waitlist_rank"] == 1


def test_daily_assignment_collides_only_on_its_own_day(api):
    """PRD 3.3: "for a daily request, no RESERVED or ACTIVE assignment of either
    type may occupy the booth on that market day." A second DAILY on the same
    occupied day waitlists, while a DAILY for a different free day reserves at the
    daily fee (4000 SINGLE).

    Design: Corner/state_machines/daily_assignment_collides_only_on_its_own_day
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    v1 = create_active_vendor(market["id"], "CRAFTS", "V1", "v1@x.com")
    v2 = create_active_vendor(market["id"], "FLOWERS", "V2", "v2@x.com")
    day_a = create_open_market_day(market["id"], market_date="2026-06-06")
    day_b = create_open_market_day(market["id"], market_date="2026-06-13")
    reserve_daily_assignment(market["id"], booth["id"], v1["id"], day_a["id"])

    vh_v2 = make_vendor_headers(v2["id"])
    asg_a2 = get_success_data(api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], v2["id"],
                                        assignment_type="DAILY",
                                        market_day_id=day_a["id"], allow_waitlist=True), vh_v2))
    assert asg_a2["status"] == "WAITLISTED", "collides on the occupied day A"

    asg_b = get_success_data(api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], v2["id"],
                                        assignment_type="DAILY",
                                        market_day_id=day_b["id"]), vh_v2))
    assert asg_b["status"] == "RESERVED", "day B is free"
    assert asg_b["fee_charged_cents"] == 4000


def test_waitlist_rank_ordered_by_created_at(api):
    """PRD 3.3: "Its waitlist_rank is its 1-based position among the waitlisted
    assignments on the same booth ... ordered by created_at ascending, so the
    earliest waitlister ranks first". V2 then V3 get ranks 1 and 2.

    Design: Corner/calculations/waitlist_rank_ordered_by_created_at
    """
    s = setup_season_held_two_waitlisters()
    asg2 = get_success_data(api.get_booth_assignment(s["asg2"]["id"], ADMIN))
    asg3 = get_success_data(api.get_booth_assignment(s["asg3"]["id"], ADMIN))
    assert asg2["waitlist_rank"] == 1
    assert asg3["waitlist_rank"] == 2
