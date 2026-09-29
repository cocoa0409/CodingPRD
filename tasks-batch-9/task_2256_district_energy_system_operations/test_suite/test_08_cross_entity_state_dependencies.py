"""Transitions whose legality is owned by a different entity's state."""

from test_helpers import (
    ApiErrorId,
    BILLING_ANALYST,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    FIELD_TECHNICIAN_ALT,
    NETWORK_ENGINEER,
    activate_agreement,
    api_client,
    assert_agreement_state,
    assert_dispatch_order,
    assert_forecast_projection,
    assert_loop_state,
    assert_plan_metrics,
    assert_segment_condition,
    backfill_work_order,
    begin_excavation,
    begin_repair,
    commercial_rate_schedule,
    complete_work_order,
    create_agreement,
    create_loop,
    create_plan,
    create_segment,
    create_work_order,
    decide_permit,
    get_success_data,
    optimize_plan,
    plan_orders,
    published_forecast,
    read_agreement,
    read_forecast,
    read_loop,
    read_plan,
    set_clock,
    single_asset_stack,
    submit_permit,
    validate_error,
)


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


class TestActivationDependsOnLoopPosture:
    """A pending customer cannot be switched on while the loop is dug open."""

    def _isolated_loop_with_waiting_customer(self):
        set_clock()
        loop = create_loop(
            code="LOOP-G",
            name="Industrial Loop G",
            service_mode="HEATING",
            design_supply_temp_c=110.0,
            max_pressure_kpa=2000.0,
            rated_capacity_kw=20000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-G9",
            length_m=900.0,
            diameter_mm=250,
            install_year=2010,
            insulation_class="A",
            buried_depth_m=1.3,
        )
        tariff = commercial_rate_schedule()
        agreement = create_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Foundry Park",
            customer_class="COMMERCIAL_OFFICE",
            reserved_capacity_kw=5000.0,
            service_mode="HEATING",
            service_start_date="2026-06-01T00:00:00Z",
            service_end_date="2026-12-01T00:00:00Z",
        )
        order = create_work_order(
            segment["id"],
            loop["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T16:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="INSPECTION",
            requires_isolation=True,
        )
        submit_permit(order["id"], FIELD_TECHNICIAN)
        decide_permit(order["id"], "GRANTED", decision_note="inspection permit issued")
        set_clock("2026-09-01T09:00:00Z")
        begin_excavation(order["id"], FIELD_TECHNICIAN)
        return {
            "loop": loop,
            "segment": segment,
            "tariff": tariff,
            "agreement": agreement,
            "order": order,
        }

    def _close_the_ground(self, stack):
        begin_repair(stack["order"]["id"], FIELD_TECHNICIAN)
        backfill_work_order(stack["order"]["id"], FIELD_TECHNICIAN)
        return complete_work_order(
            stack["order"]["id"],
            completion_note="inspection closed, no leak found",
            completer_headers=FIELD_TECHNICIAN_ALT,
        )

    def test_activation_is_refused_while_the_loop_sits_isolated(self):
        """The agreement's own state is fine; the loop's posture is not.

        PRD: "It requires that the agreement be in `PENDING_CAPACITY`, that the
        loop's `posture` not be `ISOLATED` — an activation attempted on an isolated
        loop is refused with `ERR_LOOP_ISOLATED` — and that a reservation sweep
        across the loop's whole reservation calendar find no breach."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_blocked_while_network_loop_is_isolated
        """
        stack = self._isolated_loop_with_waiting_customer()
        assert_loop_state(read_loop(stack["loop"]["id"]), posture="ISOLATED")

        response = api_client.activate_connection_agreement(
            stack["agreement"]["id"], {}, BILLING_ANALYST
        )

        validate_error(response, ApiErrorId.LOOP_ISOLATED)

    def test_the_refused_activation_reserves_nothing_on_the_loop(self):
        """A blocked activation leaves both entities exactly as they were.

        PRD: "When the sweep clears, the agreement becomes `ACTIVE`, the loop's
        `committed_reserved_kw` is increased by the agreement's
        `reserved_capacity_kw`, and both the loop's and the agreement's `version`
        are incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_blocked_while_network_loop_is_isolated
        """
        stack = self._isolated_loop_with_waiting_customer()

        api_client.activate_connection_agreement(
            stack["agreement"]["id"], {}, BILLING_ANALYST
        )

        assert_agreement_state(
            read_agreement(stack["agreement"]["id"]), contract_state="PENDING_CAPACITY"
        )
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=0.0)

    def test_signing_off_the_inspection_returns_the_loop_to_normal(self):
        """A modern class A run scores well below the monitored floor on sign-off.

        PRD: "All three outcomes are possible and all three are reachable:
        `UNDER_REPAIR → SOUND` when the recomputed score is below 45.0;
        `UNDER_REPAIR → MONITORED` when it is at or above 45.0 and below 70.0; and
        `UNDER_REPAIR → SUSPECT` when it is at or above 70.0".

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_blocked_while_network_loop_is_isolated
        """
        stack = self._isolated_loop_with_waiting_customer()
        api_client.activate_connection_agreement(
            stack["agreement"]["id"], {}, BILLING_ANALYST
        )

        completed = self._close_the_ground(stack)

        assert completed["work_state"] == "COMPLETED"
        assert_segment_condition(
            _read_segment(stack["segment"]["id"]),
            condition="SOUND",
            leak_risk_score=10.83,
            historical_leak_count=0,
        )
        assert_loop_state(
            read_loop(stack["loop"]["id"]), posture="NORMAL", open_isolation_count=0
        )

    def test_the_identical_activate_call_then_succeeds(self):
        """Nothing about the request changed — only the loop's posture did.

        PRD: "**Activation** advances the contract dimension from
        `PENDING_CAPACITY` to `ACTIVE` and is the platform's capacity-allocation
        decision."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_blocked_while_network_loop_is_isolated
        """
        stack = self._isolated_loop_with_waiting_customer()
        api_client.activate_connection_agreement(
            stack["agreement"]["id"], {}, BILLING_ANALYST
        )
        self._close_the_ground(stack)

        activated = activate_agreement(stack["agreement"]["id"])

        assert_agreement_state(activated, contract_state="ACTIVE")
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=5000.0)


