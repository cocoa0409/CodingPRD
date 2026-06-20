"""Assignment: provider selection, dead-head storage, OCC, modality/county
matching, single-active-assignment, validation precedence.

Difficulty queue A (dual_variant_calc deadhead, boundary_precision deadhead,
priority_pair invalid-state, resource_temporal_overlap second-assignment,
cross_cutting OCC) plus corner queue B (validations modality, errors no-broker).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_member_payload,
    create_eligibility_span_payload,
    create_broker_payload,
    create_driver_payload,
    create_trip_payload,
)
from test_helpers import fixtures

COORD = TEST_USERS["coordinator_headers"]
BROKER = TEST_USERS["broker_headers"]


def _active_assignment(api, trip_id):
    resp = api.list_trip_assignments(trip_id, COORD)
    data, _ = validate_paginated(resp)
    actives = [a for a in data if a["status"] == "ACTIVE"]
    assert actives, "expected one ACTIVE assignment"
    return actives[0]


def test_deadhead_raw_stored_not_allowanced(api):
    """PRD 3.4: "The raw dead-head is the county-to-county distance between the
    driver's `base_county` and the member's `home_county`, read from the
    symmetric distance matrix (a same-county pair is zero miles). This raw value
    is stored on the assignment as `deadhead_miles`."

    Design: Difficulty/dual_variant_calc/deadhead_raw_vs_billable_diverge_on_assignment
    """
    world = fixtures.setup_world(
        modality="AMBULATORY", medicaid_id="M-DH1", deadhead_miles=12,
        free_deadhead_miles=5, deadhead_rate_cents_per_mile=80)
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    assert assigned["trip_status"] == "ASSIGNED"
    a = _active_assignment(api, assigned["id"])
    # Raw 12 stored verbatim, NOT the allowanced 7 (12-5).
    assert a["deadhead_miles"] == 12, "deadhead_miles must store raw distance, not billable"


def test_deadhead_raw_distinct_from_allowanced_value(api):
    """PRD 3.4: "The raw dead-head is the county-to-county distance between the
    driver's `base_county` and the member's `home_county` ... This raw value is
    stored on the assignment as `deadhead_miles`. Billable dead-head accrues only
    above the broker's free allowance".

    Design: Difficulty/dual_variant_calc/deadhead_raw_vs_billable_diverge_on_assignment
    """
    # Raw 20 with free 8: stored deadhead_miles must be the raw 20, not 12 (20-8).
    world = fixtures.setup_world(
        modality="AMBULATORY", medicaid_id="M-DH1b", deadhead_miles=20,
        free_deadhead_miles=8, deadhead_rate_cents_per_mile=80)
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    a = _active_assignment(api, assigned["id"])
    assert a["deadhead_miles"] == 20, "raw distance stored verbatim, not allowance-adjusted"


def test_deadhead_free_miles_strict_greater_than_boundary(api):
    """PRD 3.4: "if the raw dead-head is strictly greater than the broker's
    `free_deadhead_miles`, the billable portion is the raw dead-head minus that
    allowance; if the raw dead-head is less than or equal to the allowance, the
    billable portion is zero."

    Design: Difficulty/boundary_precision_check/deadhead_free_miles_strict_greater_than
    """
    # Raw exactly equals free allowance (5 == 5): strict '>' not crossed.
    world = fixtures.setup_world(
        modality="AMBULATORY", medicaid_id="M-BD1", deadhead_miles=5,
        free_deadhead_miles=5, deadhead_rate_cents_per_mile=80)
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    a = _active_assignment(api, assigned["id"])
    assert a["deadhead_miles"] == 5, "raw 5 stored; equal to free allowance"


def test_deadhead_above_allowance_stores_raw(api):
    """PRD 3.4: "This raw value is stored on the assignment as `deadhead_miles`. ...
    if the raw dead-head is strictly greater than the broker's `free_deadhead_miles`,
    the billable portion is the raw dead-head minus that allowance".

    Design: Difficulty/boundary_precision_check/deadhead_free_miles_strict_greater_than
    """
    # Raw 6 > free 5: billable portion exists but deadhead_miles still stores raw 6.
    world = fixtures.setup_world(
        modality="AMBULATORY", medicaid_id="M-BD1b", deadhead_miles=6,
        free_deadhead_miles=5, deadhead_rate_cents_per_mile=80)
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    a = _active_assignment(api, assigned["id"])
    assert a["deadhead_miles"] == 6


def test_assign_bumps_trip_version(api):
    """PRD 3.4: "flips the chosen driver from `AVAILABLE` to `ON_TRIP`, and
    increments the trip's `version` by one — which is precisely why a second
    writer holding a stale `expected_trip_version` is rejected."

    Design: Corner/cross_cutting_complexity_layers/assign_bumps_trip_version
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-OC2")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    v_before = scheduled["version"]
    assigned = fixtures.assign_trip(world, scheduled)
    assert assigned["version"] == v_before + 1
    assert assigned["trip_status"] == "ASSIGNED"


