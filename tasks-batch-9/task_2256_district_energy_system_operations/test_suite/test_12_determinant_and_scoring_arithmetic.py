"""Boundary arithmetic: merit inputs, tier ladders, bands, sizing and floors."""

from test_helpers import (
    ApiErrorId,
    NETWORK_ENGINEER,
    SYSTEM_CONTROLLER,
    active_agreement,
    add_reading,
    api_client,
    assert_dispatch_order,
    assert_emissions_summary,
    assert_invoice_determinants,
    assert_loop_state,
    assert_plan_metrics,
    assert_project_economics,
    assert_segment_condition,
    assess_segment,
    campus_dispatch_stack,
    commercial_rate_schedule,
    commissioned_point,
    create_invoice,
    create_loop,
    create_plan,
    create_project,
    create_segment,
    decide_project,
    get_success_data,
    optimize_plan,
    orders_by_rank,
    plan_orders,
    plan_review_payload,
    read_invoice,
    read_loop,
    read_plan,
    read_project,
    residential_rate_schedule,
    set_availability,
    set_clock,
    size_project,
    submit_plan,
    validate_error,
    void_invoice,
)


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


class TestMeritOrderInputSetWithOneMachineOut:
    """One boiler in outage rewrites both the merit list and the reserve metric."""

    def _campus_without_its_biomass_boiler(self):
        stack = campus_dispatch_stack()
        set_availability(
            stack["biomass_boiler"]["id"], "OUTAGE", reason="tube leak, unit off line"
        )
        plan = create_plan(stack["loop"]["id"], stack["forecast"]["id"])
        optimize_plan(plan["id"])
        stack["plan"] = read_plan(plan["id"])
        return stack

    def test_the_machine_left_in_outage_never_enters_the_merit_list(self):
        """Three orders come back and none of them belongs to the biomass boiler.

        PRD: "The eligible asset set is every production asset on the plan's loop
        whose `availability_state` is `AVAILABLE` or `DERATED` and whose
        `fuel_contract_id` is either null or names a contract whose `status` is
        `ACTIVE` or `SUSPENDED`."

        Design: Corner/Calculations/merit_order_input_set_skips_an_asset_left_in_outage
        """
        stack = self._campus_without_its_biomass_boiler()

        orders = orders_by_rank(plan_orders(stack["plan"]["id"]))

        assert len(orders) == 3, f"expected three dispatch orders, got {len(orders)}"
        assert all(
            order["asset_id"] != stack["biomass_boiler"]["id"] for order in orders
        ), "the outaged biomass boiler must not appear in any dispatch order"
        assert_dispatch_order(
            orders[0], asset_id=stack["storage"]["id"], merit_rank=1, allocated_kw=1000.00
        )
        assert_dispatch_order(
            orders[1], asset_id=stack["chp"]["id"], merit_rank=2, allocated_kw=1200.00
        )

    def test_the_oil_boiler_inherits_the_third_rank_and_the_tail_of_the_demand(self):
        """The dearest, dirtiest machine picks up the 327.20 kW the others left.

        PRD: "`order_emissions_kg` is `block_energy_mwh` multiplied by the asset's
        `emission_factor_kg_per_mwh`, rounded half-up to two decimal places."

        Design: Corner/Calculations/merit_order_input_set_skips_an_asset_left_in_outage
        """
        stack = self._campus_without_its_biomass_boiler()

        orders = orders_by_rank(plan_orders(stack["plan"]["id"]))

        assert_dispatch_order(
            orders[2],
            asset_id=stack["oil_boiler"]["id"],
            merit_rank=3,
            allocated_kw=327.20,
            block_energy_mwh=7.853,
            discharged_kwh=0.00,
            order_cost=706.77,
            order_emissions_kg=2041.78,
        )
        assert_plan_metrics(
            stack["plan"],
            allocated_capacity_kw=2527.20,
            unserved_demand_kw=0.00,
            total_dispatch_cost=1882.77,
            total_emissions_kg=7945.78,
        )

    def test_the_thinner_fleet_turns_the_reserve_margin_negative(self):
        """Losing 1500 kW of eligible capacity takes N-1 below the demand itself.

        PRD: "The available capacity is the sum of the effective capacity of every
        eligible asset, using exactly the same effective-capacity rule as the
        waterfall, rounded half-up to two decimal places."

        Design: Corner/Calculations/merit_order_input_set_skips_an_asset_left_in_outage
        """
        stack = self._campus_without_its_biomass_boiler()

        assert_plan_metrics(
            stack["plan"], reserve_margin_pct=-12.95, fuel_diversity_hhi=0.5489
        )

    def test_the_plan_can_be_submitted_but_not_approved(self):
        """Submission ignores the margin; approval is the gate that reads it.

        PRD: "the plan's `reserve_margin_pct` must be at or above 15.00 percent, or
        the approval is refused with `ERR_RESERVE_MARGIN_INSUFFICIENT`".

        Design: Corner/Calculations/merit_order_input_set_skips_an_asset_left_in_outage
        """
        stack = self._campus_without_its_biomass_boiler()
        submitted = submit_plan(stack["plan"]["id"], "biomass boiler out, please review")
        assert_plan_metrics(submitted, plan_state="SUBMITTED")

        response = api_client.review_dispatch_plan(
            stack["plan"]["id"],
            plan_review_payload("APPROVE", review_note="cover accepted"),
            SYSTEM_CONTROLLER,
        )

        validate_error(response, ApiErrorId.RESERVE_MARGIN_INSUFFICIENT)
        assert_plan_metrics(
            read_plan(stack["plan"]["id"]),
            plan_state="SUBMITTED",
            reviewed_by_user_id=None,
        )


