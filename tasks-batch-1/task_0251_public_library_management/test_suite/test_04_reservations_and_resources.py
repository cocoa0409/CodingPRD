"""Reservation interval semantics, OCC, and cross-entity resource dependencies.

Queue A: resource_temporal_overlap, cross_entity_state_dependency (Copy + Resource).
Queue B: OCC success, reservation temporal validation.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_patron_headers, TEST_USERS,
    setup_room_with_confirmed_reservation, current_resource_version,
    create_branch, create_patron, create_title, create_copy, create_loan,
    create_resource, create_reservation, set_clock,
)
from test_helpers import api_client as _client  # noqa

LIBRARIAN = TEST_USERS["librarian_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


# =========================================================================
# Queue A — resource_temporal_overlap
# =========================================================================
def test_room_buffer_overlap_conflict(api):
    """PRD §3.7: "For a `ROOM`, two bookings conflict if their windows, each
    expanded on the end side by the branch's `reservation_buffer_minutes`,
    intersect — concretely, a new booking conflicts with an active room
    reservation when the new start is before that reservation's end plus the buffer
    and that reservation's start is before the new end plus the buffer. Adjacency
    within the buffer counts as a conflict, because rooms need cleanup time."

    Design: Difficulty/resource_temporal_overlap/room_exclusive_with_buffer_overlap
    """
    branch = create_branch(reservation_buffer_minutes=15)
    pa = create_patron(branch["id"], full_name="Buf Pat A")
    pb = create_patron(branch["id"], full_name="Buf Pat B")
    resource = create_resource(branch["id"], "ROOM", "Buffer Room")
    set_clock("2026-06-01T09:00:00Z")
    create_reservation(resource["id"], pa["id"], "2026-06-01T10:00:00Z",
                       "2026-06-01T11:00:00Z", resource["version"],
                       patron_headers=make_patron_headers(pa["id"]))
    v = current_resource_version(resource["id"])
    # second booking 11:10-12:00 starts 10 min after prior end, inside 15-min buffer.
    res = _client.create_reservation(
        {"resource_id": resource["id"], "patron_id": pb["id"],
         "start_at": "2026-06-01T11:10:00Z", "end_at": "2026-06-01T12:00:00Z",
         "expected_resource_version": v}, make_patron_headers(pb["id"]))
    validate_error(res, "ERR_RESERVATION_CONFLICT")


def test_computer_aggregate_capacity_overlap(api):
    """PRD §3.7: "For a `COMPUTER`, there is no buffer and capacity is aggregate:
    gather the active reservations whose half-open windows strictly overlap the new
    window (the new start before an existing end and that existing start before the
    new end), and reject only if, at the busiest instant across the combined set
    including the new booking, the number of simultaneously overlapping
    reservations would exceed the resource's `capacity`. A second overlapping
    computer booking is therefore fine as long as it stays within capacity."

    Design: Difficulty/resource_temporal_overlap/computer_aggregate_capacity_overlap
    """
    branch = create_branch()
    pa = create_patron(branch["id"], full_name="Comp Pat A")
    pb = create_patron(branch["id"], full_name="Comp Pat B")
    pc = create_patron(branch["id"], full_name="Comp Pat C")
    resource = create_resource(branch["id"], "COMPUTER", "PC Bank", capacity=2)
    set_clock("2026-06-01T09:00:00Z")
    create_reservation(resource["id"], pa["id"], "2026-06-01T10:00:00Z",
                       "2026-06-01T11:00:00Z", resource["version"],
                       patron_headers=make_patron_headers(pa["id"]))
    v1 = current_resource_version(resource["id"])
    # second overlapping booking within capacity 2 succeeds (no buffer/exclusion).
    create_reservation(resource["id"], pb["id"], "2026-06-01T10:00:00Z",
                       "2026-06-01T11:00:00Z", v1,
                       patron_headers=make_patron_headers(pb["id"]))
    v2 = current_resource_version(resource["id"])
    # third overlapping booking -> peak concurrency 3 > capacity 2.
    res = _client.create_reservation(
        {"resource_id": resource["id"], "patron_id": pc["id"],
         "start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T10:45:00Z",
         "expected_resource_version": v2}, make_patron_headers(pc["id"]))
    validate_error(res, "ERR_RESERVATION_CONFLICT")


# =========================================================================
# Queue A — cross_entity_state_dependency
# =========================================================================
def test_checkout_blocked_when_copy_not_available(api):
    """PRD §3.3: "The copy must be `AVAILABLE` (otherwise
    `ERR_RESOURCE_NOT_AVAILABLE`)".

    Design: Difficulty/cross_entity_state_dependency/checkout_blocked_when_copy_not_available
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    pa = create_patron(branch["id"], full_name="Dep Pat A")
    pb = create_patron(branch["id"], full_name="Dep Pat B")
    title = create_title(branch["id"], "9780000000013", title_text="Dep Book")
    copy = create_copy(title["id"], branch["id"], "BC-CD")
    create_loan(copy["id"], pa["id"])  # copy now ON_LOAN
    res = _client.create_loan({"copy_id": copy["id"], "patron_id": pb["id"]}, LIBRARIAN)
    validate_error(res, "ERR_RESOURCE_NOT_AVAILABLE")


