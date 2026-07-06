"""Second tests for every Difficulty (queue A) instance.

Each test here shares the Design tag of the primary test in test_03..test_09 but
probes a complementary, independently PRD-derivable facet of the same rule (a
different branch, the other side of a boundary, or a co-asserted side effect) so
that every difficulty instance carries >= 2 executing tests.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, ApiErrorId,
    make_operator_headers, make_guide_headers, make_guest_headers,
    make_partner_venue_headers,
    get_success_data,
    create_guest_payload, create_booking_payload, create_add_on_payload,
    setup_scheduled_departure, setup_scheduled_departure_with_confirmed_stop,
    setup_requested_venue_confirmation, create_paid_booking, create_cleared_guest,
)
from test_helpers import api_client

OP = make_operator_headers()
GUIDE = make_guide_headers()


# ---------------------------------------------------------------------------
# dual_variant_calc
# ---------------------------------------------------------------------------
def test_commission_estimated_written_at_confirm_before_complete(api):
    """PRD §3.7: "The **estimated** variant runs when a departure is confirmed
    (`SCHEDULED → CONFIRMED`): its headcount is the forward-looking sum of
    `party_size` over the departure's bookings in `RESERVED` or `PAID`, and it
    is written to each stop's `estimated_commission_cents`."
    PRD §3.3: "A new stop is created in `PLANNED` status with both its
    `estimated_commission_cents` and `settled_commission_cents` initialized to 0;
    these two figures remain 0 until the departure is confirmed and completed
    respectively"

    Design: Difficulty/dual_variant_calc/commission_estimated_vs_settled_diverge_on_stop
    """
    # Forward-looking estimated over RESERVED+PAID = 6 -> round(6*1200*0.10)=720 at confirm;
    # settled stays 0 because the departure has not completed.
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=6,
        venue_overrides={"name": "Oak", "kind": "WINERY", "commission_pct": 0.10,
                         "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18})
    create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 6)
    stop_before = validate_success(api.get_stop(s["stop"]["id"], OP))
    assert stop_before["estimated_commission_cents"] == 0, \
        f"estimated must be 0 before confirm, got {stop_before['estimated_commission_cents']}"
    get_success_data(api.confirm_departure(s["departure"]["id"], OP))
    stop_after = validate_success(api.get_stop(s["stop"]["id"], OP))
    assert stop_after["estimated_commission_cents"] == 720, \
        f"estimated at confirm expected 720, got {stop_after['estimated_commission_cents']}"
    assert stop_after["settled_commission_cents"] == 0, \
        f"settled must remain 0 before complete, got {stop_after['settled_commission_cents']}"


def test_refund_weather_full_refund_payment_status_refunded(api):
    """PRD §3.8: "every non-terminal booking is moved to `CANCELLED` with
    `refund_cents` set to 100 percent of its `amount_paid_cents`, and each such
    booking whose `payment_status` was `CAPTURED` advances to `REFUNDED`."

    Design: Difficulty/dual_variant_calc/refund_weather_full_vs_leadtime_tiered_on_booking
    """
    # A single PAID booking on a weather-cancelled departure: full refund + REFUNDED.
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=4,
        venue_overrides={"name": "Oak", "kind": "WINERY", "commission_pct": 0.10,
                         "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18})
    booking, _ = create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 4)
    paid = booking["amount_paid_cents"]
    get_success_data(api.confirm_departure(s["departure"]["id"], OP))
    get_success_data(api.cancel_departure_weather(s["departure"]["id"], "storm", OP))
    final = validate_success(api.get_booking(booking["id"], OP))
    assert final["refund_cents"] == paid, \
        f"weather refund must equal amount_paid {paid}, got {final['refund_cents']}"
    assert final["payment_status"] == "REFUNDED", \
        f"expected payment_status REFUNDED, got {final['payment_status']}"


# ---------------------------------------------------------------------------
# combinatorial_formula
# ---------------------------------------------------------------------------
def test_quote_no_addon_no_charter_round_then_multiply(api):
    """PRD §3.7: "The discounted per-person fare is computed by multiplying
    `base_price_per_person_cents` by one minus the selected tier rate and
    rounding that per-person figure half up to whole cents first; the seats
    total is then that rounded per-person fare multiplied by `party_size`."

    Design: Difficulty/combinatorial_formula/quote_round_per_person_then_multiply_mode_b
    """
    # base 8001, party 4 -> tier 5%: round(8001*0.95)=round(7600.95)=7601; seats=7601*4=30404.
    # sum-then-round would give round(8001*0.95*4)=round(30403.8)=30404 here too, but the
    # per-person rounding is the contract; no add-on, no charter -> subtotal == seats total.
    s = setup_scheduled_departure(seat_capacity=12,
                                  product_overrides={"base_price_per_person_cents": 8001,
                                                     "gratuity_pct": 0.18})
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])), expected_status=201)
    assert booking["subtotal_cents"] == 30404, \
        f"expected subtotal 30404 (round-per-person 7601 * 4), got {booking['subtotal_cents']}"


def test_gratuity_base_excludes_charter_total_consistency(api):
    """PRD §3.7: "the gratuity base is the seats total plus the add-on total —
    the charter component is not part of it."
    PRD §3.7: "The booking's `total_cents` is then `subtotal_cents` plus
    `gratuity_cents`"

    Design: Difficulty/combinatorial_formula/gratuity_circular_dep_excludes_charter_mode_c
    """
    # Charter party 12, base 9000, gratuity 0.18, charter 5000:
    # seats 91800, charter 5000 -> subtotal 96800; gratuity over 91800 = 16524; total 113324.
    # The discriminating fact: gratuity (16524) != round(subtotal*0.18) = round(96800*0.18)=17424.
    s = setup_scheduled_departure(seat_capacity=12, is_private_charter=True,
                                  product_overrides={"base_price_per_person_cents": 9000,
                                                     "gratuity_pct": 0.18,
                                                     "charter_fee_cents": 5000})
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 12),
        make_guest_headers(guest["id"])), expected_status=201)
    assert booking["gratuity_cents"] == 16524, \
        f"gratuity must exclude charter (expected 16524), got {booking['gratuity_cents']}"
    assert booking["total_cents"] == booking["subtotal_cents"] + booking["gratuity_cents"], \
        "total must equal subtotal + gratuity"


# ---------------------------------------------------------------------------
# non_linear_state_machine
# ---------------------------------------------------------------------------
def test_venue_confirmation_two_full_revision_cycles(api):
    """PRD §3.4: "The `Operator` resubmits it with a revised `requested_headcount`,
    advancing `CHANGES_REQUESTED → REQUESTED`, updating the held headcount from
    the body, and incrementing `revision_count` by one as a cycle counter."

    Design: Difficulty/non_linear_state_machine/venue_confirmation_cyclic_revision_loop
    """
    # Two full request-changes -> resubmit cycles -> revision_count 2, status REQUESTED.
    s = setup_requested_venue_confirmation(requested_headcount=8,
                                           venue_overrides={"name": "Hop", "kind": "BREWERY",
                                                            "commission_pct": 0.10,
                                                            "tasting_cost_per_guest_cents": 1000})
    vc_id = s["confirmation"]["id"]
    vh = make_partner_venue_headers(s["venue"]["id"])
    get_success_data(api.request_changes_venue_confirmation(vc_id, "c1", vh))
    get_success_data(api.resubmit_venue_confirmation(vc_id, 9, OP))
    get_success_data(api.request_changes_venue_confirmation(vc_id, "c2", vh))
    after = validate_success(api.resubmit_venue_confirmation(vc_id, 11, OP))
    assert after["status"] == "REQUESTED", f"expected REQUESTED, got {after['status']}"
    assert after["revision_count"] == 2, f"expected revision_count 2, got {after['revision_count']}"
    assert after["requested_headcount"] == 11, \
        f"expected requested_headcount 11, got {after['requested_headcount']}"


def test_booking_payment_dimension_independent_of_lifecycle(api):
    """PRD §3.6: "On creation the booking enters `DRAFT` with `payment_status`
    of `UNPAID`"
    PRD §3.6: "When all preconditions hold, the reservation adds `party_size` to
    the departure's `seats_taken`" (i.e. reserve advances lifecycle to RESERVED).

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_and_payment_dimensions
    """
    # On create (DRAFT) and after reserve (RESERVED) payment_status stays UNPAID:
    # the two axes are independent until pay is called.
    s = setup_scheduled_departure(seat_capacity=12)
    guest = create_cleared_guest()
    created = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])), expected_status=201)
    assert created["status"] == "DRAFT" and created["payment_status"] == "UNPAID"
    reserved = validate_success(api.reserve_booking(
        created["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    assert reserved["status"] == "RESERVED", f"expected RESERVED, got {reserved['status']}"
    assert reserved["payment_status"] == "UNPAID", \
        f"payment dimension must stay UNPAID after reserve, got {reserved['payment_status']}"


# ---------------------------------------------------------------------------
# transitive_cascade
# ---------------------------------------------------------------------------
def test_weather_cancel_releases_confirmed_venue_confirmation(api):
    """PRD §3.8: "In the same atomic request, every stop's `CONFIRMED` venue
    confirmation is moved to `RELEASED`. The departure's `version` is
    incremented."

    Design: Difficulty/transitive_cascade/weather_cancel_cascade_depth3_booking_payment_seatpool
    """
    # The weather cascade also releases the CONFIRMED venue confirmation (a sibling hop).
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=4,
        venue_overrides={"name": "Oak", "kind": "WINERY", "commission_pct": 0.10,
                         "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18})
    create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 4)
    get_success_data(api.confirm_departure(s["departure"]["id"], OP))
    get_success_data(api.cancel_departure_weather(s["departure"]["id"], "storm", OP))
    vc = validate_success(api.get_venue_confirmation(s["confirmation"]["id"], OP))
    assert vc["status"] == "RELEASED", \
        f"weather cancel must release the venue confirmation, got {vc['status']}"


def test_ops_cancel_cascades_booking_to_cancelled(api):
    """PRD §3.8: "Every non-terminal booking is moved to `CANCELLED` with
    `refund_cents` computed by that tiered rule; each cancelled booking whose
    refund is greater than 0 and whose `payment_status` was `CAPTURED` advances
    to `REFUNDED`."

    Design: Difficulty/transitive_cascade/ops_cancel_cascade_depth2_venue_confirmation_release
    """
    # The ops cascade also cancels the booking with a 50% refund (72h) -> REFUNDED.
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=4,
        venue_overrides={"name": "Oak", "kind": "WINERY", "commission_pct": 0.10,
                         "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18})
    booking, _ = create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 4)
    paid = booking["amount_paid_cents"]
    get_success_data(api.confirm_departure(s["departure"]["id"], OP))
    get_success_data(api.set_clock("2026-04-07T18:00:00Z", OP))  # 72h before depart -> 50%
    get_success_data(api.cancel_departure_ops(s["departure"]["id"], "low bookings", OP))
    final = validate_success(api.get_booking(booking["id"], OP))
    assert final["status"] == "CANCELLED", f"expected CANCELLED, got {final['status']}"
    assert final["refund_cents"] == round(paid * 0.5), \
        f"ops 72h refund expected {round(paid*0.5)}, got {final['refund_cents']}"
    assert final["payment_status"] == "REFUNDED", \
        f"expected REFUNDED (refund>0, was CAPTURED), got {final['payment_status']}"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_state_check_precedes_capacity_on_completed_departure_reserve(api):
    """PRD §3.6: "This ordering ensures, for example, that a reservation against
    a non-`SCHEDULED` departure surfaces as `ERR_DEPARTURE_NOT_BOOKABLE` rather
    than as a capacity or version error."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve_terminal_departure
    """
    # CANCELLED_WEATHER departure (non-SCHEDULED) + oversized party: state error still wins.
    s = setup_scheduled_departure(seat_capacity=4)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 8),
        make_guest_headers(guest["id"])))
    cancelled = get_success_data(api.cancel_departure_weather(s["departure"]["id"], "storm", OP))
    # PRD §3.8's cancel-weather cascade moves "every non-terminal booking" (incl.
    # this DRAFT one) to CANCELLED. A PRD-faithful impl checking the booking's own
    # state first reports ERR_INVALID_STATE; one checking departure state first
    # reports ERR_DEPARTURE_NOT_BOOKABLE. The PRD names both as possible and does
    # not order booking-state vs departure-state; both are HTTP 409.
    resp = api.reserve_booking(booking["id"], cancelled["version"],
                               make_guest_headers(guest["id"]))
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_DEPARTURE_NOT_BOOKABLE.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])


def test_underage_check_precedes_capacity_isolated(api):
    """PRD §3.6: "the guest's age, computed from `birth_date` against the logical
    clock at reserve time, must be at least `min_guest_age`, and an underage lead
    guest is rejected with `ERR_UNDERAGE_GUEST`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_reserve_underage_overcapacity
    """
    # party exactly == capacity (no capacity violation) but lead guest underage:
    # underage fires; confirms the age check is reached independent of capacity.
    s = setup_scheduled_departure(seat_capacity=4, product_overrides={"min_guest_age": 21})
    guest = get_success_data(api.create_guest(
        create_guest_payload(full_name="Kid", birth_date="2010-06-15T00:00:00Z"), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])))
    resp = api.reserve_booking(booking["id"], s["departure"]["version"],
                               make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_UNDERAGE_GUEST.value, expected_status=422)


# ---------------------------------------------------------------------------
# boundary_precision_check
# ---------------------------------------------------------------------------
def test_seat_capacity_full_van_single_booking_succeeds(api):
    """PRD §3.6: "the sum of its current `seats_taken` plus this booking's
    `party_size` must not exceed the departure's `seat_capacity`"

    Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_vs_overflow
    """
    # Single party-12 reserve on a 12-seat van: 0+12 == 12 (boundary equal) succeeds.
    s = setup_scheduled_departure(seat_capacity=12)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 12),
        make_guest_headers(guest["id"])))
    reserved = validate_success(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    assert reserved["status"] == "RESERVED", f"12==12 must reserve, got {reserved['status']}"
    dep = validate_success(api.get_departure(s["departure"]["id"], OP))
    assert dep["seats_taken"] == 12, f"expected seats_taken 12, got {dep['seats_taken']}"


def test_confirm_with_one_reserved_booking_passes_headcount(api):
    """PRD §3.8: "the departure must have at least one expected guest — its
    `expected_headcount` must be at least 1, meaning at least one booking is
    `RESERVED` or `PAID`"

    Design: Difficulty/boundary_precision_check/confirm_empty_booking_set_zero_headcount_edge
    """
    # expected_headcount == 1 (the lower-edge non-empty case) -> confirm succeeds.
    s = setup_scheduled_departure_with_confirmed_stop(seat_capacity=12, requested_headcount=1)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 1),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    confirmed = validate_success(api.confirm_departure(s["departure"]["id"], OP))
    assert confirmed["status"] == "CONFIRMED", \
        f"confirm with headcount 1 must succeed, got {confirmed['status']}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_booking_pay_requires_age_verified(api):
    """PRD §3.6: "it requires that the lead guest be fully cleared — both
    `age_verified` and `waiver_signed` must be true — failing which the payment
    is rejected with `ERR_GUEST_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/booking_pay_requires_guest_cleared
    """
    # The other half of the AND: waiver signed but age NOT verified -> still not cleared.
    s = setup_scheduled_departure(seat_capacity=12)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    get_success_data(api.sign_waiver(guest["id"], make_guest_headers(guest["id"])))  # waiver only
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    resp = api.pay_booking(booking["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_GUEST_NOT_CLEARED.value, expected_status=409)


def test_departure_confirm_succeeds_when_vehicle_available(api):
    """PRD §3.8: "The assigned vehicle must be `AVAILABLE`, failing which the
    confirm is rejected with `ERR_VEHICLE_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/departure_confirm_requires_vehicle_available
    """
    # Positive complement: with the assigned vehicle AVAILABLE the confirm proceeds.
    s = setup_scheduled_departure_with_confirmed_stop(seat_capacity=12, requested_headcount=4)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    assert s["vehicle"]["status"] == "AVAILABLE"
    confirmed = validate_success(api.confirm_departure(s["departure"]["id"], OP))
    assert confirmed["status"] == "CONFIRMED", \
        f"confirm with AVAILABLE vehicle must succeed, got {confirmed['status']}"


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_seat_pool_overlap_third_booking_at_capacity_boundary(api):
    """PRD §3.6: "the sum of its current `seats_taken` plus this booking's
    `party_size` must not exceed the departure's `seat_capacity`, and a
    reservation that would overflow the pool is rejected with
    `ERR_SEAT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/shared_van_seat_pool_aggregate_capacity_overlap
    """
    # seat_capacity 10; reserved party 4 + party 4 (seats_taken 8); a party-2 fills to 10
    # exactly (8+2==10) -> succeeds, showing the aggregate sum is the gating metric.
    s = setup_scheduled_departure(seat_capacity=10)
    dep_id = s["departure"]["id"]
    pickup_id = s["pickup"]["id"]
    g1 = get_success_data(api.create_guest(create_guest_payload(full_name="G1"), OP))
    g2 = get_success_data(api.create_guest(create_guest_payload(full_name="G2"), OP))
    g3 = get_success_data(api.create_guest(create_guest_payload(full_name="G3"), OP))
    b1 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g1["id"], pickup_id, 4), make_guest_headers(g1["id"])))
    b2 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g2["id"], pickup_id, 4), make_guest_headers(g2["id"])))
    b3 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g3["id"], pickup_id, 2), make_guest_headers(g3["id"])))
    get_success_data(api.reserve_booking(b1["id"], s["departure"]["version"],
                                         make_guest_headers(g1["id"])))
    v1 = get_success_data(api.get_departure(dep_id, OP))["version"]
    get_success_data(api.reserve_booking(b2["id"], v1, make_guest_headers(g2["id"])))
    v2 = get_success_data(api.get_departure(dep_id, OP))["version"]
    r3 = validate_success(api.reserve_booking(b3["id"], v2, make_guest_headers(g3["id"])))
    assert r3["status"] == "RESERVED", f"8+2==10 must reserve, got {r3['status']}"
    dep = validate_success(api.get_departure(dep_id, OP))
    assert dep["seats_taken"] == 10, f"expected seats_taken 10, got {dep['seats_taken']}"


def test_private_charter_full_van_single_booking_succeeds(api):
    """PRD §3.6: "If the departure is a private charter, the booking must take
    the whole van — its `party_size` must equal the departure's `seat_capacity`
    — and it must be the only non-terminal booking on that departure"

    Design: Difficulty/resource_temporal_overlap/private_charter_whole_van_exclusive_occupation
    """
    # Positive complement of exclusivity: a party == seat_capacity sole booking reserves.
    s = setup_scheduled_departure(seat_capacity=12, is_private_charter=True,
                                  product_overrides={"charter_fee_cents": 5000})
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 12),
        make_guest_headers(guest["id"])))
    reserved = validate_success(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    assert reserved["status"] == "RESERVED", \
        f"whole-van charter booking must reserve, got {reserved['status']}"


# ---------------------------------------------------------------------------
# compensating_invariant
# ---------------------------------------------------------------------------
def test_seat_pool_conserved_expected_headcount_restored_on_cancel(api):
    """PRD §3.6: "Cancelling a `RESERVED` booking returns its seats: the
    departure's `seats_taken` and `expected_headcount` are each reduced by the
    booking's `party_size`, and the departure's `version` is incremented."

    Design: Difficulty/compensating_invariant/seat_pool_conserved_under_reserve_then_cancel
    """
    # expected_headcount is the second conserved counter: reserve 5 then cancel -> back to 0.
    s = setup_scheduled_departure(seat_capacity=12)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 5),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    mid = validate_success(api.get_departure(s["departure"]["id"], OP))
    assert mid["expected_headcount"] == 5, \
        f"expected_headcount 5 after reserve, got {mid['expected_headcount']}"
    get_success_data(api.cancel_booking(booking["id"], make_guest_headers(guest["id"])))
    final = validate_success(api.get_departure(s["departure"]["id"], OP))
    assert final["expected_headcount"] == 0, \
        f"expected_headcount must restore to 0, got {final['expected_headcount']}"


def test_payment_ledger_paid_then_paid_booking_cancel_full_refund(api):
    """PRD §3.6: "Cancelling a `PAID` booking does the same seat restoration and
    additionally computes a refund: `refund_cents` is set by the lead-time refund
    rule of Section 3.7 over the booking's `amount_paid_cents`, measured against
    the departure's `depart_at`; if that refund is greater than 0 and the
    `payment_status` is `CAPTURED`, the `payment_status` advances to `REFUNDED`."

    Design: Difficulty/compensating_invariant/payment_ledger_conserved_under_pay_then_weather_refund
    """
    # Money conservation via a direct PAID-booking cancel at >= 168h lead time (100% refund):
    # net charge (amount_paid - refund) == 0, payment_status REFUNDED. Clock at startup
    # default 2026-03-01 is > 168h before depart_at 2026-04-10 -> 100%.
    s = setup_scheduled_departure(seat_capacity=12,
                                  product_overrides={"base_price_per_person_cents": 9000,
                                                     "gratuity_pct": 0.18})
    booking, guest = create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 4)
    paid = booking["amount_paid_cents"]
    cancelled = validate_success(api.cancel_booking(booking["id"], make_guest_headers(guest["id"])))
    assert cancelled["refund_cents"] == paid, \
        f"100% refund at >=168h expected {paid}, got {cancelled['refund_cents']}"
    assert cancelled["payment_status"] == "REFUNDED", \
        f"expected REFUNDED, got {cancelled['payment_status']}"
    assert cancelled["amount_paid_cents"] - cancelled["refund_cents"] == 0, \
        "net charge must be conserved at 0"
