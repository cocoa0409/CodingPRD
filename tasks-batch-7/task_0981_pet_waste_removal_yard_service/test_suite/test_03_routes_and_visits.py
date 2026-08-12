"""Route capacity, route lifecycle, visit execution gating, and cascades."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    create_subscription_payload,
    create_technician,
    create_service_route,
    create_scheduled_visit,
    setup_active_subscription,
    create_customer,
    create_yard,
    create_access_profile,
    create_verified_access_profile,
    create_subscription_plan,
    setup_in_progress_route_with_visit,
    complete_visit_through_workflow,
)

OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Difficulty / boundary_precision_check / route_capacity_at_10000bp_boundary
# =========================================================================

class TestRouteCapacityAt10000Bp:
    def _setup_full_route(self):
        # PRD §2.9 #16 requires load factor to remain strictly below 10000bp
        # after adding; with max_capacity=3, two visits yield load=6666 (<10000)
        # and a third would yield 10000, which is the rejected boundary.
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            route_code="RJ",
            service_date="2026-05-08T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=3,
        )
        v1 = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T08:00:00Z",
            scheduled_window_end="2026-05-08T09:00:00Z",
        )
        v2 = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T10:00:00Z",
            scheduled_window_end="2026-05-08T11:00:00Z",
        )
        return customer, subscription, route, [v1, v2]

    def test_third_visit_rejected_at_capacity(self, api):
        """PRD §2.8: "When the load factor would reach or exceed 10000, the
        platform rejects any further visit assignment to that route with
        `ERR_ROUTE_AT_CAPACITY` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/route_capacity_at_10000bp_boundary
        """
        customer, subscription, route, _ = self._setup_full_route()
        resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T13:00:00Z",
                "scheduled_window_end": "2026-05-08T14:00:00Z",
                "service_route_id": route["id"],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_AT_CAPACITY)

    def test_route_counters_unchanged_after_rejected_assignment(self, api):
        """PRD §2.8: "Every `ServiceRoute` tracks a `committed_visit_count` —
        the number of visits on the route whose status is `SCHEDULED`,
        `EN_ROUTE`, or `ON_SITE` — and a derived `route_load_factor_bp` in
        basis points."

        Design: Difficulty/boundary_precision_check/route_capacity_at_10000bp_boundary
        """
        customer, subscription, route, _ = self._setup_full_route()
        api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T13:00:00Z",
                "scheduled_window_end": "2026-05-08T14:00:00Z",
                "service_route_id": route["id"],
            },
            OPS,
        )
        get_resp = api_client.get_service_route(route["id"], OPS)
        data = validate_success(get_resp)
        assert data["committed_visit_count"] == 2
        # 2 * 10000 // 3 = 6666 (floor division); rejected 3rd visit must not change counters
        assert data["route_load_factor_bp"] == 6666


# =========================================================================
# Corner / calculations / route_load_factor_floor_division
# Corner / consistency_model / immediate_consistency_visit_create_route_counters
# =========================================================================

class TestRouteLoadFactorComputation:
    def test_load_factor_uses_floor_division(self, api):
        """PRD §2.8: "The load factor is the committed count multiplied by
        10000 and divided by `max_visit_capacity`, computed with integer
        floor division."

        Design: Corner/calculations/route_load_factor_floor_division
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            service_date="2026-05-08T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=7,
        )
        # Add 3 visits with 2h spacing to avoid window conflicts.
        for start_h in (8, 10, 12):
            create_scheduled_visit(
                subscription["id"],
                route_id=route["id"],
                scheduled_date="2026-05-08T00:00:00Z",
                scheduled_window_start=f"2026-05-08T{start_h:02d}:00:00Z",
                scheduled_window_end=f"2026-05-08T{start_h + 1:02d}:00:00Z",
            )
        resp = api_client.get_service_route(route["id"], OPS)
        data = validate_success(resp)
        assert data["committed_visit_count"] == 3
        # floor(3 * 10000 / 7) = floor(4285.71) = 4285
        assert data["route_load_factor_bp"] == 4285

    def test_route_counters_visible_immediately_after_create(self, api):
        """PRD §3.5: "On creation, `provisional_visit_charge_cents` is computed
        via the PROVISIONAL per-visit charge, and if a route was supplied the
        route's `committed_visit_count` is incremented and
        `route_load_factor_bp` recomputed."

        Design: Corner/consistency_model/immediate_consistency_visit_create_route_counters
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            service_date="2026-05-08T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=5,
        )
        create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T09:00:00Z",
            scheduled_window_end="2026-05-08T10:00:00Z",
        )
        resp = api_client.get_service_route(route["id"], OPS)
        data = validate_success(resp)
        assert data["committed_visit_count"] == 1
        assert data["route_load_factor_bp"] == 2000  # floor(1*10000/5)


# =========================================================================
# Difficulty / compensating_invariant / route_committed_visit_count_invariant
# =========================================================================

class TestRouteCommittedCountInvariant:
    def _setup(self):
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            route_code="RQ",
            service_date="2026-05-12T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=5,
        )
        v_pre = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-12T00:00:00Z",
            scheduled_window_start="2026-05-12T09:00:00Z",
            scheduled_window_end="2026-05-12T10:00:00Z",
        )
        return customer, subscription, route, v_pre

    def test_committed_count_returns_to_pre_pair_value(self, api):
        """PRD §3.5: "An `OperationsManager` may reassign a visit's route at
        any time before the visit reaches a terminal state by supplying a new
        `service_route_id`; the operation decrements the old route's committed
        count, increments the new route's, and recomputes
        `route_load_factor_bp` on both." Also: "The committed count and load
        factor are recomputed on every visit mutation that affects the route —
        creation, route reassignment, completion, skip, miss, and cancel."
        (PRD §2.8)

        Design: Difficulty/compensating_invariant/route_committed_visit_count_invariant
        """
        customer, subscription, route, v_pre = self._setup()
        pre = validate_success(api_client.get_service_route(route["id"], OPS))
        assert pre["committed_visit_count"] == 1
        assert pre["route_load_factor_bp"] == 2000
        v_new = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-12T00:00:00Z",
            scheduled_window_start="2026-05-12T11:00:00Z",
            scheduled_window_end="2026-05-12T12:00:00Z",
        )
        # Cancel the just-created visit.
        cancel_resp = api_client.cancel_visit(
            v_new["id"], make_customer_headers(customer["id"])
        )
        validate_success(cancel_resp)
        post = validate_success(api_client.get_service_route(route["id"], OPS))
        assert post["committed_visit_count"] == 1, (
            f"Expected committed to return to 1, got {post['committed_visit_count']}"
        )

    def test_load_factor_returns_to_pre_pair_value(self, api):
        """PRD §2.8: "The committed count and load factor are recomputed on
        every visit mutation that affects the route — creation, route
        reassignment, completion, skip, miss, and cancel."

        Design: Difficulty/compensating_invariant/route_committed_visit_count_invariant
        """
        customer, subscription, route, v_pre = self._setup()
        v_new = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-12T00:00:00Z",
            scheduled_window_start="2026-05-12T11:00:00Z",
            scheduled_window_end="2026-05-12T12:00:00Z",
        )
        api_client.cancel_visit(v_new["id"], make_customer_headers(customer["id"]))
        post = validate_success(api_client.get_service_route(route["id"], OPS))
        assert post["route_load_factor_bp"] == 2000


# =========================================================================
# Corner / state_machines / service_route_publish_precondition_tech_required
# Corner / endpoints / route_start_wrong_day
# Corner / endpoints / visit_depart_without_route_assigned
# Corner / state_machines / subscription_pause_blocked_when_visit_in_flight
# =========================================================================

class TestRouteAndVisitPreconditions:
    def test_publish_rejected_without_assigned_technician(self, api):
        """PRD §3.5: "Publishing moves a route from `PLANNED` to `PUBLISHED`
        and is performed by an `OperationsManager`. Three preconditions hold:
        `assigned_technician_id` must be non-null (else `ERR_TECH_REQUIRED`)"

        Design: Corner/state_machines/service_route_publish_precondition_tech_required
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        route = create_service_route(
            route_code="RNT",
            service_date="2026-05-06T00:00:00Z",
            max_visit_capacity=5,
            # no assigned_technician_id
        )
        create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-06T00:00:00Z",
            scheduled_window_start="2026-05-06T09:00:00Z",
            scheduled_window_end="2026-05-06T10:00:00Z",
        )
        resp = api_client.publish_service_route(route["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_TECH_REQUIRED)

    def test_route_start_rejected_on_wrong_day(self, api):
        """PRD §3.5: "Starting requires the acting technician's id to equal
        `assigned_technician_id` (else `ERR_ROUTE_TECH_MISMATCH`) and the
        current logical date to equal `service_date` (else
        `ERR_ROUTE_WRONG_DAY`)."

        Design: Corner/endpoints/route_start_wrong_day
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            route_code="RWD",
            service_date="2026-05-08T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=5,
        )
        create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T09:00:00Z",
            scheduled_window_end="2026-05-08T10:00:00Z",
        )
        api_client.publish_service_route(route["id"], OPS)
        # Move clock to 2026-05-07 (one day before service_date).
        api_client.set_current_utc("2026-05-07T08:00:00Z", OPS)
        resp = api_client.start_service_route(
            route["id"], make_technician_headers(technician["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_WRONG_DAY)

    def test_depart_rejected_without_route_assignment(self, api):
        """PRD §3.5: "departure requires the visit's `service_route_id` to be
        non-null (else `ERR_ROUTE_NOT_ASSIGNED`)"

        Design: Corner/endpoints/visit_depart_without_route_assigned
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        # Visit with NO service_route_id.
        visit = create_scheduled_visit(
            subscription["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T09:00:00Z",
            scheduled_window_end="2026-05-08T10:00:00Z",
        )
        resp = api_client.depart_visit(
            visit["id"], make_technician_headers(technician["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_ASSIGNED)

    def test_pause_rejected_when_visit_in_flight(self, api):
        """PRD §3.3: "Pausing moves an `ACTIVE` subscription to `PAUSED` and is
        available only when no visit on the subscription is currently
        `EN_ROUTE` or `ON_SITE`; if one is, the pause is rejected with
        `ERR_VISIT_IN_FLIGHT`."

        Design: Corner/state_machines/subscription_pause_blocked_when_visit_in_flight
        """
        customer, yard, profile, plan, subscription, technician, route, visit = (
            setup_in_progress_route_with_visit()
        )
        # visit is now EN_ROUTE.
        resp = api_client.pause_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_IN_FLIGHT)


# =========================================================================
# Difficulty / cross_entity_state_dependency / visit_arrive_depends_on_technician_certification_state
# Corner / validations / pet_safety_ack_required_before_arrive
# =========================================================================

class TestVisitArriveSafetyGating:
    def test_arrive_rejected_when_ack_missing_for_caution_yard(self, api):
        """PRD §2.9 item 8: "Visit arrival requires the pet-safety
        acknowledgement when the yard's `pet_aggression_flag` is not `NONE` —
        otherwise `ERR_PET_SAFETY_ACK_REQUIRED`."

        Design: Corner/validations/pet_safety_ack_required_before_arrive
        """
        customer, yard, profile, plan, subscription, technician, route, visit = (
            setup_in_progress_route_with_visit(
                profile_overrides={"pet_aggression_flag": "CAUTION", "pet_on_premises": True},
            )
        )
        # Visit is EN_ROUTE without ack-safety.
        resp = api_client.arrive_visit(visit["id"], make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_PET_SAFETY_ACK_REQUIRED)

    def test_arrive_rejected_when_tech_not_certified_for_aggressive(self, api):
        """PRD §3.5: "if the flag is `AGGRESSIVE`, the acting technician's
        `certified_for_aggressive_pets` must be true (else
        `ERR_TECH_NOT_CERTIFIED_AGGRESSIVE`)."

        Design: Difficulty/cross_entity_state_dependency/visit_arrive_depends_on_technician_certification_state
        """
        customer, yard, profile, plan, subscription, technician, route, visit = (
            setup_in_progress_route_with_visit(
                profile_overrides={"pet_aggression_flag": "AGGRESSIVE", "pet_on_premises": True},
                technician_overrides={"certified_for_aggressive_pets": False},
            )
        )
        # Ack the safety requirement first so we isolate the certification check.
        api_client.ack_safety_visit(visit["id"], make_technician_headers(technician["id"]))
        resp = api_client.arrive_visit(visit["id"], make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_TECH_NOT_CERTIFIED_AGGRESSIVE)

    def test_visit_remains_en_route_after_certification_rejection(self, api):
        """PRD §3.5: "Arrival moves the visit from `EN_ROUTE` to `ON_SITE`" —
        a rejected arrival leaves the visit EN_ROUTE.

        Design: Difficulty/cross_entity_state_dependency/visit_arrive_depends_on_technician_certification_state
        """
        customer, yard, profile, plan, subscription, technician, route, visit = (
            setup_in_progress_route_with_visit(
                profile_overrides={"pet_aggression_flag": "AGGRESSIVE", "pet_on_premises": True},
                technician_overrides={"certified_for_aggressive_pets": False},
            )
        )
        api_client.ack_safety_visit(visit["id"], make_technician_headers(technician["id"]))
        api_client.arrive_visit(visit["id"], make_technician_headers(technician["id"]))
        get_resp = api_client.get_visit(visit["id"], OPS)
        data = validate_success(get_resp)
        assert data["status"] == "EN_ROUTE"


# =========================================================================
# Corner / state_machines / visit_terminal_completed_lockdown
# Corner / cross_cutting_complexity_layers / cascading_side_effects_visit_complete_bubbles_to_route_close
# =========================================================================

class TestVisitTerminalAndRouteBubble:
    def test_skip_rejected_on_completed_visit(self, api):
        """PRD §3.5: "Completion moves the visit from `ON_SITE` to
        `COMPLETED`" — and PRD's state machine (§3.5) has no exit transitions
        from COMPLETED; attempting any further transition is invalid.

        Design: Corner/state_machines/visit_terminal_completed_lockdown
        """
        customer, yard, profile, plan, subscription, technician, route, visit = (
            setup_in_progress_route_with_visit()
        )
        complete_visit_through_workflow(visit["id"], technician["id"])
        # Now COMPLETED; a skip attempt must fail.
        resp = api_client.skip_visit(visit["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_last_visit_completion_bubbles_route_to_closed(self, api):
        """PRD §3.5: "Completion moves the visit from `ON_SITE` to `COMPLETED`,
        stamps `completed_at` with the current logical time, computes
        `final_visit_charge_cents` via the FINAL per-visit variant, increments
        the customer's `lifetime_visits_completed` by one, recomputes the
        customer's `satisfaction_rolling_avg`, and — when the completion
        leaves every visit on the parent route in a terminal state — bubbles
        the route from `IN_PROGRESS` to `CLOSED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_visit_complete_bubbles_to_route_close
        """
        customer, yard, profile, plan, subscription, technician, route, visit = (
            setup_in_progress_route_with_visit()
        )
        complete_visit_through_workflow(visit["id"], technician["id"])
        route_resp = api_client.get_service_route(route["id"], OPS)
        route_data = validate_success(route_resp)
        assert route_data["route_status"] == "CLOSED"
