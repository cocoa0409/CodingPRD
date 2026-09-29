"""Which rung of the admission ladder answers, and when a rule applies at all."""

from test_helpers import (
    ApiErrorId,
    BILLING_ANALYST,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    NETWORK_ENGINEER,
    NON_EXISTENT_UUID,
    active_agreement,
    add_reading,
    api_client,
    assert_invoice_determinants,
    assert_loop_state,
    assert_plan_metrics,
    assert_segment_condition,
    begin_excavation,
    commissioned_point,
    connection_agreement_payload,
    create_asset,
    create_fuel_contract,
    create_invoice,
    create_loop,
    create_plan,
    create_segment,
    create_work_order,
    decide_permit,
    decommit_plan,
    get_success_data,
    optimize_plan,
    pipe_segment_payload,
    plan_in_state,
    plan_review_payload,
    published_forecast,
    read_invoice,
    read_loop,
    read_plan,
    read_work_order,
    residential_rate_schedule,
    set_clock,
    submit_permit,
    university_rate_schedule,
    validate_error,
    validate_paginated,
    void_invoice,
)


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


def _count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


class TestRoleAndForeignKeyOutrankTheLowerRungs:
    """Three different rung pairs, each answered by the higher rung."""

    def _two_loops_and_a_tariff(self):
        set_clock()
        first = create_loop(
            code="LOOP-Y1",
            name="Yardley Loop One",
            service_mode="HEATING",
            rated_capacity_kw=7000.0,
        )
        second = create_loop(
            code="LOOP-Y2",
            name="Yardley Loop Two",
            service_mode="HEATING",
            rated_capacity_kw=7000.0,
        )
        return {
            "first_loop": first,
            "second_loop": second,
            "first_segment": create_segment(first["id"], code="SEG-Y1"),
            "second_segment": create_segment(second["id"], code="SEG-Y2"),
            "tariff": university_rate_schedule(code="RS-U"),
        }

    def test_the_role_check_answers_before_the_plan_has_to_exist(self):
        """A technician reviewing an unknown plan learns nothing about the plan.

        PRD: "a request that would fail several checks fails on the earliest one, so a
        caller with a bad role never learns whether its body was well formed, and a
        caller acting on a wrongly-stated version never learns whether the target's
        state permitted the action."

        Design: Corner/Validations/role_check_and_foreign_key_check_win_over_lower_priority_rules
        """
        self._two_loops_and_a_tariff()

        response = api_client.review_dispatch_plan(
            NON_EXISTENT_UUID,
            plan_review_payload("APPROVE", review_note="not my desk"),
            FIELD_TECHNICIAN,
        )

        validate_error(response, ApiErrorId.UNAUTHORIZED)

    def test_the_unresolvable_loop_reference_answers_before_the_class_mismatch(self):
        """A hospital customer on a university tariff still reports the missing loop.

        PRD: "Every foreign key supplied in the request body resolves to an existing
        row, evaluated in body-field declaration order — `loop_id`, then
        `upstream_segment_id`, then `fuel_contract_id`, then `forecast_id`, then
        `rate_schedule_id`, then `agreement_id`, then `segment_id` — with the first
        unresolved reference yielding `ERR_FK_NOT_FOUND` (404)."

        Design: Corner/Validations/role_check_and_foreign_key_check_win_over_lower_priority_rules
        """
        stack = self._two_loops_and_a_tariff()

        response = api_client.create_connection_agreement(
            connection_agreement_payload(
                NON_EXISTENT_UUID,
                stack["tariff"]["id"],
                customer_name="Yardley General Hospital",
                customer_class="HOSPITAL",
            ),
            BILLING_ANALYST,
        )

        validate_error(response, ApiErrorId.FK_NOT_FOUND)
        assert (
            _count(
                api_client.list_connection_agreements(
                    BILLING_ANALYST, {"loop_id": stack["first_loop"]["id"]}
                )
            )
            == 0
        ), "the refused draft must not have been persisted against the loop"

    def test_the_duplicate_code_answers_before_the_upstream_graph_check(self):
        """The code is taken and the upstream segment is off-loop; uniqueness wins.

        PRD: "**Code uniqueness.** `ERR_DUPLICATE_CODE` (409) on loop, segment, asset,
        fuel-contract, tariff and metering-point creation."

        Design: Corner/Validations/role_check_and_foreign_key_check_win_over_lower_priority_rules
        """
        stack = self._two_loops_and_a_tariff()

        response = api_client.create_pipe_segment(
            pipe_segment_payload(
                stack["first_loop"]["id"],
                code="SEG-Y1",
                upstream_segment_id=stack["second_segment"]["id"],
            ),
            NETWORK_ENGINEER,
        )

        validate_error(response, ApiErrorId.DUPLICATE_CODE)
        assert (
            _count(
                api_client.list_pipe_segments(
                    NETWORK_ENGINEER, {"loop_id": stack["first_loop"]["id"]}
                )
            )
            == 1
        ), "the refused segment must not have been registered on the loop"

    def test_freeing_the_code_lets_the_graph_check_speak(self):
        """With a unique code the same off-loop upstream reference is what fails.

        PRD: "A chain that closes on itself or wanders off the loop is rejected with
        `ERR_SEGMENT_CYCLE`."

        Design: Corner/Validations/role_check_and_foreign_key_check_win_over_lower_priority_rules
        """
        stack = self._two_loops_and_a_tariff()

        response = api_client.create_pipe_segment(
            pipe_segment_payload(
                stack["first_loop"]["id"],
                code="SEG-Y3",
                upstream_segment_id=stack["second_segment"]["id"],
            ),
            NETWORK_ENGINEER,
        )

        validate_error(response, ApiErrorId.SEGMENT_CYCLE)


