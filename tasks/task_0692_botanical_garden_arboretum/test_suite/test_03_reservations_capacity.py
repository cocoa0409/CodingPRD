"""Reservation lifecycle and slot-capacity tests: the HELD fork-join into three
terminals, slot-capacity boundary, aggregate-capacity overlap, guest-pass
conservation, expiry sweep, check-in window, and immediate consistency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visitor_headers,
    set_clock,
    create_garden,
    create_time_slot,
    create_nonmember_reservation,
    setup_household_member_with_slot,
)

STAFF = TEST_USERS["staff_headers"]
VISITOR = TEST_USERS["visitor_headers"]


# =============================================================================
# non_linear_state_machine — Reservation fork-join HELD -> CHECKED_IN
# =============================================================================
def test_held_reservation_checks_in_keeps_held_count(api):
    """PRD §3.3: "A `GardenStaff` member checks a reservation in at the gate,
    advancing `HELD` to `CHECKED_IN`; this is allowed only while the reservation
    is `HELD`, only when the current clock falls within the slot window (at or
    after `starts_at` and strictly before `ends_at`)". PRD §3.3: "Check-in does
    *not* release capacity; the heads remain counted in `held_count`."

    HELD party of 1 checks in with clock inside the window -> CHECKED_IN, slot
    held_count stays 1.

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_fork_join_three_terminals
    """
    garden = create_garden(name="Echinacea Field")
    slot = create_time_slot(garden["id"], "2026-04-02T10:00:00Z", "2026-04-02T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    set_clock("2026-04-02T10:30:00Z")
    checked = validate_success(api.check_in_reservation(res["id"], STAFF))
    assert checked["status"] == "CHECKED_IN"
    refreshed_slot = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed_slot["held_count"] == 1, "check-in must NOT release held_count"


def test_held_reservation_cancel_releases_held_count(api):
    """PRD §3.3: "the visitor cancels a `HELD` reservation, advancing `HELD` to
    `CANCELLED`: this releases the reservation's `party_size` from the slot's
    `held_count`, reopens the slot to `OPEN` if it was `CLOSED` and now sits
    below capacity".

    The CANCELLED terminal of the fork-join releases capacity (held_count back to
    0), in contrast to the CHECKED_IN terminal which retains it.

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_fork_join_three_terminals
    """
    garden = create_garden(name="Echinacea Field C")
    slot = create_time_slot(garden["id"], "2026-04-02T10:00:00Z", "2026-04-02T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    cancelled = validate_success(api.cancel_reservation(res["id"], make_visitor_headers("anon-r1")))
    assert cancelled["status"] == "CANCELLED"
    refreshed_slot = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed_slot["held_count"] == 0, "cancel must release held_count"


# =============================================================================
# boundary_precision_check — slot capacity exact fill then one over
# =============================================================================
def test_slot_fills_to_exact_capacity_then_one_over_rejected(api):
    """PRD §3.3: "Holding the party then requires room: the slot's current
    `held_count` plus this reservation's `party_size` must not exceed the slot's
    `capacity`, or the create fails with `ERR_SLOT_CAPACITY_EXCEEDED`." PRD §3.3:
    "if that brings `held_count` up to `capacity` the slot's `status` flips to
    `CLOSED`."

    Capacity 3: a party of 3 fills it exactly (allowed, slot CLOSED); a further
    single head (would be 4 > 3) is rejected.

    Design: Difficulty/boundary_precision_check/bpc_slot_capacity_exact_fill_then_one_over
    """
    garden = create_garden(name="Kalmia Knoll")
    slot = create_time_slot(garden["id"], "2026-04-05T10:00:00Z", "2026-04-05T12:00:00Z",
                           capacity=3, ga_price_cents=2000)
    full = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=3)
    assert full["party_size"] == 3
    refreshed = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed["held_count"] == 3
    assert refreshed["status"] == "CLOSED"
    resp = api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "paid_heads": 1},
        make_visitor_headers("anon-over"),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, expected_status=409)


def test_slot_accepts_party_up_to_capacity(api):
    """PRD §3.3: "the slot's current `held_count` plus this reservation's
    `party_size` must not exceed the slot's `capacity`".

    The boundary is inclusive (<= not <): a party of exactly 3 on a capacity-3
    slot is accepted, confirming X==capacity is allowed.

    Design: Difficulty/boundary_precision_check/bpc_slot_capacity_exact_fill_then_one_over
    """
    garden = create_garden(name="Kalmia Knoll Edge")
    slot = create_time_slot(garden["id"], "2026-04-05T10:00:00Z", "2026-04-05T12:00:00Z",
                           capacity=3, ga_price_cents=2000)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "paid_heads": 3},
        make_visitor_headers("anon-exact"),
    ), expected_status=201)
    assert res["status"] == "HELD"
    assert res["party_size"] == 3


# =============================================================================
# resource_temporal_overlap — TimeSlot aggregate-capacity overlap
# =============================================================================
def test_timeslot_aggregate_capacity_overlap_rejects_second_party(api):
    """PRD §3.3: "the slot's current `held_count` plus this reservation's
    `party_size` must not exceed the slot's `capacity`, or the create fails with
    `ERR_SLOT_CAPACITY_EXCEEDED`."

    On a capacity-3 slot, a first party of 2 (held_count 2) then a second party
    of 2 collides because 2+2 > 3 (aggregate-capacity within one fixed window).

    Design: Difficulty/resource_temporal_overlap/rto_timeslot_aggregate_capacity_overlap
    """
    garden = create_garden(name="Petunia Plaza")
    slot = create_time_slot(garden["id"], "2026-04-07T10:00:00Z", "2026-04-07T12:00:00Z",
                           capacity=3, ga_price_cents=2000)
    create_nonmember_reservation(garden["id"], slot["id"], paid_heads=2)
    refreshed = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed["held_count"] == 2
    resp = api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "paid_heads": 2},
        make_visitor_headers("anon-2"),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, expected_status=409)


def test_timeslot_two_small_parties_share_window_within_capacity(api):
    """PRD §3.3: "On success the slot's `held_count` increases by `party_size`".

    Two parties of 1 each on a capacity-3 slot both succeed and share the single
    fixed window, accumulating held_count to 2 (no pairwise buffer arithmetic,
    unlike venue overlap).

    Design: Difficulty/resource_temporal_overlap/rto_timeslot_aggregate_capacity_overlap
    """
    garden = create_garden(name="Petunia Plaza Share")
    slot = create_time_slot(garden["id"], "2026-04-07T10:00:00Z", "2026-04-07T12:00:00Z",
                           capacity=3, ga_price_cents=2000)
    create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    refreshed = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed["held_count"] == 2, "two parties of 1 accumulate held_count to 2"
    assert refreshed["status"] == "OPEN"


# =============================================================================
# compensating_invariant — guest passes conserved on reserve then cancel
# =============================================================================
def test_guest_passes_refunded_on_reservation_cancel(api):
    """PRD §3.3: "When a membership is attached, the spent guest passes are
    deducted (`guest_passes_remaining` decreases by `guest_heads`)". PRD §3.3:
    "refunds the spent guest passes by adding `guest_heads` back to the
    membership's `guest_passes_remaining`."

    Grant 4; reservation spends 2 (remaining 2); cancel refunds 2 (remaining 4)
    == original grant, and held_count returns to 0.

    Design: Difficulty/compensating_invariant/ci_guest_passes_conserved_on_reserve_then_cancel
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=5,
        slot_starts="2026-04-08T10:00:00Z", slot_ends="2026-04-08T12:00:00Z",
    )
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "guest_heads": 2, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    mid_state = validate_success(api.get_membership(m_id, h))
    assert mid_state["guest_passes_remaining"] == 2, "spending 2 of 4 leaves 2"
    cancelled = validate_success(api.cancel_reservation(res["id"], h))
    assert cancelled["status"] == "CANCELLED"
    final_state = validate_success(api.get_membership(m_id, h))
    assert final_state["guest_passes_remaining"] == 4, "cancel refunds the 2 spent passes back to 4"
    refreshed_slot = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed_slot["held_count"] == 0


