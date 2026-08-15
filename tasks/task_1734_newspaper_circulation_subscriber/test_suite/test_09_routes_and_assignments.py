"""Routes and route assignments: capacity, deactivation, closed-interval overlap."""
from test_helpers import (
    MGR,
    ApiErrorId,
    create_active_subscription,
    create_assignment,
    create_plan,
    create_route,
    create_subscriber,
    create_subscription,
    get_route,
    get_subscription,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    validate_error,
    validate_success,
)


class TestAssignmentCapacity:
    def test_route_at_capacity_rejected(self, api):
        """PRD §3.6: "Three guards protect the route: it must be `ACTIVE`
        (`ERR_ROUTE_INACTIVE`), it must have spare capacity —
        `assigned_stop_count` already at `max_stops` yields
        `ERR_ROUTE_AT_CAPACITY` — and the new closed interval must not
        collide with another `ACTIVE` assignment of the same subscription."

        Design: Corner/validations/route_at_capacity_rejected
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="RC", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        sub1 = create_subscriber(display_name="R1", email="r1@x.com", service_address="10 Oak St")
        sub2 = create_subscriber(display_name="R2", email="r2@x.com", service_address="11 Oak St")
        subsc1 = create_subscription(sub1["id"], plan["id"], start_date="2026-08-03")
        subsc2 = create_subscription(sub2["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()

        route = create_route(route_code="RCAP", max_stops=1)
        create_assignment(subsc1["id"], route["id"], "2026-08-03")
        assert get_route(route["id"])["assigned_stop_count"] == 1

        resp = api.create_route_assignment(
            {"subscription_id": subsc2["id"], "route_id": route["id"], "start_date": "2026-08-03"},
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_AT_CAPACITY, 409)
        assert get_route(route["id"])["assigned_stop_count"] == 1

    def test_assignment_increments_and_end_decrements_stop_count(self, api):
        """PRD §3.6: "A successful assignment begins `ACTIVE` and increments
        the route's `assigned_stop_count`. Ending an assignment requires it
        to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and takes an
        `end_date` no earlier than its `start_date` (otherwise
        `ERR_INVALID_REQUEST`); the assignment flips to `ENDED`, the end date
        is recorded, and the route's `assigned_stop_count` decrements."

        Design: Corner/validations/route_at_capacity_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        route = create_route(route_code="RC2", max_stops=1)
        assignment = create_assignment(ctx["subscription"]["id"], route["id"], "2026-08-03")
        assert get_route(route["id"])["assigned_stop_count"] == 1

        ended = validate_success(
            api.end_route_assignment(assignment["id"], {"end_date": "2026-08-10"}, MGR)
        )
        assert ended["status"] == "ENDED"
        assert ended["end_date"] == "2026-08-10"
        assert get_route(route["id"])["assigned_stop_count"] == 0

        # Capacity freed: a new assignment now fits the route again.
        ctx2 = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z",
            subscriber_overrides={"service_address": "12 Oak St"},
        )
        second = api.create_route_assignment(
            {
                "subscription_id": ctx2["subscription"]["id"],
                "route_id": route["id"],
                "start_date": "2026-08-11",
            },
            MGR,
        )
        validate_success(second, 201)


class TestInactiveRoute:
    def test_assignment_into_inactive_route_rejected(self, api):
        """PRD §3.6: "Routes begin `ACTIVE`; deactivating via a route update
        carrying `status` of `INACTIVE` blocks new assignments into the route
        (`ERR_ROUTE_INACTIVE`) while leaving existing assignments untouched."

        Design: Corner/validations/assignment_into_inactive_route_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        route = create_route(route_code="RIR", max_stops=5)
        updated = validate_success(api.update_route(route["id"], {"status": "INACTIVE"}, MGR))
        assert updated["status"] == "INACTIVE"

        resp = api.create_route_assignment(
            {
                "subscription_id": ctx["subscription"]["id"],
                "route_id": route["id"],
                "start_date": "2026-08-03",
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_INACTIVE, 409)

    def test_existing_assignment_survives_route_deactivation(self, api):
        """PRD §3.6: "Routes begin `ACTIVE`; deactivating via a route update
        carrying `status` of `INACTIVE` blocks new assignments into the route
        (`ERR_ROUTE_INACTIVE`) while leaving existing assignments untouched."

        Design: Corner/validations/assignment_into_inactive_route_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        route = create_route(route_code="RIR2", max_stops=5)
        assignment = create_assignment(ctx["subscription"]["id"], route["id"], "2026-08-03")

        validate_success(api.update_route(route["id"], {"status": "INACTIVE"}, MGR))

        surviving = validate_success(api.get_route_assignment(assignment["id"], MGR))
        assert surviving["status"] == "ACTIVE", (
            "deactivation leaves existing assignments untouched"
        )
        assert get_route(route["id"])["assigned_stop_count"] == 1


