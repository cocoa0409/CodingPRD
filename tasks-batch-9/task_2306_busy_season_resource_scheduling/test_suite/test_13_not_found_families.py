"""Unknown identifiers: one code per entity, and the order they are resolved in."""

from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_assignment_payload,
    create_senior,
    create_workload_waiver_payload,
    make_engagement_staff_headers,
    set_clock,
    validate_error,
    validate_paginated,
)

_READ_BY_ID_ROUTES = [
    ("get_client", ApiErrorId.CLIENT_NOT_FOUND),
    ("get_staff_member", ApiErrorId.STAFF_MEMBER_NOT_FOUND),
    ("get_engagement", ApiErrorId.ENGAGEMENT_NOT_FOUND),
    ("get_engagement_phase", ApiErrorId.PHASE_NOT_FOUND),
    ("get_assignment", ApiErrorId.ASSIGNMENT_NOT_FOUND),
    ("get_independence_restriction", ApiErrorId.RESTRICTION_NOT_FOUND),
    ("get_review_capacity_window", ApiErrorId.REVIEW_WINDOW_NOT_FOUND),
    ("get_reschedule_plan", ApiErrorId.RESCHEDULE_PLAN_NOT_FOUND),
    ("get_workload_waiver", ApiErrorId.WAIVER_NOT_FOUND),
]


class TestPathIdentifiersHaveEntitySpecificCodes:
    """One unknown identifier, nine routes, nine different answers."""

    @pytest.mark.parametrize("reader, expected_error", _READ_BY_ID_ROUTES)
    def test_each_read_route_names_the_entity_it_could_not_find(
        self, api, admin_headers, reader, expected_error
    ):
        """The route decides which of the nine not-found codes comes back.

        PRD 2.10: "Each identifier has its own code, all of them HTTP 404:
        `ERR_CLIENT_NOT_FOUND` for a `client_id`, `ERR_STAFF_MEMBER_NOT_FOUND` for a
        `staff_member_id`, `engagement_partner_staff_id`, `review_owner_staff_id` or
        `reviewer_staff_id`, `ERR_ENGAGEMENT_NOT_FOUND` for an `engagement_id`,
        `ERR_PHASE_NOT_FOUND` for an `engagement_phase_id`,
        `ERR_ASSIGNMENT_NOT_FOUND` for an `assignment_id`,
        `ERR_RESTRICTION_NOT_FOUND` for an `independence_restriction_id`,
        `ERR_REVIEW_WINDOW_NOT_FOUND` for a `review_capacity_window_id`,
        `ERR_RESCHEDULE_PLAN_NOT_FOUND` for a `reschedule_plan_id`, and
        `ERR_WAIVER_NOT_FOUND` for a `workload_waiver_id`."

        PRD 2.9: "4. Every identifier in the URL path resolves to an existing row,
        validated left to right — the 404 family described in §2.10. All endpoints
        carrying a path identifier."

        Design: Corner/entities/unknown_ids_return_entity_specific_not_found
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        validate_error(
            getattr(api, reader)(NON_EXISTENT_UUID, admin_headers),
            expected_error.value,
            404,
        )

    def test_no_two_routes_share_a_generic_not_found_code(self, api, admin_headers):
        """Nine routes produce nine distinct identifiers, not one catch-all.

        PRD 2.10: "Path identifiers are resolved strictly left to right, and the
        first identifier that resolves to nothing determines the rejection — the
        server does not attempt to locate later segments."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/entities/unknown_ids_return_entity_specific_not_found
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        reported = []
        for reader, expected_error in _READ_BY_ID_ROUTES:
            error = validate_error(
                getattr(api, reader)(NON_EXISTENT_UUID, admin_headers),
                expected_error.value,
                404,
            )
            reported.append(error["error_id"])

        assert len(set(reported)) == len(_READ_BY_ID_ROUTES)


class TestBodyForeignKeysResolveInDeclaredOrder:
    """Two unknown references in one body: the first declared field is reported."""

    def test_a_booking_with_two_unknown_references_reports_the_phase(
        self, api, manager_headers
    ):
        """The phase is the first input field, so the staff member is never reached.

        PRD 2.10: "The same families apply to foreign keys carried in a request body,
        evaluated in the field order that operation declares."

        PRD 3.3: "A `SchedulingManager` books a named person onto a phase by
        supplying the `engagement_phase_id`, the `staff_member_id`, the half-open
        interval `start_date` and `end_date`, the `allocated_hours` for the booking
        (strictly greater than zero and no more than 400.00), and — only in the
        offshore case described in §3.5 — a `review_owner_staff_id`."

        PRD 2.9: "5. Every foreign-key identifier in the request body resolves to an
        existing row, validated in the order the fields are declared for that
        operation — the 404 family."

        Design: Corner/entities/assignment_create_with_two_unknown_body_ids_reports_phase_not_found
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        error = validate_error(
            api.create_assignment(
                create_assignment_payload(
                    NON_EXISTENT_UUID,
                    "11111111-2222-4333-8444-555555555555",
                    start_date="2026-08-03",
                    end_date="2026-08-10",
                    allocated_hours=20.00,
                ),
                manager_headers,
            ),
            ApiErrorId.PHASE_NOT_FOUND.value,
            404,
        )
        assert error["error_id"] != ApiErrorId.STAFF_MEMBER_NOT_FOUND.value

        _, meta = validate_paginated(api.list_assignments(manager_headers))
        assert meta["total_count"] == 0

    def test_an_overtime_request_for_no_engagement_never_reaches_the_monday_check(
        self, api
    ):
        """A real staff member, a fictional engagement, and a Tuesday that goes unnoticed.

        PRD 2.10: "The same families apply to foreign keys carried in a request body,
        evaluated in the field order that operation declares."

        PRD 3.4: "An `EngagementStaff` requests a **WorkloadWaiver** for themselves,
        naming their own `staff_member_id`, the `engagement_id` justifying the
        overtime, the `week_start_date` Monday the relief applies to, an
        `extra_hours_allowance` between 0.25 and 10.00 inclusive, and an optional
        `justification_note`."

        PRD 2.9: "9. `week_start_date` is a Monday — `ERR_NOT_WEEK_START`."

        Design: Corner/entities/workload_waiver_create_with_unknown_engagement_returns_not_found
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        senior = create_senior(api)

        error = validate_error(
            api.create_workload_waiver(
                create_workload_waiver_payload(
                    senior["id"],
                    NON_EXISTENT_UUID,
                    week_start_date="2026-08-04",
                    extra_hours_allowance=3.00,
                ),
                make_engagement_staff_headers(senior["id"]),
            ),
            ApiErrorId.ENGAGEMENT_NOT_FOUND.value,
            404,
        )
        assert error["error_id"] != ApiErrorId.NOT_WEEK_START.value