def test_guest_pass_balance_conserved_invariant_after_cycle(api):
    """PRD §3.2: "Guest passes are granted by tier at this moment: an
    `INDIVIDUAL` membership receives 0, a `HOUSEHOLD` membership receives the
    garden's `guest_pass_grant_household`". PRD §3.3: "refunds the spent guest
    passes by adding `guest_heads` back to the membership's
    `guest_passes_remaining`."

    The conserved quantity (grant 4) is fully restored after a reserve-then-cancel
    cycle; no passes are leaked or duplicated.

    Design: Difficulty/compensating_invariant/ci_guest_passes_conserved_on_reserve_then_cancel
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=5,
        slot_starts="2026-04-08T10:00:00Z", slot_ends="2026-04-08T12:00:00Z",
    )
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    assert membership["guest_passes_remaining"] == 4, "grant is 4 at activation"
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "guest_heads": 2, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    validate_success(api.cancel_reservation(res["id"], h))
    final_state = validate_success(api.get_membership(m_id, h))
    assert final_state["guest_passes_remaining"] == membership["guest_passes_remaining"], (
        "guest_passes_remaining returns to the original grant after the full cycle"
    )


# =============================================================================
# Corner: state_machines — reservation expiry & check-in window; consistency
# =============================================================================
def test_reservation_expires_on_clock_advance_releases_capacity(api):
    """PRD §2.5: "Any reservation still in `HELD` status whose referenced time
    slot has already ended — that is, the new clock value has reached or passed
    the slot's `ends_at` — transitions to `EXPIRED`. Expiring a reservation
    releases its `party_size` from the slot's `held_count`".

    Advancing to ends_at sweeps a HELD reservation to EXPIRED, held_count -> 0.

    Design: Corner/state_machines/reservation_expires_on_clock_advance_releases_capacity
    """
    garden = create_garden(name="Bluebell Basin")
    slot = create_time_slot(garden["id"], "2026-04-02T10:00:00Z", "2026-04-02T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=2)
    set_clock("2026-04-02T12:00:00Z")
    expired = validate_success(api.get_reservation(res["id"], STAFF))
    assert expired["status"] == "EXPIRED"
    refreshed_slot = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed_slot["held_count"] == 0


def test_checkin_before_slot_window_returns_invalid_state(api):
    """PRD §3.3: "this is allowed only while the reservation is `HELD`, only when
    the current clock falls within the slot window (at or after `starts_at` and
    strictly before `ends_at`)". PRD §3.3: "acting on a terminal reservation
    yields `ERR_INVALID_STATE`."

    Clock still at default (2026-04-01) which is before the slot's 2026-04-02
    start -> check-in rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/checkin_outside_slot_window_returns_invalid_state
    """
    garden = create_garden(name="Crocus Corner")
    slot = create_time_slot(garden["id"], "2026-04-02T10:00:00Z", "2026-04-02T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    resp = api.check_in_reservation(res["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_held_count_visible_immediately_after_reserve(api):
    """PRD §3.3: "On success the slot's `held_count` increases by `party_size`,
    and if that brings `held_count` up to `capacity` the slot's `status` flips to
    `CLOSED`."

    Creating a reservation of 2 heads is immediately reflected by a subsequent
    GET on the slot (held_count 2, still OPEN since 2 < capacity 5).

    Design: Corner/consistency_model/immediate_consistency_held_count_visible_same_request
    """
    garden = create_garden(name="Erica Edge")
    slot = create_time_slot(garden["id"], "2026-04-16T10:00:00Z", "2026-04-16T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    create_nonmember_reservation(garden["id"], slot["id"], paid_heads=2)
    refreshed = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert refreshed["held_count"] == 2
    assert refreshed["status"] == "OPEN"
