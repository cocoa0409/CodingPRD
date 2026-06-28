"""Resource temporal-overlap semantics (technician no-buffer vs room
buffer-inclusive), the no-show sweep 15-minute boundary, and two
single-failure validation-conflict scenarios where the higher-priority guard is
the only one that can bite."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_studio,
    set_clock,
    create_location,
    create_service_type,
    create_room,
    create_technician,
    create_member,
    book_reservation,
    create_and_activate_membership,
    check_in,
    complete,
    get_room_version,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["studio_admin_headers"]


def test_technician_overlapping_slot_rejected(api):
    """PRD 3.4: "The technician double-booking check compares the requested
    interval from the slot start through the slot end — with no buffer — against
    the same bare intervals of the technician's other non-terminal reservations,
    treating each interval as closed at the start and open at the end so that one
    slot ending exactly when another begins is not a conflict."

    A second 30-min booking for the same technician starting at 10:15 overlaps a
    10:00-10:30 booking and is rejected ERR_TECH_DOUBLE_BOOKED (two rooms so the
    room check cannot mask the technician conflict).

    Design: Difficulty/resource_temporal_overlap/technician_overlap_no_buffer_closed_open
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Techoverlap")
    svc = create_service_type(name="Leg", duration_minutes=30, list_price_cents=4000)
    room1 = create_room(loc["id"], label="Room 1")
    room2 = create_room(loc["id"], label="Room 2")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Tess")
    member = create_member(loc["id"])
    book_reservation(member=member, location_id=loc["id"], room_id=room1["id"],
                     technician_id=tech["id"], service_type_id=svc["id"],
                     start_utc="2026-06-16T10:00:00Z", payment_method="WALK_IN",
                     expected_room_version=room1["version"], booked_by="frontdesk")
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room2["id"],
        "technician_id": tech["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:15:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room2["version"],
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)


