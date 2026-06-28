"""Second-angle coverage for every difficulty-design instance.

Each test here pairs with the primary test of the same Design tag elsewhere in
the suite, asserting a distinct observable consequence of the same rule (the
unchanged branch, the side-effect, the partner boundary, or an independent
literal) — each still grounded in a verbatim PRD sentence that uniquely
determines the asserted outcome.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_event, add_menu_line, add_schedule_item, record_payment,
    get_event, get_event_version, create_hotel_room_block, get_block,
    create_room_block_link, create_function_room,
    setup_tentative_event_with_hold_booking, setup_tentative_event_with_definite_booking,
    setup_definite_event, setup_confirmed_event,
    setup_existing_definite_booking_on_room, make_definite,
    TEST_USERS,
)
from test_helpers.api_client import api_client

_SALES = TEST_USERS["sales_manager_headers"]
_CAPTAIN = TEST_USERS["banquet_captain_headers"]
_CLERK = TEST_USERS["accounting_clerk_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc (second angle)
# ===========================================================================

def test_charge_rollup_estimate_variant_at_confirmed(api):
    """PRD §3.7: "The **estimate** variant writes the event's `estimated_total_cents` and
    applies while the event is `DEFINITE` or `CONFIRMED`, feeding per-person lines with the
    estimate headcount (the planning attendance, or the oversetted guarantee once locked)."

    Design: Difficulty/dual_variant_calc/charge_rollup_estimate_vs_actual_on_event
    """
    confirmed, _room, _booking, _ = setup_confirmed_event(
        event_overrides={"account_name": "Acme Gala 2", "event_date": "2026-09-10",
                         "setup_style": "THEATER", "expected_attendance": 100,
                         "overset_pct": 0.05, "service_charge_pct": 0.20,
                         "gratuity_pct": 0.0, "sales_tax_pct": 0.10},
        room_overrides={"name": "Grand Ballroom 2", "max_capacity": 200,
                        "turnover_buffer_minutes": 60, "hourly_rental_cents": 50000},
        menu_lines=[{"name": "Plated Filet", "pricing_mode": "PER_PERSON", "unit_price_cents": 10000}],
        guarantee_count=120, deposit_amount_cents=500000,
    )
    # At CONFIRMED the estimate variant is in force; actualized_total stays null.
    assert confirmed["estimated_total_cents"] == 1883200, (
        f"estimate total at CONFIRMED should be 1883200, got {confirmed['estimated_total_cents']}"
    )
    assert confirmed["actualized_total_cents"] is None, (
        f"actualized_total must be null until COMPLETED, got {confirmed['actualized_total_cents']}"
    )


def test_rooms_committed_reserved_reading_before_pickup(api):
    """PRD §3.6: "The block's `rooms_committed` is the sum, across all of the block's links,
    of each link's own contribution by status: a `RESERVED` link contributes its
    `rooms_reserved` (the optimistic hold), a `PICKED_UP` link contributes its
    `rooms_picked_up` (the realized count, which is at most the rooms reserved), and a
    `RELEASED` link contributes nothing."

    Design: Difficulty/dual_variant_calc/rooms_committed_reserved_vs_pickedup_on_block
    """
    block = create_hotel_room_block(block_name="Wedding Block 2", total_rooms=10, nightly_rate_cents=19900)
    event = create_event(account_name="Beta Wedding 2", event_date="2026-07-02",
                         setup_style="ROUNDS", expected_attendance=50)
    # While RESERVED, committed counts rooms_reserved (8 -> available 2).
    create_room_block_link(event["id"], block["id"], 8, "2026-07-01", "2026-07-03")
    block_reserved = get_block(block["id"])
    assert block_reserved["rooms_committed"] == 8, f"got {block_reserved['rooms_committed']}"
    assert block_reserved["rooms_available"] == 2, f"got {block_reserved['rooms_available']}"


# ===========================================================================
# Difficulty: combinatorial_formula (second angle)
# ===========================================================================

def test_billable_count_pre_guarantee_uses_expected_attendance(api):
    """PRD §3.5: "Before any guarantee is locked — while the event is still gathering its
    order — `billable_count` is simply the planning `expected_attendance`."

    Design: Difficulty/combinatorial_formula/billable_count_nested_conditional_mode_a
    """
    # A fresh INQUIRY event has no guarantee, so billable_count == expected_attendance.
    event = create_event(account_name="Gamma Pre", event_date="2026-10-01",
                         setup_style="THEATER", expected_attendance=100,
                         overset_pct=0.05)
    ev = get_event(event["id"])
    assert ev["billable_count"] == 100, (
        f"pre-guarantee billable should equal expected_attendance 100, got {ev['billable_count']}"
    )


def test_charge_rollup_gratuity_excluded_from_tax(api):
    """PRD §3.7: "The gratuity is the gratuity base multiplied by the event's `gratuity_pct`,
    rounded half-up to a whole cent; it is not taxable. The taxable base is the
    food-and-beverage subtotal plus the service subtotal plus the rental subtotal plus the
    service charge."

    Design: Difficulty/combinatorial_formula/charge_rollup_per_component_rounding_order_mode_b
    """
    # Same setup as the primary mode_b test. Independent check: the grand total 6445
    # includes gratuity 346 but the sales_tax 452 is computed on a base that EXCLUDES it.
    # If gratuity entered the taxable base, sales_tax would be rhu((4610+1037+346)*0.08)=479
    # and the grand total would differ. We assert the gratuity-excluded total 6445.
    event_definite, _room, _booking = setup_definite_event(
        event_overrides={"account_name": "Delta Dinner 2", "event_date": "2026-11-05",
                         "setup_style": "CLASSROOM", "expected_attendance": 30,
                         "service_charge_pct": 0.225, "gratuity_pct": 0.075,
                         "sales_tax_pct": 0.08},
        room_overrides={"name": "Salon C2", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2026-11-05T18:00:00Z", end_utc="2026-11-05T21:00:00Z",
        menu_lines=[{"name": "Open Bar", "pricing_mode": "CONSUMPTION",
                     "unit_price_cents": 461, "consumption_qty": 10}],
    )
    assert event_definite["estimated_total_cents"] == 6445, (
        f"gratuity must be excluded from the taxable base; total should be 6445, "
        f"got {event_definite['estimated_total_cents']}"
    )


# ===========================================================================
# Difficulty: non_linear_state_machine (second angle)
# ===========================================================================

def test_reopen_then_reconfirm_returns_to_definite(api):
    """PRD §3.2: "Confirming the space advances the event from `TENTATIVE` to `DEFINITE`."
    PRD §3.5: "Reopening reverts every `DEFINITE` booking on the event back to `HOLD`
    occupancy as a cascade and recomputes `estimated_total_cents` using the estimate variant."

    Design: Difficulty/non_linear_state_machine/event_revision_loop_definite_to_tentative
    """
    event_definite, _room, booking = setup_definite_event(
        event_overrides={"account_name": "Epsilon Loop", "event_date": "2026-12-01",
                         "setup_style": "THEATER", "expected_attendance": 80},
        room_overrides={"name": "Salon D2", "max_capacity": 200,
                        "turnover_buffer_minutes": 60, "hourly_rental_cents": 40000},
        start_utc="2026-12-01T09:00:00Z", end_utc="2026-12-01T12:00:00Z",
    )
    validate_success(api.reopen_event(event_definite["id"], _SALES))
    # Re-flip the booking and confirm-space again — closing the back-edge cycle.
    make_definite(event_definite["id"], booking["id"])
    reconfirmed = validate_success(api.confirm_space(event_definite["id"], _SALES))
    assert reconfirmed["status"] == "DEFINITE", (
        f"TENTATIVE->DEFINITE after the revision loop, got {reconfirmed['status']}"
    )


def test_booking_soften_returns_definite_to_hold(api):
    """PRD §3.3: "The reverse move, softening a booking, returns its occupancy from
    `DEFINITE` to `HOLD`, again only while the owning event is `TENTATIVE` or `DEFINITE`;
    this frees the buffered window so other rooms or bookings may claim it."

    Design: Difficulty/non_linear_state_machine/booking_hold_definite_cycle
    """
    held, _room, booking = setup_tentative_event_with_definite_booking(
        event_overrides={"account_name": "Zeta Soft", "event_date": "2027-01-15",
                         "setup_style": "ROUNDS", "expected_attendance": 60},
        room_overrides={"name": "Salon E2", "max_capacity": 200,
                        "turnover_buffer_minutes": 30, "hourly_rental_cents": 30000},
        start_utc="2027-01-15T11:00:00Z", end_utc="2027-01-15T14:00:00Z",
    )
    softened = validate_success(api.soften_booking(held["id"], booking["id"], _SALES))
    assert softened["hold_status"] == "HOLD", (
        f"soften must return DEFINITE booking to HOLD, got {softened['hold_status']}"
    )


# ===========================================================================
# Difficulty: transitive_cascade (second angle)
# ===========================================================================

def test_cancel_event_releases_bookings(api):
    """PRD §3.9: "Cancellation unwinds the event fully: every non-released booking is
    released, every non-released room-block link is released (each returning its committed
    rooms to its block's available pool as a second hop), and both `estimated_total_cents`
    and `actualized_total_cents` are frozen at their last computed values."

    Design: Difficulty/transitive_cascade/cancel_event_releases_links_returns_block_rooms_depth3
    """
    block = create_hotel_room_block(block_name="Conf Block 2", total_rooms=10, nightly_rate_cents=15000)
    held, _room, booking = setup_tentative_event_with_definite_booking(
        event_overrides={"account_name": "Eta Summit 2", "event_date": "2027-02-02",
                         "setup_style": "THEATER", "expected_attendance": 80},
        room_overrides={"name": "Salon F2", "max_capacity": 200,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2027-02-02T18:00:00Z", end_utc="2027-02-02T22:00:00Z",
    )
    create_room_block_link(held["id"], block["id"], 6, "2027-02-01", "2027-02-03")
    validate_success(api.cancel_event(held["id"], _SALES))
    booking_after = get_success_data(api.get_booking(held["id"], booking["id"], _SALES))
    assert booking_after["hold_status"] == "RELEASED", (
        f"cancel must release the DEFINITE booking, got {booking_after['hold_status']}"
    )


def test_actualize_sets_actual_attendance_and_completes(api):
    """PRD §3.5: "A `BanquetCaptain` actualizes the event on the day, advancing it from
    `CONFIRMED` to the terminal `COMPLETED`."
    PRD §3.5: "On success the system sets `actual_attendance` to the supplied value,
    recomputes `billable_count` (now the larger of guarantee and actual), recomputes the
    `extended_cents` of every `PER_PERSON` menu line as a cascade from that headcount
    change, computes `actualized_total_cents` using the actual variant of the charge rollup,
    and recomputes `balance_due_cents`."

    Design: Difficulty/transitive_cascade/actualize_recomputes_billable_menu_and_total_depth3
    """
    confirmed, _room, _booking, _ = setup_confirmed_event(
        event_overrides={"account_name": "Theta Gala 2", "event_date": "2027-03-10",
                         "setup_style": "THEATER", "expected_attendance": 100,
                         "overset_pct": 0.05, "service_charge_pct": 0.20,
                         "gratuity_pct": 0.0, "sales_tax_pct": 0.10},
        room_overrides={"name": "Salon G2", "max_capacity": 200,
                        "turnover_buffer_minutes": 60, "hourly_rental_cents": 50000},
        start_utc="2027-03-10T18:00:00Z", end_utc="2027-03-10T22:00:00Z",
        menu_lines=[{"name": "Plated Filet", "pricing_mode": "PER_PERSON", "unit_price_cents": 10000}],
        guarantee_count=120, deposit_amount_cents=500000,
    )
    completed = validate_success(
        api.actualize_event(confirmed["id"], {"actual_attendance": 140}, _CAPTAIN))
    assert completed["status"] == "COMPLETED", f"got {completed['status']}"
    assert completed["actual_attendance"] == 140, f"got {completed['actual_attendance']}"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict (second angle)
# ===========================================================================

def test_make_definite_temporal_beats_capacity_booking_stays_hold(api):
    """PRD §3.3: "Only when both checks pass does the booking flip to `DEFINITE` and its
    `rental_charge_cents` recompute."

    Design: Difficulty/priority_pair_validation_conflict/make_definite_temporal_beats_capacity
    """
    room_id, _event_a, _booking_a = setup_existing_definite_booking_on_room(
        {"name": "Tiny Room 2", "max_capacity": 10, "turnover_buffer_minutes": 60,
         "hourly_rental_cents": 0},
        a_start="2027-04-01T18:00:00Z", a_end="2027-04-01T22:00:00Z",
        event_overrides={"account_name": "Iota A2", "event_date": "2027-04-01",
                         "setup_style": "ROUNDS", "expected_attendance": 5},
    )
    event_b = create_event(account_name="Iota B2", event_date="2027-04-01",
                           setup_style="ROUNDS", expected_attendance=100)
    booking_b = get_success_data(api.create_booking(
        event_b["id"], {"function_room_id": room_id, "start_utc": "2027-04-01T21:00:00Z",
                        "end_utc": "2027-04-01T23:00:00Z",
                        "expected_event_version": event_b["version"]}, _SALES))
    get_success_data(api.hold_event(event_b["id"], _SALES))
    resp = api.make_definite(event_b["id"], booking_b["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)
    # Both checks did not pass, so the booking remains HOLD.
    booking_after = get_success_data(api.get_booking(event_b["id"], booking_b["id"], _SALES))
    assert booking_after["hold_status"] == "HOLD", f"got {booking_after['hold_status']}"


def test_make_definite_state_check_runs_before_temporal(api):
    """PRD §2.8: "State is checked next: a transition endpoint whose target resource is not
    in a valid state for the requested transition — for example, locking the guarantee on
    an event that is not `DEFINITE`, or voiding a payment that is not `APPLIED` — is
    rejected with the generic `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/make_definite_state_beats_temporal
    """
    # Event B is INQUIRY (state gate fails) and its window buffer-overlaps an existing
    # DEFINITE booking (temporal gate would also fail). State error must surface.
    room_id, _event_a, _booking_a = setup_existing_definite_booking_on_room(
        {"name": "Salon H2", "max_capacity": 300, "turnover_buffer_minutes": 60,
         "hourly_rental_cents": 0},
        a_start="2027-05-01T18:00:00Z", a_end="2027-05-01T22:00:00Z",
        event_overrides={"account_name": "Kappa A2", "event_date": "2027-05-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
    )
    event_b = create_event(account_name="Kappa B2", event_date="2027-05-01",
                           setup_style="THEATER", expected_attendance=50)
    booking_b = get_success_data(api.create_booking(
        event_b["id"], {"function_room_id": room_id, "start_utc": "2027-05-01T22:30:00Z",
                        "end_utc": "2027-05-01T23:30:00Z",
                        "expected_event_version": event_b["version"]}, _SALES))
    resp = api.make_definite(event_b["id"], booking_b["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty: boundary_precision_check (second angle)
# ===========================================================================

def test_room_rental_one_minute_over_boundary_adds_an_hour(api):
    """PRD §3.3: "Because the rounding is upward, a two-hour-and-one-minute window bills
    three hours, while a window whose duration is an exact multiple of 60 minutes bills no
    extra hour."

    Design: Difficulty/boundary_precision_check/room_rental_ceil_started_hour_boundary
    """
    # Partner boundary: 241 minutes (one past the exact 240) bills 5 hours, not 4.
    held, _room, booking = setup_tentative_event_with_hold_booking(
        event_overrides={"account_name": "Lambda Plus", "event_date": "2027-06-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
        room_overrides={"name": "Salon I2", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 50000},
        start_utc="2027-06-01T18:00:00Z", end_utc="2027-06-01T22:01:00Z",
    )
    definite = validate_success(api.make_definite(held["id"], booking["id"], _SALES))
    assert definite["rental_charge_cents"] == 250000, (
        f"241 min should bill 5 hours = 250000, got {definite['rental_charge_cents']}"
    )


def test_hold_with_zero_bookings_keeps_event_in_inquiry(api):
    """PRD §3.2: "A `SalesManager` may do this only once the event has at least one
    function-room booking and every booking on the event sits in either `HOLD` or
    `DEFINITE` occupancy; if no non-released booking exists the move is rejected with
    `ERR_NO_BOOKINGS`."

    Design: Difficulty/boundary_precision_check/confirm_space_empty_bookings_set_boundary
    """
    event = create_event(account_name="Mu Inquiry 2", event_date="2027-07-01",
                         setup_style="RECEPTION", expected_attendance=40)
    resp = api.hold_event(event["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_NO_BOOKINGS.value)
    # The rejected transition leaves the event untouched in INQUIRY.
    assert get_event(event["id"])["status"] == "INQUIRY"


# ===========================================================================
# Difficulty: cross_entity_state_dependency (second angle)
# ===========================================================================

def test_make_definite_succeeds_on_tentative_event(api):
    """PRD §3.3: "A `SalesManager` makes a booking definite, advancing its occupancy from
    `HOLD` to `DEFINITE`, only while the owning event is in `TENTATIVE` or `DEFINITE`
    status."

    Design: Difficulty/cross_entity_state_dependency/make_definite_requires_event_tentative_or_definite
    """
    # The positive side: on a TENTATIVE event the make-definite succeeds.
    held, _room, booking = setup_tentative_event_with_hold_booking(
        event_overrides={"account_name": "Nu Tentative", "event_date": "2027-08-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
        room_overrides={"name": "Salon J2", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2027-08-01T18:00:00Z", end_utc="2027-08-01T22:00:00Z",
    )
    definite = validate_success(api.make_definite(held["id"], booking["id"], _SALES))
    assert definite["hold_status"] == "DEFINITE", (
        f"make-definite must succeed on a TENTATIVE event, got {definite['hold_status']}"
    )


def test_lock_guarantee_succeeds_once_deposit_settled(api):
    """PRD §3.8: "the deposit milestone (the item whose `sequence_no` is 1) must be settled
    — its `allocated_cents` at least its `amount_due_cents` — before a `BanquetCaptain` may
    lock the guarantee, failing otherwise with `ERR_DEPOSIT_UNSETTLED`."
    PRD §3.5: "A `BanquetCaptain` locks the guarantee, advancing the event from `DEFINITE`
    to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/lock_guarantee_requires_settled_deposit_schedule_item
    """
    # The positive side: with the deposit settled, lock-guarantee succeeds to CONFIRMED.
    event_definite, _room, _booking = setup_definite_event(
        event_overrides={"account_name": "Xi Settled", "event_date": "2027-09-01",
                         "setup_style": "THEATER", "expected_attendance": 50,
                         "service_charge_pct": 0.0, "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon K2", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2027-09-01T18:00:00Z", end_utc="2027-09-01T22:00:00Z",
    )
    add_schedule_item(event_definite["id"], 500000, label="Deposit", due_date="2027-08-01")
    v = get_event_version(event_definite["id"])
    record_payment(event_definite["id"], 500000, v, method="WIRE")
    confirmed = validate_success(
        api.lock_guarantee(event_definite["id"], {"guarantee_count": 50}, _CAPTAIN))
    assert confirmed["status"] == "CONFIRMED", f"got {confirmed['status']}"


# ===========================================================================
# Difficulty: resource_temporal_overlap (second angle)
# ===========================================================================

def test_function_room_touching_endpoint_after_buffer_does_not_collide(api):
    """PRD §3.3: "Overlap is judged by strict inequality, so two windows that touch only at
    an endpoint after the buffer expansion (the expanded start of one exactly meeting the
    end of the other) do *not* collide."

    Design: Difficulty/resource_temporal_overlap/function_room_buffered_pairwise_overlap
    """
    # Buffer 60. Existing DEFINITE 18:00-22:00. Candidate 23:00-23:30 expands to
    # 22:00-00:30; expanded-start 22:00 exactly meets the other's end 22:00 -> no collide.
    room_id, _event_a, _booking_a = setup_existing_definite_booking_on_room(
        {"name": "Buffered Room 2", "max_capacity": 300, "turnover_buffer_minutes": 60,
         "hourly_rental_cents": 0},
        a_start="2027-10-01T18:00:00Z", a_end="2027-10-01T22:00:00Z",
        event_overrides={"account_name": "Omicron A2", "event_date": "2027-10-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
    )
    event_b = create_event(account_name="Omicron B2", event_date="2027-10-01",
                           setup_style="THEATER", expected_attendance=50)
    booking_b = get_success_data(api.create_booking(
        event_b["id"], {"function_room_id": room_id, "start_utc": "2027-10-01T23:00:00Z",
                        "end_utc": "2027-10-01T23:30:00Z",
                        "expected_event_version": event_b["version"]}, _SALES))
    get_success_data(api.hold_event(event_b["id"], _SALES))
    definite = validate_success(api.make_definite(event_b["id"], booking_b["id"], _SALES))
    assert definite["hold_status"] == "DEFINITE", (
        f"touching-endpoint after buffer must not collide, got {definite['hold_status']}"
    )


def test_hotel_block_admits_candidate_when_every_night_fits(api):
    """PRD §3.6: "The candidate is admitted only if, for *every* night in its own range,
    that night's already-occupied total plus the candidate's `rooms_reserved` does not
    exceed the block's `total_rooms`."

    Design: Difficulty/resource_temporal_overlap/hotel_block_per_night_aggregate_capacity_overlap
    """
    # Existing RESERVED link 7 over [11-01,11-03). Candidate 3 over the same nights:
    # 7+3=10 <= 10 on every night, so it is admitted.
    block = create_hotel_room_block(block_name="Night Block 2", total_rooms=10, nightly_rate_cents=12000)
    event_a = create_event(account_name="Pi A2", event_date="2027-11-02",
                           setup_style="ROUNDS", expected_attendance=40)
    create_room_block_link(event_a["id"], block["id"], 7, "2027-11-01", "2027-11-03")
    event_b = create_event(account_name="Pi B2", event_date="2027-11-02",
                           setup_style="ROUNDS", expected_attendance=40)
    link_b = validate_success(api.create_room_block_link(
        event_b["id"], {"hotel_room_block_id": block["id"], "rooms_reserved": 3,
                        "check_in_date": "2027-11-01", "check_out_date": "2027-11-03"}, _SALES),
        expected_status=201)
    assert link_b["link_status"] == "RESERVED", (
        f"7+3=10 <= 10 on every night must be admitted, got {link_b['link_status']}"
    )


# ===========================================================================
# Difficulty: compensating_invariant (second angle)
# ===========================================================================

def test_link_release_returns_inventory_invariant_holds_throughout(api):
    """PRD §3.6: "The block's `rooms_available` is `total_rooms` minus `rooms_committed`,
    never negative."

    Design: Difficulty/compensating_invariant/link_reserve_then_release_conserves_block_total_rooms
    """
    # A second link's reserve+release must also leave inventory conserved at total_rooms.
    block = create_hotel_room_block(block_name="Invariant Block 2", total_rooms=12, nightly_rate_cents=10000)
    event = create_event(account_name="Rho Event 2", event_date="2027-12-02",
                         setup_style="ROUNDS", expected_attendance=40)
    link = create_room_block_link(event["id"], block["id"], 9, "2027-12-01", "2027-12-03")
    mid = get_block(block["id"])
    assert mid["rooms_committed"] + mid["rooms_available"] == 12, "invariant must hold while RESERVED"
    assert mid["rooms_available"] == 3, f"got {mid['rooms_available']}"
    validate_success(api.release_link(event["id"], link["id"], _CLERK))
    after = get_block(block["id"])
    assert after["rooms_committed"] == 0 and after["rooms_available"] == 12, (
        f"release must restore available to 12, got {after['rooms_available']}"
    )


def test_payment_void_restores_deposit_unsettled_on_inquiry_event(api):
    """PRD §3.9: "When a void succeeds, the voided payment is excluded from
    `paid_to_date_cents`, the allocation waterfall is re-run so every schedule item's
    `allocated_cents` and `settled` are recomputed, and the event's `balance_due_cents` is
    recomputed."

    Design: Difficulty/compensating_invariant/payment_apply_then_void_conserves_paid_and_allocations
    """
    # A different conserved-money angle: the FIRST schedule item's allocation+settled flag
    # roll back to their pre-payment values when the only payment is voided (INQUIRY event,
    # so the deposit-lock guard does not apply).
    event = create_event(account_name="Sigma Reset", event_date="2028-01-15",
                         setup_style="THEATER", expected_attendance=50,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    item1 = add_schedule_item(event["id"], 500000, label="Deposit", due_date="2027-12-01")
    v0 = get_event_version(event["id"])
    pay = record_payment(event["id"], 500000, v0, method="WIRE")
    items_before = get_success_data(api.list_payment_schedule_items(event["id"], _CLERK))
    i1_before = next(i for i in items_before if i["id"] == item1["id"])
    assert i1_before["settled"] is True and i1_before["allocated_cents"] == 500000

    validate_success(api.void_payment(event["id"], pay["id"], _CLERK))
    items_after = get_success_data(api.list_payment_schedule_items(event["id"], _CLERK))
    i1_after = next(i for i in items_after if i["id"] == item1["id"])
    assert i1_after["allocated_cents"] == 0, f"got {i1_after['allocated_cents']}"
    assert i1_after["settled"] is False, f"got {i1_after['settled']}"
    assert get_event(event["id"])["paid_to_date_cents"] == 0
