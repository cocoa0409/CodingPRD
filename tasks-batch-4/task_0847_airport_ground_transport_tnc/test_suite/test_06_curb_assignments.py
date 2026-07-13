"""Curb-zone assignments: trip-active guard, half-open overlap capacity, occupancy conservation."""
from test_helpers import (
    validate_error, validate_paginated, ApiErrorId,
    TEST_USERS,
    setup_completed_trip, setup_dispatched_trip, setup_two_dispatched_trips,
    create_curb_zone, create_curb_assignment, transition_trip,
)

AA = TEST_USERS["airport_authority_headers"]
CC = TEST_USERS["curb_coordinator_headers"]


def _active_count(api, zone_id):
    resp = api.list_curb_assignments(AA, params={"curb_zone_id": zone_id, "status": "ACTIVE"})
    _, meta = validate_paginated(resp)
    return meta["total_count"]


# --- cross-entity state dependency: curb assignment requires live trip ----
def test_curb_assignment_on_completed_trip_returns_trip_not_active(api):
    """PRD §3.6: "the referenced trip must be operationally live, in `DISPATCHED` or
    `PICKED_UP` status (else `ERR_TRIP_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/curb_assignment_requires_trip_active
    """
    ctx = setup_completed_trip(api, operator_type="TNC", clock="2026-04-20T12:00:00Z", avi_tag="AVI-DV1")
    zone = create_curb_zone(api, name="Z2", capacity=1)
    resp = api.create_curb_assignment(
        {"curb_zone_id": zone["id"], "trip_id": ctx["trip"]["id"],
         "start_ts": "2026-04-20T12:30:00Z", "end_ts": "2026-04-20T13:00:00Z"},
        CC,
    )
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_ACTIVE.value, 409)


def test_curb_assignment_on_dispatched_trip_succeeds(api):
    """PRD §3.6: "the referenced trip must be operationally live, in `DISPATCHED` or
    `PICKED_UP` status (else `ERR_TRIP_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/curb_assignment_requires_trip_active
    """
    ctx = setup_dispatched_trip(api, operator_type="TNC", clock="2026-04-20T12:00:00Z", avi_tag="AVI-DV2")
    zone = create_curb_zone(api, name="Z2b", capacity=1)
    ca = create_curb_assignment(api, zone["id"], ctx["trip"]["id"],
                                "2026-04-20T12:30:00Z", "2026-04-20T13:00:00Z")
    assert ca["status"] == "ACTIVE", f"expected ACTIVE curb assignment, got {ca['status']}"


# --- resource temporal overlap: half-open interval on curb zone -----------
def test_curb_overlapping_window_at_capacity_rejected(api):
    """PRD §3.6: "the number of `ACTIVE` assignments on that zone whose
    `[start_ts, end_ts)` half-open interval overlaps the requested
    `[start_ts, end_ts)` window must be strictly below the zone's `capacity`, or the
    assignment is rejected with `ERR_CURB_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/curb_half_open_interval_overlap_conflict
    """
    ctx = setup_two_dispatched_trips(api, clock="2026-04-25T09:00:00Z")
    zone = create_curb_zone(api, name="Z3", capacity=1)
    create_curb_assignment(api, zone["id"], ctx["trip1"]["id"],
                           "2026-04-25T10:00:00Z", "2026-04-25T10:30:00Z")
    resp = api.create_curb_assignment(
        {"curb_zone_id": zone["id"], "trip_id": ctx["trip2"]["id"],
         "start_ts": "2026-04-25T10:15:00Z", "end_ts": "2026-04-25T10:45:00Z"},
        CC,
    )
    validate_error(resp, ApiErrorId.ERR_CURB_CONFLICT.value, 409)


def test_curb_adjacent_window_allowed(api):
    """PRD §3.6: "Because the interval is half-open, an existing assignment ending
    exactly when a new one begins does not count as an overlap."

    Design: Difficulty/resource_temporal_overlap/curb_half_open_interval_overlap_conflict
    """
    ctx = setup_two_dispatched_trips(api, clock="2026-04-25T09:00:00Z")
    zone = create_curb_zone(api, name="Z3b", capacity=1)
    create_curb_assignment(api, zone["id"], ctx["trip1"]["id"],
                           "2026-04-25T10:00:00Z", "2026-04-25T10:30:00Z")
    ca2 = create_curb_assignment(api, zone["id"], ctx["trip2"]["id"],
                                 "2026-04-25T10:30:00Z", "2026-04-25T11:00:00Z")
    assert ca2["status"] == "ACTIVE", (
        f"adjacent [10:30,11:00) after [10:00,10:30) must be allowed, got {ca2['status']}"
    )


# --- compensating invariant: occupancy conserved --------------------------
def test_curb_occupancy_returns_to_baseline_after_completion(api):
    """PRD §3.4: "Completing (`PICKED_UP → COMPLETED`) stamps `complete_ts`,
    computes and locks `final_fee_cents` using the final fee variant anchored on
    `pickup_ts`, adds that final fee into the operator's `outstanding_fees_cents`,
    and releases any of the trip's curb assignments still in `ACTIVE` status to
    `RELEASED`."

    Design: Difficulty/compensating_invariant/curb_occupancy_conserved_assign_then_release
    """
    ctx = setup_dispatched_trip(api, operator_type="TNC", clock="2026-05-10T10:00:00Z", avi_tag="AVI-OV1")
    op_id = ctx["operator"]["id"]
    zone = create_curb_zone(api, name="Z4", capacity=2)
    ca = create_curb_assignment(api, zone["id"], ctx["trip"]["id"],
                                "2026-05-10T10:00:00Z", "2026-05-10T10:30:00Z")
    transition_trip(api, op_id, ctx["trip"]["id"], "PICKUP")
    transition_trip(api, op_id, ctx["trip"]["id"], "COMPLETE")
    released = validate_paginated(
        api.list_curb_assignments(AA, params={"curb_zone_id": zone["id"], "trip_id": ctx["trip"]["id"]})
    )[0]
    assert released[0]["status"] == "RELEASED", (
        f"curb assignment {ca['id']} should be RELEASED after completion"
    )
    assert _active_count(api, zone["id"]) == 0, "zone occupancy should return to baseline 0"


def test_curb_occupancy_incremented_on_assignment(api):
    """PRD §3.6: "A new assignment is created in `ACTIVE` status."
    PRD §3.4: "Completing (`PICKED_UP → COMPLETED`) stamps `complete_ts`, computes
    and locks `final_fee_cents` using the final fee variant anchored on `pickup_ts`,
    adds that final fee into the operator's `outstanding_fees_cents`, and releases
    any of the trip's curb assignments still in `ACTIVE` status to `RELEASED`."

    Design: Difficulty/compensating_invariant/curb_occupancy_conserved_assign_then_release
    """
    ctx = setup_dispatched_trip(api, operator_type="TNC", clock="2026-05-10T10:00:00Z", avi_tag="AVI-OV2")
    op_id = ctx["operator"]["id"]
    zone = create_curb_zone(api, name="Z4b", capacity=2)
    create_curb_assignment(api, zone["id"], ctx["trip"]["id"],
                           "2026-05-10T10:00:00Z", "2026-05-10T10:30:00Z")
    assert _active_count(api, zone["id"]) == 1, "one ACTIVE assignment after assign (+1)"
    transition_trip(api, op_id, ctx["trip"]["id"], "PICKUP")
    transition_trip(api, op_id, ctx["trip"]["id"], "COMPLETE")
    assert _active_count(api, zone["id"]) == 0, "release on completion returns occupancy to 0 (-1)"
