"""Who may act: the identity gate, the role matrix, ownership and self-dealing."""

from __future__ import annotations

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_hours,
    create_assignment,
    create_assignment_payload,
    create_client,
    create_engagement,
    create_independence_restriction_payload,
    create_offshore_staff,
    create_partner,
    create_phase,
    create_reviewer,
    create_review_window,
    create_senior,
    create_staff_member_payload,
    create_time_entry_payload,
    create_workload_waiver_payload,
    headers_with_blank_role,
    headers_with_blank_user_id,
    make_engagement_partner_headers,
    make_engagement_staff_headers,
    make_headers,
    read_assignment,
    read_review_window,
    read_waiver,
    request_waiver,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _role_matrix_world(api):
    """A client, a partner, a senior, one phase and one pending overtime request."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    senior = create_senior(api)
    engagement = create_engagement(api, client["id"], partner["id"])
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=20.00,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
    )
    waiver = request_waiver(api, senior["id"], engagement["id"], "2026-08-03", 3.00)
    return {
        "client": client,
        "partner": partner,
        "senior": senior,
        "engagement": engagement,
        "phase": phase,
        "waiver": waiver,
    }


class TestIdentityGate:
    """The two headers are inspected before anything else about the request."""

    def test_a_blank_identity_header_is_refused_as_unauthenticated(self, api):
        """An empty user identifier and an empty role name both fail the same way.

        PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`,
        identifying the acting person, and `X-User-Role`, naming the capacity in
        which they act. If either header is absent or empty, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD 2.9: "1. Both auth headers present and non-empty —
        `ERR_UNAUTHENTICATED`. All endpoints."

        Design: Corner/rbac/missing_or_unknown_identity_headers_rejected_before_any_lookup
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        senior = create_senior(api)

        validate_error(
            api.get_staff_member(
                senior["id"], headers_with_blank_user_id("SchedulingManager")
            ),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.get_staff_member(senior["id"], headers_with_blank_role(senior["id"])),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

    def test_an_undeclared_role_is_refused_before_the_path_is_resolved(self, api):
        """A role nobody declared loses even when the identifier it names is a fiction.

        PRD 2.1: "If `X-User-Role` is not one of the five recognised role names, the
        rejection is `ERR_INVALID_ROLE` (HTTP 401)."

        PRD 2.1: "The five roles are `FirmAdmin`, `SchedulingManager`,
        `EngagementPartner`, `EngagementStaff` and `IndependenceOfficer`."

        PRD 2.9: "Validations are evaluated in a single, strictly ordered ladder.
        **The first check that fails determines the response, and no later check is
        evaluated.**"

        PRD 2.9: "4. Every identifier in the URL path resolves to an existing row,
        validated left to right — the 404 family described in §2.10. All endpoints
        carrying a path identifier."

        Design: Corner/rbac/missing_or_unknown_identity_headers_rejected_before_any_lookup
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        senior = create_senior(api)
        planner = make_headers("ResourcePlanner", senior["id"])

        validate_error(
            api.get_staff_member(senior["id"], planner),
            ApiErrorId.INVALID_ROLE.value,
            401,
        )

        error = validate_error(
            api.get_staff_member(NON_EXISTENT_UUID, planner),
            ApiErrorId.INVALID_ROLE.value,
            401,
        )
        assert error["error_id"] != ApiErrorId.STAFF_MEMBER_NOT_FOUND.value


class TestRolesAreRefusedWhatTheyDoNotOwn:
    """The role model is a matrix, not a hierarchy."""

    def test_five_calls_across_four_roles_are_all_unauthorised(
        self, api, admin_headers, manager_headers
    ):
        """Booking, provisioning, approving, restricting and reading the roster.

        PRD 2.1: "If the role is recognised but is not among the roles authorised for
        the endpoint being called (see the authorisation column of §4), the rejection
        is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD 2.1: "It owns reference data — clients, the staff roster, availability
        exceptions and review capacity windows — plus the logical clock. It never
        books work and never approves anything."

        PRD 2.1: "`SchedulingManager` is the resource management office: it builds
        the engagement inventory, books and reschedules work, and drives the staffing
        and phase lifecycles, but cannot approve overtime allowances, cannot review
        offshore work and cannot impose independence restrictions."

        PRD 2.1: "`EngagementStaff` is any staff member charging time: it logs hours
        against its own active bookings and requests overtime allowances for itself,
        and can never book, approve or review."

        Design: Corner/rbac/each_role_is_refused_the_other_roles_exclusive_operations
        """

        world = _role_matrix_world(api)

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    world["phase"]["id"],
                    world["senior"]["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=5.00,
                ),
                admin_headers,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Interloper", hourly_bill_rate=100.00
                ),
                manager_headers,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.approve_workload_waiver(world["waiver"]["id"], manager_headers),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_independence_restriction(
                create_independence_restriction_payload(
                    world["client"]["id"],
                    world["senior"]["id"],
                    restriction_type="EMPLOYMENT_NEGOTIATION",
                    effective_start_date="2026-08-01",
                    effective_end_date="2026-12-31",
                ),
                manager_headers,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.list_clients(make_engagement_staff_headers(world["senior"]["id"])),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

    def test_none_of_the_refused_calls_left_a_trace(self, api, manager_headers):
        """No booking, no third staff row, and the overtime request is still pending.

        PRD 2.1: "If the role is recognised but is not among the roles authorised for
        the endpoint being called (see the authorisation column of §4), the rejection
        is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD 3.4: "The request is created `REQUESTED` and changes no cap yet."

        Design: Corner/rbac/each_role_is_refused_the_other_roles_exclusive_operations
        """

        world = _role_matrix_world(api)
        validate_error(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Interloper", hourly_bill_rate=100.00
                ),
                manager_headers,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.approve_workload_waiver(world["waiver"]["id"], manager_headers),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        _, bookings_meta = validate_paginated(
            api.list_assignments(
                manager_headers, engagement_phase_id=world["phase"]["id"]
            )
        )
        assert bookings_meta["total_count"] == 0

        _, roster_meta = validate_paginated(api.list_staff_members(manager_headers))
        assert roster_meta["total_count"] == 2

        assert read_waiver(api, world["waiver"]["id"])["status"] == "REQUESTED"


class TestRolesPerformWhatTheyDoOwn:
    """The positive half of the matrix: each owner's own call succeeds."""

    def test_the_manager_books_and_the_signing_partner_grants_the_overtime(
        self, api, manager_headers
    ):
        """Two different roles, two different writes, both accepted.

        PRD 3.3: "A `SchedulingManager` books a named person onto a phase by
        supplying the `engagement_phase_id`, the `staff_member_id`, the half-open
        interval `start_date` and `end_date`, the `allocated_hours` for the booking
        (strictly greater than zero and no more than 400.00), and — only in the
        offshore case described in §3.5 — a `review_owner_staff_id`. The booking is
        created in `PROPOSED` with `fit_score` 0.00, because no selector ranked it."

        PRD 3.4: "Approval moves the allowance `REQUESTED → APPROVED`, stamps the
        deciding operator's `X-User-ID` onto `approved_by_user_id`, recomputes the
        beneficiary's `effective_weekly_cap_hours` and `daily_capacity_hours` for
        that ISO week so the extra hours become spendable, recomputes their
        `workload_status`, and increments the allowance's `version`."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
        """

        world = _role_matrix_world(api)

        booking = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    world["phase"]["id"],
                    world["senior"]["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=20.00,
                ),
                manager_headers,
            ),
            201,
        )
        assert booking["staffing_status"] == "PROPOSED"

        approved = validate_success(
            api.approve_workload_waiver(
                world["waiver"]["id"],
                make_engagement_partner_headers(world["partner"]["id"]),
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == world["partner"]["id"]

    def test_the_officer_imposes_the_bar_that_unwinds_the_managers_booking(
        self, api, manager_headers, officer_headers
    ):
        """The restriction lands, counts the booking it released, and is then lifted.

        PRD 3.8: "A newly created restriction takes `status` `ACTIVE` immediately,
        with `released_assignment_count` starting at 0."

        PRD 3.8: "The first hop releases: every booking with `staffing_status`
        `PROPOSED` or `CONFIRMED` whose `staff_member_id` is this person, whose phase
        belongs to an engagement for this client, and whose occupied dates share any
        date with the restriction's closed window, moves to `RELEASED`; the count of
        bookings released is recorded on the restriction as
        `released_assignment_count`."

        PRD 3.8: "The same officer may lift a restriction, moving it `ACTIVE →
        LIFTED` and incrementing its `version`; `LIFTED` is terminal, and lifting an
        already-lifted restriction is refused with `ERR_RESTRICTION_INVALID_STATE`."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
        """

        world = _role_matrix_world(api)
        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["senior"]["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=20.00,
        )

        restriction = validate_success(
            api.create_independence_restriction(
                create_independence_restriction_payload(
                    world["client"]["id"],
                    world["senior"]["id"],
                    restriction_type="FINANCIAL_INTEREST",
                    effective_start_date="2026-08-01",
                    effective_end_date="2026-12-31",
                ),
                officer_headers,
            ),
            201,
        )
        assert restriction["status"] == "ACTIVE"
        assert restriction["released_assignment_count"] == 1
        assert read_assignment(api, booking["id"])["staffing_status"] == "RELEASED"

        lifted = validate_success(
            api.lift_independence_restriction(restriction["id"], officer_headers)
        )
        assert lifted["status"] == "LIFTED"


class TestOwnershipIsCheckedBeforeLifecycle:
    """Acting for somebody else fails on ownership, not on the target's state."""

    def _two_of_everything(self, api):
        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        other_partner = create_partner(
            api,
            full_name="Nadia Bloom",
            industry_specialization="FINANCIAL_SERVICES",
            hourly_bill_rate=420.00,
        )
        senior = create_senior(api)
        other_senior = create_senior(
            api, full_name="Dana Kirsch", hourly_bill_rate=165.00
        )
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=20.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        booking = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=20.00,
        )
        return {
            "engagement": engagement,
            "phase": phase,
            "booking": booking,
            "partner": partner,
            "other_partner": other_partner,
            "senior": senior,
            "other_senior": other_senior,
        }

    def test_three_owner_bound_writes_all_report_the_ownership_failure(self, api):
        """Somebody else's booking, somebody else's engagement, somebody else's week.

        PRD 2.1: "For the entity-backed roles, acting on a resource that is not yours
        is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        PRD 2.1: "An `EngagementStaff` logging a time entry must present the
        `X-User-ID` that equals the target assignment's `staff_member_id`, and an
        `EngagementStaff` requesting an overtime allowance must present the
        `X-User-ID` that equals the `staff_member_id` in the request body."

        PRD 2.1: "An `EngagementPartner` clearing a client block or delivering an
        engagement must present the `X-User-ID` that equals that engagement's
        `engagement_partner_staff_id`, and the same comparison applies when an
        `EngagementPartner` approves or denies an overtime allowance, evaluated
        against the engagement named by the waiver's `engagement_id`."

        PRD 2.9: "10. Resource ownership for entity-backed roles per §2.1 —
        `ERR_NOT_RESOURCE_OWNER`."

        PRD 2.9: "11. The target row is in a state its requested transition allows,
        including terminal-state lockdown — the invalid-state family described in
        §2.10."

        Design: Corner/rbac/owner_bound_actions_reject_a_different_staff_member
        """

        world = self._two_of_everything(api)
        intruder = make_engagement_staff_headers(world["other_senior"]["id"])

        time_error = validate_error(
            api.create_time_entry(
                create_time_entry_payload(
                    world["booking"]["id"], work_date="2026-08-04", hours=4.00
                ),
                intruder,
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        assert time_error["error_id"] != ApiErrorId.ASSIGNMENT_INVALID_STATE.value

        clear_error = validate_error(
            api.clear_client_block(
                world["engagement"]["id"],
                make_engagement_partner_headers(world["other_partner"]["id"]),
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        assert clear_error["error_id"] != ApiErrorId.ENGAGEMENT_INVALID_STATE.value

        validate_error(
            api.create_workload_waiver(
                create_workload_waiver_payload(
                    world["senior"]["id"],
                    world["engagement"]["id"],
                    week_start_date="2026-08-03",
                    extra_hours_allowance=3.00,
                ),
                intruder,
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

    def test_the_refused_time_entry_was_never_written(self, api, manager_headers):
        """The booking still carries no logged line at all.

        PRD 2.1: "An `EngagementStaff` logging a time entry must present the
        `X-User-ID` that equals the target assignment's `staff_member_id`, and an
        `EngagementStaff` requesting an overtime allowance must present the
        `X-User-ID` that equals the `staff_member_id` in the request body."

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/rbac/owner_bound_actions_reject_a_different_staff_member
        """

        world = self._two_of_everything(api)
        validate_error(
            api.create_time_entry(
                create_time_entry_payload(
                    world["booking"]["id"], work_date="2026-08-04", hours=4.00
                ),
                make_engagement_staff_headers(world["other_senior"]["id"]),
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

        _, meta = validate_paginated(
            api.list_assignment_time_entries(world["booking"]["id"], manager_headers)
        )
        assert meta["total_count"] == 0


class TestNobodyReviewsTheirOwnWork:
    """The self-review collision is caught at booking time, above eligibility."""

    def _offshore_world(self, api):
        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        reviewer = create_reviewer(
            api,
            full_name="Mel Arbogast",
            base_weekly_cap_hours=40.00,
            hourly_bill_rate=260.00,
        )
        offshore = create_offshore_staff(
            api,
            full_name="Ravi Menon",
            level="SENIOR",
            base_weekly_cap_hours=40.00,
            hourly_bill_rate=90.00,
        )
        window = create_review_window(api, reviewer["id"], "2026-08-03", 10.00)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=20.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
            requires_cpa_licensed=False,
        )
        return {
            "reviewer": reviewer,
            "offshore": offshore,
            "window": window,
            "engagement": engagement,
            "phase": phase,
        }

    def test_nominating_yourself_as_your_own_reviewer_is_refused(self, api, manager_headers):
        """The collision is reported even though the nominee is also not review-capable.

        PRD 2.12: "**Segregation of duties.** The staff member executing a booking may
        never be the person who reviews it, and the beneficiary of an overtime
        allowance may never be the person who approves or denies it. Concretely: at
        booking time the nominated `review_owner_staff_id` must differ from the
        assigned `staff_member_id`; when a review is opened or accepted, the acting
        `X-User-ID` must differ from the booking's `staff_member_id`; and when an
        overtime allowance is approved or denied, the acting `X-User-ID` must differ
        from the allowance's `staff_member_id`. Any of these collisions is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        PRD 3.3: "A nominated `review_owner_staff_id` equal to the `staff_member_id`
        being booked is refused with `ERR_SEGREGATION_OF_DUTIES`."

        PRD 3.1: "From `level` and `service_center` the server derives
        `review_capable`, which is true exactly when the level is `MANAGER` or
        `PARTNER` **and** the service centre is `DOMESTIC`."

        Design: Corner/rbac/booking_where_the_review_owner_is_the_assigned_staff_member_rejected
        """

        world = self._offshore_world(api)

        error = validate_error(
            api.create_assignment(
                create_assignment_payload(
                    world["phase"]["id"],
                    world["offshore"]["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=10.00,
                    review_owner_staff_id=world["offshore"]["id"],
                ),
                manager_headers,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.REVIEW_OWNER_NOT_ELIGIBLE.value

    def test_the_same_booking_with_a_proper_reviewer_charges_two_review_hours(
        self, api, manager_headers
    ):
        """Ten offshore hours charge the two-hour minimum block, and only once.

        PRD 3.5: "For an `OFFSHORE_SHARED_SERVICE` booking the charge starts as
        one-fifth of `allocated_hours`, rounded to two decimals, but floored at a
        two-hour minimum review block: the base is the larger of those two figures."

        PRD 3.5: "Thereafter `committed_review_hours` is the sum, rounded to two
        decimals, of `review_hours_charged` over every booking bound to that window
        whose staffing dimension is `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED`
        — released bookings are excluded — and `remaining_review_hours` is
        `review_capacity_hours` minus that committed figure, rounded to two
        decimals."

        Design: Corner/rbac/booking_where_the_review_owner_is_the_assigned_staff_member_rejected
        """

        world = self._offshore_world(api)
        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    world["phase"]["id"],
                    world["offshore"]["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=10.00,
                    review_owner_staff_id=world["offshore"]["id"],
                ),
                manager_headers,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            409,
        )

        booking = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    world["phase"]["id"],
                    world["offshore"]["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=10.00,
                    review_owner_staff_id=world["reviewer"]["id"],
                ),
                manager_headers,
            ),
            201,
        )
        assert booking["review_owner_staff_id"] == world["reviewer"]["id"]
        assert_hours(booking["review_hours_charged"], 2.00)

        window_after = read_review_window(api, world["window"]["id"])
        assert_hours(window_after["committed_review_hours"], 2.00)


class TestNobodyApprovesTheirOwnOvertime:
    """Ownership at stage ten, self-dealing at stage sixteen, in that order."""

    def _partner_asking_for_himself(self, api):
        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        other_partner = create_partner(
            api,
            full_name="Nadia Bloom",
            industry_specialization="FINANCIAL_SERVICES",
            hourly_bill_rate=420.00,
        )
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        own_waiver = request_waiver(
            api, partner["id"], engagement["id"], "2026-08-03", 2.00
        )
        senior_waiver = request_waiver(
            api, senior["id"], engagement["id"], "2026-08-03", 3.00
        )
        return {
            "partner": partner,
            "other_partner": other_partner,
            "senior": senior,
            "engagement": engagement,
            "own_waiver": own_waiver,
            "senior_waiver": senior_waiver,
        }

    def test_the_beneficiary_partner_can_neither_approve_nor_deny_his_own_request(
        self, api
    ):
        """Both decisions are shut, and the outsider partner fails one rung earlier.

        PRD 2.12: "**Segregation of duties.** The staff member executing a booking may
        never be the person who reviews it, and the beneficiary of an overtime
        allowance may never be the person who approves or denies it."

        PRD 3.4: "Either decision requires the acting `X-User-ID` to be the
        engagement's `engagement_partner_staff_id` and to differ from the allowance's
        `staff_member_id`."

        PRD 2.9: "10. Resource ownership for entity-backed roles per §2.1 —
        `ERR_NOT_RESOURCE_OWNER`."

        PRD 2.9: "16. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`. This
        guards six operations: booking creation, reassignment, review opening, review
        acceptance, and overtime-allowance approval and denial."

        Design: Corner/rbac/partner_cannot_approve_the_waiver_written_for_himself
        """

        world = self._partner_asking_for_himself(api)
        beneficiary = make_engagement_partner_headers(world["partner"]["id"])

        validate_error(
            api.approve_workload_waiver(world["own_waiver"]["id"], beneficiary),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            409,
        )
        validate_error(
            api.deny_workload_waiver(world["own_waiver"]["id"], beneficiary),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            409,
        )

        outsider_error = validate_error(
            api.approve_workload_waiver(
                world["own_waiver"]["id"],
                make_engagement_partner_headers(world["other_partner"]["id"]),
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        assert outsider_error["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES.value

        assert read_waiver(api, world["own_waiver"]["id"])["status"] == "REQUESTED"

    def test_the_same_partner_may_approve_somebody_elses_request(self, api):
        """The legitimate path: a different beneficiary on the same engagement.

        PRD 3.4: "The engagement partner of the justifying engagement decides."

        PRD 3.4: "Approval moves the allowance `REQUESTED → APPROVED`, stamps the
        deciding operator's `X-User-ID` onto `approved_by_user_id`, recomputes the
        beneficiary's `effective_weekly_cap_hours` and `daily_capacity_hours` for
        that ISO week so the extra hours become spendable, recomputes their
        `workload_status`, and increments the allowance's `version`."

        Design: Corner/rbac/partner_cannot_approve_the_waiver_written_for_himself
        """

        world = self._partner_asking_for_himself(api)

        approved = validate_success(
            api.approve_workload_waiver(
                world["senior_waiver"]["id"],
                make_engagement_partner_headers(world["partner"]["id"]),
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == world["partner"]["id"]

        assert read_waiver(api, world["own_waiver"]["id"])["status"] == "REQUESTED"