def test_assign_sets_driver_on_trip(api):
    """PRD 3.4: "It sets the trip's `assigned_broker_id` and `assigned_driver_id`,
    flips the chosen driver from `AVAILABLE` to `ON_TRIP`, and increments the
    trip's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/assign_bumps_trip_version
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-OC2b")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    assert assigned["assigned_driver_id"] == world["driver"]["id"]
    driver = fixtures.get_driver(world["driver"]["id"])
    assert driver["status"] == "ON_TRIP"


def test_occ_stale_version_assign_rejected(api):
    """PRD 2.8: "If `expected_trip_version` does not equal the trip's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_assign_rejected
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-OC1")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    stale_version = scheduled["version"] - 1
    resp = api.assign_trip(
        scheduled["id"],
        {"expected_trip_version": stale_version, "preferred_broker_id": world["broker"]["id"]},
        BROKER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_success_data(api.get_trip(scheduled["id"], COORD))
    assert after["trip_status"] == "SCHEDULED"


def test_modality_mismatch_on_assign_preferred_broker_below_modality(api):
    """PRD 3.4: "If a specific selected or preferred broker or driver is examined
    but fails the modality or county test — its modality rank is below the trip's,
    or its broker does not cover the member's home county — that specific mismatch
    is reported as `ERR_MODALITY_MISMATCH`."

    Design: Corner/validations/modality_mismatch_on_assign_when_no_driver_supports_modality
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    fixtures.create_rate(modality="STRETCHER", base_fare_cents=4000,
                         loaded_rate_cents_per_mile=250, dwell_free_minutes=10,
                         dwell_cents_per_minute=60)
    member = fixtures.create_member(medicaid_id="M-MM1", mobility_level="STRETCHER",
                                    home_county="C1")
    fixtures.create_span(member["id"], level_of_service="BARIATRIC",
                         coverage_start="2026-01-01T00:00:00Z",
                         coverage_end="2027-01-01T00:00:00Z")
    broker = fixtures.create_broker(name="BrokerMM", covered_counties=["C1"],
                                    max_modality="WHEELCHAIR", free_deadhead_miles=5,
                                    deadhead_rate_cents_per_mile=80)
    fixtures.seed_distance("C2", "C1", 12)
    fixtures.create_driver(broker["id"], vehicle_modality="WHEELCHAIR", base_county="C2")
    trip = fixtures.create_trip(member["id"], modality="STRETCHER",
                                requested_level_of_service="BARIATRIC",
                                appointment_at="2026-03-02T09:00:00Z",
                                scheduled_loaded_miles=6, is_round_trip=False)
    scheduled = get_success_data(api.schedule_trip(trip["id"], COORD))
    resp = api.assign_trip(
        trip["id"],
        {"expected_trip_version": scheduled["version"], "preferred_broker_id": broker["id"]},
        BROKER,
    )
    validate_error(resp, ApiErrorId.ERR_MODALITY_MISMATCH.value)
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["trip_status"] == "SCHEDULED"


def test_no_broker_available_when_county_uncovered(api):
    """PRD 3.4: "If no candidate broker-and-driver pair satisfies these conditions
    at all, the assignment is rejected with `ERR_NO_BROKER_AVAILABLE`."

    Design: Corner/errors/error_no_broker_available_when_county_uncovered
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = fixtures.create_member(medicaid_id="M-NB1", mobility_level="AMBULATORY",
                                    home_county="C5")
    fixtures.create_span(member["id"], level_of_service="ROUTINE",
                         coverage_start="2026-01-01T00:00:00Z",
                         coverage_end="2027-01-01T00:00:00Z")
    broker = fixtures.create_broker(name="BrokerNB", covered_counties=["C1"],
                                    max_modality="AMBULATORY", free_deadhead_miles=5,
                                    deadhead_rate_cents_per_mile=80)
    fixtures.create_driver(broker["id"], vehicle_modality="AMBULATORY", base_county="C2")
    trip = fixtures.create_trip(member["id"], modality="AMBULATORY",
                                requested_level_of_service="ROUTINE",
                                appointment_at="2026-03-02T09:00:00Z",
                                scheduled_loaded_miles=8, is_round_trip=False)
    scheduled = get_success_data(api.schedule_trip(trip["id"], COORD))
    resp = api.assign_trip(
        trip["id"], {"expected_trip_version": scheduled["version"]}, BROKER)
    validate_error(resp, ApiErrorId.ERR_NO_BROKER_AVAILABLE.value)


def test_invalid_state_beats_no_broker_on_assign(api):
    """PRD 2.10: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`) ... then candidate-pair
    availability (`ERR_NO_BROKER_AVAILABLE`)".
    PRD 3.4: "Assignment is a `Broker` operation that advances a trip from
    `SCHEDULED` to `ASSIGNED`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_no_broker_on_assign
    """
    # DRAFT trip (never scheduled) AND no broker covers county C9: state check (5)
    # must beat candidate-availability (13).
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = fixtures.create_member(medicaid_id="M-PP2", mobility_level="AMBULATORY",
                                    home_county="C9")
    fixtures.create_span(member["id"], level_of_service="ROUTINE",
                         coverage_start="2026-01-01T00:00:00Z",
                         coverage_end="2027-01-01T00:00:00Z")
    trip = fixtures.create_trip(member["id"], modality="AMBULATORY",
                                requested_level_of_service="ROUTINE",
                                appointment_at="2026-03-02T09:00:00Z",
                                scheduled_loaded_miles=5, is_round_trip=False)
    resp = api.assign_trip(
        trip["id"], {"expected_trip_version": trip["version"]}, BROKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_second_active_assignment_blocked_on_trip(api):
    """PRD 3.4: "A trip may have at most one `ACTIVE` assignment; attempting to
    create a second `ACTIVE` assignment without the prior one having been
    superseded is rejected with `ERR_ASSIGNMENT_EXISTS`."

    Design: Difficulty/resource_temporal_overlap/second_active_assignment_blocked_on_trip
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-RO2")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    # Second assign with the post-assign (current) version so OCC passes; the
    # single-active-assignment rule must fire.
    resp = api.assign_trip(
        assigned["id"],
        {"expected_trip_version": assigned["version"], "preferred_broker_id": world["broker"]["id"]},
        BROKER,
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_EXISTS.value)


def test_invalid_state_beats_no_broker_trip_unchanged(api):
    """PRD 2.10: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`) ... then candidate-pair
    availability (`ERR_NO_BROKER_AVAILABLE`)".
    PRD 3.3: "A new trip begins with `trip_status` of `DRAFT`".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_no_broker_on_assign
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = fixtures.create_member(medicaid_id="M-PP2b", mobility_level="AMBULATORY",
                                    home_county="C9")
    fixtures.create_span(member["id"], level_of_service="ROUTINE",
                         coverage_start="2026-01-01T00:00:00Z",
                         coverage_end="2027-01-01T00:00:00Z")
    trip = fixtures.create_trip(member["id"], modality="AMBULATORY",
                                requested_level_of_service="ROUTINE",
                                appointment_at="2026-03-02T09:00:00Z",
                                scheduled_loaded_miles=5, is_round_trip=False)
    resp = api.assign_trip(trip["id"], {"expected_trip_version": trip["version"]}, BROKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["trip_status"] == "DRAFT", "DRAFT trip never advanced"


def test_second_active_assignment_blocked_trip_stays_assigned(api):
    """PRD 3.4: "A trip may have at most one `ACTIVE` assignment; attempting to
    create a second `ACTIVE` assignment without the prior one having been
    superseded is rejected with `ERR_ASSIGNMENT_EXISTS`. ... An assignment's
    `status` is one of `ACTIVE`, `SUPERSEDED`, or `RELEASED`, and only one
    assignment per trip is `ACTIVE` at a time."

    Design: Difficulty/resource_temporal_overlap/second_active_assignment_blocked_on_trip
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-RO2b")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    resp = api.assign_trip(
        assigned["id"],
        {"expected_trip_version": assigned["version"], "preferred_broker_id": world["broker"]["id"]},
        BROKER,
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_EXISTS.value)
    # Exactly one ACTIVE assignment remains; trip unchanged.
    a = _active_assignment(api, assigned["id"])
    assert a["status"] == "ACTIVE"
    after = get_success_data(api.get_trip(assigned["id"], COORD))
    assert after["trip_status"] == "ASSIGNED"


def test_filtered_assignments_by_broker_id(api):
    """PRD 2.3: "Every list response surfaces `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD 3.4: "When a candidate is found, the system creates an **Assignment** in
    `ACTIVE` status recording the chosen `trip_id`, `broker_id`, and `driver_id`."

    Design: Corner/endpoints/filtered_assignments_by_broker_id
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-FA1")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    fixtures.assign_trip(world, scheduled)
    resp = api.list_assignments(COORD, params={"broker_id": world["broker"]["id"]})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert all(a["broker_id"] == world["broker"]["id"] for a in data)