def test_reservation_checkin_blocked_when_resource_out_of_service(api):
    """PRD §3.7: "A confirmed reservation is checked in by a librarian, permitted
    only from `CONFIRMED`, only while the resource is `IN_SERVICE`, and only once
    the clock has reached `start_at`".
    PRD §3.7: "An `OUT_OF_SERVICE` resource blocks new reservations and check-ins."

    Design: Difficulty/cross_entity_state_dependency/reservation_checkin_blocked_when_resource_out_of_service
    """
    branch, patron, resource, reservation = setup_room_with_confirmed_reservation(
        buffer_minutes=0, clock_before="2026-06-01T09:00:00Z",
        start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    get_success_data(api.set_service_status(resource["id"], "OUT_OF_SERVICE", MANAGER))
    set_clock("2026-06-01T10:05:00Z")
    res = api.checkin_reservation(reservation["id"], LIBRARIAN)
    validate_error(res, "ERR_RESOURCE_NOT_AVAILABLE")


# =========================================================================
# Queue B — OCC + reservation validation
# =========================================================================
def test_occ_correct_resource_version_succeeds(api):
    """PRD §2.9: "A successful reservation create advances the
    `BookableResource.version` by one, so the next sequential writer observes the
    change."
    PRD §3.7: "On success the reservation is created in `REQUESTED` status and the
    resource's `version` advances by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_resource_version_succeeds
    """
    branch = create_branch()
    patron = create_patron(branch["id"], full_name="Occ Pat")
    resource = create_resource(branch["id"], "COMPUTER", "Occ PC", capacity=3)
    set_clock("2026-06-01T09:00:00Z")
    res = validate_success(_client.create_reservation(
        {"resource_id": resource["id"], "patron_id": patron["id"],
         "start_at": "2026-06-01T10:00:00Z", "end_at": "2026-06-01T11:00:00Z",
         "expected_resource_version": resource["version"]},
        make_patron_headers(patron["id"])), 201)
    assert res["status"] == "REQUESTED"
    resource_after = validate_success(api.get_resource(resource["id"], LIBRARIAN), 200)
    assert resource_after["version"] == resource["version"] + 1


def test_occ_stale_resource_version_rejected(api):
    """PRD §2.9: "If `expected_resource_version` does not match the resource's
    current `version` — because another writer advanced the resource's `version`
    since the client last read it — the create is rejected with
    `ERR_STALE_RESOURCE_VERSION` (HTTP 412)".

    Design: Difficulty/resource_temporal_overlap/computer_aggregate_capacity_overlap
    """
    branch = create_branch()
    patron = create_patron(branch["id"], full_name="Stale Pat")
    other = create_patron(branch["id"], full_name="Other Pat")
    resource = create_resource(branch["id"], "COMPUTER", "Stale PC", capacity=3)
    set_clock("2026-06-01T09:00:00Z")
    stale_version = resource["version"]
    # Advance the resource version with a first successful booking by another patron.
    create_reservation(resource["id"], other["id"], "2026-06-01T08:00:00Z",
                       "2026-06-01T09:00:00Z", stale_version,
                       patron_headers=make_patron_headers(other["id"]))
    # Now `stale_version` is behind the resource's current version.
    res = _client.create_reservation(
        {"resource_id": resource["id"], "patron_id": patron["id"],
         "start_at": "2026-06-01T12:00:00Z", "end_at": "2026-06-01T13:00:00Z",
         "expected_resource_version": stale_version},
        make_patron_headers(patron["id"]))
    validate_error(res, "ERR_STALE_RESOURCE_VERSION")


def test_reservation_end_before_start_invalid_request(api):
    """PRD §3.7: "`end_at` must be strictly after `start_at` or the request is
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/reservation_end_before_start_returns_invalid_request
    """
    branch = create_branch(reservation_buffer_minutes=0)
    patron = create_patron(branch["id"], full_name="RevBad Pat")
    resource = create_resource(branch["id"], "ROOM", "Bad Room")
    res = _client.create_reservation(
        {"resource_id": resource["id"], "patron_id": patron["id"],
         "start_at": "2026-06-01T11:00:00Z", "end_at": "2026-06-01T10:00:00Z",
         "expected_resource_version": resource["version"]},
        make_patron_headers(patron["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")