class TestLoadFactorTierLadderAtThirtyPercent:
    """The first tier closes at a load factor of 30; the ladder is walked upward."""

    PERIOD_START = "2026-06-01T00:00:00Z"
    PERIOD_END = "2026-07-01T00:00:00Z"

    def _billed_customer(self):
        set_clock()
        loop = create_loop(
            code="LOOP-T",
            name="Tramway Loop T",
            service_mode="DUAL",
            rated_capacity_kw=8000.0,
        )
        segment = create_segment(loop["id"], code="SEG-T1")
        tariff = commercial_rate_schedule(code="RS-T")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Tramway Offices",
            reserved_capacity_kw=4000.0,
        )
        point = commissioned_point(agreement["id"], segment["id"], code="MP-T1")
        add_reading(point["id"], "2026-06-01T00:00:00Z", 1000.000, 1500.0)
        add_reading(point["id"], "2026-06-30T00:00:00Z", 1432.000, 1500.0)
        return {
            "loop": loop,
            "tariff": tariff,
            "agreement": agreement,
            "point": point,
        }

    def test_a_load_factor_of_exactly_thirty_takes_the_first_tier(self):
        """432.000 MWh against 2000.00 kW over 720 hours lands on 30.00 exactly.

        PRD: "The tier applied is the first entry of the tariff's `tiers`, walked in
        `load_factor_max` ascending order, whose `load_factor_max` is greater than or
        equal to `load_factor_pct`; when no entry qualifies, the last entry — the
        fallback tier — is used."

        Design: Corner/Calculations/load_factor_tier_ladder_switches_one_hundredth_of_a_point_above_thirty
        """
        stack = self._billed_customer()

        invoice = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )

        assert_invoice_determinants(
            invoice,
            billed_energy_mwh=432.000,
            billed_demand_kw=2000.00,
            load_factor_pct=30.00,
            energy_charge=38016.00,
            demand_charge=24000.00,
            fixed_charge=800.00,
            total_amount=62816.00,
            minimum_bill_applied=False,
            variant_applied="ESTIMATED",
        )

    def test_one_hundredth_of_a_point_higher_drops_to_the_second_tier(self):
        """A tenth of a megawatt-hour more energy moves 432 MWh onto the 74.00 rate.

        PRD: "`energy_charge` is `billed_energy_mwh` multiplied by that tier's
        `energy_rate_per_mwh`, rounded half-up to two decimal places."

        Design: Corner/Calculations/load_factor_tier_ladder_switches_one_hundredth_of_a_point_above_thirty
        """
        stack = self._billed_customer()
        boundary = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )
        void_invoice(boundary["id"], "re-billing on a corrected register history")
        add_reading(stack["point"]["id"], "2026-06-30T12:00:00Z", 1432.100, 1500.0)

        rebilled = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )

        assert read_invoice(boundary["id"])["invoice_state"] == "VOID"
        assert_invoice_determinants(
            rebilled,
            billed_energy_mwh=432.100,
            billed_demand_kw=2000.00,
            load_factor_pct=30.01,
            energy_charge=31975.40,
            demand_charge=24000.00,
            fixed_charge=800.00,
            total_amount=56775.40,
            minimum_bill_applied=False,
        )

    def test_the_cheaper_tier_more_than_offsets_the_extra_energy(self):
        """More energy for 6040.60 less money is the point of a declining ladder.

        PRD: "The three charges are added and the sum rounded half-up to two decimal
        places to give a subtotal, and **the subtotal is rounded before the
        minimum-bill comparison**."

        Design: Corner/Calculations/load_factor_tier_ladder_switches_one_hundredth_of_a_point_above_thirty
        """
        stack = self._billed_customer()
        boundary = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )
        void_invoice(boundary["id"], "re-billing on a corrected register history")
        add_reading(stack["point"]["id"], "2026-06-30T12:00:00Z", 1432.100, 1500.0)
        rebilled = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )

        difference = round(boundary["total_amount"] - rebilled["total_amount"], 2)

        assert difference == 6040.60, (
            f"expected the tier switch to cut 6040.60, got {difference}"
        )
        assert rebilled["billed_energy_mwh"] > boundary["billed_energy_mwh"], (
            "the re-billed invoice should carry the larger consumption delta"
        )


