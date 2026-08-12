"""Processing facilities and facility deliveries: toggling, buffered bay
windows, and the receive-time accept gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_facility_delivery,
    assert_processing_facility,
    create_delivery,
    create_facility,
    create_facility_delivery_payload,
    create_giveback_event_payload,
    create_receive_payload,
    make_supervisor_headers,
    receive_delivery,
    set_clock,
    setup_facility_with_route,
    validate_error,
    validate_success,
)

# Route window for the safety-vs-referential scenario: archives once the clock
# passes 2026-08-01.
SHORT_ROUTE_WINDOW = {"effective_start_date": "2026-05-01", "effective_end_date": "2026-08-01"}


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / receive_safety_trumps_referential
# ---------------------------------------------------------------------------

def _setup_dual_violation_receive():
    """Route window [2026-05-01, 2026-08-01) published; delivery scheduled
    2026-06-15 10:00-11:00 while the route is PUBLISHED; clock then advanced to
    2026-08-15 so the route has auto-archived."""
    ctx = setup_facility_with_route(clock="2026-06-01T00:00:00Z",
                                    route_overrides=SHORT_ROUTE_WINDOW,
                                    daily_receiving_capacity_lbs=50000,
                                    safety_contamination_item_limit=5)
    delivery = create_delivery(ctx["facility"]["id"], ctx["route"]["id"],
                               delivery_date="2026-06-15",
                               window_start="2026-06-15T10:00:00Z",
                               window_end="2026-06-15T11:00:00Z")
    set_clock("2026-08-15T00:00:00Z")  # route auto-archives lazily past 2026-08-01
    ctx["delivery"] = delivery
    return ctx


def test_receive_safety_error_trumps_referential_error(api, admin_headers, supervisor_headers):
    """PRD section 3.8: "An accept outcome then faces three gates in this
    order: the safety gate rejects with `ERR_LOAD_SAFETY_LIMIT_EXCEEDED` when
    `contaminated_item_count` exceeds the facility's
    `safety_contamination_item_limit`; the capacity gate rejects with
    `ERR_FACILITY_CAPACITY_EXCEEDED` when the facility's already-accepted
    pounds on that `delivery_date` plus `gross_weight_lbs` would exceed
    `daily_receiving_capacity_lbs`; and the referential gate rejects with
    `ERR_ROUTE_NOT_PUBLISHED` if the origin route is no longer `PUBLISHED` at
    receive time."

    Design: Difficulty/priority_pair_validation_conflict/receive_safety_trumps_referential
    """
    ctx = _setup_dual_violation_receive()
    # Both the safety gate (6 > 5) and the referential gate (route ARCHIVED)
    # are violated; the earlier safety gate surfaces.
    res = api.receive_facility_delivery(
        ctx["delivery"]["id"], create_receive_payload("ACCEPT", 1000, 6), supervisor_headers)
    validate_error(res, ApiErrorId.ERR_LOAD_SAFETY_LIMIT_EXCEEDED)


def test_receive_dual_violation_leaves_delivery_scheduled(api, admin_headers, supervisor_headers):
    """PRD section 3.8: "the referential gate rejects with
    `ERR_ROUTE_NOT_PUBLISHED` if the origin route is no longer `PUBLISHED` at
    receive time." and "The delivery must be `SCHEDULED` (otherwise
    `ERR_INVALID_STATE`)." A receive rejected at the safety gate leaves the
    delivery SCHEDULED while the route reads ARCHIVED.

    Design: Difficulty/priority_pair_validation_conflict/receive_safety_trumps_referential
    """
    ctx = _setup_dual_violation_receive()
    res = api.receive_facility_delivery(
        ctx["delivery"]["id"], create_receive_payload("ACCEPT", 1000, 6), supervisor_headers)
    validate_error(res, ApiErrorId.ERR_LOAD_SAFETY_LIMIT_EXCEEDED)

    route_after = validate_success(api.get_route(ctx["route"]["id"], admin_headers), 200)
    assert route_after["status"] == "ARCHIVED"
    delivery_after = validate_success(
        api.get_facility_delivery(ctx["delivery"]["id"], admin_headers), 200)
    assert delivery_after["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / delivery_window_buffered_overlap
# ---------------------------------------------------------------------------

def _setup_existing_delivery():
    ctx = setup_facility_with_route(clock="2026-06-01T00:00:00Z")
    d1 = create_delivery(ctx["facility"]["id"], ctx["route"]["id"],
                         delivery_date="2026-06-15",
                         window_start="2026-06-15T10:00:00Z",
                         window_end="2026-06-15T11:00:00Z")
    ctx["d1"] = d1
    return ctx


def test_delivery_window_buffered_overlap_rejected(api, admin_headers, supervisor_headers):
    """PRD section 3.8: "Bay scheduling uses a buffered-overlap rule: each
    appointment's window is expanded by thirty minutes on both sides, and if
    that expanded window overlaps another delivery at the same facility on the
    same date, the new appointment is rejected with
    `ERR_DELIVERY_WINDOW_OVERLAP`". 11:15-12:00 collides with the buffered
    [09:30, 11:30) of the existing 10:00-11:00 booking.

    Design: Difficulty/resource_temporal_overlap/delivery_window_buffered_overlap
    """
    ctx = _setup_existing_delivery()
    res = api.create_facility_delivery(
        create_facility_delivery_payload(ctx["facility"]["id"], ctx["route"]["id"],
                                         delivery_date="2026-06-15",
                                         window_start="2026-06-15T11:15:00Z",
                                         window_end="2026-06-15T12:00:00Z"),
        supervisor_headers,
    )
    validate_error(res, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)


def test_delivery_window_buffer_edge_touch_allowed(api, admin_headers, supervisor_headers):
    """PRD section 3.8: "appointments whose buffers merely touch at the edges
    are allowed." Buffered [09:30, 11:30) vs the new 12:00-12:30 (buffered
    [11:30, 13:00)) touch at 11:30 without overlapping.

    Design: Difficulty/resource_temporal_overlap/delivery_window_buffered_overlap
    """
    ctx = _setup_existing_delivery()
    d3 = validate_success(api.create_facility_delivery(
        create_facility_delivery_payload(ctx["facility"]["id"], ctx["route"]["id"],
                                         delivery_date="2026-06-15",
                                         window_start="2026-06-15T12:00:00Z",
                                         window_end="2026-06-15T12:30:00Z"),
        supervisor_headers), 201)
    assert_facility_delivery(d3)
    assert d3["status"] == "SCHEDULED"

    d1_after = validate_success(api.get_facility_delivery(ctx["d1"]["id"], admin_headers), 200)
    assert d1_after["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue B: facility lifecycle and delivery receive paths
# ---------------------------------------------------------------------------

def test_facility_close_open_cycle(api, admin_headers):
    """PRD section 3.8: "A facility starts `OPEN` and may be toggled to
    `CLOSED` and back by a `ProgramAdmin`; each toggle requires the opposite
    current state (otherwise `ERR_INVALID_STATE`), and limits may be adjusted
    the same way, every update incrementing the facility's `version`."

    Design: Corner/state_machines/facility_close_open_cycle
    """
    facility = create_facility()
    assert_processing_facility(facility)
    assert facility["status"] == "OPEN"
    assert facility["version"] == 1

    closed = validate_success(api.update_facility(facility["id"], {"status": "CLOSED"}, admin_headers), 200)
    assert closed["status"] == "CLOSED"
    assert closed["version"] == facility["version"] + 1

    reopened = validate_success(api.update_facility(facility["id"], {"status": "OPEN"}, admin_headers), 200)
    assert reopened["status"] == "OPEN"


def test_facility_not_open_blocks_delivery(api, admin_headers, supervisor_headers):
    """PRD section 3.8: "The facility must be `OPEN` (`ERR_FACILITY_NOT_OPEN`)
    and the route must be `PUBLISHED` (`ERR_ROUTE_NOT_PUBLISHED`)" for delivery
    scheduling.

    Design: Corner/validations/facility_not_open_blocks_delivery
    """
    ctx = setup_facility_with_route(clock="2026-06-01T00:00:00Z")
    validate_success(api.update_facility(ctx["facility"]["id"], {"status": "CLOSED"}, admin_headers), 200)

    res = api.create_facility_delivery(
        create_facility_delivery_payload(ctx["facility"]["id"], ctx["route"]["id"],
                                         delivery_date="2026-06-15",
                                         window_start="2026-06-15T09:00:00Z",
                                         window_end="2026-06-15T10:00:00Z"),
        supervisor_headers,
    )
    validate_error(res, ApiErrorId.ERR_FACILITY_NOT_OPEN)


def test_receive_reject_path_records_zero_acceptance(api, admin_headers, supervisor_headers):
    """PRD section 3.8: "A reject outcome is the operator's prerogative and
    bypasses all three gates — no load enters the facility,
    `accepted_weight_lbs` is set to 0, and the delivery is `REJECTED`."

    Design: Corner/endpoints/receive_reject_path_records_zero_acceptance
    """
    ctx = setup_facility_with_route(clock="2026-06-01T00:00:00Z")
    delivery = create_delivery(ctx["facility"]["id"], ctx["route"]["id"],
                               delivery_date="2026-06-15",
                               window_start="2026-06-15T09:00:00Z",
                               window_end="2026-06-15T10:00:00Z")

    # Contaminated count 9 exceeds the safety limit of 5, yet REJECT bypasses it.
    rejected = receive_delivery(delivery["id"], "REJECT", gross_weight_lbs=3000,
                                contaminated_item_count=9)
    assert rejected["status"] == "REJECTED"
    assert rejected["accepted_weight_lbs"] == 0

    facility_after = validate_success(api.get_facility(ctx["facility"]["id"], admin_headers), 200)
    assert facility_after["season_accepted_lbs"] == 0


def test_inventory_excludes_rejected_deliveries(api, admin_headers):
    """PRD section 3.8: "At creation, the event's `initial_inventory_gallons`
    is computed once: sum `accepted_weight_lbs` over every `ACCEPTED` facility
    delivery whose route belongs to the event's zone and whose `delivery_date`
    falls inside the zone's season window, convert at the same half yield and
    twenty pounds per gallon, and floor the result to whole gallons." 4000 lbs
    ACCEPTED plus 8000 lbs REJECTED yields floor(4000 x 0.025) = 100 gallons.

    Design: Corner/calculations/inventory_excludes_rejected_deliveries
    """
    ctx = setup_facility_with_route(clock="2026-06-01T00:00:00Z")
    d1 = create_delivery(ctx["facility"]["id"], ctx["route"]["id"],
                         delivery_date="2026-06-15",
                         window_start="2026-06-15T09:00:00Z",
                         window_end="2026-06-15T10:00:00Z")
    receive_delivery(d1["id"], "ACCEPT", gross_weight_lbs=4000, contaminated_item_count=0)
    d2 = create_delivery(ctx["facility"]["id"], ctx["route"]["id"],
                         delivery_date="2026-06-16",
                         window_start="2026-06-16T09:00:00Z",
                         window_end="2026-06-16T10:00:00Z")
    receive_delivery(d2["id"], "REJECT", gross_weight_lbs=8000, contaminated_item_count=9)

    from test_helpers import api_client, TEST_USERS
    event = validate_success(api_client.create_giveback_event(
        create_giveback_event_payload(ctx["zone"]["id"], event_date="2026-11-15",
                                      per_household_cap_gallons=10),
        TEST_USERS["admin_headers"]), 201)
    assert event["initial_inventory_gallons"] == 100

    d2_after = validate_success(api.get_facility_delivery(d2["id"], admin_headers), 200)
    assert d2_after["accepted_weight_lbs"] == 0
    facility_after = validate_success(api.get_facility(ctx["facility"]["id"], admin_headers), 200)
    assert facility_after["season_accepted_lbs"] == 4000
