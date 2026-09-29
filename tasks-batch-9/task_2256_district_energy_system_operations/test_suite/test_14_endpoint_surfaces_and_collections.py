"""Round trips, action endpoints, computed reads and discriminating collections."""

from test_helpers import (
    ApiErrorId,
    BILLING_ANALYST,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    NETWORK_ENGINEER,
    SYSTEM_CONTROLLER,
    active_agreement,
    add_reading,
    api_client,
    assert_agreement_state,
    assert_common_fields,
    assert_emissions_summary,
    assert_envelope_meta,
    assert_pagination_meta,
    assert_plan_metrics,
    assert_read_at_ascending,
    commercial_rate_schedule,
    commission_point,
    commissioned_point,
    convert_project_payload,
    create_asset,
    create_forecast,
    create_fuel_contract,
    create_loop,
    create_plan,
    create_point,
    create_project,
    create_segment,
    create_work_order,
    decide_project,
    get_success_data,
    meter_reading_payload,
    metering_point_payload,
    plan_in_state,
    published_forecast,
    read_project,
    remove_point,
    set_clock,
    set_fuel_contract_status,
    size_project,
    submit_permit,
    university_rate_schedule,
    validate_error,
    validate_paginated,
    validate_success,
    work_order_payload,
)


def _page(response):
    return validate_paginated(response)


def _count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


def _read_point(point_id):
    return get_success_data(api_client.get_metering_point(point_id, FIELD_TECHNICIAN))


class TestFuelSupplyContractRoundTrip:
    """Create, read one and list: the contract has no update or delete surface."""

    def _three_contracts(self):
        set_clock()
        gas = create_fuel_contract(
            supplier_code="FC-GAS-1",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=40000.0,
            price_per_mwh=34.50,
            delivery_firmness="FIRM",
        )
        peaking_gas = create_fuel_contract(
            supplier_code="FC-GAS-2",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=12000.0,
            price_per_mwh=31.00,
            delivery_firmness="INTERRUPTIBLE",
        )
        biomass = create_fuel_contract(
            supplier_code="FC-BIO-1",
            fuel_type="BIOMASS",
            contracted_energy_mwh_per_year=9000.0,
            price_per_mwh=45.00,
            delivery_firmness="FIRM",
        )
        return {"gas": gas, "peaking_gas": peaking_gas, "biomass": biomass}

    def test_a_registered_contract_opens_active_at_version_one(self):
        """The declared opening status is the only status a create can produce.

        PRD: "The contract opens at `status` `ACTIVE`."

        Design: Corner/Endpoints/fuel_supply_contract_create_read_and_filtered_list_round_trip
        """
        stack = self._three_contracts()

        assert stack["gas"]["status"] == "ACTIVE"
        assert stack["gas"]["delivery_firmness"] == "FIRM"
        assert_common_fields(stack["gas"], expected_version=1)

    def test_reading_the_first_contract_back_is_unaffected_by_later_writes(self):
        """Two further creates and a status change elsewhere leave row one alone.

        PRD: "A `SystemController` registers a **FuelSupplyContract** with a
        `supplier_code` unique across all contracts, a `fuel_type` drawn from
        `NATURAL_GAS`, `BIOMASS`, `ELECTRICITY`, `WASTE_HEAT` and `FUEL_OIL`, a
        `contracted_energy_mwh_per_year` giving the firm annual contracted energy in
        MWh which must be greater than zero, a `price_per_mwh` giving the delivered
        price, and a `delivery_firmness` of either `FIRM` or `INTERRUPTIBLE`."

        Design: Corner/Endpoints/fuel_supply_contract_create_read_and_filtered_list_round_trip
        """
        stack = self._three_contracts()
        suspended = set_fuel_contract_status(
            stack["biomass"]["id"], "SUSPENDED", reason="supplier plant outage"
        )

        again = get_success_data(
            api_client.get_fuel_supply_contract(stack["gas"]["id"], SYSTEM_CONTROLLER)
        )

        assert suspended["status"] == "SUSPENDED"
        assert again["supplier_code"] == "FC-GAS-1"
        assert again["price_per_mwh"] == 34.50
        assert again["version"] == 1, (
            f"an untouched contract should still be at version 1, got {again['version']}"
        )

    def test_the_collection_returns_all_three_rows_in_one_window(self):
        """Three contracts fit inside the default window, so nothing remains beyond.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        size of the filtered result set before the window is applied and `has_more`
        indicates whether items remain beyond the window."

        Design: Corner/Endpoints/fuel_supply_contract_create_read_and_filtered_list_round_trip
        """
        self._three_contracts()

        response = api_client.list_fuel_supply_contracts(SYSTEM_CONTROLLER)

        rows, meta = _page(response)
        assert len(rows) == 3, f"expected three contracts in the window, got {len(rows)}"
        assert_pagination_meta(meta, total_count=3, has_more=False)
        assert_envelope_meta(response.json())

    def test_the_declared_contract_filters_narrow_the_result_set(self):
        """Fuel type alone keeps two rows; status with firmness keeps one.

        PRD: "Fuel supply contracts filter on `fuel_type`, `status` and
        `delivery_firmness`."

        Design: Corner/Endpoints/fuel_supply_contract_create_read_and_filtered_list_round_trip
        """
        stack = self._three_contracts()
        set_fuel_contract_status(
            stack["biomass"]["id"], "SUSPENDED", reason="supplier plant outage"
        )

        by_fuel = _count(
            api_client.list_fuel_supply_contracts(
                SYSTEM_CONTROLLER, {"fuel_type": "NATURAL_GAS"}
            )
        )
        firm_and_active = _page(
            api_client.list_fuel_supply_contracts(
                SYSTEM_CONTROLLER, {"status": "ACTIVE", "delivery_firmness": "FIRM"}
            )
        )

        assert by_fuel == 2, f"two contracts are natural gas, got {by_fuel}"
        rows, meta = firm_and_active
        assert_pagination_meta(meta, total_count=1)
        assert rows[0]["supplier_code"] == "FC-GAS-1", (
            "the interruptible contract and the suspended one must both drop out"
        )


