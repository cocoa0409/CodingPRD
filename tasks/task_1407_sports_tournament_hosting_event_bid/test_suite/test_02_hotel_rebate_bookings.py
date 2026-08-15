"""Hotel block rebate economics and room booking tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_hotel_block_payload, create_booking_payload,
    create_event, create_hotel_block, create_booking, reconcile_block, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]


def _get_block(api, block_id):
    return get_success_data(api.get_hotel_block(block_id, ANY))


# ===========================================================================
# Corner / entities (booking computed fields)
# ===========================================================================

def test_booking_computed_money_fields(api):
    """PRD §3.3: "At creation the booking pins its `rate_cents` from the block's
    current `room_rate_cents`; later changes to the block's rate never reprice
    an existing booking. Two values derive from the pin: `room_nights`, the
    `rooms_count` multiplied by the number of nights in the stay window, and
    `total_charge_cents`, the `room_nights` multiplied by the pinned
    `rate_cents`."
    PRD §3.3: "A booking is born `RESERVED`..."

    Design: Corner/entities/booking_computed_money_fields
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    resp = api.create_booking(block["id"], create_booking_payload(
        rooms_count=3, check_in_date="2026-10-08", check_out_date="2026-10-12"), ADMIN)
    booking = validate_success(resp, expected_status=201)
    assert booking["room_nights"] == 12
    assert booking["rate_cents"] == 15000
    assert booking["total_charge_cents"] == 180000
    assert booking["status"] == "RESERVED"