class TestLeakRiskScoreOnTheSuspectFloor:
    """Two sixty-year-old runs, four hundredths of a point apart, band differently."""

    def _two_surveyed_segments(self):
        set_clock()
        loop = create_loop(
            code="LOOP-R",
            name="Riverbank Loop R",
            service_mode="HEATING",
            rated_capacity_kw=9000.0,
        )
        on_the_floor = create_segment(
            loop["id"], code="SEG-R1", install_year=1966, insulation_class="B"
        )
        below_the_floor = create_segment(
            loop["id"], code="SEG-R2", install_year=1966, insulation_class="B"
        )
        assess_segment(
            on_the_floor["id"], 0.02486, 2, "B", survey_note="acoustic survey, June"
        )
        assess_segment(
            below_the_floor["id"], 0.02480, 2, "B", survey_note="acoustic survey, June"
        )
        return {
            "loop": loop,
            "on_the_floor": on_the_floor,
            "below_the_floor": below_the_floor,
        }

    def test_a_score_landing_exactly_on_seventy_bands_as_suspect(self):
        """35.00 plus 14.916 plus 13.334 plus 6.75 is 70.00 to the cent.

        PRD: "The band follows from the score with inclusive floors: a score at or
        above 70.0 is `SUSPECT`, a score at or above 45.0 but below 70.0 is
        `MONITORED`, and anything below 45.0 is `SOUND`."

        Design: Corner/Calculations/leak_risk_weighted_score_lands_exactly_on_the_suspect_floor
        """
        stack = self._two_surveyed_segments()

        assert_segment_condition(
            _read_segment(stack["on_the_floor"]["id"]),
            condition="SUSPECT",
            leak_risk_score=70.00,
            makeup_water_ratio=0.02486,
            historical_leak_count=2,
        )

    def test_four_hundredths_of_a_point_lower_bands_as_monitored(self):
        """The same pipe with a whisker less makeup water stays out of SUSPECT.

        PRD: "The **makeup-water component** takes the `makeup_water_ratio` divided
        by a full-penalty ratio of 0.05, capped at 1, multiplied by 100; a loop losing
        five percent of its circulating volume as makeup water scores the full 100."

        Design: Corner/Calculations/leak_risk_weighted_score_lands_exactly_on_the_suspect_floor
        """
        stack = self._two_surveyed_segments()

        assert_segment_condition(
            _read_segment(stack["below_the_floor"]["id"]),
            condition="MONITORED",
            leak_risk_score=69.96,
            makeup_water_ratio=0.02480,
            historical_leak_count=2,
        )

    def test_only_the_segment_on_the_floor_counts_against_the_loop(self):
        """One of the two surveys crossed the band edge, so the counter reads one.

        PRD: "`SOUND → SUSPECT` and `MONITORED → SUSPECT` each increment the loop's
        `suspect_segment_count` by 1 and increment the loop's `version` by 1."

        Design: Corner/Calculations/leak_risk_weighted_score_lands_exactly_on_the_suspect_floor
        """
        stack = self._two_surveyed_segments()

        assert_loop_state(
            read_loop(stack["loop"]["id"]), posture="NORMAL", suspect_segment_count=1
        )