class TestMeteringPointRemovalLocksTheRegister:
    """Removal is terminal, and the banked reading survives it."""

    def _removed_point(self):
        set_clock()
        loop = create_loop(
            code="LOOP-T",
            name="Tanner Loop T",
            service_mode="HEATING",
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(loop["id"], code="SEG-T1")
        tariff = university_rate_schedule(code="RS-U")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Tanner College",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=800.0,
        )
        point = create_point(agreement["id"], segment["id"], code="MP-T1")
        installed_state = point["meter_state"]
        commissioned = commission_point(point["id"])
        reading = add_reading(point["id"], "2026-06-10T00:00:00Z", 42.500, 900.0)
        return {
            "loop": loop,
            "segment": segment,
            "agreement": agreement,
            "point": point,
            "installed_state": installed_state,
            "commissioned_state": commissioned["meter_state"],
            "reading": reading,
        }

    def test_the_point_walks_installed_then_commissioned_then_removed(self):
        """Two source states are permitted and this one arrives from COMMISSIONED.

        PRD: "Exactly two source states are permitted — `INSTALLED` and
        `COMMISSIONED` — and they behave identically: a `COMMISSIONED → REMOVED`
        removal and an `INSTALLED → REMOVED` removal each simply set `meter_state` to
        `REMOVED` and increment the point's `version` by 1."

        Design: Corner/Endpoints/metering_point_removal_action_locks_out_further_register_reads
        """
        stack = self._removed_point()
        assert stack["installed_state"] == "INSTALLED"
        assert stack["commissioned_state"] == "COMMISSIONED"

        removed = remove_point(stack["point"]["id"])

        assert removed["meter_state"] == "REMOVED"
        assert removed["last_reading_energy_mwh"] == 42.500
        assert removed["reading_count"] == 1

    def test_a_further_register_read_on_a_removed_point_is_refused(self):
        """Recording is gated on COMMISSIONED and REMOVED is not it.

        PRD: "Recording a register read requires the point to be `COMMISSIONED`;
        attempting it in any other state is rejected with `ERR_METER_STATE_INVALID`."

        Design: Corner/Endpoints/metering_point_removal_action_locks_out_further_register_reads
        """
        stack = self._removed_point()
        remove_point(stack["point"]["id"])

        response = api_client.create_meter_reading(
            stack["point"]["id"],
            meter_reading_payload("2026-06-20T00:00:00Z", 55.000, 950.0),
            FIELD_TECHNICIAN,
        )

        validate_error(response, ApiErrorId.METER_STATE_INVALID)

    def test_a_removed_point_cannot_be_commissioned_again(self):
        """There is no route back out of the terminal state.

        PRD: "Removing a point that is already `REMOVED` is rejected with
        `ERR_METER_STATE_INVALID`."

        Design: Corner/Endpoints/metering_point_removal_action_locks_out_further_register_reads
        """
        stack = self._removed_point()
        remove_point(stack["point"]["id"])

        response = api_client.commission_metering_point(
            stack["point"]["id"], {}, FIELD_TECHNICIAN
        )

        validate_error(response, ApiErrorId.METER_STATE_INVALID)
        assert _read_point(stack["point"]["id"])["meter_state"] == "REMOVED"

    def test_the_reading_banked_before_removal_stays_readable(self):
        """Register history is append-only, so removal erases nothing.

        PRD: "Recording a reading raises the point's `last_reading_energy_mwh` to the
        new `cumulative_energy_mwh`, increments `reading_count` by 1 and increments the
        point's `version` by 1."

        Design: Corner/Endpoints/metering_point_removal_action_locks_out_further_register_reads
        """
        stack = self._removed_point()
        remove_point(stack["point"]["id"])

        banked = get_success_data(
            api_client.get_meter_reading(stack["reading"]["id"], FIELD_TECHNICIAN)
        )

        assert banked["cumulative_energy_mwh"] == 42.500
        assert (
            _count(
                api_client.list_point_readings(stack["point"]["id"], FIELD_TECHNICIAN)
            )
            == 1
        ), "the point's register history should still hold its single read"


