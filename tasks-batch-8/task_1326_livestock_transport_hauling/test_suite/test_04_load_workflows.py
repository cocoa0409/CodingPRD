"""Load lifecycle: finalize/reopen, assign/unassign, depart, holds, cancel.

Covers PRD §3.4 (finalize/reopen), §3.5 (assign, depart gates, weather holds,
rest/unload, arrive, cancel).
"""
from test_helpers import (
    TEST_USERS,
    assert_ts_eq,
    create_driver_payload,
    create_weather_hold_payload,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    allocate_all,
    assign_driver,
    attach_and_verify_paperwork,
    create_driver,
    create_load,
    create_shipper,
    create_trailer,
    get_load,
    get_trailer,
    plan_load,
    set_clock,
    setup_assigned_load,
    setup_delivered_load,
    setup_in_transit_load,
    setup_planned_load,
)

DISP = TEST_USERS["dispatcher_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestFinalizeReopenCycle:
    def test_finalize_plan_from_planned_rejected(self, api):
        """PRD §3.4: "The transition enforces four checks in order: the load is
        `DRAFT` (`ERR_LOAD_NOT_DRAFT`); every `ACTIVE` allocation belongs to
        compartments of a single trailer (`ERR_MIXED_TRAILER_ALLOCATIONS`,
        HTTP 422); at least one `ACTIVE` allocation exists and the allocated
        totals equal the declared totals — `allocated_head_count` must equal
        `declared_head_count` and `allocated_weight_lb` must equal
        `declared_weight_lb` (`ERR_ALLOCATION_TOTAL_MISMATCH`, HTTP 422); and
        the load's `allocated_weight_lb` must not exceed the trailer's
        `max_gross_weight_lb` (`ERR_GVWR_EXCEEDED`, HTTP 422)."

        Design: Corner/state_machines/finalize_plan_from_planned_rejected
        """
        ctx = setup_planned_load()
        resp = api.finalize_plan(ctx["load"]["id"], DISP)
        validate_error(resp, E.ERR_LOAD_NOT_DRAFT)
        assert get_load(ctx["load"]["id"])["status"] == "PLANNED"

    def test_reopen_plan_releases_allocations_and_returns_to_draft(self, api):
        """PRD §3.4: "Reopening reverses finalization: a `Dispatcher` may move a
        `PLANNED` load back to `DRAFT` (any other state fails with
        `ERR_LOAD_NOT_PLANNED`, HTTP 409). Every `ACTIVE` allocation is released
        with `release_reason` `REPLANNED` and compartment occupancy recomputed,
        the load's `trailer_id` is cleared to null, and the load `version`
        increments by 1."

        Design: Corner/state_machines/reopen_plan_releases_allocations_and_returns_to_draft
        """
        ctx = setup_planned_load()
        reopened = validate_success(api.reopen_plan(ctx["load"]["id"], DISP), 200)
        assert reopened["status"] == "DRAFT"
        assert reopened["trailer_id"] is None

        allocs, _ = validate_paginated(
            api.list_load_allocations(ctx["load"]["id"], ADMIN))
        assert len(allocs) == 1
        assert allocs[0]["status"] == "RELEASED"
        assert allocs[0]["release_reason"] == "REPLANNED"

        comps, _ = validate_paginated(
            api.list_compartments(ctx["trailer"]["id"], ADMIN))
        assert comps[0]["occupied_head_count"] == 0
        assert comps[0]["occupied_weight_lb"] == 0


class TestAssignUnassign:
    def test_unassign_driver_reverts_to_paperwork_verified(self, api):
        """PRD §3.5: "Unassigning compensates an assignment: a `Dispatcher`
        moves an `ASSIGNED` load back to `PAPERWORK_VERIFIED` (any other state
        fails with `ERR_LOAD_NOT_ASSIGNED`). The load's `driver_id` is cleared
        to null, the driver `version` increments by 1, the load `version`
        increments by 1, and the trailer's `reserved_until` is recomputed."

        Design: Corner/state_machines/unassign_driver_reverts_to_paperwork_verified
        """
        ctx = setup_assigned_load()
        unassigned = validate_success(
            api.unassign_driver(ctx["load"]["id"], DISP), 200)
        assert unassigned["status"] == "PAPERWORK_VERIFIED"
        assert unassigned["driver_id"] is None
        trailer = get_trailer(ctx["trailer"]["id"])
        assert trailer["reserved_until"] is None


class TestDepartGates:
    def test_depart_from_weather_hold_rejected(self, api):
        """PRD §3.5: "the load is `ASSIGNED` (`ERR_LOAD_NOT_ASSIGNED`)"

        Design: Corner/state_machines/depart_from_weather_hold_rejected
        """
        ctx = setup_assigned_load()
        hold = validate_success(
            api.create_weather_hold(
                ctx["load"]["id"],
                create_weather_hold_payload(hold_type="HEAT", temperature_f=97),
                DISP), 201)
        assert hold["status"] == "ACTIVE"

        resp = api.depart(ctx["load"]["id"], {"origin_temperature_f": 70},
                          make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_LOAD_NOT_ASSIGNED)
        assert get_load(ctx["load"]["id"])["status"] == "WEATHER_HOLD"

    def test_depart_other_drivers_load_forbidden(self, api):
        """PRD §3.5: "Departure belongs to the assigned driver: the caller's
        `X-User-ID` must equal the load's `driver_id`
        (`ERR_OWNERSHIP_MISMATCH`)."
        PRD §2.1: "Ownership rule for the `Driver` role: a driver may append
        duty events only to their own record (the path driver id must equal
        `X-User-ID`), and may perform depart, arrive, rest-unload,
        resume-transit, weather-hold placement and release, and welfare-incident
        reporting only on a load whose `driver_id` equals `X-User-ID`."

        Design: Corner/validations/depart_other_drivers_load_forbidden
        """
        ctx = setup_assigned_load()
        other = validate_success(
            api.create_driver(create_driver_payload(), ADMIN), 201)
        resp = api.depart(ctx["load"]["id"], {"origin_temperature_f": 70},
                          make_driver_headers(other["id"]))
        validate_error(resp, E.ERR_OWNERSHIP_MISMATCH)
        assert get_load(ctx["load"]["id"])["status"] == "ASSIGNED"


class TestArriveGates:
    def test_arrive_from_assigned_rejected(self, api):
        """PRD §3.5: "Arrival moves `IN_TRANSIT → ARRIVED` under the assigned
        driver (ownership first, then the `ERR_LOAD_NOT_IN_TRANSIT` state
        check)."

        Design: Corner/state_machines/arrive_from_assigned_rejected
        """
        ctx = setup_assigned_load()
        resp = api.arrive(ctx["load"]["id"],
                          make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_LOAD_NOT_IN_TRANSIT)
        assert get_load(ctx["load"]["id"])["status"] == "ASSIGNED"


class TestResumeGates:
    def test_resume_transit_requires_rest_unload_state(self, api):
        """PRD §3.5: "Resuming transit moves `REST_UNLOAD → IN_TRANSIT` (any
        other state fails with `ERR_LOAD_NOT_REST_UNLOAD`) and is allowed only
        once at least 300 minutes (five hours) have elapsed since
        `rest_unload_started_at` — exactly 300 minutes qualifies, anything less
        fails with `ERR_INSUFFICIENT_REST_UNLOAD` (HTTP 422)."

        Design: Corner/state_machines/resume_transit_requires_rest_unload_state
        """
        ctx = setup_in_transit_load()
        resp = api.resume_transit(ctx["load"]["id"],
                                  make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_LOAD_NOT_REST_UNLOAD)
        assert get_load(ctx["load"]["id"])["status"] == "IN_TRANSIT"


class TestWeatherHoldPlacement:
    def test_weather_hold_on_draft_load_rejected(self, api, dispatcher_headers):
        """PRD §3.5: "A `Dispatcher`, or the assigned `Driver` on their own
        load, may place a hold while the load is `ASSIGNED` or `IN_TRANSIT`
        (any other state fails with `ERR_LOAD_NOT_HOLDABLE`, HTTP 409)."

        Design: Corner/errors/weather_hold_on_draft_load_rejected
        """
        shipper = create_shipper()
        load = create_load(shipper["id"])
        resp = api.create_weather_hold(
            load["id"],
            create_weather_hold_payload(hold_type="HEAT", temperature_f=100),
            dispatcher_headers)
        validate_error(resp, E.ERR_LOAD_NOT_HOLDABLE)


class TestTrailerWindowOverlap:
    """The window rule treats planned windows as closed intervals; touching
    endpoints conflict (PRD §3.5)."""

    def _verified_load_on(self, shipper_id, compartment_id, departure,
                          destination="Y"):
        """A 4-head / 8000 lb load allocated on the given compartment,
        finalized and paperwork-verified (PAPERWORK_VERIFIED)."""
        load = create_load(shipper_id, declared_head_count=4,
                           declared_weight_lb=8000,
                           planned_departure_at=departure,
                           planned_duration_hours=10,
                           destination=destination)
        allocate_all(load, [compartment_id])
        plan_load(load["id"])
        attach_and_verify_paperwork(get_load(load["id"]))
        return get_load(load["id"])

    def test_touching_window_endpoints_conflict_on_trailer(self, api):
        """PRD §3.5: "The window rule treats every load's planned window as the
        closed interval from `planned_departure_at` to `planned_departure_at`
        plus `planned_duration_hours`, inclusive at both ends. A conflict
        exists when any other load sharing the same `driver_id` or the same
        `trailer_id`, in any of `ASSIGNED`, `IN_TRANSIT`, `WEATHER_HOLD`,
        `REST_UNLOAD`, or `ARRIVED`, has a window that touches or overlaps this
        load's window. Touching endpoints conflict — one load's window
        beginning exactly when another's ends leaves no turnaround and is
        rejected."

        Design: Difficulty/resource_temporal_overlap/trailer_planned_windows_closed_interval_touching_conflicts
        """
        set_clock("2026-08-01T01:00:00Z")
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 20000},
            {"compartment_index": 2, "max_head_count": 10,
             "max_weight_lb": 20000}])
        c1, c2 = tt["compartments"][0]["id"], tt["compartments"][1]["id"]
        d1, d2, d3 = create_driver(), create_driver(), create_driver()

        set_clock("2026-08-01T07:00:00Z")
        # load A: window [2026-08-02T08:00, 2026-08-02T18:00], ASSIGNED
        load_a = self._verified_load_on(shipper["id"], c1,
                                        "2026-08-02T08:00:00Z")
        assign_driver(load_a["id"], d1["id"])

        # load B starts exactly when A's window ends: closed intervals touch
        load_b = self._verified_load_on(shipper["id"], c2,
                                        "2026-08-02T18:00:00Z",
                                        destination="Z")
        resp = api.assign_driver(
            load_b["id"],
            {"driver_id": d2["id"],
             "expected_driver_version": d2["version"]},
            DISP)
        validate_error(resp, E.ERR_TRAILER_WINDOW_OVERLAP)
        assert get_load(load_b["id"])["status"] == "PAPERWORK_VERIFIED"

        # one minute later there is a turnaround gap: C assigns cleanly
        load_c = self._verified_load_on(shipper["id"], c2,
                                        "2026-08-02T18:01:00Z",
                                        destination="Z")
        assign_driver(load_c["id"], d3["id"])
        assert get_load(load_c["id"])["status"] == "ASSIGNED"

        # reserved_until is the latest window end over the ASSIGNED loads A, C
        trailer = get_trailer(tt["trailer"]["id"])
        assert_ts_eq(trailer["reserved_until"], "2026-08-03T04:01:00Z",
                     "reserved_until")

    def test_touching_window_endpoints_conflict_on_driver(self, api):
        """PRD §3.5: "A conflict exists when any other load sharing the same
        `driver_id` or the same `trailer_id`, in any of `ASSIGNED`,
        `IN_TRANSIT`, `WEATHER_HOLD`, `REST_UNLOAD`, or `ARRIVED`, has a window
        that touches or overlaps this load's window. Touching endpoints
        conflict — one load's window beginning exactly when another's ends
        leaves no turnaround and is rejected."
        PRD §3.5: "and neither the driver nor the trailer has a conflicting
        planned window (`ERR_TRAILER_WINDOW_OVERLAP`, HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/trailer_planned_windows_closed_interval_touching_conflicts
        """
        set_clock("2026-08-01T01:00:00Z")
        shipper = create_shipper()
        t1 = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 20000}])
        t2 = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 20000}])
        d1 = create_driver()

        set_clock("2026-08-01T07:00:00Z")
        # load A on trailer 1, window [08:00, 18:00], assigned to driver d1
        load_a = self._verified_load_on(shipper["id"],
                                        t1["compartments"][0]["id"],
                                        "2026-08-02T08:00:00Z")
        assign_driver(load_a["id"], d1["id"])

        # a different trailer does not help: the shared driver's window touches
        load_d = self._verified_load_on(shipper["id"],
                                        t2["compartments"][0]["id"],
                                        "2026-08-02T18:00:00Z",
                                        destination="Z")
        d1_now = validate_success(api.get_driver(d1["id"], ADMIN))
        resp = api.assign_driver(
            load_d["id"],
            {"driver_id": d1["id"],
             "expected_driver_version": d1_now["version"]},
            DISP)
        validate_error(resp, E.ERR_TRAILER_WINDOW_OVERLAP)
        assert get_load(load_d["id"])["status"] == "PAPERWORK_VERIFIED"

        # one minute after A's window ends, the same driver assigns cleanly
        load_e = self._verified_load_on(shipper["id"],
                                        t2["compartments"][0]["id"],
                                        "2026-08-02T18:01:00Z",
                                        destination="Z")
        assign_driver(load_e["id"], d1["id"])
        assert get_load(load_e["id"])["status"] == "ASSIGNED"


