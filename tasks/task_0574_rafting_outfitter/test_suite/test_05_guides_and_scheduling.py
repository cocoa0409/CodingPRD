"""Guide certification/scheduling constraints, guide-ratio boundary at check-in, shuttle
turnaround buffer, guide deactivation, and shuttle-run cancellation."""
from test_helpers import validate_success, validate_error
from test_helpers import TEST_USERS
from test_helpers.fixtures import (
    create_trip, create_guide, assign_guide, setup_open_trip, setup_confirmed_reservation,
)
from test_helpers.factories import (
    create_guide_assignment_payload, create_shuttle_vehicle_payload, create_shuttle_run_payload,
)

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]


# ── Guide-ratio ceiling boundary at check-in ──

def test_guide_ratio_unmet_at_seven_committed_with_one_guide(api):
    """PRD §3.5: "The required guide count is the trip's `committed_guests` divided by its
    `guide_ratio_max`, rounded up to the next whole number — so a committed load exactly
    equal to `guide_ratio_max` needs one guide, and one more guest tips the requirement to two."
    PRD §3.5: "the trip's `assigned_guide_count` must be at least the required guide count
    for the trip, otherwise `ERR_GUIDE_RATIO_UNMET`."

    Design: Difficulty/boundary_precision_check/guide_ratio_ceiling_boundary_at_seven_guests
    """
    ctx = setup_confirmed_reservation(
        api, party_size=7, deposit_cents=20000, with_gear=True, sign=True,
        guide_ratio_max=6, max_capacity=12, guest_weight=175, guest_age=28,
    )
    validate_error(api.check_in_reservation(ctx["res"]["id"], RESV), "ERR_GUIDE_RATIO_UNMET")


def test_guide_ratio_met_at_six_committed_with_one_guide(api):
    """PRD §3.5: "The required guide count is the trip's `committed_guests` divided by its
    `guide_ratio_max`, rounded up to the next whole number — so a committed load exactly
    equal to `guide_ratio_max` needs one guide, and one more guest tips the requirement to two."

    Design: Difficulty/boundary_precision_check/guide_ratio_ceiling_boundary_at_seven_guests
    """
    ctx = setup_confirmed_reservation(
        api, party_size=6, deposit_cents=20000, with_gear=True, sign=True,
        guide_ratio_max=6, max_capacity=12, guest_weight=175, guest_age=28,
    )
    checked_in = validate_success(api.check_in_reservation(ctx["res"]["id"], RESV), 200)
    assert checked_in["fulfillment_status"] == "CHECKED_IN"


# ── Guide temporal overlap (half-open interval) ──

def test_guide_double_booked_on_overlapping_intervals(api):
    """PRD §3.1: "if the guide is already `ASSIGNED` to another trip whose half-open
    interval from that trip's `trip_date` up to but not including its `end_time` strictly
    overlaps this trip's half-open interval, the assignment is rejected with
    `ERR_GUIDE_DOUBLE_BOOKED`; exact adjacency, where the next trip's `trip_date` equals
    the previous trip's `end_time`, is permitted."

    Design: Difficulty/resource_temporal_overlap/guide_double_booked_on_overlapping_trip_intervals
    """
    trip_a = create_trip(api, river_name="TripA", trip_date="2026-07-01T09:00:00Z", end_time="2026-07-01T15:00:00Z")
    trip_b = create_trip(api, river_name="TripB", trip_date="2026-07-01T12:00:00Z", end_time="2026-07-01T18:00:00Z")
    guide = create_guide(api, max_class="CLASS_III")
    assign_guide(api, trip_a["id"], guide["id"], "LEAD")
    resp = api.create_guide_assignment(
        create_guide_assignment_payload(trip_b["id"], guide["id"], "LEAD"), MGR)
    validate_error(resp, "ERR_GUIDE_DOUBLE_BOOKED")


def test_guide_exact_adjacency_intervals_allowed(api):
    """PRD §3.1: "exact adjacency, where the next trip's `trip_date` equals the previous
    trip's `end_time`, is permitted."

    Design: Difficulty/resource_temporal_overlap/guide_double_booked_on_overlapping_trip_intervals
    """
    trip_a = create_trip(api, river_name="TripA", trip_date="2026-07-01T09:00:00Z", end_time="2026-07-01T15:00:00Z")
    trip_c = create_trip(api, river_name="TripC", trip_date="2026-07-01T15:00:00Z", end_time="2026-07-01T21:00:00Z")
    guide = create_guide(api, max_class="CLASS_III")
    assign_guide(api, trip_a["id"], guide["id"], "LEAD")
    ga = validate_success(
        api.create_guide_assignment(create_guide_assignment_payload(trip_c["id"], guide["id"], "LEAD"), MGR), 201)
    assert ga["status"] == "ASSIGNED"


# ── Shuttle vehicle turnaround buffer ──