class TestLinkedReferencesMustAgreeOnTheOwningLoop:
    """Two endpoints, two different field pairs, one consistency rule."""

    def _two_loops_with_a_customer_on_the_first(self):
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
        tariff = university_rate_schedule(code="RS-U")
        return {
            "first_loop": first,
            "second_loop": second,
            "first_segment": create_segment(first["id"], code="SEG-Y1"),
            "second_segment": create_segment(second["id"], code="SEG-Y2"),
            "tariff": tariff,
            "agreement": active_agreement(
                first["id"],
                tariff["id"],
                customer_name="Yardley College",
                customer_class="UNIVERSITY",
                reserved_capacity_kw=600.0,
            ),
        }

    def test_a_work_order_naming_a_segment_from_another_loop_is_refused(self):
        """The stated loop and the segment's own loop have to be the same row.

        PRD: "It supplies the `segment_id` being worked, the `loop_id` the segment
        belongs to — which must equal the segment's own loop, or the create is rejected
        with `ERR_SEGMENT_LOOP_MISMATCH` — a `work_type` of `LEAK_REPAIR`, `INSPECTION`
        or `VALVE_REPLACEMENT`, a `window_start` and `window_end` bounding the requested
        work window inclusively at both ends, and an optional `requires_isolation` flag
        defaulting to false that declares whether the segment must be hydraulically
        isolated for the work."

        Design: Corner/Endpoints/work_order_and_metering_point_links_must_agree_on_the_owning_loop
        """
        stack = self._two_loops_with_a_customer_on_the_first()

        response = api_client.create_work_order(
            work_order_payload(
                stack["second_segment"]["id"],
                stack["first_loop"]["id"],
                "2026-09-10T08:00:00Z",
                "2026-09-10T18:00:00Z",
                work_type="INSPECTION",
            ),
            FIELD_TECHNICIAN,
        )

        validate_error(response, ApiErrorId.SEGMENT_LOOP_MISMATCH)

    def test_a_meter_tapped_into_another_loops_segment_is_refused(self):
        """Same error, reached from the agreement-and-segment pair instead.

        PRD: "The meter's segment and its agreement must sit on the same loop; a meter
        tapped into a segment belonging to a different loop from the one supplying its
        agreement is rejected with `ERR_SEGMENT_LOOP_MISMATCH`."

        Design: Corner/Endpoints/work_order_and_metering_point_links_must_agree_on_the_owning_loop
        """
        stack = self._two_loops_with_a_customer_on_the_first()

        response = api_client.create_metering_point(
            metering_point_payload(
                stack["agreement"]["id"], stack["second_segment"]["id"], code="MP-Y9"
            ),
            FIELD_TECHNICIAN,
        )

        validate_error(response, ApiErrorId.SEGMENT_LOOP_MISMATCH)

    def test_the_consistent_pair_stores_both_references_on_each_endpoint(self):
        """With the references agreeing, both creates land and keep their links.

        PRD: "The order opens in `DRAFT` with `permit_decision` `PENDING`,
        `reported_by_user_id` taken from the acting `X-User-ID` and
        `completed_by_user_id` null."

        Design: Corner/Endpoints/work_order_and_metering_point_links_must_agree_on_the_owning_loop
        """
        stack = self._two_loops_with_a_customer_on_the_first()

        order = create_work_order(
            stack["first_segment"]["id"],
            stack["first_loop"]["id"],
            "2026-09-10T08:00:00Z",
            "2026-09-10T18:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="INSPECTION",
        )
        point = create_point(
            stack["agreement"]["id"], stack["first_segment"]["id"], code="MP-Y1"
        )

        assert order["segment_id"] == stack["first_segment"]["id"]
        assert order["loop_id"] == stack["first_loop"]["id"]
        assert order["reported_by_user_id"] == "tech-1"
        assert order["work_state"] == "DRAFT"
        assert point["segment_id"] == stack["first_segment"]["id"]
        assert point["agreement_id"] == stack["agreement"]["id"]
        assert point["meter_state"] == "INSTALLED"
        assert (
            _count(
                api_client.list_work_orders(
                    FIELD_TECHNICIAN, {"loop_id": stack["first_loop"]["id"]}
                )
            )
            == 1
        ), "only the consistent work order should be on the loop"
        assert (
            _count(
                api_client.list_metering_points(
                    FIELD_TECHNICIAN, {"agreement_id": stack["agreement"]["id"]}
                )
            )
            == 1
        ), "only the consistent metering point should be on the agreement"


