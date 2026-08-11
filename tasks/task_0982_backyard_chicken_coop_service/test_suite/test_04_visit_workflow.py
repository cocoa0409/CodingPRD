"""Service visit workflow: lifecycle states, reschedule loop, buffered tech
conflicts, household gates, fulfillment side effects, predator grade ladder,
listing pagination."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID, assert_same_instant,
    create_household, create_coop, create_visit, create_product,
    assign_visit, check_in_visit, complete_visit, create_order, place_order,
    set_logical_clock, make_customer_headers, make_service_tech_headers,
    install_coop, proof_coop_once,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestVisitCreation:
    def test_new_visit_starts_requested_with_null_technician(self, api):
        """PRD §3.5: "A new visit starts in `REQUESTED` status with
        `reschedule_count` at 0; its `coverage` is resolved per §3.3 into
        `SUBSCRIPTION_COVERED` or `BILLABLE` — with `subscription_id` set to the
        covering subscription when covered and left null otherwise — and its
        `provisional_price_cents` is computed immediately. The visit's
        `final_price_cents` and `completed_at` remain null until the visit
        actually completes, and `assigned_technician_id` remains null until a
        dispatcher assigns it."

        Design: Corner/state_machines/visit_created_initial_state_requested
        """
        household = create_household(name="H Init", address="26 Hen Ln")
        coop = create_coop(household, 4)
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
        assert visit["status"] == "REQUESTED"
        assert visit["assigned_technician_id"] is None
        assert visit["reschedule_count"] == 0

    def test_visit_scheduled_in_the_past_rejected(self, api):
        """PRD §3.5: "The window must be well-formed — `scheduled_end` strictly
        after `scheduled_start`, else `ERR_INVALID_TIME_RANGE` — and must not
        lie in the past: `scheduled_start` before the current logical clock
        time is rejected with `ERR_SCHEDULE_IN_PAST`."

        Design: Corner/validations/visit_scheduled_in_past_rejected
        """
        household = create_household(name="H Past", address="43 Hen Ln")
        coop = create_coop(household, 4)
        set_logical_clock("2026-06-01T00:00:00Z")
        res = api.create_service_visit(
            {"household_id": household["id"], "coop_site_id": coop["id"],
             "visit_type": "SETUP_INSTALL",
             "scheduled_start": "2026-05-20T09:00:00Z",
             "scheduled_end": "2026-05-20T11:00:00Z"},
            make_customer_headers(household["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SCHEDULE_IN_PAST)

    def test_get_unknown_visit_returns_not_found(self, api):
        """PRD §2.9: "Each resource type has its own not-found error:
        `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COOP_SITE_NOT_FOUND`,
        `ERR_VISIT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`,
        `ERR_STOP_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and
        `ERR_INVOICE_NOT_FOUND`."

        Design: Corner/entities/visit_get_not_found_returns_404
        """
        res = api.get_service_visit("11111111-2222-4333-8444-555555555555", DISPATCHER)
        validate_error(res, ApiErrorId.ERR_VISIT_NOT_FOUND)
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)

    def test_cancel_unknown_visit_returns_not_found(self, api):
        """PRD §2.9: "Resources are addressed by a flat URL structure under the
        API prefix; path parameters are validated for existence in left-to-right
        order, and the request is rejected immediately with the 404
        corresponding to the first identifier that does not match an existing
        resource."

        Design: Corner/validations/visit_cancel_nonexistent_returns_not_found
        """
        res = api.cancel_visit("11111111-2222-4333-8444-555555555555", DISPATCHER)
        validate_error(res, ApiErrorId.ERR_VISIT_NOT_FOUND)


class TestVisitCompletionRules:
    def test_complete_from_scheduled_rejected(self, api):
        """PRD §3.5: "Completion then moves the visit from `ON_SITE` to
        `COMPLETED` — completion from any other state yields
        `ERR_VISIT_NOT_ON_SITE`, and again only the assigned technician may
        perform it."
        PRD §3.5: "The visit's `final_price_cents` and `completed_at` remain
        null until the visit actually completes, and `assigned_technician_id`
        remains null until a dispatcher assigns it."

        Design: Corner/state_machines/visit_complete_from_scheduled_rejected
        """
        household = create_household(name="H Inv", address="27 Hen Ln")
        coop = create_coop(household, 4)
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
        assign_visit(visit["id"], "tech-1")

        res = api.complete_visit(
            visit["id"], {"observed_flock_size": 4, "actual_duration_minutes": 180},
            make_service_tech_headers("tech-1"))
        validate_error(res, ApiErrorId.ERR_VISIT_NOT_ON_SITE)

        after = validate_success(api.get_service_visit(visit["id"], DISPATCHER), 200)
        assert after["status"] == "SCHEDULED"
        assert after["final_price_cents"] is None


class TestRescheduleLoop:
    def _scheduled_install(self, api):
        household = create_household(name="H Cyc", address="4 Hen Ln")
        coop = create_coop(household, 4, site_label="east")
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
        assign_visit(visit["id"], "tech-1")
        return household, visit

    def test_reschedule_cycle_traversed_once(self, api):
        """PRD §3.5: "A reschedule request, available only in `SCHEDULED`
        (otherwise `ERR_VISIT_NOT_SCHEDULED`), moves the visit to
        `RESCHEDULE_REQUESTED` and increments `reschedule_count`."
        PRD §3.5: "The payload names the `technician_id` and may optionally
        carry replacement `scheduled_start` and `scheduled_end` values, in
        which case the visit's window is replaced."

        Design: Difficulty/non_linear_state_machine/visit_reschedule_cycle
        """
        household, visit = self._scheduled_install(api)
        customer = make_customer_headers(household["id"])

        rescheduled = validate_success(api.request_reschedule(visit["id"], customer), 200)
        assert rescheduled["status"] == "RESCHEDULE_REQUESTED"
        assert rescheduled["reschedule_count"] == 1

        reassigned = validate_success(api.assign_service_visit(
            visit["id"],
            {"technician_id": "tech-1",
             "scheduled_start": "2026-06-11T09:00:00Z",
             "scheduled_end": "2026-06-11T11:00:00Z"},
            DISPATCHER), 200)
        assert reassigned["status"] == "SCHEDULED", "fresh assignment from RESCHEDULE_REQUESTED"
        assert_same_instant(reassigned["scheduled_start"], "2026-06-11T09:00:00Z",
                            "scheduled_start override")

    def test_third_reschedule_request_rejected_at_limit(self, api):
        """PRD §3.5: "The loop is bounded: a visit whose `reschedule_count` has
        already reached 2 rejects further reschedule requests with
        `ERR_RESCHEDULE_LIMIT_REACHED`, and the only way forward is a fresh
        assignment, which accepts the visit from `RESCHEDULE_REQUESTED` exactly
        as from `REQUESTED`."

        Design: Difficulty/non_linear_state_machine/visit_reschedule_cycle
        """
        household, visit = self._scheduled_install(api)
        customer = make_customer_headers(household["id"])

        for day in ("11", "12"):
            validate_success(api.request_reschedule(visit["id"], customer), 200)
            validate_success(api.assign_service_visit(
                visit["id"],
                {"technician_id": "tech-1",
                 "scheduled_start": f"2026-06-{day}T09:00:00Z",
                 "scheduled_end": f"2026-06-{day}T11:00:00Z"},
                DISPATCHER), 200)

        current = validate_success(api.get_service_visit(visit["id"], DISPATCHER), 200)
        assert current["status"] == "SCHEDULED", "cycle traversed twice"
        assert current["reschedule_count"] == 2
        assert_same_instant(current["scheduled_start"], "2026-06-12T09:00:00Z",
                            "scheduled_start override")

        res = api.request_reschedule(visit["id"], customer)
        validate_error(res, ApiErrorId.ERR_RESCHEDULE_LIMIT_REACHED)


class TestTechnicianScheduleConflict:
    def _three_install_requests(self, api):
        household = create_household(name="H Ovl2", address="15 Hen Ln")
        coop = create_coop(household, 6)
        v1 = create_visit(household, coop, "SETUP_INSTALL",
                          "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
        assign_visit(v1["id"], "tech-5")
        v2 = create_visit(household, coop, "SETUP_INSTALL",
                          "2026-06-10T10:15:00Z", "2026-06-10T11:15:00Z")
        v3 = create_visit(household, coop, "SETUP_INSTALL",
                          "2026-06-10T10:30:00Z", "2026-06-10T11:30:00Z")
        return v1, v2, v3

    def test_assign_inside_thirty_minute_buffer_rejected(self, api):
        """PRD §3.5: "Before committing, the server checks the technician's
        buffered schedule: the technician's occupied set is their visits in
        `SCHEDULED` or `ON_SITE` status, and the new window conflicts with an
        existing one unless it starts at least 30 minutes after the existing
        window ends or ends at least 30 minutes before the existing window
        starts. Touching at exactly the 30-minute mark is allowed; one minute
        closer is a conflict and rejects the assignment with
        `ERR_TECH_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tech_visit_buffered_half_open_conflict
        """
        _, v2, _ = self._three_install_requests(api)
        # V1 occupies 09:00-10:00; buffered tail is 10:30. V2 starts 10:15 -> conflict.
        res = api.assign_service_visit(v2["id"], {"technician_id": "tech-5"}, DISPATCHER)
        validate_error(res, ApiErrorId.ERR_TECH_SCHEDULE_CONFLICT)
        after = validate_success(api.get_service_visit(v2["id"], DISPATCHER), 200)
        assert after["status"] == "REQUESTED"

    def test_assign_exactly_at_buffer_boundary_allowed(self, api):
        """PRD §3.5: "Touching at exactly the 30-minute mark is allowed; one
        minute closer is a conflict and rejects the assignment with
        `ERR_TECH_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tech_visit_buffered_half_open_conflict
        """
        _, _, v3 = self._three_install_requests(api)
        # V1 ends 10:00; V3 starts exactly 10:30 == end + 30 minutes -> allowed.
        assigned = validate_success(
            api.assign_service_visit(v3["id"], {"technician_id": "tech-5"}, DISPATCHER), 200)
        assert assigned["status"] == "SCHEDULED"
        assert assigned["assigned_technician_id"] == "tech-5"


class TestCheckInHouseholdGate:
    def _suspended_household_with_scheduled_visit(self, api):
        household = create_household(name="H XDep2", address="13 Hen Ln")
        coop = create_coop(household, 6, site_label="raw")
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z")
        assert visit["coverage"] == "BILLABLE", "no subscription -> BILLABLE"
        assign_visit(visit["id"], "tech-1")
        validate_success(api.suspend_household(household["id"], BILLING), 200)
        return household, visit

    def test_check_in_rejected_while_household_suspended(self, api):
        """PRD §3.5: "The caller must be the recorded technician (`X-User-ID`
        equal to `assigned_technician_id`, else `ERR_NOT_ASSIGNED_TECH`), and
        the household must still be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`)."
        PRD §3.1: "Second — caused by that pause — every covered ServiceVisit
        of the subscription (coverage `SUBSCRIPTION_COVERED` with status
        `REQUESTED`, `SCHEDULED`, or `RESCHEDULE_REQUESTED`) is cancelled, and
        each cancellation releases its reservation by decrementing the
        subscription's `used_cleanings` or `used_health_checks` counter."

        Design: Difficulty/cross_entity_state_dependency/visit_checkin_requires_household_active
        """
        household, visit = self._suspended_household_with_scheduled_visit(api)

        res = api.check_in_visit(visit["id"], make_service_tech_headers("tech-1"))
        validate_error(res, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

        after = validate_success(api.get_service_visit(visit["id"], DISPATCHER), 200)
        assert after["status"] == "SCHEDULED", (
            "BILLABLE visit is not cascade-cancelled by suspension; the gate rejects the check-in")

    def test_check_in_succeeds_after_reinstatement(self, api):
        """PRD §3.1: "A `BillingAdmin` may reinstate a `SUSPENDED` household
        back to `ACTIVE`; attempting it on a household that is not `SUSPENDED`
        yields `ERR_INVALID_STATE`."
        PRD §3.5: "On the day, the assigned `ServiceTech` checks the visit in —
        `SCHEDULED` to `ON_SITE`."

        Design: Difficulty/cross_entity_state_dependency/visit_checkin_requires_household_active
        """
        household, visit = self._suspended_household_with_scheduled_visit(api)

        validate_success(api.reinstate_household(household["id"], BILLING), 200)
        checked_in = validate_success(
            api.check_in_visit(visit["id"], make_service_tech_headers("tech-1")), 200)
        assert checked_in["status"] == "ON_SITE"


class TestCompletionSideEffects:
    def test_linked_placed_order_fulfilled_on_completion(self, api):
        """PRD §3.5: "Completion also fires the coop transitions of §3.4 and
        flips any `PLACED` supply order whose `fulfillment_visit_id` is this
        visit to `FULFILLED`."
        PRD §3.8: "When the fulfillment visit completes, the order becomes
        `FULFILLED`, its terminal state."
        PRD §3.4: "When a `SETUP_INSTALL` visit completes, the coop moves from
        `PLANNED` to `INSTALLED`."

        Design: Corner/state_machines/order_auto_fulfilled_on_visit_completion
        """
        household = create_household(name="H AF", address="30 Hen Ln")
        coop = create_coop(household, 4)
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z")
        assign_visit(visit["id"], "tech-1")
        create_product(sku="FEED-C", name="Grower Feed", unit_price_cents=700)
        order = create_order(household, [("FEED-C", 2)], fulfillment_visit_id=visit["id"])
        order = place_order(order["id"], household)

        check_in_visit(visit["id"], "tech-1")
        completed = complete_visit(visit["id"], "tech-1",
                                   observed_flock_size=4, actual_duration_minutes=180)
        assert completed["status"] == "COMPLETED"

        order_after = validate_success(api.get_supply_order(order["id"], DISPATCHER), 200)
        assert order_after["status"] == "FULFILLED"
        coop_after = validate_success(api.get_coop_site(coop["id"], DISPATCHER), 200)
        assert coop_after["status"] == "INSTALLED"

    def test_predator_grade_climbs_one_rung_per_proofing(self, api):
        """PRD §3.4: "When a `PREDATOR_PROOFING` visit completes on an installed
        coop, the predator grade climbs one rung — `NONE` to `B`, `B` to `A`,
        and `A` to `A` (further proofing of a top-grade coop changes nothing
        but remains permitted)."

        Design: Corner/endpoints/predator_proofing_grade_ladder
        """
        household = create_household(name="H Grade", address="49 Hen Ln")
        coop = create_coop(household, 6)
        install_coop(household, coop, date="2026-06-01")

        proof_coop_once(household, coop, date="2026-06-02")
        after_1 = validate_success(api.get_coop_site(coop["id"], DISPATCHER), 200)
        assert after_1["predator_grade"] == "B"

        proof_coop_once(household, coop, date="2026-06-03")
        after_2 = validate_success(api.get_coop_site(coop["id"], DISPATCHER), 200)
        assert after_2["predator_grade"] == "A"

        proof_coop_once(household, coop, date="2026-06-04")
        after_3 = validate_success(api.get_coop_site(coop["id"], DISPATCHER), 200)
        assert after_3["predator_grade"] == "A", "ladder saturated at A"


class TestVisitListing:
    def _three_visits(self, api):
        household = create_household(name="H Page", address="24 Hen Ln")
        coop = create_coop(household, 4)
        visits = [
            create_visit(household, coop, "SETUP_INSTALL",
                         f"2026-06-{day}T09:00:00Z", f"2026-06-{day}T11:00:00Z")
            for day in ("10", "11", "12")
        ]
        return household, visits

    def test_listing_pagination_limit_offset_meta(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/service_visit_listing_pagination_defaults
        """
        household, _ = self._three_visits(api)
        page1, meta1 = validate_paginated(api.list_service_visits(
            DISPATCHER, params={"household_id": household["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_service_visits(
            DISPATCHER, params={"household_id": household["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

    def test_filter_and_pagination_compose(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.5: "Visits can be listed filtered by `household_id`,
        `coop_site_id`, `subscription_id`, and `status`."

        Design: Corner/cross_cutting_complexity_layers/visit_list_pagination_filter_interaction
        """
        household, visits = self._three_visits(api)
        assign_visit(visits[0]["id"], "tech-1")

        page, meta = validate_paginated(api.list_service_visits(
            DISPATCHER, params={"household_id": household["id"], "status": "REQUESTED",
                                "limit": 1, "offset": 0}))
        assert len(page) == 1
        assert meta["total_count"] == 2, "total_count reflects the filtered set"
        assert meta["has_more"] is True
        assert page[0]["status"] == "REQUESTED"
