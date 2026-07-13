"""Trip creation, initial state, opening preconditions, listing, and creation-time validation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_trip_payload, create_reservation_payload,
    assert_river_trip, TEST_USERS, make_guest_headers, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import create_trip, trip_version

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]


def test_create_trip_returns_201_with_defaults(api):
    """PRD §3.1: "A new trip begins in status `SCHEDULED` with `booking_mode` `GROUP`,
    and its computed aggregates `committed_guests`, `assigned_guide_count`, and
    `deposits_held_cents` all start at zero."
    PRD §2.4: "`version`, an integer that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/create_trip_returns_201_with_defaults
    """
    data = validate_success(api.create_trip(create_trip_payload(river_name="Colorado"), MGR), 201)
    assert_river_trip(data)
    assert data["status"] == "SCHEDULED"
    assert data["booking_mode"] == "GROUP"
    assert data["committed_guests"] == 0
    assert data["assigned_guide_count"] == 0
    assert data["deposits_held_cents"] == 0
    assert data["version"] == 1


def test_get_trip_not_found_returns_404(api):
    """PRD §2.7: "Each entity type has its own not-found error: `ERR_TRIP_NOT_FOUND`,
    `ERR_GUIDE_NOT_FOUND`, `ERR_GUIDE_ASSIGNMENT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
    `ERR_GUEST_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_GEAR_NOT_FOUND`,
    `ERR_GEAR_ASSIGNMENT_NOT_FOUND`, `ERR_SHUTTLE_VEHICLE_NOT_FOUND`, and
    `ERR_SHUTTLE_RUN_NOT_FOUND`."

    Design: Corner/entities/get_trip_not_found_returns_404
    """
    validate_error(api.get_trip(NON_EXISTENT_UUID, MGR), "ERR_TRIP_NOT_FOUND")


def test_create_reservation_missing_party_size_returns_invalid_request(api):
    """PRD §2.6: "Malformed request bodies — a missing required field, a value of the
    wrong type, or an invalid enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_reservation_missing_required_party_size_returns_invalid_request
    """
    trip = create_trip(api, river_name="Green", difficulty_class="CLASS_II")
    payload = {
        "trip_id": trip["id"],
        "booking_type": "GROUP",
        "deposit_cents": 3000,
        "expected_trip_version": trip["version"],
    }
    validate_error(api.create_reservation(payload, RESV), "ERR_INVALID_REQUEST")


def test_create_trip_invalid_time_window_rejected(api):
    """PRD §2.6: "A time-window body that is internally inconsistent (a trip whose
    scheduled take-out is not strictly after its launch, or a shuttle run whose arrival
    is not strictly after its departure) is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 400)."

    Design: Corner/entities/create_trip_invalid_time_window_rejected
    """
    payload = create_trip_payload(
        trip_date="2026-08-03T15:00:00Z", end_time="2026-08-03T09:00:00Z"
    )
    validate_error(api.create_trip(payload, MGR), "ERR_INVALID_TIME_WINDOW")


def test_reservation_list_is_paginated(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/reservation_list_is_paginated
    """
    trip = create_trip(api, difficulty_class="CLASS_II")
    res = validate_success(
        api.create_reservation(create_reservation_payload(trip["id"], trip["version"]), RESV), 201
    )
    data, meta = validate_paginated(api.list_reservations(RESV, params={"trip_id": trip["id"]}))
    assert "total_count" in meta and "has_more" in meta
    assert isinstance(data, list)
    assert any(r["id"] == res["id"] for r in data)


def test_initial_trip_status_is_scheduled(api):
    """PRD §3.1: "A new trip begins in status `SCHEDULED` with `booking_mode` `GROUP`,
    and its computed aggregates `committed_guests`, `assigned_guide_count`, and
    `deposits_held_cents` all start at zero."

    Design: Corner/state_machines/initial_trip_status_is_scheduled
    """
    data = validate_success(api.create_trip(create_trip_payload(difficulty_class="CLASS_I"), MGR), 201)
    assert data["status"] == "SCHEDULED"


def test_open_trip_without_guide_returns_no_guide_assigned(api):
    """PRD §3.1: "Opening requires that the trip already have at least one guide
    assigned — its `assigned_guide_count` must be one or more — otherwise the open is
    rejected with `ERR_NO_GUIDE_ASSIGNED`."

    Design: Corner/state_machines/open_trip_without_guide_returns_no_guide_assigned
    """
    trip = create_trip(api)
    validate_error(api.open_trip(trip["id"], MGR), "ERR_NO_GUIDE_ASSIGNED")


def test_guest_cannot_create_trip_returns_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/guest_cannot_create_trip_returns_forbidden
    """
    headers = make_guest_headers("00000000-0000-4000-8000-000000000abc")
    validate_error(api.create_trip(create_trip_payload(difficulty_class="CLASS_I"), headers),
                   "ERR_FORBIDDEN_ROLE")
