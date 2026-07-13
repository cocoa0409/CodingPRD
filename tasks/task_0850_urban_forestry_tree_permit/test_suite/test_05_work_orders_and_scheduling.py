"""Work orders, 811 dig tickets, contractor scheduling, storm overlap, and removal cascade."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_work_order_payload, create_dig_ticket_payload, create_storm_event_payload,
    setup_tree, setup_approved_removal_permit, setup_emergency_context,
    setup_emergency_work_order, setup_started_removal_work_order,
    new_zone, new_storm, new_contractor, new_work_order, new_dig_ticket, mark_valid,
    make_contractor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["forestry_admin_headers"]
STAFF = TEST_USERS["forestry_staff_headers"]


# ── transitive_cascade: complete removal flips zone to DEFICIT ───────────
def test_complete_removal_retires_tree_and_flips_zone_deficit(api):
    """PRD §3.6: "When the `work_type` is `REMOVAL` or `EMERGENCY_REMOVAL`, the subject
    tree's `health_status` is set to `REMOVED`, which in turn recomputes the owning zone's
    `live_canopy_sqm`, `current_canopy_pct`, `canopy_status`, `tree_count`, and
    `high_risk_tree_count`."
    PRD §2.9: "The `canopy_status` is `MEETS` when `current_canopy_pct` is greater than or
    equal to the zone's `target_canopy_pct`, and `DEFICIT` otherwise".

    Design: Difficulty/transitive_cascade/workorder_complete_removes_tree_flips_zone_deficit
    """
    ctx = setup_started_removal_work_order()
    validate_success(
        api.complete_work_order(ctx["work_order"]["id"],
                                make_contractor_headers(ctx["contractor"]["id"])), 200)
    tree = validate_success(api.get_tree(ctx["tree"]["id"], ADMIN), 200)
    assert tree["health_status"] == "REMOVED"
    zone = validate_success(api.get_zone(ctx["zone"]["id"], ADMIN), 200)
    assert zone["live_canopy_sqm"] == pytest.approx(0, abs=0.005)
    assert zone["current_canopy_pct"] == pytest.approx(0.00, abs=0.005)
    assert zone["canopy_status"] == "DEFICIT"


def test_complete_removal_closes_authorizing_permit(api):
    """PRD §3.6: "When the work order carries a non-null `permit_id`, completion transitions
    that permit `ISSUED → CLOSED` and subtracts its `mitigation_fee_cents` from the
    outstanding mitigation total."

    Design: Difficulty/transitive_cascade/workorder_complete_removes_tree_flips_zone_deficit
    """
    ctx = setup_started_removal_work_order()
    validate_success(
        api.complete_work_order(ctx["work_order"]["id"],
                                make_contractor_headers(ctx["contractor"]["id"])), 200)
    permit = validate_success(api.get_permit(ctx["permit"]["id"], ADMIN), 200)
    assert permit["status"] == "CLOSED"


# ── cross_entity_state_dependency: start requires VALID dig ticket ───────
def test_start_with_requested_dig_ticket_rejected(api):
    """PRD §3.6: "The server first requires that some dig ticket for this work order be
    `VALID` and in-window — its window must contain the clock, meaning `valid_from` at or
    before now and now strictly before `valid_to`; if no such ticket exists the start fails
    with `ERR_DIG_TICKET_INVALID` (409)."

    Design: Difficulty/cross_entity_state_dependency/workorder_start_requires_valid_dig_ticket
    """
    ctx = setup_emergency_work_order()
    new_dig_ticket(ctx["work_order"]["id"], ctx["contractor"]["id"],
                   ticket_number="811-1",
                   valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-02T00:00:00Z")
    # Ticket is still REQUESTED (never marked VALID).
    res = api.start_work_order(ctx["work_order"]["id"],
                               make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(res, "ERR_DIG_TICKET_INVALID", expected_status=409)


def test_start_succeeds_with_valid_in_window_dig_ticket(api):
    """PRD §3.6: "A `ForestryAdmin` records 811 utility clearance, moving the ticket
    `REQUESTED → VALID`."
    PRD §3.6: "The assigned `Contractor` **starts** the work order (`CREATED →
    IN_PROGRESS`)."

    Design: Difficulty/cross_entity_state_dependency/workorder_start_requires_valid_dig_ticket
    """
    ctx = setup_emergency_work_order()
    dt = new_dig_ticket(ctx["work_order"]["id"], ctx["contractor"]["id"],
                        ticket_number="811-1",
                        valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-02T00:00:00Z")
    mark_valid(dt["id"])  # ticket now VALID; default clock 2026-03-01 is in-window
    res = api.start_work_order(ctx["work_order"]["id"],
                               make_contractor_headers(ctx["contractor"]["id"]))
    started = validate_success(res, 200)
    assert started["status"] == "IN_PROGRESS"


# ── resource_temporal_overlap: contractor double-booking (half-open) ─────
def test_contractor_overlapping_window_rejected(api):
    """PRD §3.6: "the new work order's half-open window from `scheduled_start` up to
    `scheduled_end` must not overlap the window of any other work order for the same
    contractor that is currently in `CREATED` or `IN_PROGRESS`."
    PRD §3.6: "a genuine overlap is rejected with `ERR_CONTRACTOR_DOUBLE_BOOKED` (409)."

    Design: Difficulty/resource_temporal_overlap/contractor_double_booking_half_open_adjacency_ok
    """
    ctx = setup_emergency_context()
    new_work_order(ctx["tree"]["id"], ctx["contractor"]["id"], "EMERGENCY_REMOVAL",
                   "2026-03-01T08:00:00Z", "2026-03-01T10:00:00Z")
    res = api.create_work_order(
        create_work_order_payload(ctx["tree"]["id"], ctx["contractor"]["id"],
                                  "EMERGENCY_REMOVAL",
                                  "2026-03-01T09:00:00Z", "2026-03-01T11:00:00Z"), STAFF)
    validate_error(res, "ERR_CONTRACTOR_DOUBLE_BOOKED", expected_status=409)


def test_contractor_adjacent_window_accepted(api):
    """PRD §3.6: "Because the intervals are half-open, two windows that merely touch at an
    endpoint — one ending exactly where the next begins — do not overlap".

    Design: Difficulty/resource_temporal_overlap/contractor_double_booking_half_open_adjacency_ok
    """
    ctx = setup_emergency_context()
    new_work_order(ctx["tree"]["id"], ctx["contractor"]["id"], "EMERGENCY_REMOVAL",
                   "2026-03-01T08:00:00Z", "2026-03-01T10:00:00Z")
    res = api.create_work_order(
        create_work_order_payload(ctx["tree"]["id"], ctx["contractor"]["id"],
                                  "EMERGENCY_REMOVAL",
                                  "2026-03-01T10:00:00Z", "2026-03-01T12:00:00Z"), STAFF)
    wo3 = validate_success(res, 201)
    assert wo3["status"] == "CREATED"


# ── resource_temporal_overlap: storm zone overlap (closed interval) ──────
def test_storm_touching_endpoint_conflicts(api):
    """PRD §3.7: "Two active storm events may not overlap on the same zone, and because the
    interval is closed, two windows that touch at an endpoint do overlap — an overlapping
    declaration on a zone already under an `ACTIVE` event is rejected with
    `ERR_STORM_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/storm_event_zone_overlap_closed_interval_touch_conflicts
    """
    zone = new_zone()
    new_storm(zone["id"], severity="MAJOR",
              window_start="2026-05-01T00:00:00Z", window_end="2026-06-01T00:00:00Z")
    res = api.create_storm_event(
        create_storm_event_payload(zone["id"], severity="MINOR",
                                   window_start="2026-06-01T00:00:00Z",
                                   window_end="2026-07-01T00:00:00Z"), ADMIN)
    validate_error(res, "ERR_STORM_OVERLAP", expected_status=409)


def test_storm_disjoint_window_accepted(api):
    """PRD §3.7: "Two active storm events may not overlap on the same zone, and because the
    interval is closed, two windows that touch at an endpoint do overlap — an overlapping
    declaration on a zone already under an `ACTIVE` event is rejected with
    `ERR_STORM_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/storm_event_zone_overlap_closed_interval_touch_conflicts
    """
    zone = new_zone()
    new_storm(zone["id"], severity="MAJOR",
              window_start="2026-05-01T00:00:00Z", window_end="2026-06-01T00:00:00Z")
    # Starts strictly after the first window closes -> no overlap.
    res = api.create_storm_event(
        create_storm_event_payload(zone["id"], severity="MINOR",
                                   window_start="2026-06-02T00:00:00Z",
                                   window_end="2026-07-01T00:00:00Z"), ADMIN)
    accepted = validate_success(res, 201)
    assert accepted["status"] == "ACTIVE"


# ── priority_pair_validation_conflict: start safety vs referential ───────
def test_start_dig_safety_outranks_expired_license(api):
    """PRD §3.6: "the dig-ticket safety check outranks the license referential check."
    PRD §3.6: "The server first requires that some dig ticket for this work order be
    `VALID` and in-window — its window must contain the clock, meaning `valid_from` at or
    before now and now strictly before `valid_to`; if no such ticket exists the start fails
    with `ERR_DIG_TICKET_INVALID` (409)."

    Design: Difficulty/priority_pair_validation_conflict/workorder_start_safety_outranks_referential
    """
    ctx = setup_emergency_work_order(
        contractor_overrides={"name": "Expired Co", "license_number": "L-2",
                              "license_expiry": "2026-02-01T00:00:00Z",
                              "is_certified_arborist": False})
    # No dig ticket at all AND an expired license: safety check must win.
    res = api.start_work_order(ctx["work_order"]["id"],
                               make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(res, "ERR_DIG_TICKET_INVALID", expected_status=409)


def test_start_expired_license_reported_once_dig_ticket_valid(api):
    """PRD §3.6: "Only once a valid in-window ticket is confirmed does the server require
    the contractor to be `ACTIVE` with an unexpired license — the logical clock strictly
    before `license_expiry` — failing with `ERR_CONTRACTOR_LICENSE_EXPIRED` (422) if the
    license has expired."

    Design: Difficulty/priority_pair_validation_conflict/workorder_start_safety_outranks_referential
    """
    ctx = setup_emergency_work_order(
        contractor_overrides={"name": "Expired Co", "license_number": "L-2",
                              "license_expiry": "2026-02-01T00:00:00Z",
                              "is_certified_arborist": False})
    dt = new_dig_ticket(ctx["work_order"]["id"], ctx["contractor"]["id"],
                        ticket_number="811-2",
                        valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-02T00:00:00Z")
    mark_valid(dt["id"])  # dig safety now passes at the default clock; license is expired
    res = api.start_work_order(ctx["work_order"]["id"],
                               make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(res, "ERR_CONTRACTOR_LICENSE_EXPIRED", expected_status=422)


# ── Corner: dig-ticket & work-order validations ──────────────────────────
def test_mark_valid_twice_rejected(api):
    """PRD §3.6: "A `ForestryAdmin` records 811 utility clearance, moving the ticket
    `REQUESTED → VALID`."
    PRD §2.5: "Only after all of that does the server evaluate state-machine legality
    (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/mark_valid_twice_rejects_invalid_state
    """
    ctx = setup_emergency_work_order()
    dt = new_dig_ticket(ctx["work_order"]["id"], ctx["contractor"]["id"],
                        ticket_number="811-1",
                        valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-02T00:00:00Z")
    mark_valid(dt["id"])
    res = api.mark_valid_dig_ticket(dt["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dig_ticket_window_invalid_rejected(api):
    """PRD §3.6: "The lawful dig window is half-open: `valid_from` is inclusive, `valid_to`
    is exclusive and must be strictly after `valid_from`, otherwise the create is rejected
    with `ERR_DIG_WINDOW_INVALID` (422)."

    Design: Corner/validations/dig_ticket_window_invalid_rejected
    """
    ctx = setup_emergency_work_order()
    res = api.create_dig_ticket(
        ctx["work_order"]["id"],
        create_dig_ticket_payload(ticket_number="811-x",
                                  valid_from="2026-03-02T00:00:00Z",
                                  valid_to="2026-03-01T00:00:00Z"),
        make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(res, "ERR_DIG_WINDOW_INVALID", expected_status=422)


def test_work_order_on_unissued_permit_rejected(api):
    """PRD §3.6: "A `REMOVAL` or `PRUNING` work order requires its `permit_id` to reference
    a permit in `ISSUED`; a permit in any other state causes `ERR_PERMIT_NOT_ISSUED`
    (409)."

    Design: Corner/validations/work_order_on_unissued_permit_rejects_permit_not_issued
    """
    ctx = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    contractor = new_contractor()
    res = api.create_work_order(
        create_work_order_payload(ctx["tree"]["id"], contractor["id"], "REMOVAL",
                                  "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
                                  permit_id=ctx["permit"]["id"]), STAFF)
    validate_error(res, "ERR_PERMIT_NOT_ISSUED", expected_status=409)


def test_emergency_work_order_without_storm_rejected(api):
    """PRD §3.6: "An `EMERGENCY_REMOVAL` work order instead requires `permit_id` to be null
    and an `ACTIVE` storm event covering the tree's zone at the current clock; absent that
    declaration the create is rejected with `ERR_EMERGENCY_NOT_DECLARED` (422)."

    Design: Corner/validations/emergency_work_order_without_storm_rejects
    """
    zone, species, tree = setup_tree(dbh=20.0)
    contractor = new_contractor()
    res = api.create_work_order(
        create_work_order_payload(tree["id"], contractor["id"], "EMERGENCY_REMOVAL",
                                  "2026-03-01T08:00:00Z", "2026-03-01T10:00:00Z"), STAFF)
    validate_error(res, "ERR_EMERGENCY_NOT_DECLARED", expected_status=422)
