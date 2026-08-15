"""Transport trips, vehicle turnaround buffer, seat bookings and inventory."""
from test_helpers import (
    validate_success, validate_error,
    create_active_incident, vet_volunteer, create_published_request,
    create_open_shift, propose_accept_confirm_assignment, create_trip_payload,
    create_shift_payload, create_seat_booking_payload, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
LOGI = TEST_USERS["logistics_headers"]


def _incident_with_shift(api, name="Quake Pi"):
    incident = create_active_incident(name=name)
    shift = validate_success(api.create_shift(
        create_shift_payload(incident["id"], site_name="Civic Center", capacity=10),
        LOGI), 201)
    return incident, shift


def test_vehicle_turnaround_rejects_gap_below_45_minutes(api):
    """PRD section 3.4: "Unlike the shift-adjacency rule, plain adjacency is
    not enough here: a gap of exactly 45 minutes between one trip's estimated
    arrival and the other's departure is required and sufficient, and anything
    shorter is illegal."

    Design: Difficulty/resource_temporal_overlap/vehicle_turnaround_buffer_blocks_adjacency_allows_exact_45min_gap
    """
    incident, shift = _incident_with_shift(api)
    validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-9",
                            seat_capacity=30, depart_at="2026-08-10T07:00:00Z",
                            arrive_estimate_at="2026-08-10T08:00:00Z"), LOGI), 201)
    res = api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-9",
                            seat_capacity=30, depart_at="2026-08-10T08:30:00Z",
                            arrive_estimate_at="2026-08-10T09:00:00Z"), LOGI)
    validate_error(res, "ERR_VEHICLE_TURNAROUND_CONFLICT")


def test_vehicle_turnaround_allows_exactly_45_minute_gap(api):
    """PRD section 3.4: "a gap of exactly 45 minutes between one trip's
    estimated arrival and the other's departure is required and sufficient, and
    anything shorter is illegal."

    Design: Difficulty/resource_temporal_overlap/vehicle_turnaround_buffer_blocks_adjacency_allows_exact_45min_gap
    """
    incident, shift = _incident_with_shift(api)
    validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-9",
                            seat_capacity=30, depart_at="2026-08-10T07:00:00Z",
                            arrive_estimate_at="2026-08-10T08:00:00Z"), LOGI), 201)
    created = validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-9",
                            seat_capacity=30, depart_at="2026-08-10T08:45:00Z",
                            arrive_estimate_at="2026-08-10T09:15:00Z"), LOGI), 201)
    assert created["status"] == "SCHEDULED"


def _two_confirmed_volunteers_with_trip(api, name, seat_capacity):
    """Two READY volunteers, both CONFIRMED on one shift; one trip on it."""
    incident = create_active_incident(name=name)
    v1 = vet_volunteer(incident["id"], full_name="Lara Loh")["volunteer"]
    v2 = vet_volunteer(incident["id"], full_name="Mona Mah")["volunteer"]
    request = create_published_request(incident["id"], headcount_needed=2)
    shift = create_open_shift(incident["id"], capacity=5)
    a1 = propose_accept_confirm_assignment(v1, request, shift)
    a2 = propose_accept_confirm_assignment(v2, request, shift)
    trip = validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="VAN-1",
                            seat_capacity=seat_capacity), LOGI), 201)
    return incident, v1, v2, a1, a2, trip


def test_seat_booking_last_seat_allowed(api):
    """PRD section 3.4: "The trip must still have a free seat — a booking that
    takes the last seat is allowed, while one beyond it fails with
    `ERR_SEAT_CAPACITY_REACHED`"

    Design: Difficulty/boundary_precision_check/seat_booking_last_seat_allowed_overflow_rejected
    """
    _, _, _, a1, _, trip = _two_confirmed_volunteers_with_trip(api, "Fire Mu", 1)
    booking = validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], a1["id"]), LOGI), 201)
    assert booking["status"] == "BOOKED"
    trip_after = validate_success(api.get_trip(trip["id"], MGR))
    assert trip_after["booked_seats"] == 1 == trip_after["seat_capacity"]


def test_seat_booking_beyond_capacity_rejected(api):
    """PRD section 3.4: "The trip must still have a free seat — a booking that
    takes the last seat is allowed, while one beyond it fails with
    `ERR_SEAT_CAPACITY_REACHED`"

    Design: Difficulty/boundary_precision_check/seat_booking_last_seat_allowed_overflow_rejected
    """
    _, _, _, a1, a2, trip = _two_confirmed_volunteers_with_trip(api, "Fire Mu", 1)
    validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], a1["id"]), LOGI), 201)
    res = api.create_seat_booking(create_seat_booking_payload(trip["id"], a2["id"]), LOGI)
    validate_error(res, "ERR_SEAT_CAPACITY_REACHED")