def test_shuttle_buffer_conflict_within_thirty_minutes(api):
    """PRD §3.8: "if the same vehicle already has a `SCHEDULED` run and the gap between the
    nearer endpoints of the two runs is strictly less than 30 minutes, the new run is
    rejected with `ERR_SHUTTLE_BUFFER_CONFLICT`; a gap of exactly 30 minutes is permitted."

    Design: Difficulty/resource_temporal_overlap/shuttle_vehicle_buffer_conflict_within_30_minutes
    """
    trip = create_trip(api, river_name="ShuttleTrip", difficulty_class="CLASS_III")
    veh = validate_success(api.create_shuttle_vehicle(create_shuttle_vehicle_payload(name="Van 1", seat_capacity=14), MGR), 201)
    validate_success(api.create_shuttle_run(create_shuttle_run_payload(
        trip["id"], veh["id"], direction="FROM_TAKE_OUT",
        depart_time="2026-07-02T15:00:00Z", arrive_time="2026-07-02T16:00:00Z"), MGR), 201)
    resp = api.create_shuttle_run(create_shuttle_run_payload(
        trip["id"], veh["id"], direction="TO_PUT_IN",
        depart_time="2026-07-02T16:15:00Z", arrive_time="2026-07-02T17:00:00Z"), MGR)
    validate_error(resp, "ERR_SHUTTLE_BUFFER_CONFLICT")


def test_shuttle_buffer_exactly_thirty_minutes_allowed(api):
    """PRD §3.8: "a gap of exactly 30 minutes is permitted."

    Design: Difficulty/resource_temporal_overlap/shuttle_vehicle_buffer_conflict_within_30_minutes
    """
    trip = create_trip(api, river_name="ShuttleTrip", difficulty_class="CLASS_III")
    veh = validate_success(api.create_shuttle_vehicle(create_shuttle_vehicle_payload(name="Van 1", seat_capacity=14), MGR), 201)
    validate_success(api.create_shuttle_run(create_shuttle_run_payload(
        trip["id"], veh["id"], direction="FROM_TAKE_OUT",
        depart_time="2026-07-02T15:00:00Z", arrive_time="2026-07-02T16:00:00Z"), MGR), 201)
    run2 = validate_success(api.create_shuttle_run(create_shuttle_run_payload(
        trip["id"], veh["id"], direction="TO_PUT_IN",
        depart_time="2026-07-02T16:30:00Z", arrive_time="2026-07-02T17:00:00Z"), MGR), 201)
    assert run2["status"] == "SCHEDULED"


# ── Corner: guide class, deactivation, shuttle cancel ──

def test_assign_guide_below_trip_class_returns_class_insufficient(api):
    """PRD §3.1: "the guide's `max_class` must be at least the trip's `difficulty_class` on
    the `CLASS_I`-through-`CLASS_V` ordering, otherwise `ERR_GUIDE_CLASS_INSUFFICIENT`."

    Design: Corner/validations/assign_guide_below_trip_class_returns_class_insufficient
    """
    trip = create_trip(api, difficulty_class="CLASS_IV")
    guide = create_guide(api, max_class="CLASS_II", full_name="Junior")
    resp = api.create_guide_assignment(create_guide_assignment_payload(trip["id"], guide["id"], "LEAD"), MGR)
    validate_error(resp, "ERR_GUIDE_CLASS_INSUFFICIENT")


def test_deactivate_guide_in_use_returns_guide_in_use(api):
    """PRD §3.1: "The manager may deactivate a guide, moving `status` from `ACTIVE` to
    `INACTIVE`, but only when the guide holds no `ASSIGNED` guide assignment on any
    non-terminal trip; attempting to deactivate a guide still committed to live work is
    rejected with `ERR_GUIDE_IN_USE`."

    Design: Corner/state_machines/deactivate_guide_in_use_returns_guide_in_use
    """
    trip = create_trip(api, difficulty_class="CLASS_III")
    guide = create_guide(api, max_class="CLASS_III", full_name="Busy")
    assign_guide(api, trip["id"], guide["id"], "LEAD")
    validate_error(api.deactivate_guide(guide["id"], MGR), "ERR_GUIDE_IN_USE")


def test_cancel_shuttle_run_from_scheduled_succeeds(api):
    """PRD §3.8: "A run may be cancelled, moving its `status` from `SCHEDULED` to `CANCELLED`."

    Design: Corner/state_machines/cancel_shuttle_run_from_scheduled_succeeds
    """
    trip = create_trip(api, difficulty_class="CLASS_II")
    veh = validate_success(api.create_shuttle_vehicle(create_shuttle_vehicle_payload(name="Van", seat_capacity=12), MGR), 201)
    run = validate_success(api.create_shuttle_run(create_shuttle_run_payload(
        trip["id"], veh["id"], direction="TO_PUT_IN",
        depart_time="2026-06-15T07:00:00Z", arrive_time="2026-06-15T08:00:00Z"), MGR), 201)
    cancelled = validate_success(api.cancel_shuttle_run(run["id"], MGR), 200)
    assert cancelled["status"] == "CANCELLED"
