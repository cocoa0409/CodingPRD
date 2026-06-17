"""Second tests for difficulty-queue instances, each asserting a distinct facet of
the same rule so every difficulty instance carries >= 2 tests. All citations are the
same verbatim PRD rules; the assertions probe a different observable than the first
test of each instance.
"""
from test_helpers import (
    validate_error, validate_success, ApiErrorId,
    setup_base, create_held_reservation, confirm_reservation,
    create_confirmed_reservation, create_checked_in_reservation,
    create_group_package, add_fb_order, close_reservation, set_clock,
    create_song, queue_song, run_ops, get_room, get_queue_entry, get_customer,
    get_reservation, get_room_version, get_reservation_version,
    list_payments, payments_of_kind, sum_amount_for_kind,
    create_reservation_payload, create_extension_payload, apply_extension,
    make_customer_headers, make_front_desk_headers, make_venue_manager_headers,
)

FD = make_front_desk_headers()
VM = make_venue_manager_headers()


def _cust(c):
    return make_customer_headers(c["id"])


# ─── dual_variant_calc ────────────────────────────────────────────
def test_quoted_offpeak_only_then_settled_equals_within_plan(api):
    """PRD §3.3: "The two exact segment costs are summed first, and only that sum is
    rounded — once, half-up, to whole cents — to yield `quoted_room_subtotal_cents`."
    PRD §3.4: "For an à la carte session, the accumulated exact total is rounded once,
    half-up, to whole cents to give `settled_room_subtotal_cents`."

    A wholly off-peak 16:00-17:00 LARGE booking quotes 60 * 100 = 6000; running exactly
    to plan settles to the same 6000 — the two algorithms agree when the actual run
    matches the booked interval, the converse of the diverge case.

    Design: Difficulty/dual_variant_calc/room_quoted_forward_vs_settled_chronological_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-01T15:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-07-01T16:00:00.000Z", "2026-07-01T17:00:00.000Z",
        checkin_clock_utc="2026-07-01T16:00:00.000Z",
    )
    assert res["quoted_room_subtotal_cents"] == 6000
    closed = close_reservation(res, "2026-07-01T17:00:00.000Z")
    assert closed["settled_room_subtotal_cents"] == 6000


def test_fb_shortfall_package_credit_alone_meets_minimum(api):
    """PRD §3.4: "The package credit is the package's `included_fb_credit_cents` when a
    package is attached, and 0 otherwise; the effective food-and-beverage figure is the
    consumed amount plus that credit."
    PRD §3.4: "when the effective figure equals or exceeds the floor, `fb_shortfall_cents`
    is 0."

    A package whose credit (5000) alone meets the floor (5000) with zero consumed settles
    fb_shortfall 0 — the credit term of the dual-variant F&B formula in isolation.

    Design: Difficulty/dual_variant_calc/fb_shortfall_package_credit_vs_no_credit_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 5000},
        clock_utc="2026-07-02T17:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    pkg = create_group_package(venue["id"], base["room_type"]["id"], name="Credit",
                               flat_price_cents=20000, included_hours=2.0,
                               included_fb_credit_cents=5000)
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-07-02T20:00:00.000Z", "2026-07-02T22:00:00.000Z",
        checkin_clock_utc="2026-07-02T20:00:00.000Z",
        group_package_id=pkg["id"], party_size=8,
    )
    closed = close_reservation(res, "2026-07-02T22:00:00.000Z")
    assert closed["fb_consumed_cents"] == 0
    assert closed["fb_shortfall_cents"] == 0