class TestAssignmentIntervalSemantics:
    def test_route_assignment_closed_interval_touching_collides(self, api):
        """PRD §2.8: "**Route assignments** use a closed interval: both
        `start_date` and `end_date` are inclusive delivery days, and a null
        `end_date` means open-ended. Two active assignments for the same
        subscription collide if their closed intervals intersect — and unlike
        holds, touching ends (the new assignment's `start_date` equal to an
        existing assignment's `end_date`) **do** collide."

        Design: Difficulty/resource_temporal_overlap/route_assignment_closed_interval_touching_collides
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        route = create_route(route_code="RC", max_stops=10)
        create_assignment(ctx["subscription"]["id"], route["id"], "2026-08-03", "2026-08-09")

        touching = api.create_route_assignment(
            {
                "subscription_id": ctx["subscription"]["id"],
                "route_id": route["id"],
                "start_date": "2026-08-09",
            },
            MGR,
        )
        validate_error(touching, ApiErrorId.ERR_ASSIGNMENT_OVERLAP, 409)

        gap = api.create_route_assignment(
            {
                "subscription_id": ctx["subscription"]["id"],
                "route_id": route["id"],
                "start_date": "2026-08-10",
            },
            MGR,
        )
        validate_success(gap, 201)

    def test_route_assignment_open_ended_collides_with_later_start(self, api):
        """PRD §2.8: "**Route assignments** use a closed interval: both
        `start_date` and `end_date` are inclusive delivery days, and a null
        `end_date` means open-ended. Two active assignments for the same
        subscription collide if their closed intervals intersect — and unlike
        holds, touching ends (the new assignment's `start_date` equal to an
        existing assignment's `end_date`) **do** collide."

        Design: Difficulty/resource_temporal_overlap/route_assignment_closed_interval_touching_collides
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        route = create_route(route_code="ROI", max_stops=10)
        create_assignment(ctx["subscription"]["id"], route["id"], "2026-08-03")  # open-ended

        resp = api.create_route_assignment(
            {
                "subscription_id": ctx["subscription"]["id"],
                "route_id": route["id"],
                "start_date": "2026-09-01",
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP, 409)


class TestAssignmentStateGate:
    def test_route_assignment_requires_subscription_active(self, api):
        """PRD §3.6: "Assignments require the subscription's billing axis in
        an active set and a print-capable plan (`ERR_DIGITAL_ONLY_PLAN`
        otherwise)."

        Design: Difficulty/cross_entity_state_dependency/route_assignment_requires_subscription_active
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="RA", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        bad_subscriber = create_subscriber(
            display_name="Bad", email="bad@x.com", service_address="11 Main St"
        )
        bad_subscription = create_subscription(
            bad_subscriber["id"], plan["id"], start_date="2026-08-03"
        )
        run_daily_cycle()

        # BAD: SUSPENDED on 2026-09-08 (oldest charge 22 days past due).
        set_clock("2026-09-08T00:00:00Z")
        good_subscriber = create_subscriber(
            display_name="Good", email="good@x.com", service_address="12 Main St"
        )
        good_subscription = create_subscription(
            good_subscriber["id"], plan["id"], start_date="2026-09-08"
        )
        run_daily_cycle()
        assert get_subscription(bad_subscription["id"])["billing_status"] == "SUSPENDED"
        assert get_subscription(good_subscription["id"])["billing_status"] == "ACTIVE"

        route = create_route(route_code="R1", max_stops=10)

        rejected = api.create_route_assignment(
            {
                "subscription_id": bad_subscription["id"],
                "route_id": route["id"],
                "start_date": "2026-09-09",
            },
            MGR,
        )
        validate_error(rejected, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)

        accepted = api.create_route_assignment(
            {
                "subscription_id": good_subscription["id"],
                "route_id": route["id"],
                "start_date": "2026-09-09",
            },
            MGR,
        )
        validate_success(accepted, 201)
        assert get_route(route["id"])["assigned_stop_count"] == 1

    def test_route_assignment_into_grace_subscription_allowed(self, api):
        """PRD §3.6: "Assignments require the subscription's billing axis in
        an active set and a print-capable plan (`ERR_DIGITAL_ONLY_PLAN`
        otherwise)."
        PRD §3.2: "More than seven but at most twenty-one days: the
        subscription sits in `GRACE`."

        Design: Difficulty/cross_entity_state_dependency/route_assignment_requires_subscription_active
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="RG", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="Grace", email="grace@x.com", service_address="13 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()

        # Oldest charge (due 2026-08-17) is 9 days past due -> GRACE.
        set_clock_and_cycle("2026-08-26T00:00:00Z")
        assert get_subscription(subscription["id"])["billing_status"] == "GRACE"

        route = create_route(route_code="RG1", max_stops=10)
        accepted = api.create_route_assignment(
            {
                "subscription_id": subscription["id"],
                "route_id": route["id"],
                "start_date": "2026-08-27",
            },
            MGR,
        )
        data = validate_success(accepted, 201)
        assert data["status"] == "ACTIVE"


class TestEndAssignment:
    def test_end_ended_assignment_rejected(self, api):
        """PRD §3.6: "Ending an assignment requires it to be `ACTIVE`
        (otherwise `ERR_INVALID_STATE`) and takes an `end_date` no earlier
        than its `start_date` (otherwise `ERR_INVALID_REQUEST`); the
        assignment flips to `ENDED`, the end date is recorded, and the
        route's `assigned_stop_count` decrements."

        Design: Corner/errors/end_ended_assignment_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        route = create_route(route_code="REE", max_stops=5)
        assignment = create_assignment(ctx["subscription"]["id"], route["id"], "2026-08-03")
        validate_success(
            api.end_route_assignment(assignment["id"], {"end_date": "2026-08-10"}, MGR)
        )

        resp = api.end_route_assignment(assignment["id"], {"end_date": "2026-08-11"}, MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        assert get_route(route["id"])["assigned_stop_count"] == 0, (
            "stop count decremented exactly once by the first end"
        )