def test_booking_room_nights_input_ignored(api):
    """PRD §3.3: "Two values derive from the pin: `room_nights`, the
    `rooms_count` multiplied by the number of nights in the stay window, and
    `total_charge_cents`, the `room_nights` multiplied by the pinned
    `rate_cents`."

    Design: Corner/entities/booking_room_nights_input_ignored
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    payload = create_booking_payload(rooms_count=3, check_in_date="2026-10-08",
                                     check_out_date="2026-10-12")
    payload["room_nights"] = 999
    resp = api.create_booking(block["id"], payload, ADMIN)
    booking = validate_success(resp, expected_status=201)
    assert booking["room_nights"] == 12


# ===========================================================================
# Queue A: dual_variant_calc / hotel_rebate_estimated_vs_final
# ===========================================================================

def _setup_rebate_dual_variant(api):
    """Block contracted; B1 18 rooms (72 nights) and B2 1 room (4 nights) both
    RESERVED. Captures the estimated rebate, then drives B1 to CHECKED_OUT and
    cancels B2, then closes the cutoff. Returns (block_id, estimated_before)."""
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    b1 = create_booking(block["id"], rooms_count=18, guest_name="Block A")
    b2 = create_booking(block["id"], rooms_count=1, guest_name="Block B")
    estimated_before = _get_block(api, block["id"])["estimated_rebate_cents"]
    # Cancel B2 before confirming B1 (cancel is allowed from RESERVED).
    validate_success(api.transition_booking(b2["id"], {"action": "CANCEL"}, ADMIN))
    validate_success(api.transition_booking(b1["id"], {"action": "CONFIRM"}, ADMIN))
    set_clock("2026-10-09T00:00:00Z")
    validate_success(api.transition_booking(b1["id"], {"action": "CHECK_IN"}, ADMIN))
    set_clock("2026-10-13T00:00:00Z")
    validate_success(api.transition_booking(b1["id"], {"action": "CHECK_OUT"}, ADMIN))
    validate_success(api.close_cutoff(block["id"], ADMIN))
    return block["id"], estimated_before


def test_hotel_rebate_estimated_vs_final_variants_differ(api):
    """PRD §3.3: "Two variants of this calculation exist, and they differ only
    in which bookings count. The estimated variant — exposed as
    `estimated_rebate_cents` and recomputed on every read of the block before
    reconcile — is forward-looking and counts bookings in `RESERVED`,
    `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, or `NO_SHOW`, including bookings
    that may still cancel; `rebate_tier` follows this estimated computation and
    sits at `TIER_0` until it is computable. The final variant runs once, at
    reconcile, and counts only actualized pickup — bookings in `CHECKED_OUT` or
    `NO_SHOW`; it writes `final_rebate_cents` (null before reconcile), freezes
    `rebate_tier`, and on identical data yields a rebate lower than or equal to
    the estimate."

    Design: Difficulty/dual_variant_calc/hotel_rebate_estimated_vs_final
    """
    block_id, estimated_before = _setup_rebate_dual_variant(api)
    # Estimated variant: 76 picked-up nights (72+4) at pickup 0.9500 -> rate
    # 0.10; per-booking rounding: round(1080000*0.10) + round(60000*0.10).
    assert estimated_before == 114000
    reconciled = validate_success(api.reconcile_hotel_block(block_id, ADMIN))
    # Final variant: only the CHECKED_OUT booking (72 nights) counts.
    assert reconciled["final_rebate_cents"] == 108000
    assert reconciled["picked_up_room_nights"] == 72
    assert reconciled["rebate_tier"] == "TIER_2"
    assert reconciled["attrition_penalty_cents"] == 0
    assert estimated_before != reconciled["final_rebate_cents"]


def test_hotel_rebate_final_frozen_and_pickup_set_excludes_cancelled(api):
    """PRD §3.3: "The final variant runs once, at reconcile, and counts only
    actualized pickup — bookings in `CHECKED_OUT` or `NO_SHOW`; it writes
    `final_rebate_cents` (null before reconcile), freezes `rebate_tier`, and on
    identical data yields a rebate lower than or equal to the estimate."
    PRD §3.3: "the block's `picked_up_room_nights` — the sum of `room_nights`
    over bookings in `RESERVED`, `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, or
    `NO_SHOW` — is recomputed to include it immediately."

    Design: Difficulty/dual_variant_calc/hotel_rebate_estimated_vs_final
    """
    block_id, estimated_before = _setup_rebate_dual_variant(api)
    block = validate_success(api.reconcile_hotel_block(block_id, ADMIN))
    assert block["status"] == "RECONCILED"
    assert block["final_rebate_cents"] == 108000
    assert block["picked_up_room_nights"] == 72
    # The CANCELLED 4-night booking is excluded from the final variant, so the
    # final rebate is strictly below the estimated one computed on the same rows.
    assert block["final_rebate_cents"] < estimated_before


# ===========================================================================
# Queue A: combinatorial_formula / hotel_rebate_tier_attrition_interplay
# ===========================================================================

def test_hotel_rebate_tier_zero_with_attrition_penalty(api):
    """PRD §3.3: "The tier ladder reads: a ratio of at least 1.0000 earns
    `TIER_3` at a rate of 0.12; at least 0.9000 earns `TIER_2` at 0.10; at least
    0.8000 earns `TIER_1` at 0.07; anything lower is `TIER_0` with no rebate."
    PRD §3.3: "Attrition punishes slippage. The attrition floor is one minus
    `attrition_allowance_pct`. When the pickup ratio falls below that floor, the
    shortfall in room-nights is the floor multiplied by the contracted supply,
    rounded down to a whole number, minus `picked_up_room_nights`; the
    `attrition_penalty_cents` is that shortfall multiplied by the block's
    `room_rate_cents` and then by one half, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/hotel_rebate_tier_attrition_interplay
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    create_booking(block["id"], rooms_count=15, guest_name="Block A", check_in_out=True)
    validate_success(api.close_cutoff(block["id"], ADMIN))
    reconciled = validate_success(api.reconcile_hotel_block(block["id"], ADMIN))
    # 60 picked-up nights / 80 contracted = 0.7500 < 0.8000 -> TIER_0.
    assert reconciled["picked_up_room_nights"] == 60
    assert reconciled["rebate_tier"] == "TIER_0"
    assert reconciled["final_rebate_cents"] == 0
    # shortfall = floor(0.8 * 80) - 60 = 4 nights; penalty = 4 * 15000 * 0.5.
    assert reconciled["attrition_penalty_cents"] == 30000