# ─── combinatorial_formula ────────────────────────────────────────
def test_quoted_all_peak_full_multiplier(api):
    """PRD §3.3: "the peak cost is the peak minute count times that per-minute base
    times the venue's `peak_multiplier`."

    A wholly-peak 19:00-20:00 LARGE booking is 60 peak minutes at 100 * 1.5 = 9000 —
    the all-peak branch of the per-minute combinatorial quote.

    Design: Difficulty/combinatorial_formula/quoted_peak_straddle_nonlinear_branch
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-02T16:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-07-02T19:00:00.000Z", "2026-07-02T20:00:00.000Z",
                                  party_size=6)
    confirmed = confirm_reservation(res, customer)
    assert confirmed["quoted_room_subtotal_cents"] == 9000


def test_quoted_rounding_deposit_single_round(api):
    """PRD §2.6: "The deposit figure is likewise produced by a single round-half-up
    step."
    PRD §3.3: "recomputes `deposit_cents` as that subtotal multiplied by the venue's
    `deposit_pct` and rounded half-up to whole cents".

    SMALL 17:40-18:15 quotes 2479; deposit = round_half_up(2479 * 0.2) =
    round_half_up(495.8) = 496.

    Design: Difficulty/combinatorial_formula/quoted_rounding_order_sum_then_round
    """
    base = setup_base(
        room_type_overrides={"name": "SMALL", "capacity": 4, "base_hourly_rate_cents": 3500,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-04T16:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-07-04T17:40:00.000Z", "2026-07-04T18:15:00.000Z",
                                  party_size=2)
    confirmed = confirm_reservation(res, customer)
    assert confirmed["quoted_room_subtotal_cents"] == 2479
    assert confirmed["deposit_cents"] == 496


# ─── non_linear_state_machine (queue branch) ──────────────────────
def test_queue_cancel_head_promotes_next(api):
    """PRD §3.6: "a guest may remove their own `PENDING` entry, moving it
    `PENDING → CANCELLED` ... both recompute `play_order` over the remaining `PENDING`
    entries".

    The PENDING fork's third arm (CANCELLED): cancelling the head (priority 10) promotes
    the second entry (priority 20) to play_order 1, mirroring the skip branch on a
    different terminal state.

    Design: Difficulty/non_linear_state_machine/queue_entry_pending_branch_play_vs_skip_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-11T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    s1 = create_song(venue["id"], title="One", artist="A")
    s2 = create_song(venue["id"], title="Two", artist="B")
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-07-11T20:00:00.000Z", "2026-07-11T22:00:00.000Z",
                                        checkin_clock_utc="2026-07-11T20:00:00.000Z")
    q1 = queue_song(res, customer, s1["id"], priority=10)
    q2 = queue_song(res, customer, s2["id"], priority=20)
    data = validate_success(api.cancel_queue_entry(q1["id"], _cust(customer)), 200)
    assert data["status"] == "CANCELLED"
    q2_after = get_queue_entry(q2["id"])
    assert q2_after["status"] == "PENDING"
    assert q2_after["play_order"] == 1


# ─── transitive_cascade ───────────────────────────────────────────
def test_noshow_cascade_reservation_terminal(api):
    """PRD §3.7: "it transitions `CONFIRMED → NO_SHOW` ... its `PENDING` queue entries
    cascade to `CANCELLED`".
    PRD §3.7: "Both `EXPIRED` and `NO_SHOW`, like `CLOSED` and `CANCELLED`, are terminal
    states from which no further transition is possible."

    After the ops sweep no-shows the booking, the cascade leaves the reservation NO_SHOW
    (terminal) and its queue entry CANCELLED — probing the chain's head and tail states
    rather than the payment/strike middle link.

    Design: Difficulty/transitive_cascade/noshow_cascade_payment_customer_queue_depth3
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-12T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="X", artist="X")
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-07-12T20:00:00.000Z", "2026-07-12T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=6)
    q = queue_song(res, customer, song["id"], priority=5)
    set_clock(venue["id"], "2026-07-12T20:16:00.000Z")
    run_ops(venue["id"])
    assert get_reservation(res["id"])["status"] == "NO_SHOW"
    assert get_queue_entry(q["id"])["status"] == "CANCELLED"
    # Terminal: a subsequent cancel is rejected because NO_SHOW is terminal.
    validate_error(api.cancel_reservation(res["id"], _cust(customer)),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_close_cascade_appends_settlement_payment(api):
    """PRD §3.4: "a `Payment` of kind `SETTLEMENT` is appended whose `amount_cents`
    equals the reservation's `final_total_cents`."

    The close cascade's payment link: closing appends exactly one SETTLEMENT payment
    equal to final_total_cents (a different cascade consequence than the room release).

    Design: Difficulty/transitive_cascade/close_cascade_room_release_depth2
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-13T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-07-13T20:00:00.000Z", "2026-07-13T22:00:00.000Z",
                                        checkin_clock_utc="2026-07-13T20:00:00.000Z")
    closed = close_reservation(res, "2026-07-13T21:30:00.000Z")
    settlements = payments_of_kind(list_payments(res["id"]), "SETTLEMENT")
    assert len(settlements) == 1
    assert settlements[0]["amount_cents"] == closed["final_total_cents"]