class TestLoopEmissionsSummaryAgainstTheCityTarget:
    """Only committed production counts toward the municipal intensity target."""

    def _committed_loop_with_a_draft_alongside(self):
        stack = campus_dispatch_stack(plan_state="COMMITTED")
        stack["draft"] = create_plan(stack["loop"]["id"], stack["forecast"]["id"])
        return stack

    def _summary(self, loop_id):
        return get_success_data(
            api_client.get_emissions_summary(loop_id, SYSTEM_CONTROLLER)
        )

    def test_only_the_committed_plan_enters_the_contributing_set(self):
        """A second plan sits in DRAFT on the same loop and is passed over.

        PRD: "drawing only on dispatch plans on the loop whose `plan_state` is
        `COMMITTED` or `RECONCILED`; plans in `DRAFT`, `SUBMITTED`, `APPROVED` or
        `SUPERSEDED` are excluded, because only committed production actually burned
        fuel."

        Design: Corner/Calculations/loop_emissions_summary_reports_efficiency_and_intensity_against_the_city_target
        """
        stack = self._committed_loop_with_a_draft_alongside()
        assert_plan_metrics(read_plan(stack["draft"]["id"]), plan_state="DRAFT")
        assert_plan_metrics(read_plan(stack["plan"]["id"]), plan_state="COMMITTED")

        summary = self._summary(stack["loop"]["id"])

        assert_emissions_summary(
            summary,
            contributing_plan_count=1,
            total_energy_mwh=40.653,
            total_emissions_kg=6123.88,
        )
        assert summary["loop_id"] == stack["loop"]["id"], (
            "the summary must echo the loop it was computed for"
        )

    def test_the_delivered_intensity_sits_above_the_hundred_and_fifty_target(self):
        """Eight percent of the block is lost in the pipes before the ratio is taken.

        PRD: "`emissions_intensity_kg_per_mwh` is `total_emissions_kg` divided by
        `delivered_energy_mwh`, rounded half-up to two decimal places, and is reported
        as 0.0 when `delivered_energy_mwh` is exactly zero."

        Design: Corner/Calculations/loop_emissions_summary_reports_efficiency_and_intensity_against_the_city_target
        """
        stack = self._committed_loop_with_a_draft_alongside()

        summary = self._summary(stack["loop"]["id"])

        assert_emissions_summary(
            summary,
            delivered_energy_mwh=37.401,
            system_efficiency_pct=92.00,
            emissions_intensity_kg_per_mwh=163.74,
            target_gap_kg_per_mwh=13.74,
            climate_goal_status="EXCEEDING",
        )

    def test_the_summary_read_moves_nothing_on_the_loop_or_the_plan(self):
        """A pure read leaves both the posture block and the plan metrics alone.

        PRD: "The summary is a pure read: it persists nothing and mutates nothing."

        Design: Corner/Calculations/loop_emissions_summary_reports_efficiency_and_intensity_against_the_city_target
        """
        stack = self._committed_loop_with_a_draft_alongside()
        before = read_loop(stack["loop"]["id"])

        self._summary(stack["loop"]["id"])
        self._summary(stack["loop"]["id"])

        after = read_loop(stack["loop"]["id"])
        assert after["version"] == before["version"], (
            f"loop version moved from {before['version']} to {after['version']}"
        )
        assert_loop_state(
            after,
            posture="NORMAL",
            committed_reserved_kw=3000.0,
            open_isolation_count=0,
            suspect_segment_count=0,
        )