class TestOptimiseDependsOnForecastState:
    """A plan stays draftable while the forecast it binds is pushed aside."""

    def _plan_on_a_superseded_forecast(self):
        stack = single_asset_stack()
        first = published_forecast(
            stack["loop"]["id"], "2026-08-07T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        plan = create_plan(stack["loop"]["id"], first["id"])
        second = published_forecast(
            stack["loop"]["id"], "2026-08-07T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        stack["first_forecast"] = first
        stack["second_forecast"] = second
        stack["first_plan"] = plan
        return stack

    def test_the_second_publication_supersedes_the_first_forecast(self):
        """Two forecasts for one loop and one service date cannot both be live.

        PRD: "Publication supersedes competition: any **other** forecast on the same
        `loop_id` with the same `service_date` that is currently `PUBLISHED` is
        cascaded from `PUBLISHED` to `SUPERSEDED` and has its `version` incremented
        by 1."

        Design: Difficulty/cross_entity_state_dependency/plan_optimize_blocked_when_bound_forecast_was_superseded
        """
        stack = self._plan_on_a_superseded_forecast()

        assert_forecast_projection(
            read_forecast(stack["first_forecast"]["id"]), forecast_state="SUPERSEDED"
        )
        assert_forecast_projection(
            read_forecast(stack["second_forecast"]["id"]),
            forecast_state="PUBLISHED",
            coincident_demand_kw=756.00,
        )

    def test_optimising_against_the_superseded_forecast_is_refused(self):
        """The plan is a draft, but the forecast behind it no longer qualifies.

        PRD: "Three things must hold: the plan is in `DRAFT`, the referenced forecast
        is `PUBLISHED` (otherwise `ERR_FORECAST_STATE_INVALID`), and at least one
        production asset on the loop has an `availability_state` of `AVAILABLE` or
        `DERATED`."

        Design: Difficulty/cross_entity_state_dependency/plan_optimize_blocked_when_bound_forecast_was_superseded
        """
        stack = self._plan_on_a_superseded_forecast()

        response = api_client.optimize_dispatch_plan(
            stack["first_plan"]["id"], {}, DISPATCH_OPERATOR
        )

        validate_error(response, ApiErrorId.FORECAST_STATE_INVALID)

    def test_a_fresh_plan_bound_to_the_surviving_forecast_optimises(self):
        """Rebinding to the live forecast makes the identical optimise call work.

        PRD: "A remaining-demand counter starts at the forecast's
        `coincident_demand_kw`, and a rank counter starts at zero."

        Design: Difficulty/cross_entity_state_dependency/plan_optimize_blocked_when_bound_forecast_was_superseded
        """
        stack = self._plan_on_a_superseded_forecast()

        second_plan = create_plan(stack["loop"]["id"], stack["second_forecast"]["id"])
        optimize_plan(second_plan["id"])

        assert_plan_metrics(
            read_plan(second_plan["id"]),
            plan_state="DRAFT",
            allocated_capacity_kw=756.00,
            total_dispatch_cost=907.20,
            total_emissions_kg=453.60,
        )
        orders = plan_orders(second_plan["id"])
        assert len(orders) == 1, f"expected one dispatch order, got {len(orders)}"
        assert_dispatch_order(
            orders[0],
            asset_id=stack["asset"]["id"],
            merit_rank=1,
            allocated_kw=756.00,
            block_energy_mwh=18.144,
        )

    def test_opening_the_replacement_plan_supersedes_the_stranded_one(self):
        """The stranded draft is swept aside with none of its metrics ever filled in.

        PRD: "Creation is also a broom: every other dispatch plan on the same loop
        whose `plan_state` is `DRAFT`, `SUBMITTED` or `APPROVED` is cascaded to
        `SUPERSEDED` with its `version` incremented by 1, and the loop's own
        `version` is incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/plan_optimize_blocked_when_bound_forecast_was_superseded
        """
        stack = self._plan_on_a_superseded_forecast()

        create_plan(stack["loop"]["id"], stack["second_forecast"]["id"])

        assert_plan_metrics(
            read_plan(stack["first_plan"]["id"]),
            plan_state="SUPERSEDED",
            allocated_capacity_kw=0.0,
        )