# ─── priority_pair_validation_conflict ────────────────────────────
def test_confirm_invalid_state_when_checked_in_and_late(api):
    """PRD §3.3: "Confirming requires the reservation to be in `HELD` status; confirming
    anything else is rejected with `ERR_INVALID_STATE`."
    PRD §2.8: "where two checks could both fire on the same request, the lower-numbered
    one is the one that is returned."

    A CHECKED_IN reservation confirmed after slot start violates both state (5) and
    timing (7); state still wins -> ERR_INVALID_STATE, from a different non-HELD state
    than the already-CONFIRMED case.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_timing_window
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-07-14T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-07-14T20:00:00.000Z", "2026-07-14T22:00:00.000Z",
                                        checkin_clock_utc="2026-07-14T20:00:00.000Z")
    set_clock(venue["id"], "2026-07-14T20:30:00.000Z")
    validate_error(api.confirm_reservation(res["id"], _cust(customer)),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_capacity_beats_double_booked_different_overlap(api):
    """PRD §3.3: "The `party_size` must be at least 1 and must not exceed the capacity
    of the reservation's room type; a party larger than the room allows is rejected with
    `ERR_CAPACITY_EXCEEDED`."
    PRD §2.8: "where two checks could both fire on the same request, the lower-numbered
    one is the one that is returned."

    A second create that overlaps an existing booking (10) AND requests party_size 12 >
    capacity 4 (8) still returns the lower-numbered capacity error — a different overlap
    geometry (front-overlap) than the first test of this instance.

    Design: Difficulty/priority_pair_validation_conflict/create_capacity_exceeded_beats_double_booked
    """
    base = setup_base(
        room_type_overrides={"name": "SMALL", "capacity": 4, "base_hourly_rate_cents": 3500},
        clock_utc="2026-07-15T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    create_held_reservation(venue, room, customer,
                            "2026-07-15T18:00:00.000Z", "2026-07-15T20:00:00.000Z",
                            party_size=2)
    room_v = get_room_version(room["id"])
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_v,
        "2026-07-15T19:00:00.000Z", "2026-07-15T21:00:00.000Z", party_size=12,
    )
    validate_error(api.create_reservation(payload, _cust(customer)),
                   ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


# ─── boundary_precision_check ─────────────────────────────────────
def test_fb_minimum_one_over_boundary_no_shortfall(api):
    """PRD §3.4: "when the effective figure equals or exceeds the floor,
    `fb_shortfall_cents` is 0."

    fb_minimum 5000, consumed 5001 (one cent over the boundary) -> shortfall 0, the
    X+1 side of the strictly-below threshold.

    Design: Difficulty/boundary_precision_check/fb_minimum_exact_boundary_no_shortfall
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 5000},
        clock_utc="2026-07-16T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-07-16T20:00:00.000Z", "2026-07-16T22:00:00.000Z",
                                        checkin_clock_utc="2026-07-16T20:00:00.000Z")
    add_fb_order(res, customer, unit_price_cents=5001, quantity=1, description="One over")
    closed = close_reservation(res, "2026-07-16T21:00:00.000Z")
    assert closed["fb_consumed_cents"] == 5001
    assert closed["fb_shortfall_cents"] == 0


def test_play_then_skip_remaining_empties_queue(api):
    """PRD §3.6: "Playing requires the entry to be `PENDING` ... playing a non-`PENDING`
    entry ... is rejected with `ERR_INVALID_STATE`."

    With one PENDING entry, skipping it (not playing) empties the PENDING set; a play on
    the now-SKIPPED entry is rejected ERR_INVALID_STATE — the zero-PENDING edge reached
    via skip rather than play.

    Design: Difficulty/boundary_precision_check/play_on_empty_queue_zero_count_edge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-17T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="Solo", artist="S")
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-07-17T20:00:00.000Z", "2026-07-17T22:00:00.000Z",
                                        checkin_clock_utc="2026-07-17T20:00:00.000Z")
    q = queue_song(res, customer, song["id"], priority=10)
    validate_success(api.skip_queue_entry(q["id"], FD), 200)
    validate_error(api.play_queue_entry(q["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)


# ─── cross_entity_state_dependency ────────────────────────────────
def test_checkin_succeeds_after_room_returned_to_service(api):
    """PRD §3.4: "requires the assigned room to be `AVAILABLE` rather than `OCCUPIED` or
    `OUT_OF_SERVICE`."
    PRD §3.1: "Returning a room to service moves it from `OUT_OF_SERVICE` back to
    `AVAILABLE`".

    The cross-entity gate releases once the room is restored: a room toggled OUT_OF_SERVICE
    then back to AVAILABLE permits check-in (the AVAILABLE side of the same dependency).

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_room_out_of_service
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-07-18T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-07-18T20:00:00.000Z", "2026-07-18T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=6)
    from test_helpers import get_success_data
    get_success_data(api.room_maintenance(room["id"], {"target": "OUT_OF_SERVICE"}, VM))
    get_success_data(api.room_maintenance(room["id"], {"target": "AVAILABLE"}, VM))
    set_clock(venue["id"], "2026-07-18T20:00:00.000Z")
    data = validate_success(api.check_in_reservation(res["id"], FD), 200)
    assert data["status"] == "CHECKED_IN"
    assert get_room(room["id"])["status"] == "OCCUPIED"