def test_hotel_rebate_attrition_floor_boundary_no_penalty_at_floor(api):
    """PRD §3.3: "When the ratio meets or exceeds the floor, the penalty is
    zero."
    PRD §3.3: "The tier ladder reads: a ratio of at least 1.0000 earns `TIER_3`
    at a rate of 0.12; at least 0.9000 earns `TIER_2` at 0.10; at least 0.8000
    earns `TIER_1` at 0.07; anything lower is `TIER_0` with no rebate."

    Design: Difficulty/combinatorial_formula/hotel_rebate_tier_attrition_interplay
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    # 16 rooms x 4 nights = 64 picked-up nights; 64/80 = 0.8000 exactly hits
    # both the TIER_1 floor and the attrition floor (1 - 0.20).
    create_booking(block["id"], rooms_count=16, guest_name="Block A", check_in_out=True)
    validate_success(api.close_cutoff(block["id"], ADMIN))
    reconciled = validate_success(api.reconcile_hotel_block(block["id"], ADMIN))
    assert reconciled["picked_up_room_nights"] == 64
    assert reconciled["rebate_tier"] == "TIER_1"
    assert reconciled["final_rebate_cents"] == 67200  # round(960000 * 0.07)
    assert reconciled["attrition_penalty_cents"] == 0


# ===========================================================================
# Queue A: boundary_precision_check / rebate_tier_boundary_exactly_090
# ===========================================================================

def test_rebate_tier_boundary_exactly_090_earns_tier2(api):
    """PRD §3.3: "The tier ladder reads: a ratio of at least 1.0000 earns
    `TIER_3` at a rate of 0.12; at least 0.9000 earns `TIER_2` at 0.10; at least
    0.8000 earns `TIER_1` at 0.07; anything lower is `TIER_0` with no rebate."

    Design: Difficulty/boundary_precision_check/rebate_tier_boundary_exactly_090
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    create_booking(block["id"], rooms_count=18, guest_name="Block A", check_in_out=True)
    validate_success(api.close_cutoff(block["id"], ADMIN))
    reconciled = validate_success(api.reconcile_hotel_block(block["id"], ADMIN))
    # 72/80 = 0.9000 exactly; the floor is inclusive so TIER_2 (0.10) applies.
    assert reconciled["picked_up_room_nights"] == 72
    assert reconciled["rebate_tier"] == "TIER_2"
    assert reconciled["final_rebate_cents"] == 108000