class TestCancel:
    def test_cancel_from_delivered_rejected(self, api, dispatcher_headers):
        """PRD §3.5: "A `Dispatcher` may cancel a load from `DRAFT`, `PLANNED`,
        `PAPERWORK_VERIFIED`, or `ASSIGNED` — from any other state the attempt
        fails with `ERR_LOAD_NOT_CANCELLABLE` (HTTP 409)."

        Design: Corner/state_machines/cancel_from_delivered_rejected
        """
        ctx = setup_delivered_load()
        resp = api.cancel_load(ctx["load"]["id"], dispatcher_headers)
        validate_error(resp, E.ERR_LOAD_NOT_CANCELLABLE)
        assert get_load(ctx["load"]["id"])["status"] == "DELIVERED"

    def test_cancel_from_assigned_releases_without_dirtying_trailer(self, api):
        """PRD §3.5: "Cancellation releases every `ACTIVE` allocation with
        `release_reason` `CANCELLED` and recomputes compartment occupancy; it
        does not dirty the trailer. When the load was `ASSIGNED`, the driver is
        detached — `driver_id` set to null and the driver `version` incremented
        — and the trailer's `reserved_until` is recomputed. In all cases the
        load's `trailer_id` is cleared to null and the load `version` increments
        by 1, leaving the load terminally `CANCELLED`."

        Design: Corner/state_machines/cancel_from_assigned_releases_without_dirtying_trailer
        """
        ctx = setup_assigned_load()
        cancelled = validate_success(api.cancel_load(ctx["load"]["id"], DISP), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["driver_id"] is None
        assert cancelled["trailer_id"] is None

        allocs, _ = validate_paginated(
            api.list_load_allocations(ctx["load"]["id"], ADMIN))
        assert len(allocs) == 1
        assert allocs[0]["status"] == "RELEASED"
        assert allocs[0]["release_reason"] == "CANCELLED"

        comps, _ = validate_paginated(
            api.list_compartments(ctx["trailer"]["id"], ADMIN))
        assert comps[0]["occupied_head_count"] == 0

        trailer = get_trailer(ctx["trailer"]["id"])
        assert trailer["washout_status"] == "CLEAN"
        assert trailer["reserved_until"] is None