class TestOrderCountBeatsUnservedDemandOnSubmit:
    """An empty plan is reported as empty, not as short of generation."""

    def _plan_with_nothing_dispatchable(self):
        set_clock()
        loop = create_loop(
            code="LOOP-V",
            name="Vale Loop V",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
        tariff = university_rate_schedule(code="RS-V")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Vale University",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
        )
        asset = create_asset(
            loop["id"],
            code="V_H",
            asset_type="BOILER",
            rated_capacity_kw=5000.0,
            marginal_cost_per_mwh=35.00,
            emission_factor_kg_per_mwh=190.0,
            min_stable_output_kw=4000.0,
        )
        forecast = published_forecast(
            loop["id"], "2026-08-05T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        plan = create_plan(loop["id"], forecast["id"])
        optimize_plan(plan["id"])
        return {
            "loop": loop,
            "tariff": tariff,
            "agreement": agreement,
            "asset": asset,
            "forecast": forecast,
            "plan": read_plan(plan["id"]),
        }

    def test_the_only_machine_cannot_run_stably_on_the_forecast_block(self):
        """A 756.00 kW block is far below a 4000.0 kW minimum stable output.

        PRD: "If the block is strictly less than the asset's `min_stable_output_kw`,
        the asset is passed over as unable to run stably — a block exactly equal to
        `min_stable_output_kw` does dispatch."

        Design: Corner/Validations/order_count_check_runs_before_the_unserved_demand_check_on_submit
        """
        stack = self._plan_with_nothing_dispatchable()

        assert stack["forecast"]["coincident_demand_kw"] == 756.00, (
            f"expected a 756.00 kW block, got {stack['forecast']['coincident_demand_kw']}"
        )
        assert (
            _count(
                api_client.list_dispatch_orders(
                    DISPATCH_OPERATOR, {"plan_id": stack["plan"]["id"]}
                )
            )
            == 0
        ), "a skipped asset must not emit a dispatch order"

    def test_optimising_still_succeeds_and_leaves_the_whole_block_unserved(self):
        """Optimisation is a draft self-loop, so an empty waterfall is not an error.

        PRD: "Whatever remains — floored at 0.0, so it is never negative — is stored
        on the plan as `unserved_demand_kw`."

        Design: Corner/Validations/order_count_check_runs_before_the_unserved_demand_check_on_submit
        """
        stack = self._plan_with_nothing_dispatchable()

        assert_plan_metrics(
            stack["plan"],
            plan_state="DRAFT",
            allocated_capacity_kw=0.00,
            unserved_demand_kw=756.00,
            total_dispatch_cost=0.00,
            total_emissions_kg=0.00,
            fuel_diversity_hhi=0.0000,
        )

    def test_submission_reports_the_empty_plan_not_the_missing_generation(self):
        """Both submit-time gates are violated and the order-count gate answers.

        PRD: "It must own at least one dispatch order, or `ERR_PLAN_HAS_NO_ORDERS` — a
        plan that was never optimised cannot be submitted. And its
        `unserved_demand_kw` must be exactly 0.0, meaning the waterfall covered the
        whole coincident demand, or `ERR_INSUFFICIENT_GENERATION`."

        Design: Corner/Validations/order_count_check_runs_before_the_unserved_demand_check_on_submit
        """
        stack = self._plan_with_nothing_dispatchable()

        response = api_client.submit_dispatch_plan(
            stack["plan"]["id"],
            {"submission_note": "nothing to dispatch"},
            DISPATCH_OPERATOR,
        )

        validate_error(response, ApiErrorId.PLAN_HAS_NO_ORDERS)
        assert_plan_metrics(read_plan(stack["plan"]["id"]), plan_state="DRAFT")


class TestIsolationClearanceOnlyBindsIsolatingWork:
    """One committed plan, two digs: only the one that isolates is refused."""

    WINDOW_START = "2026-09-10T08:00:00Z"
    WINDOW_END = "2026-09-10T18:00:00Z"

    def _committed_loop_with_two_scheduled_digs(self):
        set_clock()
        loop = create_loop(
            code="LOOP-W",
            name="Westbrook Loop W",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
        open_cut = create_segment(loop["id"], code="SEG-W1")
        isolating_cut = create_segment(loop["id"], code="SEG-W2")
        tariff = university_rate_schedule(code="RS-W")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Westbrook University",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
        )
        gas = create_fuel_contract(
            supplier_code="FCG-W",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=15000.0,
            price_per_mwh=28.00,
            delivery_firmness="FIRM",
        )
        biomass = create_fuel_contract(
            supplier_code="FCB-W",
            fuel_type="BIOMASS",
            contracted_energy_mwh_per_year=9000.0,
            price_per_mwh=36.00,
            delivery_firmness="FIRM",
        )
        oil = create_fuel_contract(
            supplier_code="FCO-W",
            fuel_type="FUEL_OIL",
            contracted_energy_mwh_per_year=6000.0,
            price_per_mwh=75.00,
            delivery_firmness="FIRM",
        )
        create_asset(
            loop["id"],
            code="W_G",
            asset_type="CHP",
            rated_capacity_kw=400.0,
            marginal_cost_per_mwh=30.00,
            emission_factor_kg_per_mwh=220.0,
            fuel_contract_id=gas["id"],
        )
        create_asset(
            loop["id"],
            code="W_B",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=500.0,
            marginal_cost_per_mwh=32.00,
            emission_factor_kg_per_mwh=30.0,
            fuel_contract_id=biomass["id"],
        )
        create_asset(
            loop["id"],
            code="W_S",
            asset_type="BOILER",
            rated_capacity_kw=2000.0,
            marginal_cost_per_mwh=90.00,
            emission_factor_kg_per_mwh=260.0,
            fuel_contract_id=oil["id"],
        )
        forecast = published_forecast(
            loop["id"], "2026-08-05T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        plan = plan_in_state("COMMITTED", loop["id"], forecast["id"])
        orders = {}
        for code, segment, isolation in (
            ("open_cut_order", open_cut, False),
            ("isolating_order", isolating_cut, True),
        ):
            order = create_work_order(
                segment["id"],
                loop["id"],
                self.WINDOW_START,
                self.WINDOW_END,
                reporter_headers=FIELD_TECHNICIAN,
                work_type="VALVE_REPLACEMENT",
                requires_isolation=isolation,
            )
            submit_permit(order["id"], FIELD_TECHNICIAN)
            decide_permit(order["id"], "GRANTED", decision_note="permit issued")
            orders[code] = order
        set_clock("2026-09-10T09:00:00Z")
        return {
            "loop": loop,
            "open_cut": open_cut,
            "isolating_cut": isolating_cut,
            "agreement": agreement,
            "forecast": forecast,
            "plan": plan,
            **orders,
        }

    def test_the_committed_plan_carries_the_margin_and_diversity_it_needed(self):
        """Two of the three machines cover 756.00 kW between them.

        PRD: "For each distinct fuel key, the energy dispatched under that key is
        summed and rounded half-up to three decimal places, divided by that plan
        total, and the quotient squared; the squares are added across all distinct keys
        and the sum rounded half-up to four decimal places to give
        `fuel_diversity_hhi`."

        Design: Corner/Validations/isolation_clearance_rule_applies_only_to_work_orders_that_request_isolation
        """
        stack = self._committed_loop_with_two_scheduled_digs()

        assert_plan_metrics(
            read_plan(stack["plan"]["id"]),
            plan_state="COMMITTED",
            allocated_capacity_kw=756.00,
            unserved_demand_kw=0.00,
            total_dispatch_cost=561.41,
            total_emissions_kg=2368.32,
            reserve_margin_pct=19.05,
            fuel_diversity_hhi=0.5017,
        )

    def test_the_non_isolating_dig_proceeds_under_a_committed_plan(self):
        """The clearance rule reads the order's own flag, which is false here.

        PRD: "When `requires_isolation` is true, no dispatch plan on the loop may be in
        `plan_state` `COMMITTED` — you do not isolate a loop that the plant is actively
        serving — and a violation is refused with `ERR_ISOLATION_CLEARANCE_DENIED`."

        Design: Corner/Validations/isolation_clearance_rule_applies_only_to_work_orders_that_request_isolation
        """
        stack = self._committed_loop_with_two_scheduled_digs()

        opened = begin_excavation(stack["open_cut_order"]["id"], FIELD_TECHNICIAN)

        assert opened["work_state"] == "EXCAVATING"
        assert opened["requires_isolation"] is False
        assert_segment_condition(
            _read_segment(stack["open_cut"]["id"]), condition="UNDER_REPAIR"
        )
        assert_loop_state(
            read_loop(stack["loop"]["id"]), posture="NORMAL", open_isolation_count=0
        )

    def test_the_isolating_dig_on_the_same_loop_is_refused(self):
        """Same loop, same window, same committed plan — but this order isolates.

        PRD: "**Breaking ground** advances a `SCHEDULED` order to `EXCAVATING` and
        carries four preconditions."

        Design: Corner/Validations/isolation_clearance_rule_applies_only_to_work_orders_that_request_isolation
        """
        stack = self._committed_loop_with_two_scheduled_digs()
        begin_excavation(stack["open_cut_order"]["id"], FIELD_TECHNICIAN)

        response = api_client.begin_excavation(
            stack["isolating_order"]["id"], {}, FIELD_TECHNICIAN
        )

        validate_error(response, ApiErrorId.ISOLATION_CLEARANCE_DENIED)
        assert read_work_order(stack["isolating_order"]["id"])["work_state"] == "SCHEDULED"
        assert_segment_condition(
            _read_segment(stack["isolating_cut"]["id"]), condition="SOUND"
        )

    def test_withdrawing_the_commitment_lets_the_isolating_dig_take_the_loop(self):
        """Decommitment removes the only obstacle and the loop goes isolated.

        PRD: "When `requires_isolation` is true the loop's `posture` is additionally
        cascaded to `ISOLATED`, its `open_isolation_count` incremented by 1 and its
        `version` incremented by 1."

        Design: Corner/Validations/isolation_clearance_rule_applies_only_to_work_orders_that_request_isolation
        """
        stack = self._committed_loop_with_two_scheduled_digs()
        begin_excavation(stack["open_cut_order"]["id"], FIELD_TECHNICIAN)
        api_client.begin_excavation(stack["isolating_order"]["id"], {}, FIELD_TECHNICIAN)
        withdrawn = decommit_plan(stack["plan"]["id"], "clearing the loop for the dig")
        assert_plan_metrics(withdrawn, plan_state="DRAFT")

        isolated = begin_excavation(stack["isolating_order"]["id"], FIELD_TECHNICIAN)

        assert isolated["work_state"] == "EXCAVATING"
        assert_segment_condition(
            _read_segment(stack["isolating_cut"]["id"]), condition="UNDER_REPAIR"
        )
        assert_loop_state(
            read_loop(stack["loop"]["id"]), posture="ISOLATED", open_isolation_count=1
        )


class TestAdjacentBillingPeriodsShareABoundary:
    """June ends where July starts, and the half-open guard allows both."""

    JUNE_START = "2026-06-01T00:00:00Z"
    JUNE_END = "2026-07-01T00:00:00Z"
    JULY_END = "2026-08-01T00:00:00Z"

    def _customer_with_a_two_month_register(self):
        set_clock()
        loop = create_loop(
            code="LOOP-M",
            name="Maple Loop M",
            service_mode="HEATING",
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(loop["id"], code="SEG-M1")
        tariff = residential_rate_schedule(code="RS-R")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Maple Court Apartments",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
        )
        point = commissioned_point(agreement["id"], segment["id"], code="MP-M1")
        add_reading(point["id"], "2026-06-01T00:00:00Z", 10.000, 55.0)
        add_reading(point["id"], "2026-06-28T00:00:00Z", 14.000, 60.0)
        add_reading(point["id"], "2026-07-02T00:00:00Z", 15.000, 70.0)
        add_reading(point["id"], "2026-07-29T00:00:00Z", 20.000, 65.0)
        return {"loop": loop, "tariff": tariff, "agreement": agreement, "point": point}

    def test_the_june_invoice_reads_only_the_june_register_window(self):
        """The two July reads sit outside the June period and contribute nothing.

        PRD: "Its input set is every register read whose `point_id` belongs to a
        metering point of this agreement with a `meter_state` of `COMMISSIONED` or
        `REMOVED` — readings taken from a removed meter still count, so that a
        terminated service can still be billed — and whose `read_at` is at or after
        `period_start` and strictly before `period_end`."

        Design: Corner/Validations/adjacent_billing_periods_that_share_a_boundary_are_both_accepted
        """
        stack = self._customer_with_a_two_month_register()

        june = create_invoice(
            stack["agreement"]["id"], self.JUNE_START, self.JUNE_END, "ESTIMATED"
        )

        assert_invoice_determinants(
            june,
            billed_energy_mwh=4.000,
            billed_demand_kw=60.00,
            load_factor_pct=9.26,
            energy_charge=440.00,
            total_amount=3000.00,
            minimum_bill_applied=True,
        )

    def test_the_july_period_starting_on_the_june_boundary_is_accepted(self):
        """A `period_start` equal to the previous `period_end` is not an overlap.

        PRD: "The billing period may not overlap the half-open period of any existing
        invoice for the same agreement whose `invoice_state` is `DRAFT`, `ISSUED`,
        `ADJUSTED` or `PAID`; only a `VOID` invoice's period is available for reuse,
        and an overlap is rejected with `ERR_INVOICE_PERIOD_OVERLAP`."

        Design: Corner/Validations/adjacent_billing_periods_that_share_a_boundary_are_both_accepted
        """
        stack = self._customer_with_a_two_month_register()
        create_invoice(
            stack["agreement"]["id"], self.JUNE_START, self.JUNE_END, "ESTIMATED"
        )

        july = create_invoice(
            stack["agreement"]["id"], self.JUNE_END, self.JULY_END, "ESTIMATED"
        )

        assert_invoice_determinants(
            july,
            billed_energy_mwh=5.000,
            billed_demand_kw=70.00,
            load_factor_pct=9.60,
            energy_charge=550.00,
            total_amount=3000.00,
            invoice_state="DRAFT",
        )

    def test_both_neighbouring_invoices_survive_as_drafts(self):
        """Two invoices, one agreement, no overlap between them.

        PRD: "A newly created invoice opens at `invoice_state` `DRAFT` with
        `paid_amount` 0.0, and creation increments the owning agreement's `version` by
        1 — the calculation read the agreement's determinants, so the agreement is
        considered touched even though none of its own stored values changed."

        Design: Corner/Validations/adjacent_billing_periods_that_share_a_boundary_are_both_accepted
        """
        stack = self._customer_with_a_two_month_register()
        june = create_invoice(
            stack["agreement"]["id"], self.JUNE_START, self.JUNE_END, "ESTIMATED"
        )
        july = create_invoice(
            stack["agreement"]["id"], self.JUNE_END, self.JULY_END, "ESTIMATED"
        )

        listed = _count(
            api_client.list_invoices(
                BILLING_ANALYST, {"agreement_id": stack["agreement"]["id"]}
            )
        )

        assert listed == 2, f"expected two invoices on the agreement, got {listed}"
        assert read_invoice(june["id"])["invoice_state"] == "DRAFT"
        assert read_invoice(july["id"])["invoice_state"] == "DRAFT"


class TestStraddlingPeriodWaitsForTheVoid:
    """The overlap guard counts only invoices that are still on the books."""

    JUNE_START = "2026-06-01T00:00:00Z"
    JUNE_END = "2026-07-01T00:00:00Z"
    STRADDLE_START = "2026-06-15T00:00:00Z"
    STRADDLE_END = "2026-07-15T00:00:00Z"

    def _customer_with_a_draft_june_invoice(self):
        set_clock()
        loop = create_loop(
            code="LOOP-M",
            name="Maple Loop M",
            service_mode="HEATING",
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(loop["id"], code="SEG-M1")
        tariff = residential_rate_schedule(code="RS-R")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Maple Court Apartments",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
        )
        point = commissioned_point(agreement["id"], segment["id"], code="MP-M1")
        add_reading(point["id"], "2026-06-01T00:00:00Z", 10.000, 55.0)
        add_reading(point["id"], "2026-06-28T00:00:00Z", 14.000, 60.0)
        add_reading(point["id"], "2026-07-02T00:00:00Z", 15.000, 70.0)
        add_reading(point["id"], "2026-07-29T00:00:00Z", 20.000, 65.0)
        june = create_invoice(agreement["id"], self.JUNE_START, self.JUNE_END, "ESTIMATED")
        return {"agreement": agreement, "point": point, "june": june}

    def _straddling_attempt(self, agreement_id):
        return api_client.create_invoice(
            {
                "agreement_id": agreement_id,
                "period_start": self.STRADDLE_START,
                "period_end": self.STRADDLE_END,
                "variant": "ESTIMATED",
                "expected_agreement_version": get_success_data(
                    api_client.get_connection_agreement(agreement_id, BILLING_ANALYST)
                )["version"],
            },
            BILLING_ANALYST,
        )

    def test_a_period_straddling_the_june_invoice_is_refused(self):
        """Half of the requested window is already billed by a draft invoice.

        PRD: "The billing period may not overlap the half-open period of any existing
        invoice for the same agreement whose `invoice_state` is `DRAFT`, `ISSUED`,
        `ADJUSTED` or `PAID`; only a `VOID` invoice's period is available for reuse,
        and an overlap is rejected with `ERR_INVOICE_PERIOD_OVERLAP`."

        Design: Corner/Validations/a_straddling_billing_period_is_rejected_until_the_earlier_invoice_is_voided
        """
        stack = self._customer_with_a_draft_june_invoice()

        response = self._straddling_attempt(stack["agreement"]["id"])

        validate_error(response, ApiErrorId.INVOICE_PERIOD_OVERLAP)

    def test_voiding_the_june_invoice_frees_the_very_same_period(self):
        """Nothing about the requested window changed — only June's state did.

        PRD: "`DRAFT → VOID` simply stamps the invoice `VOID` and increments its
        `version` by 1; because a draft invoice never entered the balance, no ledger
        work is needed."

        Design: Corner/Validations/a_straddling_billing_period_is_rejected_until_the_earlier_invoice_is_voided
        """
        stack = self._customer_with_a_draft_june_invoice()
        self._straddling_attempt(stack["agreement"]["id"])

        voided = void_invoice(stack["june"]["id"], "period re-cut across the month end")
        straddling = get_success_data(
            self._straddling_attempt(stack["agreement"]["id"]), 201
        )

        assert voided["invoice_state"] == "VOID"
        assert_invoice_determinants(
            straddling,
            billed_energy_mwh=1.000,
            billed_demand_kw=70.00,
            invoice_state="DRAFT",
        )

    def test_the_agreement_ledger_shows_one_draft_and_one_void(self):
        """The voided period is gone from the live set but still on record.

        PRD: "List invoices, filterable by agreement, lifecycle state and variant."

        Design: Corner/Validations/a_straddling_billing_period_is_rejected_until_the_earlier_invoice_is_voided
        """
        stack = self._customer_with_a_draft_june_invoice()
        void_invoice(stack["june"]["id"], "period re-cut across the month end")
        get_success_data(self._straddling_attempt(stack["agreement"]["id"]), 201)

        drafts = _count(
            api_client.list_invoices(
                BILLING_ANALYST,
                {"agreement_id": stack["agreement"]["id"], "invoice_state": "DRAFT"},
            )
        )
        voids = _count(
            api_client.list_invoices(
                BILLING_ANALYST,
                {"agreement_id": stack["agreement"]["id"], "invoice_state": "VOID"},
            )
        )

        assert drafts == 1, f"expected one draft invoice, got {drafts}"
        assert voids == 1, f"expected one voided invoice, got {voids}"