class TestEmissionsSummaryAggregatesEveryCommittedPlan:
    """The computed read sums across plans rather than reporting the latest."""

    def _loop_with_two_committed_plans(self):
        set_clock()
        loop = create_loop(
            code="LOOP-W",
            name="Westbrook Loop W",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
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
        first_forecast = published_forecast(
            loop["id"], "2026-08-05T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        first_plan = plan_in_state("COMMITTED", loop["id"], first_forecast["id"])
        second_forecast = published_forecast(
            loop["id"], "2026-08-06T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        second_plan = plan_in_state("COMMITTED", loop["id"], second_forecast["id"])
        return {
            "loop": loop,
            "agreement": agreement,
            "first_plan": first_plan,
            "second_plan": second_plan,
        }

    def test_both_plans_burn_the_same_fuel_and_reach_committed(self):
        """Each day dispatches 18.144 MWh at 2368.32 kg of carbon dioxide.

        PRD: "The plan's roll-ups take the already-rounded per-order figures and round
        each total half-up to two decimal places: `allocated_capacity_kw` is the sum of
        every order's `allocated_kw`, `total_dispatch_cost` the sum of every
        `order_cost`, and `total_emissions_kg` the sum of every `order_emissions_kg`."

        Design: Corner/Endpoints/emissions_summary_computed_read_aggregates_every_committed_plan_on_the_loop
        """
        stack = self._loop_with_two_committed_plans()

        for plan in (stack["first_plan"], stack["second_plan"]):
            assert_plan_metrics(
                plan,
                plan_state="COMMITTED",
                allocated_capacity_kw=756.00,
                total_dispatch_cost=561.41,
                total_emissions_kg=2368.32,
            )

    def test_the_summary_sums_both_plans_and_reports_compliance(self):
        """Two days of the same clean mix land 8.12 kg below the city target.

        PRD: "`target_gap_kg_per_mwh` is that intensity less the city target of 150.0
        kilograms of CO2e per delivered MWh, rounded half-up to two decimal places, and
        `climate_goal_status` reads `COMPLIANT` when the gap is at or below 0.0 and
        `EXCEEDING` when it is above 0.0."

        Design: Corner/Endpoints/emissions_summary_computed_read_aggregates_every_committed_plan_on_the_loop
        """
        stack = self._loop_with_two_committed_plans()

        summary = get_success_data(
            api_client.get_emissions_summary(stack["loop"]["id"], NETWORK_ENGINEER)
        )

        assert_emissions_summary(
            summary,
            contributing_plan_count=2,
            total_energy_mwh=36.288,
            total_emissions_kg=4736.64,
            delivered_energy_mwh=33.385,
            system_efficiency_pct=92.00,
            emissions_intensity_kg_per_mwh=141.88,
            target_gap_kg_per_mwh=-8.12,
            climate_goal_status="COMPLIANT",
        )


class TestConversionIsAllowedOnlyFromApproved:
    """A sized project is too early and a converted one is too late."""

    def _sized_project(self):
        set_clock()
        loop = create_loop(
            code="LOOP-X",
            name="Northgate Loop X",
            service_mode="HEATING",
            rated_capacity_kw=12000.0,
        )
        tariff = commercial_rate_schedule(code="RS-C")
        project = create_project(loop["id"], tariff["id"])
        sized = size_project(project["id"])
        return {"loop": loop, "tariff": tariff, "project": project, "sized": sized}

    def _convert_call(self, project_id):
        return api_client.convert_expansion_project(
            project_id,
            convert_project_payload(
                1200.0,
                "HEATING",
                "2026-10-01T00:00:00Z",
                "2027-10-01T00:00:00Z",
                customer_name="Northgate Campus Holdings",
            ),
            BILLING_ANALYST,
        )

    def test_conversion_from_the_sized_state_is_refused(self):
        """The economics are settled but the investment decision is not.

        PRD: "A `BillingAnalyst` converts an `APPROVED` project to the terminal
        `CONVERTED`, supplying the `reserved_capacity_kw`, `service_mode`,
        `service_start_date` and `service_end_date` for the real contract plus an
        optional `customer_name` for the legal name if it differs from the screened
        candidate."

        Design: Corner/Endpoints/expansion_conversion_is_allowed_only_from_the_approved_state
        """
        stack = self._sized_project()
        assert stack["sized"]["project_state"] == "SIZED"
        assert stack["sized"]["npv"] == 2051685.40

        response = self._convert_call(stack["project"]["id"])

        validate_error(response, ApiErrorId.PROJECT_STATE_INVALID)

    def test_approval_opens_the_one_window_in_which_conversion_works(self):
        """Only APPROVED converts, and the second attempt has nowhere to go.

        PRD: "Every other requested transition is rejected with
        `ERR_PROJECT_STATE_INVALID`."

        Design: Corner/Endpoints/expansion_conversion_is_allowed_only_from_the_approved_state
        """
        stack = self._sized_project()
        self._convert_call(stack["project"]["id"])
        approved = decide_project(
            stack["project"]["id"], "APPROVE", decision_note="board approved"
        )
        assert approved["project_state"] == "APPROVED"

        converted = validate_success(self._convert_call(stack["project"]["id"]))
        again = self._convert_call(stack["project"]["id"])

        assert converted["project_state"] == "CONVERTED"
        validate_error(again, ApiErrorId.PROJECT_STATE_INVALID)
        assert read_project(stack["project"]["id"])["project_state"] == "CONVERTED"

    def test_the_conversion_drafts_a_pending_agreement_on_the_projects_own_loop(self):
        """The new contract inherits the loop, the tariff and the screened class.

        PRD: "Conversion creates a new connection agreement on the project's own
        `loop_id` and `rate_schedule_id`, carrying the project's `customer_class`,
        opening at `contract_state` `PENDING_CAPACITY` and `billing_state` `CURRENT`."

        Design: Corner/Endpoints/expansion_conversion_is_allowed_only_from_the_approved_state
        """
        stack = self._sized_project()
        decide_project(stack["project"]["id"], "APPROVE", decision_note="board approved")
        self._convert_call(stack["project"]["id"])

        rows, meta = _page(
            api_client.list_connection_agreements(
                BILLING_ANALYST,
                {
                    "loop_id": stack["loop"]["id"],
                    "contract_state": "PENDING_CAPACITY",
                },
            )
        )

        assert_pagination_meta(meta, total_count=1)
        drafted = rows[0]
        assert drafted["customer_class"] == "COMMERCIAL_OFFICE"
        assert drafted["reserved_capacity_kw"] == 1200.0
        assert drafted["rate_schedule_id"] == stack["tariff"]["id"]
        assert_agreement_state(
            drafted,
            contract_state="PENDING_CAPACITY",
            billing_state="CURRENT",
            balance_due=0.0,
            billed_demand_ratchet_kw=0.0,
        )


class TestCollectionsFilterAndPaginateAMixedPopulation:
    """Each collection holds rows that differ only in the dimension being filtered."""

    def _mixed_population(self):
        set_clock()
        loop = create_loop(
            code="LOOP-L",
            name="Lakeside Loop L",
            service_mode="HEATING",
            rated_capacity_kw=8000.0,
        )
        create_loop(
            code="LOOP-L2",
            name="Lakeside Loop Two",
            service_mode="COOLING",
            rated_capacity_kw=8000.0,
        )
        first_segment = create_segment(loop["id"], code="SEG-L1")
        second_segment = create_segment(loop["id"], code="SEG-L2")
        tariff = university_rate_schedule(code="RS-L")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Lakeside College",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
        )
        create_asset(
            loop["id"],
            code="L_G",
            asset_type="CHP",
            rated_capacity_kw=600.0,
            marginal_cost_per_mwh=30.00,
            emission_factor_kg_per_mwh=210.0,
        )
        create_asset(
            loop["id"],
            code="L_B",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=800.0,
            marginal_cost_per_mwh=38.00,
            emission_factor_kg_per_mwh=30.0,
        )
        published = published_forecast(
            loop["id"], "2026-08-05T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        drafted_forecast = create_forecast(
            loop["id"], "2026-08-06T00:00:00Z", occupancy_profile="WEEKEND_REDUCED"
        )
        superseded_plan = create_plan(loop["id"], published["id"])
        live_plan = create_plan(loop["id"], published["id"])
        drafted_order = create_work_order(
            first_segment["id"],
            loop["id"],
            "2026-09-10T08:00:00Z",
            "2026-09-10T18:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="INSPECTION",
        )
        pending_order = create_work_order(
            second_segment["id"],
            loop["id"],
            "2026-09-12T08:00:00Z",
            "2026-09-12T18:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="VALVE_REPLACEMENT",
        )
        submit_permit(pending_order["id"], FIELD_TECHNICIAN)
        commercial = commercial_rate_schedule(code="RS-LC")
        sized_project = size_project(create_project(loop["id"], commercial["id"])["id"])
        screening_project = create_project(loop["id"], commercial["id"])
        point = commissioned_point(agreement["id"], first_segment["id"], code="MP-L1")
        add_reading(point["id"], "2026-06-01T00:00:00Z", 40.000, 700.0)
        add_reading(point["id"], "2026-06-15T00:00:00Z", 60.000, 750.0)
        add_reading(
            point["id"], "2026-06-29T00:00:00Z", 90.000, 780.0, read_type="ESTIMATED"
        )
        return {
            "loop": loop,
            "second_segment": second_segment,
            "published_forecast": published,
            "drafted_forecast": drafted_forecast,
            "superseded_plan": superseded_plan,
            "live_plan": live_plan,
            "drafted_order": drafted_order,
            "pending_order": pending_order,
            "sized_project": sized_project,
            "screening_project": screening_project,
            "point": point,
        }

    def test_the_loop_collection_pages_one_row_at_a_time(self):
        """Two windows of one row cover both loops exactly once.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        size of the filtered result set before the window is applied and `has_more`
        indicates whether items remain beyond the window."

        Design: Corner/Endpoints/every_collection_endpoint_filters_sorts_and_paginates_over_a_mixed_population
        """
        self._mixed_population()

        first_page, first_meta = _page(
            api_client.list_network_loops(SYSTEM_CONTROLLER, {"limit": 1, "offset": 0})
        )
        second_page, second_meta = _page(
            api_client.list_network_loops(SYSTEM_CONTROLLER, {"limit": 1, "offset": 1})
        )

        assert len(first_page) == 1 and len(second_page) == 1
        assert_pagination_meta(first_meta, total_count=2, has_more=True, limit=1, offset=0)
        assert_pagination_meta(second_meta, total_count=2, has_more=False, limit=1, offset=1)
        assert {first_page[0]["code"], second_page[0]["code"]} == {"LOOP-L", "LOOP-L2"}, (
            "the two windows together must cover both loops exactly once"
        )
        cooling, cooling_meta = _page(
            api_client.list_network_loops(SYSTEM_CONTROLLER, {"service_mode": "COOLING"})
        )
        assert_pagination_meta(cooling_meta, total_count=1)
        assert cooling[0]["code"] == "LOOP-L2"

    def test_the_forecast_and_plan_state_filters_discriminate(self):
        """One published forecast beside a draft, one superseded plan beside its heir.

        PRD: "Creation is also a broom: every other dispatch plan on the same loop
        whose `plan_state` is `DRAFT`, `SUBMITTED` or `APPROVED` is cascaded to
        `SUPERSEDED` with its `version` incremented by 1, and the loop's own `version`
        is incremented by 1."

        Design: Corner/Endpoints/every_collection_endpoint_filters_sorts_and_paginates_over_a_mixed_population
        """
        stack = self._mixed_population()

        forecasts, forecast_meta = _page(
            api_client.list_load_forecasts(
                DISPATCH_OPERATOR,
                {"loop_id": stack["loop"]["id"], "forecast_state": "PUBLISHED"},
            )
        )
        plans, plan_meta = _page(
            api_client.list_dispatch_plans(
                DISPATCH_OPERATOR,
                {"loop_id": stack["loop"]["id"], "plan_state": "SUPERSEDED"},
            )
        )

        assert_pagination_meta(forecast_meta, total_count=1)
        assert forecasts[0]["id"] == stack["published_forecast"]["id"]
        assert_pagination_meta(plan_meta, total_count=1)
        assert plans[0]["id"] == stack["superseded_plan"]["id"]
        assert plans[0]["forecast_id"] == stack["published_forecast"]["id"]
        assert (
            _count(
                api_client.list_dispatch_plans(
                    DISPATCH_OPERATOR, {"loop_id": stack["loop"]["id"]}
                )
            )
            == 2
        ), "without a state filter both plans must be listed"

    def test_the_work_order_and_project_state_filters_discriminate(self):
        """A permit-pending job and a sized project are each one of two rows.

        PRD: "**Submitting for permit** advances the order from `DRAFT` to
        `PERMIT_PENDING` and sets `permit_decision` to `PENDING`."

        Design: Corner/Endpoints/every_collection_endpoint_filters_sorts_and_paginates_over_a_mixed_population
        """
        stack = self._mixed_population()

        orders, order_meta = _page(
            api_client.list_work_orders(
                FIELD_TECHNICIAN,
                {"loop_id": stack["loop"]["id"], "work_state": "PERMIT_PENDING"},
            )
        )
        projects, project_meta = _page(
            api_client.list_expansion_projects(
                NETWORK_ENGINEER,
                {"loop_id": stack["loop"]["id"], "project_state": "SCREENING"},
            )
        )

        assert_pagination_meta(order_meta, total_count=1)
        assert orders[0]["id"] == stack["pending_order"]["id"]
        assert orders[0]["segment_id"] == stack["second_segment"]["id"]
        assert_pagination_meta(project_meta, total_count=1)
        assert projects[0]["id"] == stack["screening_project"]["id"]
        assert stack["sized_project"]["selected_diameter_mm"] == 100

    def test_the_register_listing_is_scoped_to_its_metering_point(self):
        """Three reads of two read types all belong to the one point.

        PRD: "The per-meter register-read collection filters on `read_type`; the global
        register-read collection filters on `point_id` and `read_type`."

        Design: Corner/Endpoints/every_collection_endpoint_filters_sorts_and_paginates_over_a_mixed_population
        """
        stack = self._mixed_population()

        response = api_client.list_meter_readings(
            NETWORK_ENGINEER, {"point_id": stack["point"]["id"]}
        )

        rows, meta = _page(response)
        assert_pagination_meta(meta, total_count=3)
        assert_read_at_ascending(rows)
        assert {row["read_type"] for row in rows} == {"ACTUAL", "ESTIMATED"}
        assert_envelope_meta(response.json())
        estimated = _count(
            api_client.list_meter_readings(
                NETWORK_ENGINEER,
                {"point_id": stack["point"]["id"], "read_type": "ESTIMATED"},
            )
        )
        assert estimated == 1, f"one of the three reads is estimated, got {estimated}"
