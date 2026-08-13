"""Survey route lifecycle: planning, dispatch, start, complete, abort (PRD §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_survey_route,
    get_success_data,
    make_dispatch_coordinator_headers,
    make_field_technician_headers,
    make_org,
    make_route,
    make_segment,
    set_clock,
    setup_dispatched_route,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_assignment_payload,
    create_field_technician_payload,
    create_simple_personnel_payload,
    create_survey_route_payload,
)


class TestRouteCreation:
    def test_survey_route_created_in_planned_state(self, api):
        """PRD §3.4: "The route begins in `PLANNED`."
        PRD §2.4: "an integer starting at 1 on creation".

        Design: Corner/state_machines/survey_route_created_in_planned_state
        """
        ctx = make_org()
        data = validate_success(api.create_survey_route(
            create_survey_route_payload(route_code="R-INIT"), ctx["dc_h"],
        ), expected_status=201)
        assert_survey_route(data)
        assert data["status"] == "PLANNED"
        assert data["version"] == 1

    def test_route_segment_assignment_requires_existing_segment(self, api):
        """PRD §2.5: "every identifier referenced by the request — path-template
        identifiers resolved left to right, then identifiers referenced in the
        request body — must resolve to an existing entity, else `ERR_NOT_FOUND`."

        Design: Corner/entities/route_segment_assignment_requires_existing_segment
        """
        ctx = make_org()
        route = get_success_data(api.create_survey_route(
            create_survey_route_payload(route_code="R-FK"), ctx["dc_h"],
        ))
        resp = api.add_route_segment_assignment(
            route["id"],
            create_assignment_payload(NON_EXISTENT_UUID, sequence_index=1),
            ctx["dc_h"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRouteDispatch:
    def test_survey_route_dispatch_happy_path(self, api):
        """PRD §3.4: "Dispatching the route moves it `PLANNED → DISPATCHED`".
        PRD §2.4: "incremented by exactly 1 on every mutation of that resource".

        Design: Corner/state_machines/survey_route_dispatch_happy_path
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-DSP")
        data = validate_success(
            _build_and_dispatch(api, ctx, segment["id"], "R-DSP")
        )
        assert data["status"] == "DISPATCHED"
        assert data["version"] == 2

    def test_survey_route_dispatch_twice_rejected(self, api):
        """PRD §3.4: "Dispatching the route moves it `PLANNED → DISPATCHED` and is
        refused with `ERR_ROUTE_NOT_PLANNED` if the route is not `PLANNED`."

        Design: Corner/state_machines/survey_route_dispatch_twice_rejected
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-IDM")
        resp_dispatch = _build_and_dispatch(api, ctx, segment["id"], "R-IDM")
        route_id = get_success_data(resp_dispatch)["id"]
        resp = api.dispatch_route(route_id, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNED)

    def test_survey_route_dispatch_after_window_passed(self, api):
        """PRD §3.4: "with `ERR_ROUTE_WINDOW_PASSED` if the logical clock has
        already reached `scheduled_window_end`."

        Design: Corner/state_machines/survey_route_dispatch_after_window_passed
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-WP")
        route = get_success_data(api.create_survey_route(
            create_survey_route_payload(
                route_code="R-WP",
                scheduled_window_start="2026-07-01T00:00:00Z",
                scheduled_window_end="2026-07-31T23:59:59Z",
            ),
            ctx["dc_h"],
        ))
        get_success_data(api.add_route_segment_assignment(
            route["id"], create_assignment_payload(segment["id"]), ctx["dc_h"],
        ))
        resp = api.dispatch_route(route["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_PASSED)

    def test_route_dispatch_blocked_by_inactive_segment(self, api):
        """PRD §3.4: "with `ERR_ROUTE_INCLUDES_INACTIVE_SEGMENT` if any assignment
        references a segment whose `status` is not `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/route_dispatch_blocked_by_inactive_segment
        """
        ctx = make_org()
        seg1 = make_segment(ctx, segment_code="SEG-X1")
        seg2 = make_segment(ctx, segment_code="SEG-X2")
        route = get_success_data(api.create_survey_route(
            create_survey_route_payload(route_code="R-X"), ctx["dc_h"],
        ))
        get_success_data(api.add_route_segment_assignment(
            route["id"], create_assignment_payload(seg1["id"], sequence_index=1), ctx["dc_h"],
        ))
        get_success_data(api.add_route_segment_assignment(
            route["id"], create_assignment_payload(seg2["id"], sequence_index=2), ctx["dc_h"],
        ))
        get_success_data(api.out_of_service_segment(seg2["id"], ctx["ia_h"]))
        resp = api.dispatch_route(route["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_INCLUDES_INACTIVE_SEGMENT)

    def test_route_dispatch_unblocks_after_segment_returns_to_service(self, api):
        """PRD §3.4: "with `ERR_ROUTE_INCLUDES_INACTIVE_SEGMENT` if any assignment
        references a segment whose `status` is not `ACTIVE`."
        PRD §3.12: "Returning a segment to service (`OUT_OF_SERVICE → ACTIVE`)"
        restores dispatch eligibility once every assigned segment is `ACTIVE` again.

        Design: Difficulty/cross_entity_state_dependency/route_dispatch_blocked_by_inactive_segment
        """
        ctx = make_org()
        seg1 = make_segment(ctx, segment_code="SEG-X1")
        seg2 = make_segment(ctx, segment_code="SEG-X2")
        # Clean CP reading on seg2 (needed for later return-to-service).
        get_success_data(api.create_cp_reading(
            {
                "segment_id": seg2["id"],
                "test_point_id": "TP-1",
                "pipe_to_soil_potential_mv": -1000.0,
                "instant_off_potential_mv": -950.0,
            },
            ctx["ft_h"],
        ))
        route = get_success_data(api.create_survey_route(
            create_survey_route_payload(route_code="R-X"), ctx["dc_h"],
        ))
        get_success_data(api.add_route_segment_assignment(
            route["id"], create_assignment_payload(seg1["id"], sequence_index=1), ctx["dc_h"],
        ))
        get_success_data(api.add_route_segment_assignment(
            route["id"], create_assignment_payload(seg2["id"], sequence_index=2), ctx["dc_h"],
        ))
        get_success_data(api.out_of_service_segment(seg2["id"], ctx["ia_h"]))
        validate_error(api.dispatch_route(route["id"], ctx["dc_h"]),
                       ApiErrorId.ERR_ROUTE_INCLUDES_INACTIVE_SEGMENT)

        get_success_data(api.return_to_service_segment(seg2["id"], ctx["ia_h"]))
        data = validate_success(api.dispatch_route(route["id"], ctx["dc_h"]))
        assert data["status"] == "DISPATCHED"


class TestRouteStart:
    def test_survey_route_start_from_planned_rejected(self, api):
        """PRD §3.4: "A `FieldTechnician` then starts the route
        (`DISPATCHED → IN_PROGRESS`), which requires the route to be `DISPATCHED`
        (`ERR_ROUTE_NOT_DISPATCHED`)."

        Design: Corner/state_machines/survey_route_start_from_planned_rejected
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-STP")
        route = get_success_data(api.create_survey_route(
            create_survey_route_payload(route_code="R-STP"), ctx["dc_h"],
        ))
        get_success_data(api.add_route_segment_assignment(
            route["id"], create_assignment_payload(segment["id"]), ctx["dc_h"],
        ))
        resp = api.start_route(route["id"], ctx["ft_h"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED)

    def test_survey_route_start_unqualified_technician(self, api):
        """PRD §3.4: "requires the technician's `qualified_methods` to include the
        route's `survey_method` (`ERR_TECHNICIAN_NOT_QUALIFIED`)".

        Design: Corner/state_machines/survey_route_start_unqualified_technician
        """
        ctx = setup_dispatched_route(route_code="R-TQ")
        mobile_tech = get_success_data(api.create_field_technician(
            create_field_technician_payload(
                employee_code="FT-M", full_name="Tech Mobile", qualified_methods=["MOBILE"],
            ),
            ctx["ia_h"],
        ))
        resp = api.start_route(ctx["route"]["id"], make_field_technician_headers(mobile_tech["id"]))
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_QUALIFIED)

    def test_route_start_outside_scheduled_window_rejected(self, api):
        """PRD §3.4: "requires the logical clock to be within the half-open window
        from `scheduled_window_start` to `scheduled_window_end`
        (`ERR_OUTSIDE_SCHEDULED_WINDOW`)"."

        Design: Difficulty/resource_temporal_overlap/route_start_outside_scheduled_window_rejected
        """
        ctx = setup_dispatched_route(
            route_code="R-HO1",
            window=("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"),
        )
        set_clock(ctx, "2026-09-01T00:00:00Z")
        resp = api.start_route(ctx["route"]["id"], ctx["ft_h"])
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SCHEDULED_WINDOW)

    def test_route_start_at_window_start_inclusive_succeeds(self, api):
        """PRD §3.4: "an authorized window from `scheduled_window_start`
        (inclusive) to `scheduled_window_end` (exclusive)" — at exactly
        `scheduled_window_start` the start is inside the half-open window.

        Design: Difficulty/resource_temporal_overlap/route_start_outside_scheduled_window_rejected
        """
        ctx = setup_dispatched_route(
            route_code="R-HO2",
            window=("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"),
        )
        set_clock(ctx, "2026-08-01T00:00:00Z")
        data = validate_success(api.start_route(ctx["route"]["id"], ctx["ft_h"]))
        assert data["status"] == "IN_PROGRESS"


class TestRouteCompletionAndAbort:
    def test_survey_route_complete_from_dispatched_rejected(self, api):
        """PRD §3.4: "Completing the route (`IN_PROGRESS → COMPLETED`) requires
        `IN_PROGRESS` state (`ERR_ROUTE_NOT_IN_PROGRESS`)."

        Design: Corner/state_machines/survey_route_complete_from_dispatched_rejected
        """
        ctx = setup_dispatched_route(route_code="R-CD")
        resp = api.complete_route(ctx["route"]["id"], ctx["ft_h"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_IN_PROGRESS)

    def test_survey_route_complete_without_accepted_run(self, api):
        """PRD §3.4: "and at least one `ACCEPTED` survey run for the route
        (`ERR_NO_ACCEPTED_RUN`)."

        Design: Corner/state_machines/survey_route_complete_without_accepted_run
        """
        ctx = setup_dispatched_route(route_code="R-NAR")
        get_success_data(api.start_route(ctx["route"]["id"], ctx["ft_h"]))
        resp = api.complete_route(ctx["route"]["id"], ctx["ft_h"])
        validate_error(resp, ApiErrorId.ERR_NO_ACCEPTED_RUN)

    def test_survey_route_abort_in_progress_rejected(self, api):
        """PRD §3.4: "A route may be aborted from either `PLANNED` or `DISPATCHED`
        by a `DispatchCoordinator`, moving it to the terminal state `ABORTED`; a
        route in any other state is rejected with `ERR_ROUTE_NOT_ABORTABLE`."

        Design: Corner/state_machines/survey_route_abort_in_progress_rejected
        """
        ctx = setup_dispatched_route(route_code="R-ABI")
        get_success_data(api.start_route(ctx["route"]["id"], ctx["ft_h"]))
        resp = api.abort_route(ctx["route"]["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_ABORTABLE)

    def test_survey_route_abort_then_dispatch_locked(self, api):
        """PRD §3.4: "moving it to the terminal state `ABORTED`" — a subsequent
        dispatch on the aborted route is "refused with `ERR_ROUTE_NOT_PLANNED` if
        the route is not `PLANNED`."

        Design: Corner/state_machines/survey_route_abort_then_dispatch_locked
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-TERM")
        route = get_success_data(api.create_survey_route(
            create_survey_route_payload(route_code="R-TERM"), ctx["dc_h"],
        ))
        get_success_data(api.add_route_segment_assignment(
            route["id"], create_assignment_payload(segment["id"]), ctx["dc_h"],
        ))
        aborted = validate_success(api.abort_route(route["id"], ctx["dc_h"]))
        assert aborted["status"] == "ABORTED"
        resp = api.dispatch_route(route["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNED)


def _build_and_dispatch(api, ctx, segment_id, route_code):
    route = get_success_data(api.create_survey_route(
        create_survey_route_payload(route_code=route_code), ctx["dc_h"],
    ))
    get_success_data(api.add_route_segment_assignment(
        route["id"], create_assignment_payload(segment_id), ctx["dc_h"],
    ))
    return api.dispatch_route(route["id"], ctx["dc_h"])