def test_seat_cancel_returns_booked_seats_to_prior_value(api):
    """PRD section 2.6: "a trip's `booked_seats` (its seat bookings in `BOOKED`
    or `BOARDED`)"
    PRD section 3.4: "Once the trip has `DEPARTED`, a `BOOKED` seat can be
    marked `NO_SHOW`, freeing the seat by decrementing `booked_seats`; a plain
    cancellation by a `LogisticsCoordinator` frees it the same way."

    Design: Difficulty/compensating_invariant/seat_book_then_cancel_then_rebook_preserves_seat_inventory
    """
    _, _, _, a1, a2, trip = _two_confirmed_volunteers_with_trip(
        api, "Flood Rho", seat_capacity=3)
    booking1 = validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], a1["id"]), LOGI), 201)
    validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], a2["id"]), LOGI), 201)
    trip_two = validate_success(api.get_trip(trip["id"], MGR))
    assert trip_two["booked_seats"] == 2
    validate_success(api.cancel_seat_booking(booking1["id"], LOGI))
    trip_one = validate_success(api.get_trip(trip["id"], MGR))
    assert trip_one["booked_seats"] == 1, "cancel must compensate the booking exactly"


def test_seat_rebook_after_cancel_succeeds(api):
    """PRD section 3.4: "At most one non-`CANCELLED` booking may exist for the
    same assignment on the same trip, with a duplicate refused as
    `ERR_INVALID_REQUEST`."

    Design: Difficulty/compensating_invariant/seat_book_then_cancel_then_rebook_preserves_seat_inventory
    """
    _, _, _, a1, a2, trip = _two_confirmed_volunteers_with_trip(
        api, "Flood Rho", seat_capacity=3)
    booking1 = validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], a1["id"]), LOGI), 201)
    validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], a2["id"]), LOGI), 201)
    validate_success(api.cancel_seat_booking(booking1["id"], LOGI))
    rebooked = validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], a1["id"]), LOGI), 201)
    assert rebooked["status"] == "BOOKED"
    trip_after = validate_success(api.get_trip(trip["id"], MGR))
    assert trip_after["booked_seats"] == 2


def test_ppe_issue_at_exact_stock_allowed_over_stock_rejected(api):
    """PRD section 3.4: "The request names a `volunteer_id`, an `item_type`
    among the five stock keys, and a `quantity` of at least 1, which may not
    exceed the incident's remaining `ppe_stock` for that item: issuing exactly
    the remaining units is allowed, while one unit more fails with
    `ERR_PPE_STOCK_INSUFFICIENT`."

    Design: Corner/errors/ppe_issue_at_exact_stock_allowed_over_stock_rejected
    """
    from test_helpers import vet_volunteer as _vet, issue_ppe
    incident = create_active_incident(
        name="Fire R3",
        ppe_stock={"GLOVES": 2, "MASK": 0, "HARD_HAT": 0, "VEST": 0, "GOGGLES": 0})
    volunteer = vet_volunteer(incident["id"], full_name="Jae Jun")["volunteer"]
    over = api.create_ppe_issuance(
        {"volunteer_id": volunteer["id"], "item_type": "GLOVES", "quantity": 3}, LOGI)
    validate_error(over, "ERR_PPE_STOCK_INSUFFICIENT")
    exact = validate_success(api.create_ppe_issuance(
        {"volunteer_id": volunteer["id"], "item_type": "GLOVES", "quantity": 2}, LOGI), 201)
    assert exact["status"] == "ISSUED"
    incident_after = validate_success(api.get_incident(incident["id"], MGR))
    assert incident_after["ppe_stock"]["GLOVES"] == 0


def test_volunteer_trip_double_booking_returns_double_booked_trip(api):
    """PRD section 3.4: "the volunteer must not already hold a non-`CANCELLED`
    booking on another trip whose half-open interval from `depart_at` to
    `arrive_estimate_at` intersects the candidate trip's, which fails with
    `ERR_DOUBLE_BOOKED_TRIP`."

    Design: Corner/errors/volunteer_trip_double_booking_returns_double_booked_trip
    """
    incident = create_active_incident(name="Fire O3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Gia Gio")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    trip1 = validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-1",
                            depart_at="2026-08-10T07:00:00Z",
                            arrive_estimate_at="2026-08-10T08:00:00Z"), LOGI), 201)
    trip2 = validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-2",
                            depart_at="2026-08-10T07:30:00Z",
                            arrive_estimate_at="2026-08-10T08:30:00Z"), LOGI), 201)
    validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip1["id"], assignment["id"]), LOGI), 201)
    res = api.create_seat_booking(
        create_seat_booking_payload(trip2["id"], assignment["id"]), LOGI)
    validate_error(res, "ERR_DOUBLE_BOOKED_TRIP")