def test_play_succeeds_once_reservation_checked_in(api):
    """PRD §3.6: "Playing requires the entry to be `PENDING`, requires the parent
    reservation to be `CHECKED_IN`, and requires the entry to be the current head".

    The QueueEntry->Reservation gate releases once the parent reaches CHECKED_IN: the
    head entry that was play-blocked while CONFIRMED plays successfully after check-in.

    Design: Difficulty/cross_entity_state_dependency/queue_play_blocked_when_reservation_not_checked_in
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-07-19T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="Early", artist="E")
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-07-19T20:00:00.000Z", "2026-07-19T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=6)
    q = queue_song(res, customer, song["id"], priority=10)
    # Blocked while CONFIRMED.
    validate_error(api.play_queue_entry(q["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)
    set_clock(venue["id"], "2026-07-19T20:00:00.000Z")
    from test_helpers import check_in_reservation
    check_in_reservation(res)
    data = validate_success(api.play_queue_entry(q["id"], FD), 200)
    assert data["status"] == "PLAYED"


# ─── resource_temporal_overlap (extension) ────────────────────────
def test_extension_adjacent_to_later_booking_allowed(api):
    """PRD §3.5: "if that window collides with a later active reservation on the same
    room (adjacency, where one ends exactly as the other begins, remaining allowed), the
    extension is rejected with `ERR_EXTENSION_CONFLICT`."

    R1 20:00-22:00, R2 22:30-23:30. Extending R1 to exactly 22:30 claims [22:00,22:30)
    which only touches R2's start — adjacency is allowed, so the extension succeeds.

    Design: Difficulty/resource_temporal_overlap/extension_overlap_into_later_booking_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-21T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res1 = create_held_reservation(venue, room, customer,
                                   "2026-07-21T20:00:00.000Z", "2026-07-21T22:00:00.000Z",
                                   party_size=6)
    create_held_reservation(venue, room, customer,
                            "2026-07-21T22:30:00.000Z", "2026-07-21T23:30:00.000Z",
                            party_size=6)
    res1_v = get_reservation_version(res1["id"], customer)
    ext = apply_extension(res1, customer, "2026-07-21T22:30:00.000Z", res1_v)
    assert ext["status"] == "APPLIED"
    assert get_reservation(res1["id"])["slot_end_utc"].startswith("2026-07-21T22:30:00")


# ─── compensating_invariant ───────────────────────────────────────
def test_deposit_then_settlement_ledger_on_close(api):
    """PRD §3.3: "appends a deposit payment event (a `Payment` of kind `DEPOSIT` whose
    `amount_cents` equals `deposit_cents`)".
    PRD §3.4: "a `Payment` of kind `SETTLEMENT` is appended whose `amount_cents` equals
    the reservation's `final_total_cents`."

    Confirm + close write exactly a DEPOSIT then a SETTLEMENT; the deposit amount equals
    the reservation deposit and the settlement equals final_total — the cash conservation
    invariant on the run-to-close path (vs the refund path of the first test).

    Design: Difficulty/compensating_invariant/deposit_refund_ledger_nets_to_zero
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-22T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-07-22T20:00:00.000Z", "2026-07-22T22:00:00.000Z",
                                        checkin_clock_utc="2026-07-22T20:00:00.000Z")
    assert res["deposit_cents"] == 3600
    closed = close_reservation(res, "2026-07-22T22:00:00.000Z")
    payments = list_payments(res["id"])
    assert sum_amount_for_kind(payments, "DEPOSIT") == 3600
    assert sum_amount_for_kind(payments, "SETTLEMENT") == closed["final_total_cents"]


def test_room_occupancy_conserved_via_noshow_never_occupies(api):
    """PRD §3.4: "drives the room from `AVAILABLE → OCCUPIED`".
    PRD §3.7: "any reservation still `CONFIRMED` past the grace window ... is treated as
    a no-show: it transitions `CONFIRMED → NO_SHOW`".

    A no-showed reservation never checked in, so the room was never driven to OCCUPIED
    and remains AVAILABLE — the occupancy count is conserved at 0 across an abandoned
    booking, complementing the check-in/close round trip.

    Design: Difficulty/compensating_invariant/room_occupancy_conserved_checkin_close
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-23T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-07-23T20:00:00.000Z", "2026-07-23T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=6)
    set_clock(venue["id"], "2026-07-23T20:16:00.000Z")
    run_ops(venue["id"])
    assert get_reservation(res["id"])["status"] == "NO_SHOW"
    assert get_room(room["id"])["status"] == "AVAILABLE"