def test_technician_adjacent_slot_allowed(api):
    """PRD 3.4: "treating each interval as closed at the start and open at the
    end so that one slot ending exactly when another begins is not a conflict."

    A second booking for the same technician starting exactly at the first's end
    (10:30 after a 10:00-10:30 slot) is ALLOWED — adjacency at the bare interval
    boundary is permitted for the technician. A separate room avoids the room's
    buffer-inclusive block.

    Design: Difficulty/resource_temporal_overlap/technician_overlap_no_buffer_closed_open
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Techadj")
    svc = create_service_type(name="Leg", duration_minutes=30, list_price_cents=4000,
                              buffer_minutes=0)
    room1 = create_room(loc["id"], label="Room 1")
    room2 = create_room(loc["id"], label="Room 2")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Tess")
    member = create_member(loc["id"])
    book_reservation(member=member, location_id=loc["id"], room_id=room1["id"],
                     technician_id=tech["id"], service_type_id=svc["id"],
                     start_utc="2026-06-16T10:00:00Z", payment_method="WALK_IN",
                     expected_room_version=room1["version"], booked_by="frontdesk")
    data = validate_success(api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room2["id"],
        "technician_id": tech["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:30:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room2["version"],
    }, FRONT), 201)
    assert data["booking_status"] == "BOOKED"


def test_room_buffered_adjacency_rejected(api):
    """PRD 3.4: "The room double-booking check instead compares the buffered
    window — the slot start through the slot end plus the service's
    `buffer_minutes` — against the buffered windows of the room's other
    non-terminal reservations, again as closed-open intervals."

    A 10:00-10:30 booking with a 5-minute buffer holds the room until 10:35; a
    second booking on the SAME room (different technician) starting at 10:30 is
    rejected ERR_ROOM_DOUBLE_BOOKED because 10:30 < 10:35.

    Design: Difficulty/resource_temporal_overlap/room_overlap_buffer_inclusive_adjacency_blocked
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Roomoverlap")
    svc = create_service_type(name="Side", duration_minutes=30, list_price_cents=3300,
                              buffer_minutes=5)
    room = create_room(loc["id"], label="Room Only")
    tech1 = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Ty1")
    tech2 = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Ty2")
    member = create_member(loc["id"])
    book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                     technician_id=tech1["id"], service_type_id=svc["id"],
                     start_utc="2026-06-16T10:00:00Z", payment_method="WALK_IN",
                     expected_room_version=room["version"], booked_by="frontdesk")
    rv = get_room_version(room["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech2["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:30:00Z", "payment_method": "WALK_IN",
        "expected_room_version": rv,
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


def test_room_slot_after_buffer_window_allowed(api):
    """PRD 3.4: "the slot start through the slot end plus the service's
    `buffer_minutes` ... again as closed-open intervals."

    A 10:00-10:30 booking with a 5-minute buffer holds the room until 10:35; a
    second booking on the same room starting exactly at 10:35 is ALLOWED because
    the buffered window is closed-open (10:35 is not inside [10:00, 10:35)).

    Design: Difficulty/resource_temporal_overlap/room_overlap_buffer_inclusive_adjacency_blocked
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Roomadj")
    svc = create_service_type(name="Side", duration_minutes=30, list_price_cents=3300,
                              buffer_minutes=5)
    room = create_room(loc["id"], label="Room Only")
    tech1 = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Ty1")
    tech2 = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Ty2")
    member = create_member(loc["id"])
    book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                     technician_id=tech1["id"], service_type_id=svc["id"],
                     start_utc="2026-06-16T10:00:00Z", payment_method="WALK_IN",
                     expected_room_version=room["version"], booked_by="frontdesk")
    rv = get_room_version(room["id"])
    data = validate_success(api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech2["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:35:00Z", "payment_method": "WALK_IN",
        "expected_room_version": rv,
    }, FRONT), 201)
    assert data["booking_status"] == "BOOKED"


def test_no_show_sweep_flips_at_exactly_15_minutes(api):
    """PRD 3.8: "The no-show sweep finds every reservation still `BOOKED` whose
    `start_utc` is at least 15 minutes in the past relative to the new clock and
    drives it to `NO_SHOW` with the full no-show cascade."

    At start+14m the reservation stays BOOKED; advancing to exactly start+15m
    drives it to NO_SHOW/FORFEITED (the >= boundary on the sweep).

    Design: Difficulty/boundary_precision_check/no_show_sweep_exact_15_minute_boundary
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Boundtown", deposit_required_cents=1000)
    svc = create_service_type(name="Ear", duration_minutes=15, list_price_cents=900)
    room = create_room(loc["id"], label="Room B")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Bo")
    member = create_member(loc["id"])
    res = book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                           technician_id=tech["id"], service_type_id=svc["id"],
                           start_utc="2026-06-16T10:00:00Z", payment_method="DEPOSIT",
                           expected_room_version=room["version"], booked_by="frontdesk")
    # start + 14 minutes: still BOOKED (below the 15-minute sweep boundary).
    set_clock("2026-06-16T10:14:00Z")
    still = validate_success(api.get_reservation(res["id"], FRONT), 200)
    assert still["booking_status"] == "BOOKED", "must remain BOOKED at start+14m"
    # start + 15 minutes: swept to NO_SHOW.
    set_clock("2026-06-16T10:15:00Z")
    after = validate_success(api.get_reservation(res["id"], FRONT), 200)
    assert after["booking_status"] == "NO_SHOW"
    assert after["settlement_status"] == "FORFEITED"


def test_no_show_sweep_does_not_fire_before_15_minutes(api):
    """PRD 3.8: "The no-show sweep finds every reservation still `BOOKED` whose
    `start_utc` is at least 15 minutes in the past relative to the new clock".

    At start+14m a standalone sweep run leaves the reservation BOOKED — the
    sweep does not fire one minute before the 15-minute boundary.

    Design: Difficulty/boundary_precision_check/no_show_sweep_exact_15_minute_boundary
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Boundtown2", deposit_required_cents=1000)
    svc = create_service_type(name="Ear", duration_minutes=15, list_price_cents=900)
    room = create_room(loc["id"], label="Room B2")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Bo")
    member = create_member(loc["id"])
    res = book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                           technician_id=tech["id"], service_type_id=svc["id"],
                           start_utc="2026-06-16T10:00:00Z", payment_method="DEPOSIT",
                           expected_room_version=room["version"], booked_by="frontdesk")
    set_clock("2026-06-16T10:14:00Z")
    api.run_sweeps(ADMIN)
    after = validate_success(api.get_reservation(res["id"], FRONT), 200)
    assert after["booking_status"] == "BOOKED", "must not be swept at start+14m"


def test_complete_already_completed_reservation_rejected_on_state(api):
    """PRD 3.6: "Completion is performed by a `FrontDesk` operator or by the
    assigned technician, and moves a `CHECKED_IN` reservation to `COMPLETED`".
    PRD 3.6: "A check-in attempted on a reservation that is not `BOOKED` is
    rejected with `ERR_INVALID_STATE`."

    Completing an already-COMPLETED reservation is rejected with
    ERR_INVALID_STATE — the state guard fires before any fiscal balance check on
    a terminal reservation.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_credit_conflict
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Conflicttown"},
        service_overrides={"name": "HalfLeg", "duration_minutes": 30,
                           "list_price_cents": 3500, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="BASIC",
                                         monthly_credit_grant=1, monthly_fee_cents=4000)
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="CREDIT", expected_room_version=studio["room"]["version"],
                           membership_id=mbr["id"], expected_membership_version=mbr["version"],
                           booked_by="frontdesk")
    set_clock("2026-06-16T09:45:00Z")
    check_in(res["id"])
    complete(res["id"])
    resp = api.complete_reservation(res["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_no_show_reservation_rejected_on_state(api):
    """PRD 3.6: "Completion is performed by a `FrontDesk` operator or by the
    assigned technician, and moves a `CHECKED_IN` reservation to `COMPLETED`".

    Completing a reservation that has already reached the terminal NO_SHOW state
    is rejected ERR_INVALID_STATE — the state guard bites on a terminal
    reservation regardless of its fiscal state.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_credit_conflict
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Conflict2", deposit_required_cents=1000)
    svc = create_service_type(name="HalfLeg", duration_minutes=30, list_price_cents=3500)
    room = create_room(loc["id"], label="Room K2")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Kit")
    member = create_member(loc["id"])
    res = book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                           technician_id=tech["id"], service_type_id=svc["id"],
                           start_utc="2026-06-16T10:00:00Z", payment_method="DEPOSIT",
                           expected_room_version=room["version"], booked_by="frontdesk")
    set_clock("2026-06-16T10:20:00Z")
    api.mark_no_show_reservation(res["id"], FRONT)
    resp = api.complete_reservation(res["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_booking_with_nonexistent_technician_rejected_not_found(api):
    """PRD 2.9: "every path identifier and every foreign-key reference in a
    request must resolve to an existing resource. References are validated in a
    fixed left-to-right order ... and the first reference that does not resolve
    causes the request to be rejected with `ERR_NOT_FOUND` before any business
    rule is evaluated."

    A booking whose technician_id is a non-existent UUID (and whose room belongs
    to a different location) is rejected ERR_NOT_FOUND — existence is checked
    before the cross-entity coherence rule could raise a mismatch.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_referential_book_conflict
    """
    set_clock("2026-06-15T12:00:00Z")
    loc1 = create_location(name="L1")
    create_location(name="L2")
    svc = create_service_type(name="Chin", duration_minutes=15, list_price_cents=1000)
    room = create_room(loc1["id"], label="Room E")
    member = create_member(loc1["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc1["id"], "room_id": room["id"],
        "technician_id": NON_EXISTENT_UUID, "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:00:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room["version"],
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_booking_with_nonexistent_service_type_rejected_not_found(api):
    """PRD 2.9: "every path identifier and every foreign-key reference in a
    request must resolve to an existing resource ... and the first reference that
    does not resolve causes the request to be rejected with `ERR_NOT_FOUND`
    before any business rule is evaluated."

    A booking whose service_type_id is a non-existent UUID is rejected
    ERR_NOT_FOUND — a second unresolved FK confirming existence is checked before
    business rules.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_referential_book_conflict
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="L1b")
    svc = create_service_type(name="Chin", duration_minutes=15, list_price_cents=1000)
    room = create_room(loc["id"], label="Room E2")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Tch")
    member = create_member(loc["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech["id"], "service_type_id": NON_EXISTENT_UUID,
        "start_utc": "2026-06-16T10:00:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room["version"],
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