def test_rebate_tier_one_night_below_090_falls_to_tier1(api):
    """PRD §3.3: "The tier ladder reads: a ratio of at least 1.0000 earns
    `TIER_3` at a rate of 0.12; at least 0.9000 earns `TIER_2` at 0.10; at least
    0.8000 earns `TIER_1` at 0.07; anything lower is `TIER_0` with no rebate."
    PRD §3.3: "The pickup ratio is `picked_up_room_nights` divided by that
    supply, rounded half up to four decimal places."

    Design: Difficulty/boundary_precision_check/rebate_tier_boundary_exactly_090
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    # 17 rooms x 4 nights = 68 picked-up nights; add a 3-night 1-room booking
    # for 71 total: 71/80 = 0.8875 -> below the 0.9000 floor, at/above 0.8000.
    # Both bookings must be created before the clock passes the 2026-10-01
    # cutoff (PRD §3.3: "the logical clock's date must be on or before
    # `cutoff_date` (a booking after cutoff is rejected with
    # `ERR_CUTOFF_PASSED`)"), then walked to CHECKED_OUT so the final rebate
    # variant counts them.
    b1 = create_booking(block["id"], rooms_count=17, guest_name="Block A")
    b2 = create_booking(block["id"], rooms_count=1, guest_name="Block B",
                        check_in_date="2026-10-08", check_out_date="2026-10-11")
    for b in (b1, b2):
        validate_success(api.transition_booking(b["id"], {"action": "CONFIRM"}, ADMIN))
    set_clock("2026-10-09T00:00:00Z")
    for b in (b1, b2):
        validate_success(api.transition_booking(b["id"], {"action": "CHECK_IN"}, ADMIN))
    set_clock("2026-10-13T00:00:00Z")
    for b in (b1, b2):
        validate_success(api.transition_booking(b["id"], {"action": "CHECK_OUT"}, ADMIN))
    validate_success(api.close_cutoff(block["id"], ADMIN))
    reconciled = validate_success(api.reconcile_hotel_block(block["id"], ADMIN))
    assert reconciled["picked_up_room_nights"] == 71
    assert reconciled["rebate_tier"] == "TIER_1"
    # per-booking rounding: round(17*4*15000*0.07) + round(1*3*15000*0.07)
    # = round(71400) + round(3150) = 74550.
    assert reconciled["final_rebate_cents"] == 74550


# ===========================================================================
# Queue A: resource_temporal_overlap / hotel_per_night_aggregate_capacity
# ===========================================================================

def test_hotel_per_night_aggregate_capacity_inclusive_boundary(api):
    """PRD §3.3: "per-night inventory must hold — for every night of the stay,
    the sum of `rooms_count` over all non-`CANCELLED` bookings occupying that
    night, plus the new booking's `rooms_count`, must not exceed
    `contracted_rooms_per_night` (otherwise `ERR_BLOCK_INVENTORY_EXCEEDED`, HTTP
    409)."
    PRD §3.3: "the booking occupies the nights from check-in up to but not
    including check-out, so the night count is the number of days between the
    two dates."

    Design: Difficulty/resource_temporal_overlap/hotel_per_night_aggregate_capacity
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    b1 = create_booking(block["id"], rooms_count=18, guest_name="Block A",
                        check_in_date="2026-10-08", check_out_date="2026-10-12")
    # 18 + 2 = 20 on nights 10-09 and 10-10: exactly at capacity, admitted.
    b2 = validate_success(api.create_booking(block["id"], create_booking_payload(
        guest_name="Block B", rooms_count=2,
        check_in_date="2026-10-09", check_out_date="2026-10-11"), ADMIN),
        expected_status=201)
    assert b2["room_nights"] == 4
    # One more room on the shared night 10-10 would reach 21 > 20.
    resp = api.create_booking(block["id"], create_booking_payload(
        guest_name="Block C", rooms_count=1,
        check_in_date="2026-10-10", check_out_date="2026-10-11"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_BLOCK_INVENTORY_EXCEEDED)
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 76


def test_hotel_per_night_aggregate_non_overlapping_nights_admitted(api):
    """PRD §3.3: "per-night inventory must hold — for every night of the stay,
    the sum of `rooms_count` over all non-`CANCELLED` bookings occupying that
    night, plus the new booking's `rooms_count`, must not exceed
    `contracted_rooms_per_night` (otherwise `ERR_BLOCK_INVENTORY_EXCEEDED`, HTTP
    409)."
    PRD §3.3: "the booking occupies the nights from check-in up to but not
    including check-out, so the night count is the number of days between the
    two dates."

    Design: Difficulty/resource_temporal_overlap/hotel_per_night_aggregate_capacity
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    create_booking(block["id"], rooms_count=20, guest_name="Full House",
                   check_in_date="2026-10-08", check_out_date="2026-10-10")
    # Nights 10-10 and 10-11 are free (the first booking occupies 08 and 09):
    # a full 20-room booking on the later nights is admitted.
    b2 = validate_success(api.create_booking(block["id"], create_booking_payload(
        guest_name="Late Full House", rooms_count=20,
        check_in_date="2026-10-10", check_out_date="2026-10-12"), ADMIN),
        expected_status=201)
    assert b2["room_nights"] == 40
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 80


# ===========================================================================
# Queue A: compensating_invariant / room_night_pickup_cancel_rebook_invariant
# ===========================================================================

def test_room_night_pickup_cancel_rebook_invariant(api):
    """PRD §3.3: "Cancellation computes `cancellation_fee_cents`: zero when the
    logical clock's date is on or before `cutoff_date`, otherwise half of the
    booking's `rooms_count` multiplied by its pinned `rate_cents`, rounded half
    up to whole cents; the field defaults to 0 and the block's
    `picked_up_room_nights` drops by the cancelled booking's `room_nights`."
    PRD §3.3: "the block's `picked_up_room_nights` — the sum of `room_nights`
    over bookings in `RESERVED`, `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, or
    `NO_SHOW` — is recomputed to include it immediately."

    Design: Difficulty/compensating_invariant/room_night_pickup_cancel_rebook_invariant
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    b1 = create_booking(block["id"], rooms_count=2, guest_name="Block A", confirm=True)
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 8
    cancelled = validate_success(api.transition_booking(b1["id"], {"action": "CANCEL"}, ADMIN))
    # Logical clock is still at the 2026-08-01 default, on/before the cutoff.
    assert cancelled["cancellation_fee_cents"] == 0
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 0
    b2 = create_booking(block["id"], rooms_count=2, guest_name="Block A2", confirm=True)
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 8


def test_room_night_pickup_confirm_does_not_double_count(api):
    """PRD §3.3: "Confirming a `RESERVED` booking requires the parent block to
    be `CONTRACTED` (otherwise `ERR_BLOCK_NOT_CONTRACTED`) and moves it to
    `CONFIRMED`; pickup is unchanged because the booking already counted."

    Design: Difficulty/compensating_invariant/room_night_pickup_cancel_rebook_invariant
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    b1 = create_booking(block["id"], rooms_count=2, guest_name="Block A")
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 8
    validate_success(api.transition_booking(b1["id"], {"action": "CONFIRM"}, ADMIN))
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 8


# ===========================================================================
# Queue A: priority_pair_validation_conflict /
#          booking_state_vs_inventory_priority_rejected
# ===========================================================================

def test_booking_state_vs_inventory_priority_rejected(api):
    """PRD §2.9: "Existence comes next, then the optimistic-concurrency version
    check (`ERR_STALE_VERSION`), then event-posture gating
    (`ERR_EVENT_POSTURE_FORBIDS`), then entity-state legality
    (`ERR_INVALID_STATE` or the more specific state errors such as
    `ERR_BID_NOT_EDITABLE`, `ERR_DIVISION_NOT_OPEN`, `ERR_MATCH_NOT_SCHEDULABLE`,
    or `ERR_BLOCK_NOT_CONTRACTED`)."
    PRD §2.9: "...and finally capacity and fiscal limits (room inventory, shift
    capacity, daily assignment limits, block reconcilability)."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_vs_inventory_priority_rejected
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=False)  # stays NEGOTIATING
    resp = api.create_booking(block["id"], create_booking_payload(
        guest_name="Oversize", rooms_count=25,
        check_in_date="2026-10-08", check_out_date="2026-10-12"), ADMIN)
    # Both the block-state gate (6.6) and per-night inventory (11) are violated;
    # the state error must surface first per the fixed validation order.
    validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_CONTRACTED)
    data, meta = validate_paginated(api.list_block_bookings(block["id"], ANY))
    assert meta["total_count"] == 0
    assert data == []


def test_booking_oversize_on_contracted_block_reports_inventory(api):
    """PRD §3.3: "per-night inventory must hold — for every night of the stay,
    the sum of `rooms_count` over all non-`CANCELLED` bookings occupying that
    night, plus the new booking's `rooms_count`, must not exceed
    `contracted_rooms_per_night` (otherwise `ERR_BLOCK_INVENTORY_EXCEEDED`, HTTP
    409)."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_vs_inventory_priority_rejected
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    # Only the inventory rule is violated here (block is CONTRACTED): 25 > 20.
    resp = api.create_booking(block["id"], create_booking_payload(
        guest_name="Oversize", rooms_count=25,
        check_in_date="2026-10-08", check_out_date="2026-10-12"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_BLOCK_INVENTORY_EXCEEDED)
    data, meta = validate_paginated(api.list_block_bookings(block["id"], ANY))
    assert meta["total_count"] == 0


# ===========================================================================
# Corner / errors (booking domain battery), state_machines (double cancel),
# calculations (cancellation fee)
# ===========================================================================

def test_booking_domain_error_battery_rejected(api):
    """PRD §3.3: "Later, a `CommissionAdmin` closes the booking window — legal
    only once the logical clock's date has passed `cutoff_date`, otherwise
    `ERR_CUTOFF_PASSED` (HTTP 409) — moving the block to `CUTOFF_PASSED`."
    PRD §3.3: "every occupied night must lie within the block's window from
    `block_start_date` up to but not including `block_end_date` (otherwise
    `ERR_BOOKING_OUTSIDE_BLOCK_DATES`, HTTP 422)"
    PRD §3.3: "Reconciliation, performed by a `CommissionAdmin` or by the
    block's own `HotelManager`, requires the block to be `CUTOFF_PASSED` —
    reconciling a block in any other status is rejected with
    `ERR_BLOCK_NOT_RECONCILABLE` (HTTP 409)"
    PRD §3.3: "the logical clock's date must be on or before `cutoff_date` (a
    booking after cutoff is rejected with `ERR_CUTOFF_PASSED`)"

    Design: Corner/errors/booking_domain_error_battery_rejected
    """
    ev = create_event()
    b1 = create_hotel_block(ev["id"], contracted=True)
    b2 = create_hotel_block(ev["id"], hotel_name="Hilltop Hotel",
                            contracted_rooms_per_night=10, room_rate_cents=12000,
                            contracted=True)
    # e1: close-cutoff while the clock (2026-08-01) has not passed the cutoff.
    resp = api.close_cutoff(b2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED)
    # e2: check-in night 10-07 is before block_start_date 10-08.
    resp = api.create_booking(b1["id"], create_booking_payload(
        guest_name="Early Bird", rooms_count=1,
        check_in_date="2026-10-07", check_out_date="2026-10-10"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_BOOKING_OUTSIDE_BLOCK_DATES)
    # e3: reconcile while the block is CONTRACTED (not CUTOFF_PASSED).
    resp = api.reconcile_hotel_block(b1["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_RECONCILABLE)
    # e4: booking created after the clock has passed the cutoff.
    set_clock("2026-10-02T00:00:00Z")
    resp = api.create_booking(b1["id"], create_booking_payload(
        guest_name="Late Bird", rooms_count=1,
        check_in_date="2026-10-08", check_out_date="2026-10-10"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED)


def test_booking_double_cancel_rejected(api):
    """PRD §2.10: "Terminal states are absorbing: any further transition
    attempted on an entity already in a terminal state is rejected with
    `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/booking_double_cancel_rejected
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    booking = create_booking(block["id"], rooms_count=1, guest_name="Block A")
    validate_success(api.transition_booking(booking["id"], {"action": "CANCEL"}, ADMIN))
    resp = api.transition_booking(booking["id"], {"action": "CANCEL"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 0


def test_cancellation_fee_after_cutoff(api):
    """PRD §3.3: "Cancellation computes `cancellation_fee_cents`: zero when the
    logical clock's date is on or before `cutoff_date`, otherwise half of the
    booking's `rooms_count` multiplied by its pinned `rate_cents`, rounded half
    up to whole cents; the field defaults to 0 and the block's
    `picked_up_room_nights` drops by the cancelled booking's `room_nights`."

    Design: Corner/calculations/cancellation_fee_after_cutoff
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=True)
    booking = create_booking(block["id"], rooms_count=2, guest_name="Block A", confirm=True)
    set_clock("2026-10-02T00:00:00Z")
    cancelled = validate_success(api.transition_booking(booking["id"], {"action": "CANCEL"}, ADMIN))
    assert cancelled["status"] == "CANCELLED"
    # round_half_up(2 * 15000 * 0.5) = 15000.
    assert cancelled["cancellation_fee_cents"] == 15000
    assert _get_block(api, block["id"])["picked_up_room_nights"] == 0


# ===========================================================================
# Corner / endpoints (reverse reachability)
# ===========================================================================

def test_fk_reverse_reachability_forms(api):
    """PRD §3.3: "Bookings list by `check_in_date` ascending then `created_at`
    ascending, and the filtered booking list additionally accepts
    `hotel_block_id`, `team_id`, `official_id`, and `status` filters."
    PRD §3.2: "Fields belong to venues."

    Design: Corner/endpoints/fk_reverse_reachability_forms
    """
    from test_helpers import (
        setup_event_in_registration_open, create_booking_payload,
        make_teamrep_headers, create_field_payload,
    )
    ctx = setup_event_in_registration_open(division_overrides={"team_cap": 6})
    team = get_success_data(api.create_team(
        ctx["division"]["id"],
        {"name": "Tigers", "contact_email": "t@x.com", "strength_rating": 90}, ADMIN))
    booking = get_success_data(api.create_booking(
        ctx["block"]["id"], create_booking_payload(
            booker_type="TEAM", team_id=team["id"], guest_name="Tigers Lodge",
            rooms_count=2, check_in_date="2026-10-08", check_out_date="2026-10-10"),
        make_teamrep_headers(team["id"])))
    # Filtered list form: bookings of the team.
    data, meta = validate_paginated(api.list_bookings(ANY, params={"team_id": team["id"]}))
    assert meta["total_count"] == 1
    assert [b["id"] for b in data] == [booking["id"]]
    # Sub-resource form: fields of the venue.
    fields, fmeta = validate_paginated(api.list_fields(ctx["venue"]["id"], ANY))
    assert fmeta["total_count"] == 1
    assert [f["id"] for f in fields] == [ctx["field"]["id"]]
