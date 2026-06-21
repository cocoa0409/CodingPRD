"""Business constraints at make-definite (buffered double-booking, capacity gate,
validation priority pairs), cross-entity state dependencies (booking vs event
status, deposit gate), and the room-block per-night aggregate-capacity geometry.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_event, get_event, get_event_version, add_schedule_item,
    create_hotel_room_block, create_room_block_link, create_function_room,
    setup_tentative_event_with_hold_booking, setup_definite_event,
    setup_existing_definite_booking_on_room, make_definite,
    TEST_USERS,
)
from test_helpers.api_client import api_client

_SALES = TEST_USERS["sales_manager_headers"]
_CAPTAIN = TEST_USERS["banquet_captain_headers"]
_CLERK = TEST_USERS["accounting_clerk_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict
# ===========================================================================

def test_make_definite_temporal_beats_capacity(api):
    """PRD §3.3: "Making a booking definite is gated by two business checks evaluated in
    this order."
    PRD §3.3: "A genuine intersection is rejected with `ERR_ROOM_DOUBLE_BOOKED`."
    PRD §3.3: "Second comes the **capacity gate** (described in Section 3.4): the room's
    effective seated capacity under the event's setup style must be at least the event's
    `billable_count`, otherwise the make-definite is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/make_definite_temporal_beats_capacity
    """
    # Room max_capacity 10, ROUNDS effective floor(10*0.6)=6; event B billable 100 > 6
    # would fail capacity. An existing DEFINITE booking 18:00-22:00 makes B's 21:00-23:00
    # buffer-overlap. Temporal (lower priority number) must win.
    room_id, _event_a, _booking_a = setup_existing_definite_booking_on_room(
        {"name": "Tiny Room", "max_capacity": 10, "turnover_buffer_minutes": 60,
         "hourly_rental_cents": 0},
        a_start="2027-04-01T18:00:00Z", a_end="2027-04-01T22:00:00Z",
        event_overrides={"account_name": "Iota A", "event_date": "2027-04-01",
                         "setup_style": "ROUNDS", "expected_attendance": 5},
    )
    # Event B's booking must land on the SAME room as the existing DEFINITE booking.
    event_b = create_event(account_name="Iota B", event_date="2027-04-01",
                           setup_style="ROUNDS", expected_attendance=100)
    booking_b = get_success_data(api.create_booking(
        event_b["id"], {"function_room_id": room_id, "start_utc": "2027-04-01T21:00:00Z",
                        "end_utc": "2027-04-01T23:00:00Z",
                        "expected_event_version": event_b["version"]}, _SALES))
    get_success_data(api.hold_event(event_b["id"], _SALES))
    resp = api.make_definite(event_b["id"], booking_b["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


def test_make_definite_state_beats_temporal(api):
    """PRD §2.8: "State is checked next: a transition endpoint whose target resource is not
    in a valid state for the requested transition — for example, locking the guarantee on
    an event that is not `DEFINITE`, or voiding a payment that is not `APPLIED` — is
    rejected with the generic `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "A `SalesManager` makes a booking definite, advancing its occupancy from
    `HOLD` to `DEFINITE`, only while the owning event is in `TENTATIVE` or `DEFINITE` status."

    Design: Difficulty/priority_pair_validation_conflict/make_definite_state_beats_temporal
    """
    # Existing DEFINITE booking 18:00-22:00 on a buffered room (event A). Event B stays
    # INQUIRY (never held) with a HOLD booking 22:30-23:30 that would buffer-overlap.
    # State check (lower priority) must win over the overlap error.
    room_id, _event_a, _booking_a = setup_existing_definite_booking_on_room(
        {"name": "Salon H", "max_capacity": 300, "turnover_buffer_minutes": 60,
         "hourly_rental_cents": 0},
        a_start="2027-05-01T18:00:00Z", a_end="2027-05-01T22:00:00Z",
        event_overrides={"account_name": "Kappa A", "event_date": "2027-05-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
    )
    event_b = create_event(account_name="Kappa B", event_date="2027-05-01",
                           setup_style="THEATER", expected_attendance=50)
    booking_b = get_success_data(api.create_booking(
        event_b["id"], {"function_room_id": room_id, "start_utc": "2027-05-01T22:30:00Z",
                        "end_utc": "2027-05-01T23:30:00Z",
                        "expected_event_version": event_b["version"]}, _SALES))
    # Event B is still INQUIRY (never held).
    resp = api.make_definite(event_b["id"], booking_b["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    booking_after = get_success_data(api.get_booking(event_b["id"], booking_b["id"], _SALES))
    assert booking_after["hold_status"] == "HOLD", f"got {booking_after['hold_status']}"


# ===========================================================================
# Difficulty: cross_entity_state_dependency
# ===========================================================================

def test_make_definite_requires_event_tentative_or_definite(api):
    """PRD §3.3: "A `SalesManager` makes a booking definite, advancing its occupancy from
    `HOLD` to `DEFINITE`, only while the owning event is in `TENTATIVE` or `DEFINITE` status."

    Design: Difficulty/cross_entity_state_dependency/make_definite_requires_event_tentative_or_definite
    """
    room = create_function_room(name="Salon J", max_capacity=300,
                                turnover_buffer_minutes=0, hourly_rental_cents=0)
    event = create_event(account_name="Nu Inquiry", event_date="2027-08-01",
                         setup_style="THEATER", expected_attendance=50)
    booking = get_success_data(api.create_booking(
        event["id"], {"function_room_id": room["id"], "start_utc": "2027-08-01T18:00:00Z",
                      "end_utc": "2027-08-01T22:00:00Z",
                      "expected_event_version": event["version"]}, _SALES))
    # Event is still INQUIRY (never held).
    resp = api.make_definite(event["id"], booking["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    booking_after = get_success_data(api.get_booking(event["id"], booking["id"], _SALES))
    assert booking_after["hold_status"] == "HOLD", f"got {booking_after['hold_status']}"


def test_lock_guarantee_requires_settled_deposit(api):
    """PRD §3.8: "The deposit gate on guarantee locking ties these together: the deposit
    milestone (the item whose `sequence_no` is 1) must be settled — its `allocated_cents`
    at least its `amount_due_cents` — before a `BanquetCaptain` may lock the guarantee,
    failing otherwise with `ERR_DEPOSIT_UNSETTLED`."

    Design: Difficulty/cross_entity_state_dependency/lock_guarantee_requires_settled_deposit_schedule_item
    """
    event_definite, _room, _booking = setup_definite_event(
        event_overrides={"account_name": "Xi Event", "event_date": "2027-09-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
        room_overrides={"name": "Salon K", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2027-09-01T18:00:00Z", end_utc="2027-09-01T22:00:00Z",
    )
    # Deposit item exists but is unsettled (no payment applied).
    add_schedule_item(event_definite["id"], 500000, label="Deposit", due_date="2027-08-01")
    resp = api.lock_guarantee(event_definite["id"], {"guarantee_count": 50}, _CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_UNSETTLED.value)
    assert get_event(event_definite["id"])["status"] == "DEFINITE"


# ===========================================================================
# Difficulty: resource_temporal_overlap
# ===========================================================================

def test_function_room_buffered_pairwise_overlap(api):
    """PRD §3.3: "First comes the **buffered double-booking check** (the higher-priority of
    the two): the candidate booking's window, expanded on *both* sides by the room's
    `turnover_buffer_minutes` — that is, from `start_utc` minus the buffer to `end_utc` plus
    the buffer — must not intersect the raw, unexpanded window of any *other* `DEFINITE`
    booking on the same function room."
    PRD §3.3: "A genuine intersection is rejected with `ERR_ROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/function_room_buffered_pairwise_overlap
    """
    # Buffer 60. Existing DEFINITE 18:00-22:00. Candidate 22:30-23:30 expands to
    # 21:30-00:30, intersecting 18:00-22:00 (21:30 < 22:00).
    room_id, _event_a, _booking_a = setup_existing_definite_booking_on_room(
        {"name": "Buffered Room", "max_capacity": 300, "turnover_buffer_minutes": 60,
         "hourly_rental_cents": 0},
        a_start="2027-10-01T18:00:00Z", a_end="2027-10-01T22:00:00Z",
        event_overrides={"account_name": "Omicron A", "event_date": "2027-10-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
    )
    event_b = create_event(account_name="Omicron B", event_date="2027-10-01",
                           setup_style="THEATER", expected_attendance=50)
    booking_b = get_success_data(api.create_booking(
        event_b["id"], {"function_room_id": room_id, "start_utc": "2027-10-01T22:30:00Z",
                        "end_utc": "2027-10-01T23:30:00Z",
                        "expected_event_version": event_b["version"]}, _SALES))
    get_success_data(api.hold_event(event_b["id"], _SALES))
    resp = api.make_definite(event_b["id"], booking_b["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)
    booking_after = get_success_data(api.get_booking(event_b["id"], booking_b["id"], _SALES))
    assert booking_after["hold_status"] == "HOLD", f"got {booking_after['hold_status']}"


def test_hotel_block_per_night_aggregate_capacity_overlap(api):
    """PRD §3.6: "The candidate is admitted only if, for *every* night in its own range,
    that night's already-occupied total plus the candidate's `rooms_reserved` does not
    exceed the block's `total_rooms`."
    PRD §3.6: "If any night in the candidate's range would be overbooked, the create is
    rejected with `ERR_BLOCK_INSUFFICIENT_ROOMS`."

    Design: Difficulty/resource_temporal_overlap/hotel_block_per_night_aggregate_capacity_overlap
    """
    block = create_hotel_room_block(block_name="Night Block", total_rooms=10, nightly_rate_cents=12000)
    event_a = create_event(account_name="Pi A", event_date="2027-11-02",
                           setup_style="ROUNDS", expected_attendance=40)
    create_room_block_link(event_a["id"], block["id"], 7, "2027-11-01", "2027-11-03")
    event_b = create_event(account_name="Pi B", event_date="2027-11-03",
                           setup_style="ROUNDS", expected_attendance=40)
    # Candidate 2027-11-02..2027-11-04 reserving 4: night 2027-11-02 has 7+4=11 > 10.
    resp = api.create_room_block_link(
        event_b["id"], {"hotel_room_block_id": block["id"], "rooms_reserved": 4,
                        "check_in_date": "2027-11-02", "check_out_date": "2027-11-04"}, _SALES)
    validate_error(resp, ApiErrorId.ERR_BLOCK_INSUFFICIENT_ROOMS.value)


# ===========================================================================
# Difficulty: boundary_precision_check (empty-collection edge)
# ===========================================================================

def test_hold_with_zero_bookings_returns_no_bookings(api):
    """PRD §3.2: "A `SalesManager` may do this only once the event has at least one
    function-room booking and every booking on the event sits in either `HOLD` or
    `DEFINITE` occupancy; if no non-released booking exists the move is rejected with
    `ERR_NO_BOOKINGS`."

    Design: Difficulty/boundary_precision_check/confirm_space_empty_bookings_set_boundary
    """
    event = create_event(account_name="Mu Inquiry", event_date="2027-07-01",
                         setup_style="RECEPTION", expected_attendance=40)
    resp = api.hold_event(event["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_NO_BOOKINGS.value)
    assert get_event(event["id"])["status"] == "INQUIRY"


# ===========================================================================
# Corner: validations + calculations (capacity gate, block-night half-open)
# ===========================================================================

def test_per_person_menu_line_with_consumption_qty_mode_mismatch(api):
    """PRD §3.7: "Supplying `consumption_qty` on a per-person line, or omitting it on a
    consumption line, is rejected with `ERR_PRICING_MODE_FIELD_MISMATCH`."

    Design: Corner/validations/per_person_menu_line_with_consumption_qty_returns_mode_mismatch
    """
    event = create_event(account_name="Mode Co", event_date="2029-02-01",
                         setup_style="THEATER", expected_attendance=30)
    resp = api.create_menu_line(
        event["id"], {"name": "Bad PP", "pricing_mode": "PER_PERSON",
                      "unit_price_cents": 5000, "consumption_qty": 10}, _SALES)
    validate_error(resp, ApiErrorId.ERR_PRICING_MODE_FIELD_MISMATCH.value)


def test_consumption_menu_line_without_qty_mode_mismatch(api):
    """PRD §3.7: "a `CONSUMPTION` line must supply a `consumption_qty` (at least 0 when
    set), and a `PER_PERSON` line must omit it. Supplying `consumption_qty` on a per-person
    line, or omitting it on a consumption line, is rejected with
    `ERR_PRICING_MODE_FIELD_MISMATCH`."

    Design: Corner/validations/consumption_menu_line_without_qty_returns_mode_mismatch
    """
    event = create_event(account_name="Mode2 Co", event_date="2029-03-01",
                         setup_style="THEATER", expected_attendance=30)
    resp = api.create_menu_line(
        event["id"], {"name": "Bad CONS", "pricing_mode": "CONSUMPTION",
                      "unit_price_cents": 400}, _SALES)
    validate_error(resp, ApiErrorId.ERR_PRICING_MODE_FIELD_MISMATCH.value)


def test_record_pickup_above_reserved_rejected(api):
    """PRD §3.6: "The request supplies `rooms_picked_up`, which must fall within zero and
    the link's `rooms_reserved` inclusive; a value outside that range is rejected with
    `ERR_PICKUP_EXCEEDS_RESERVED`."

    Design: Corner/validations/record_pickup_above_reserved_returns_pickup_exceeds_reserved
    """
    from test_helpers import setup_confirmed_event
    block = create_hotel_room_block(block_name="Pickup Block", total_rooms=20, nightly_rate_cents=10000)
    confirmed, _room, _booking, _ = setup_confirmed_event(
        event_overrides={"account_name": "Pickup Co", "event_date": "2029-04-02",
                         "setup_style": "THEATER", "expected_attendance": 40,
                         "service_charge_pct": 0.0, "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon S", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2029-04-02T18:00:00Z", end_utc="2029-04-02T22:00:00Z",
        guarantee_count=40, deposit_amount_cents=50000,
    )
    link = create_room_block_link(confirmed["id"], block["id"], 6, "2029-04-01", "2029-04-03",
                                  as_role="CLERK")
    resp = api.record_pickup(confirmed["id"], link["id"], {"rooms_picked_up": 9}, _CLERK)
    validate_error(resp, ApiErrorId.ERR_PICKUP_EXCEEDS_RESERVED.value)
    links = get_success_data(api.list_event_room_block_links(confirmed["id"], _CLERK))
    this_link = next(l for l in links if l["id"] == link["id"])
    assert this_link["link_status"] == "RESERVED", f"got {this_link['link_status']}"


def test_effective_capacity_classroom_factor_blocks_make_definite(api):
    """PRD §3.4: "Each setup style carries a fixed seating factor: `ROUNDS` yields a factor
    of 0.6, `THEATER` a factor of 1.0, `CLASSROOM` a factor of 0.5, and `RECEPTION` a
    factor of 0.8. The effective seated capacity is the room's `max_capacity` multiplied by
    the factor for the event's setup style, with the product floored down to a whole number
    of seats. The gate then compares this effective capacity against the event's
    `billable_count`: if the effective capacity is below `billable_count`, making the
    booking definite is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/calculations/effective_capacity_classroom_factor_blocks_make_definite
    """
    # CLASSROOM factor 0.5 on max_capacity 100 -> effective 50; billable 80 (>50).
    held, _room, booking = setup_tentative_event_with_hold_booking(
        event_overrides={"account_name": "Cap Co", "event_date": "2028-12-01",
                         "setup_style": "CLASSROOM", "expected_attendance": 80},
        room_overrides={"name": "Small Class", "max_capacity": 100,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2028-12-01T09:00:00Z", end_utc="2028-12-01T12:00:00Z",
    )
    resp = api.make_definite(held["id"], booking["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)
    booking_after = get_success_data(api.get_booking(held["id"], booking["id"], _SALES))
    assert booking_after["hold_status"] == "HOLD", f"got {booking_after['hold_status']}"


def test_block_night_half_open_adjacent_dates_do_not_collide(api):
    """PRD §3.6: "Two links where one departs the morning the other arrives therefore share
    no occupied night and never conflict."

    Design: Corner/calculations/block_night_half_open_adjacent_dates_do_not_collide
    """
    block = create_hotel_room_block(block_name="Adjacent Block", total_rooms=10, nightly_rate_cents=10000)
    event_a = create_event(account_name="Adj A", event_date="2029-01-02",
                           setup_style="ROUNDS", expected_attendance=40)
    create_room_block_link(event_a["id"], block["id"], 7, "2029-01-01", "2029-01-03")
    event_b = create_event(account_name="Adj B", event_date="2029-01-04",
                           setup_style="ROUNDS", expected_attendance=40)
    # [2029-01-03, 2029-01-05) shares no occupied night with [2029-01-01, 2029-01-03).
    link_b = validate_success(api.create_room_block_link(
        event_b["id"], {"hotel_room_block_id": block["id"], "rooms_reserved": 7,
                        "check_in_date": "2029-01-03", "check_out_date": "2029-01-05"}, _SALES),
        expected_status=201)
    assert link_b["link_status"] == "RESERVED", f"got {link_b['link_status']}"
    assert link_b["rooms_reserved"] == 7, f"got {link_b['rooms_reserved']}"


# ===========================================================================
# Corner: errors (guarantee required)
# ===========================================================================

def test_lock_guarantee_without_count_returns_guarantee_required(api):
    """PRD §3.5: "that a `guarantee_count` of at least 1 be supplied in the request body —
    absent or below 1 it is rejected with `ERR_GUARANTEE_REQUIRED`"

    Design: Corner/errors/lock_guarantee_without_count_returns_guarantee_required
    """
    event_definite, _room, _booking = setup_definite_event(
        event_overrides={"account_name": "GReq Co", "event_date": "2029-08-01",
                         "setup_style": "THEATER", "expected_attendance": 40,
                         "service_charge_pct": 0.0, "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon U", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2029-08-01T18:00:00Z", end_utc="2029-08-01T22:00:00Z",
    )
    # Settle the deposit so only the guarantee-count gate can fire.
    add_schedule_item(event_definite["id"], 50000, label="Deposit", due_date="2029-07-01")
    v = get_event_version(event_definite["id"])
    from test_helpers import record_payment
    record_payment(event_definite["id"], 50000, v, method="WIRE")
    resp = api.lock_guarantee(event_definite["id"], {}, _CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_REQUIRED.value)
    assert get_event(event_definite["id"])["status"] == "DEFINITE"