class TestExpansionSizingAndAnnuity:
    """The smallest diameter that survives both hydraulic limits sets the capex."""

    def _screened_project(self):
        set_clock()
        loop = create_loop(
            code="LOOP-X",
            name="Northgate Loop X",
            service_mode="HEATING",
            rated_capacity_kw=12000.0,
        )
        tariff = commercial_rate_schedule(code="RS-X")
        project = create_project(loop["id"], tariff["id"])
        return {"loop": loop, "tariff": tariff, "project": project}

    def test_the_screened_project_carries_no_diameter_yet(self):
        """Sizing outputs are all empty until the engineer runs the hydraulics.

        PRD: "The project opens with `selected_diameter_mm` null,
        `design_flow_m3_per_h` 0.0, `estimated_capex` 0.0, `annual_net_margin` 0.0 and
        `npv` 0.0."

        Design: Corner/Calculations/expansion_sizing_picks_the_smallest_feasible_diameter_and_prices_the_annuity
        """
        stack = self._screened_project()

        assert_project_economics(
            stack["project"],
            project_state="SCREENING",
            selected_diameter_mm=None,
            design_flow_m3_per_h=0.0,
            estimated_capex=0.0,
            annual_net_margin=0.0,
            npv=0.0,
        )

    def test_sizing_rejects_eighty_millimetres_on_pressure_drop_and_takes_a_hundred(self):
        """80 mm passes the velocity limit but drops 253.97 kPa per kilometre.

        PRD: "A diameter is feasible when its velocity is at or below 2.0 metres per
        second **and** its pressure drop is at or below 100.0 kilopascals per
        kilometre."

        Design: Corner/Calculations/expansion_sizing_picks_the_smallest_feasible_diameter_and_prices_the_annuity
        """
        stack = self._screened_project()

        sized = size_project(stack["project"]["id"])

        assert_project_economics(
            sized,
            project_state="SIZED",
            selected_diameter_mm=100,
            design_flow_m3_per_h=25.795,
            estimated_capex=892500.00,
        )

    def test_the_capitalised_margin_prices_the_connection_and_clears_approval(self):
        """A 256687.50 annual margin against a pinned annuity factor beats the capex.

        PRD: "Rather than looping year by year, the margin is capitalised against a
        pinned present-value annuity factor of 11.46992122: `npv` is the
        `annual_net_margin` multiplied by that factor, less the `estimated_capex`,
        rounded half-up to two decimal places."

        Design: Corner/Calculations/expansion_sizing_picks_the_smallest_feasible_diameter_and_prices_the_annuity
        """
        stack = self._screened_project()
        size_project(stack["project"]["id"])

        decided = decide_project(
            stack["project"]["id"], "APPROVE", decision_note="proceed to conversion"
        )

        assert_project_economics(
            read_project(stack["project"]["id"]),
            annual_net_margin=256687.50,
            npv=2051685.40,
        )
        assert_project_economics(decided, project_state="APPROVED")


class TestMinimumBillFloorReplacesTheSubtotal:
    """A small apartment block pays the tariff's floor rather than its own usage."""

    PERIOD_START = "2026-06-01T00:00:00Z"
    PERIOD_END = "2026-07-01T00:00:00Z"

    def _small_residential_customer(self):
        set_clock()
        loop = create_loop(
            code="LOOP-M",
            name="Maple Loop M",
            service_mode="HEATING",
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(loop["id"], code="SEG-M1")
        tariff = residential_rate_schedule(code="RS-M")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Maple Court Apartments",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
        )
        point = commissioned_point(agreement["id"], segment["id"], code="MP-M1")
        add_reading(point["id"], "2026-06-01T00:00:00Z", 10.000, 55.0)
        add_reading(point["id"], "2026-06-30T00:00:00Z", 14.000, 60.0)
        return {"loop": loop, "tariff": tariff, "agreement": agreement, "point": point}

    def test_every_charge_component_is_computed_before_the_floor_is_considered(self):
        """4.000 MWh at 110.00, 60.00 kW at 6.00 and a 250.00 standing charge.

        PRD: "`demand_charge` is `billed_demand_kw` multiplied by the tariff's
        `demand_charge_per_kw`, rounded half-up to two decimal places."

        Design: Corner/Calculations/minimum_bill_floor_replaces_a_smaller_computed_subtotal
        """
        stack = self._small_residential_customer()

        invoice = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )

        assert_invoice_determinants(
            invoice,
            billed_energy_mwh=4.000,
            billed_demand_kw=60.00,
            load_factor_pct=9.26,
            energy_charge=440.00,
            demand_charge=360.00,
            fixed_charge=250.00,
        )

    def test_the_floor_replaces_the_smaller_subtotal_and_raises_the_flag(self):
        """A 1050.00 subtotal is billed as the tariff's 3000.00 minimum instead.

        PRD: "If that subtotal is strictly less than the tariff's
        `minimum_bill_amount`, `total_amount` becomes the `minimum_bill_amount` and
        `minimum_bill_applied` is set to true; otherwise `total_amount` is the subtotal
        and `minimum_bill_applied` is false."

        Design: Corner/Calculations/minimum_bill_floor_replaces_a_smaller_computed_subtotal
        """
        stack = self._small_residential_customer()

        invoice = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )

        components = round(
            invoice["energy_charge"] + invoice["demand_charge"] + invoice["fixed_charge"], 2
        )
        assert components == 1050.00, (
            f"expected the three charges to sum to 1050.00, got {components}"
        )
        assert_invoice_determinants(
            invoice,
            total_amount=3000.00,
            minimum_bill_applied=True,
            invoice_state="DRAFT",
            paid_amount=0.0,
        )
