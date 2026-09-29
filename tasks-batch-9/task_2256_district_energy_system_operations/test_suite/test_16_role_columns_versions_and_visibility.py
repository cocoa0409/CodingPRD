"""Role columns, four-eyes gates, stale-version guards and immediate cascades."""

from test_helpers import (
    ApiErrorId,
    BILLING_ANALYST,
    CTRL_1,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    NETWORK_ENGINEER,
    NON_EXISTENT_UUID,
    OP_1,
    SYSTEM_CONTROLLER,
    TECH_1,
    TECH_2,
    activate_agreement,
    active_agreement,
    add_readings,
    agreement_version,
    api_client,
    assert_agreement_state,
    assert_emissions_summary,
    assert_invoice_determinants,
    assert_loop_state,
    assert_plan_metrics,
    assert_project_economics,
    assert_segment_condition,
    assess_segment,
    begin_excavation,
    commercial_rate_schedule,
    commissioned_point,
    complete_work_order,
    convert_project,
    create_agreement,
    create_asset,
    create_fuel_contract,
    create_invoice,
    create_loop,
    create_plan,
    create_project,
    create_rate_schedule,
    create_segment,
    decide_project,
    dispatch_plan_payload,
    get_success_data,
    invoice_payload,
    issue_invoice,
    load_forecast_payload,
    make_customer_account_headers,
    make_field_technician_headers,
    make_headers,
    make_system_controller_headers,
    metering_point_payload,
    network_loop_payload,
    optimize_plan,
    pay_invoice,
    payment_payload,
    pipe_segment_payload,
    plan_in_state,
    plan_review_payload,
    production_asset_payload,
    published_forecast,
    rate_schedule_payload,
    read_agreement,
    read_invoice,
    read_loop,
    read_plan,
    read_work_order,
    residential_rate_schedule,
    review_plan,
    set_clock,
    size_project,
    university_rate_schedule,
    validate_error,
    validate_paginated,
    work_order_in_state,
)

JUNE_START = "2026-06-01T00:00:00Z"
JUNE_MID = "2026-06-28T00:00:00Z"
JUNE_END = "2026-07-01T00:00:00Z"
JULY_END = "2026-08-01T00:00:00Z"
SERVICE_DATE = "2026-08-06T00:00:00Z"
WINDOW_START = "2026-07-31T00:00:00Z"
WINDOW_END = "2026-08-02T00:00:00Z"


def _count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


def _rows(response):
    rows, _ = validate_paginated(response)
    return rows


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


def _emissions_summary(loop_id):
    return get_success_data(api_client.get_emissions_summary(loop_id, NETWORK_ENGINEER))


class TestAllSixRolesDriveOneUtility:
    """One loop taken from registration to settlement, each role in its own column."""

    def _utility(self):
        set_clock()
        loop = create_loop(
            code="LOOP-W",
            name="Westgate Loop W",
            service_mode="HEATING",
            design_supply_temp_c=90.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-W1",
            length_m=500.0,
            diameter_mm=200,
            install_year=2014,
            insulation_class="A",
            buried_depth_m=1.2,
        )
        surveyed = assess_segment(
            segment["id"], 0.0, 0, "A", survey_note="baseline acoustic survey"
        )
        gas = create_fuel_contract(
            supplier_code="FC-WGAS",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=30000.0,
            price_per_mwh=27.00,
            delivery_firmness="FIRM",
        )
        biomass = create_fuel_contract(
            supplier_code="FC-WBIO",
            fuel_type="BIOMASS",
            contracted_energy_mwh_per_year=8000.0,
            price_per_mwh=30.00,
            delivery_firmness="FIRM",
        )
        oil = create_fuel_contract(
            supplier_code="FC-WOIL",
            fuel_type="FUEL_OIL",
            contracted_energy_mwh_per_year=5000.0,
            price_per_mwh=88.00,
            delivery_firmness="INTERRUPTIBLE",
        )
        create_asset(
            loop["id"],
            fuel_contract_id=gas["id"],
            code="W_G",
            asset_type="BOILER",
            rated_capacity_kw=400.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=30.00,
            emission_factor_kg_per_mwh=220.0,
        )
        create_asset(
            loop["id"],
            fuel_contract_id=biomass["id"],
            code="W_B",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=500.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=32.00,
            emission_factor_kg_per_mwh=30.0,
        )
        create_asset(
            loop["id"],
            fuel_contract_id=oil["id"],
            code="W_S",
            asset_type="BOILER",
            rated_capacity_kw=2000.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=90.00,
            emission_factor_kg_per_mwh=260.0,
        )
        campus_tariff = university_rate_schedule()
        office_tariff = commercial_rate_schedule()
        drafted = create_agreement(
            loop["id"],
            campus_tariff["id"],
            customer_name="Westgate College",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
            service_mode="HEATING",
        )
        agreement = activate_agreement(drafted["id"])
        point = commissioned_point(agreement["id"], segment["id"], code="MP-W1")
        add_readings(
            point["id"],
            [
                {
                    "read_at": JUNE_START,
                    "cumulative_energy_mwh": 100.000,
                    "peak_demand_kw": 600.0,
                },
                {
                    "read_at": JUNE_MID,
                    "cumulative_energy_mwh": 460.000,
                    "peak_demand_kw": 640.0,
                },
            ],
        )
        forecast = published_forecast(loop["id"], SERVICE_DATE)
        plan = plan_in_state("COMMITTED", loop["id"], forecast["id"])
        invoice = create_invoice(
            agreement["id"], JUNE_START, JUNE_END, "ACTUAL_TRUE_UP"
        )
        issued = issue_invoice(invoice["id"])
        project = create_project(
            loop["id"], office_tariff["id"], candidate_customer_name="Westgate Exchange"
        )
        sized = size_project(project["id"])
        return {
            "loop": loop,
            "segment": surveyed,
            "drafted": drafted,
            "agreement": agreement,
            "point": point,
            "forecast": forecast,
            "plan": plan,
            "invoice": issued,
            "project": sized,
        }

    def test_each_role_drives_only_its_own_step_of_the_chain(self):
        """Registration, survey, fuel, meter, dispatch, billing and screening all land.

        PRD: "The six roles are `SystemController`, `DispatchOperator`,
        `NetworkEngineer`, `FieldTechnician`, `BillingAnalyst` and `CustomerAccount`."

        Design: Corner/RBAC/all_six_roles_drive_one_utility_from_registration_to_settlement
        """
        built = self._utility()

        assert_loop_state(built["loop"], posture="NORMAL", committed_reserved_kw=0.0)
        assert_segment_condition(built["segment"], condition="SOUND", leak_risk_score=8.50)
        assert built["drafted"]["contract_state"] == "PENDING_CAPACITY"
        assert_agreement_state(built["agreement"], contract_state="ACTIVE")
        assert built["point"]["meter_state"] == "COMMISSIONED"
        assert built["forecast"]["coincident_demand_kw"] == 756.00
        assert_plan_metrics(
            built["plan"],
            plan_state="COMMITTED",
            reserve_margin_pct=19.05,
            fuel_diversity_hhi=0.5017,
        )
        assert_invoice_determinants(
            built["invoice"],
            billed_energy_mwh=360.000,
            load_factor_pct=78.13,
            total_amount=32300.00,
            invoice_state="ISSUED",
        )
        assert_project_economics(
            built["project"],
            project_state="SIZED",
            selected_diameter_mm=100,
            npv=2051685.40,
        )

        approved = decide_project(
            built["project"]["id"], "APPROVE", decision_note="positive net present value"
        )
        assert approved["project_state"] == "APPROVED"
        converted = convert_project(
            built["project"]["id"],
            1200.0,
            "HEATING",
            "2027-01-01T00:00:00Z",
            "2032-01-01T00:00:00Z",
            customer_name="Westgate Exchange",
        )
        assert converted["project_state"] == "CONVERTED"

    def test_the_connected_customer_reads_and_settles_its_own_bill(self):
        """The bill above the arrears ceiling is paid in full and the flag clears.

        PRD: "It is permitted from `ISSUED` and from `ADJUSTED` and from no other
        state — paying a `DRAFT`, `PAID` or `VOID` invoice is rejected with
        `ERR_INVOICE_STATE_INVALID` — and both permitted edges behave identically: the
        acting `X-User-ID` must equal the invoice's `agreement_id`, the `amount` must
        equal the invoice's `total_amount` exactly — a partial or excess payment is
        refused with `ERR_PAYMENT_AMOUNT_MISMATCH`, so there are no partial
        settlements — and on success `paid_amount` is set to the amount,
        `invoice_state` becomes the terminal `PAID`, the agreement's `balance_due` is
        recomputed, the billing dimension is cascaded from `IN_ARREARS` back to
        `CURRENT` when the recomputed balance is at or below the arrears threshold, and
        both the agreement's and the invoice's `version` are incremented by 1."

        Design: Corner/RBAC/all_six_roles_drive_one_utility_from_registration_to_settlement
        """
        built = self._utility()
        agreement_id = built["agreement"]["id"]
        invoice_id = built["invoice"]["id"]
        customer = make_customer_account_headers(agreement_id)

        own_agreement = read_agreement(agreement_id, customer)
        assert_agreement_state(
            own_agreement,
            contract_state="ACTIVE",
            billing_state="IN_ARREARS",
            balance_due=32300.00,
        )
        own_invoice = read_invoice(invoice_id, customer)
        assert_invoice_determinants(own_invoice, total_amount=32300.00)

        paid = pay_invoice(invoice_id, 32300.00, agreement_id)
        assert_invoice_determinants(paid, invoice_state="PAID", paid_amount=32300.00)
        assert_agreement_state(
            read_agreement(agreement_id),
            contract_state="ACTIVE",
            billing_state="CURRENT",
            balance_due=0.00,
        )

    def test_the_shared_reads_answer_for_the_peer_roles(self):
        """The summary, the fleet list and the meter list serve their peer columns.

        PRD: "A computed loop summary reports emissions and efficiency against the
        municipal climate target, drawing only on dispatch plans on the loop whose
        `plan_state` is `COMMITTED` or `RECONCILED`; plans in `DRAFT`, `SUBMITTED`,
        `APPROVED` or `SUPERSEDED` are excluded, because only committed production
        actually burned fuel."

        Design: Corner/RBAC/all_six_roles_drive_one_utility_from_registration_to_settlement
        """
        built = self._utility()
        loop_id = built["loop"]["id"]

        assert_emissions_summary(
            _emissions_summary(loop_id),
            contributing_plan_count=1,
            total_energy_mwh=18.144,
        )

        fleet = _rows(api_client.list_production_assets(DISPATCH_OPERATOR, {"loop_id": loop_id}))
        assert len(fleet) == 3
        assert {asset["loop_id"] for asset in fleet} == {loop_id}
        points = _rows(
            api_client.list_metering_points(
                FIELD_TECHNICIAN, {"agreement_id": built["agreement"]["id"]}
            )
        )
        assert [point["code"] for point in points] == ["MP-W1"]

        decide_project(built["project"]["id"], "APPROVE", decision_note="positive case")
        convert_project(
            built["project"]["id"],
            1200.0,
            "HEATING",
            "2027-01-01T00:00:00Z",
            "2032-01-01T00:00:00Z",
            customer_name="Westgate Exchange",
        )
        assert (
            _count(api_client.list_connection_agreements(BILLING_ANALYST, {"loop_id": loop_id}))
            == 2
        )


class TestEachRoleIsRefusedAnotherRolesOperation:
    """Seven cross-column attempts and one unrecognised role share one identifier."""

    def _zenith(self):
        set_clock()
        loop = create_loop(
            code="LOOP-Z",
            name="Zenith Loop Z",
            service_mode="HEATING",
            design_supply_temp_c=90.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=5000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-Z1",
            length_m=300.0,
            diameter_mm=150,
            install_year=2015,
            insulation_class="A",
            buried_depth_m=1.0,
        )
        tariff = commercial_rate_schedule()
        agreement = create_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Zenith Offices",
            customer_class="COMMERCIAL_OFFICE",
            reserved_capacity_kw=500.0,
            service_mode="HEATING",
        )
        return {"loop": loop, "segment": segment, "tariff": tariff, "agreement": agreement}

    def _cross_column_writes(self, built):
        """Five registrations, each attempted by a role that does not own the endpoint."""
        loop_id = built["loop"]["id"]
        return {
            "asset": api_client.create_production_asset(
                production_asset_payload(
                    loop_id,
                    code="Z_G",
                    asset_type="BOILER",
                    rated_capacity_kw=900.0,
                    min_stable_output_kw=100.0,
                    marginal_cost_per_mwh=33.00,
                    emission_factor_kg_per_mwh=215.0,
                ),
                DISPATCH_OPERATOR,
            ),
            "forecast": api_client.create_load_forecast(
                load_forecast_payload(loop_id, SERVICE_DATE), NETWORK_ENGINEER
            ),
            "tariff": api_client.create_rate_schedule(
                rate_schedule_payload(
                    "HOSPITAL",
                    code="RS-X",
                    fixed_service_charge=100.00,
                    demand_charge_per_kw=5.00,
                    minimum_bill_amount=500.00,
                    tiers=[{"load_factor_max": 100.0, "energy_rate_per_mwh": 70.00}],
                ),
                FIELD_TECHNICIAN,
            ),
            "segment": api_client.create_pipe_segment(
                pipe_segment_payload(
                    loop_id,
                    code="SEG-Z9",
                    length_m=100.0,
                    diameter_mm=100,
                    install_year=2020,
                    insulation_class="A",
                    buried_depth_m=1.0,
                ),
                BILLING_ANALYST,
            ),
            "meter": api_client.create_metering_point(
                metering_point_payload(
                    built["agreement"]["id"], built["segment"]["id"], code="MP-Z9", multiplier=1.0
                ),
                SYSTEM_CONTROLLER,
            ),
        }

    def _attempts_that_outrank_other_checks(self, built):
        """A payment on an unknown invoice, a tenant-wide list and an unknown role."""
        return {
            "payment": api_client.pay_invoice(
                NON_EXISTENT_UUID, payment_payload(100.00), BILLING_ANALYST
            ),
            "invoice_list": api_client.list_invoices(
                make_customer_account_headers(built["agreement"]["id"])
            ),
            "unknown_role": api_client.create_network_loop(
                network_loop_payload(
                    code="LOOP-Q9", name="Ghost Loop", rated_capacity_kw=1000.0
                ),
                make_headers("Auditor", CTRL_1),
            ),
        }

    def test_five_registration_endpoints_refuse_the_role_that_does_not_own_them(self):
        """Asset, forecast, tariff, segment and meter each answer the same 403.

        PRD: "If the header value is not one of the six recognised roles, or is a
        recognised role that is not authorised for the endpoint being called, the
        request is rejected with `ERR_UNAUTHORIZED` and HTTP 403."

        Design: Corner/RBAC/each_role_is_refused_another_roles_exclusive_operation
        """
        refusals = self._cross_column_writes(self._zenith())

        validate_error(refusals["asset"], ApiErrorId.UNAUTHORIZED)
        validate_error(refusals["forecast"], ApiErrorId.UNAUTHORIZED)
        validate_error(refusals["tariff"], ApiErrorId.UNAUTHORIZED)
        validate_error(refusals["segment"], ApiErrorId.UNAUTHORIZED)
        validate_error(refusals["meter"], ApiErrorId.UNAUTHORIZED)

    def test_the_role_gate_answers_before_existence_and_before_an_unknown_role(self):
        """A payment on an invoice that never existed still reports the role problem.

        PRD: "**The order matters and is asserted**: a request that would fail several
        checks fails on the earliest one, so a caller with a bad role never learns
        whether its body was well formed, and a caller acting on a wrongly-stated
        version never learns whether the target's state permitted the action."

        Design: Corner/RBAC/each_role_is_refused_another_roles_exclusive_operation
        """
        refusals = self._attempts_that_outrank_other_checks(self._zenith())

        validate_error(refusals["payment"], ApiErrorId.UNAUTHORIZED)
        validate_error(refusals["invoice_list"], ApiErrorId.UNAUTHORIZED)
        validate_error(refusals["unknown_role"], ApiErrorId.UNAUTHORIZED)

    def test_none_of_the_eight_refusals_left_a_row_behind(self):
        """The population is exactly what the owning roles wrote.

        PRD: "2. **Role authorisation.** `X-User-Role` is one of the six declared roles
        and is listed for the endpoint, or `ERR_UNAUTHORIZED` (403)."

        Design: Corner/RBAC/each_role_is_refused_another_roles_exclusive_operation
        """
        built = self._zenith()
        loop_id = built["loop"]["id"]

        refusals = dict(self._cross_column_writes(built))
        refusals.update(self._attempts_that_outrank_other_checks(built))
        assert len(refusals) == 8
        for response in refusals.values():
            validate_error(response, ApiErrorId.UNAUTHORIZED)

        assert _count(api_client.list_production_assets(SYSTEM_CONTROLLER, {"loop_id": loop_id})) == 0
        tariffs = _rows(api_client.list_rate_schedules(BILLING_ANALYST))
        assert [tariff["code"] for tariff in tariffs] == ["RS-C"]
        segments = _rows(api_client.list_pipe_segments(NETWORK_ENGINEER, {"loop_id": loop_id}))
        assert [segment["code"] for segment in segments] == ["SEG-Z1"]
        assert (
            _count(
                api_client.list_metering_points(
                    FIELD_TECHNICIAN, {"agreement_id": built["agreement"]["id"]}
                )
            )
            == 0
        )


class TestTheReviewerAndTheCompleterMustDiffer:
    """Both four-eyes gates key on the acting identifier, not on the role."""

    def _southbank(self):
        set_clock()
        loop = create_loop(
            code="LOOP-S",
            name="Southbank Loop S",
            service_mode="HEATING",
            design_supply_temp_c=90.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-S1",
            length_m=450.0,
            diameter_mm=200,
            install_year=2012,
            insulation_class="A",
            buried_depth_m=1.1,
        )
        gas = create_fuel_contract(
            supplier_code="FC-SGAS",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=30000.0,
            price_per_mwh=27.00,
            delivery_firmness="FIRM",
        )
        biomass = create_fuel_contract(
            supplier_code="FC-SBIO",
            fuel_type="BIOMASS",
            contracted_energy_mwh_per_year=8000.0,
            price_per_mwh=30.00,
            delivery_firmness="FIRM",
        )
        oil = create_fuel_contract(
            supplier_code="FC-SOIL",
            fuel_type="FUEL_OIL",
            contracted_energy_mwh_per_year=5000.0,
            price_per_mwh=88.00,
            delivery_firmness="INTERRUPTIBLE",
        )
        create_asset(
            loop["id"],
            fuel_contract_id=gas["id"],
            code="S_G",
            asset_type="BOILER",
            rated_capacity_kw=400.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=30.00,
            emission_factor_kg_per_mwh=220.0,
        )
        create_asset(
            loop["id"],
            fuel_contract_id=biomass["id"],
            code="S_B",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=500.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=32.00,
            emission_factor_kg_per_mwh=30.0,
        )
        create_asset(
            loop["id"],
            fuel_contract_id=oil["id"],
            code="S_S",
            asset_type="BOILER",
            rated_capacity_kw=2000.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=90.00,
            emission_factor_kg_per_mwh=260.0,
        )
        tariff = university_rate_schedule()
        active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Southbank University",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
            service_mode="HEATING",
        )
        forecast = published_forecast(loop["id"], SERVICE_DATE)
        plan = plan_in_state("SUBMITTED", loop["id"], forecast["id"])
        order = work_order_in_state(
            "BACKFILLED",
            segment["id"],
            loop["id"],
            WINDOW_START,
            WINDOW_END,
            work_type="INSPECTION",
        )
        return {"loop": loop, "segment": segment, "plan": plan, "order": order}

    def test_the_author_and_the_reporter_cannot_sign_off_their_own_work(self):
        """A controller carrying the author's identity is refused, and so is the reporter.

        PRD: "A dispatch plan may not be reviewed by the operator recorded in its
        `authored_by_user_id`, and a work order may not be completed by the technician
        recorded in its `reported_by_user_id`. Either violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."

        Design: Corner/RBAC/the_reviewer_and_the_completer_must_differ_from_the_originator
        """
        built = self._southbank()
        plan_id = built["plan"]["id"]
        order_id = built["order"]["id"]

        assert built["plan"]["authored_by_user_id"] == OP_1
        assert built["plan"]["plan_state"] == "SUBMITTED"
        assert built["order"]["reported_by_user_id"] == TECH_1
        assert built["order"]["work_state"] == "BACKFILLED"

        validate_error(
            api_client.review_dispatch_plan(
                plan_id,
                plan_review_payload("APPROVE", review_note="self-approval attempt"),
                make_system_controller_headers(OP_1),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
        )
        assert_plan_metrics(read_plan(plan_id), plan_state="SUBMITTED", reviewed_by_user_id=None)

        validate_error(
            api_client.complete_work_order(
                order_id,
                {"completion_note": "self-signoff attempt"},
                make_field_technician_headers(TECH_1),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
        )
        refused = read_work_order(order_id)
        assert refused["work_state"] == "BACKFILLED"
        assert refused["completed_by_user_id"] is None

    def test_a_second_identity_carries_both_sign_offs(self):
        """The independent reviewer and the independent technician are recorded.

        PRD: "**Review** is a `SystemController` decision carrying a `decision` of
        either `APPROVE` or `REJECT` plus an optional `review_note`; either branch
        stores the reviewing `X-User-ID` into `reviewed_by_user_id` and increments the
        plan's `version` by 1, and both require the plan to be `SUBMITTED` and the
        reviewer to differ from `authored_by_user_id`."

        Design: Corner/RBAC/the_reviewer_and_the_completer_must_differ_from_the_originator
        """
        built = self._southbank()

        reviewed = review_plan(built["plan"]["id"], "APPROVE", review_note="independent review")
        assert_plan_metrics(reviewed, plan_state="APPROVED", reviewed_by_user_id=CTRL_1)

        completed = complete_work_order(built["order"]["id"], "independent signoff")
        assert completed["work_state"] == "COMPLETED"
        assert completed["completed_by_user_id"] == TECH_2

    def test_the_independent_sign_off_rebands_the_segment_it_repaired(self):
        """Sign-off returns the segment to a band and leaves the loop in NORMAL.

        PRD: "Only then is the leak-risk score recomputed from those revised inputs,
        and the segment is re-banded out of `UNDER_REPAIR` into whichever band the new
        score implies, with the segment's `version` incremented by 1."

        Design: Corner/RBAC/the_reviewer_and_the_completer_must_differ_from_the_originator
        """
        built = self._southbank()
        review_plan(built["plan"]["id"], "APPROVE", review_note="independent review")
        complete_work_order(built["order"]["id"], "independent signoff")

        assert_segment_condition(
            _read_segment(built["segment"]["id"]),
            condition="SOUND",
            leak_risk_score=9.67,
            makeup_water_ratio=0.0,
            historical_leak_count=0,
        )
        assert_loop_state(
            read_loop(built["loop"]["id"]),
            posture="NORMAL",
            open_isolation_count=0,
            suspect_segment_count=0,
        )


class TestACustomerAccountIsScopedToItsOwnRows:
    """The neighbouring agreement is refused on every scoped target."""

    def _millside(self):
        set_clock()
        loop = create_loop(
            code="LOOP-M",
            name="Millside Loop M",
            service_mode="HEATING",
            design_supply_temp_c=88.0,
            max_pressure_kpa=1300.0,
            rated_capacity_kw=10000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-M1",
            length_m=400.0,
            diameter_mm=150,
            install_year=2018,
            insulation_class="A",
            buried_depth_m=1.1,
        )
        tariff = residential_rate_schedule()
        owner = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Millside Co-op",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
            service_mode="HEATING",
        )
        neighbour = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Millside Terrace",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
            service_mode="HEATING",
        )
        point = commissioned_point(owner["id"], segment["id"], code="MP-M1")
        add_readings(
            point["id"],
            [
                {
                    "read_at": JUNE_START,
                    "cumulative_energy_mwh": 10.000,
                    "peak_demand_kw": 55.0,
                },
                {
                    "read_at": JUNE_MID,
                    "cumulative_energy_mwh": 14.000,
                    "peak_demand_kw": 60.0,
                },
            ],
        )
        invoice = create_invoice(owner["id"], JUNE_START, JUNE_END, "ACTUAL_TRUE_UP")
        issued = issue_invoice(invoice["id"])
        return {
            "loop": loop,
            "owner": owner,
            "neighbour": neighbour,
            "invoice": issued,
        }

    def test_the_neighbour_is_refused_on_the_agreement_the_invoice_and_the_payment(self):
        """One identifier answers three different targets, ahead of state and amount.

        PRD: "Concretely: reading a connection agreement requires that the agreement's
        own `id` equal `X-User-ID`; reading an invoice, and paying one, require that
        the invoice's `agreement_id` equal `X-User-ID`. A `CustomerAccount` acting on
        someone else's agreement or invoice is rejected with `ERR_FORBIDDEN_AGREEMENT`
        and HTTP 403."

        Design: Corner/RBAC/a_customer_account_is_scoped_to_its_own_agreement_and_invoices
        """
        built = self._millside()
        invoice_id = built["invoice"]["id"]
        assert_invoice_determinants(
            built["invoice"],
            total_amount=3000.00,
            minimum_bill_applied=True,
            invoice_state="ISSUED",
        )
        neighbour = make_customer_account_headers(built["neighbour"]["id"])

        validate_error(
            api_client.get_connection_agreement(built["owner"]["id"], neighbour),
            ApiErrorId.FORBIDDEN_AGREEMENT,
        )
        validate_error(
            api_client.get_invoice(invoice_id, neighbour), ApiErrorId.FORBIDDEN_AGREEMENT
        )
        validate_error(
            api_client.pay_invoice(invoice_id, payment_payload(3000.00), neighbour),
            ApiErrorId.FORBIDDEN_AGREEMENT,
        )

        assert_invoice_determinants(
            read_invoice(invoice_id), invoice_state="ISSUED", paid_amount=0.00
        )

    def test_the_owner_reads_and_settles_the_same_invoice(self):
        """The identity that matches the invoice clears both balances to zero.

        PRD: "The agreement's balance ledger, recomputed on every issue, adjustment,
        payment and void, is defined precisely: `balance_due` is the sum of
        `total_amount` across every invoice of this agreement whose `invoice_state` is
        `ISSUED` or `ADJUSTED`, rounded half-up to two decimal places."

        Design: Corner/RBAC/a_customer_account_is_scoped_to_its_own_agreement_and_invoices
        """
        built = self._millside()
        owner_id = built["owner"]["id"]
        invoice_id = built["invoice"]["id"]

        own_read = read_invoice(invoice_id, make_customer_account_headers(owner_id))
        assert_invoice_determinants(own_read, total_amount=3000.00)

        paid = pay_invoice(invoice_id, 3000.00, owner_id)
        assert_invoice_determinants(paid, invoice_state="PAID", paid_amount=3000.00)
        assert_agreement_state(read_agreement(owner_id), balance_due=0.00)
        assert_agreement_state(read_agreement(built["neighbour"]["id"]), balance_due=0.00)

    def test_both_activations_were_counted_on_the_supplying_loop(self):
        """Two 120.0 kW reservations stand side by side on the same loop.

        PRD: "Alongside it the loop maintains three computed counters:
        `committed_reserved_kw`, the sum of `reserved_capacity_kw` across the
        agreements on this loop whose `contract_state` is `ACTIVE` or `SUSPENDED`;
        `open_isolation_count`, the number of work orders on this loop that require
        isolation and are currently in `EXCAVATING`, `REPAIRING` or `BACKFILLED`; and
        `suspect_segment_count`, the number of pipe segments on this loop whose
        `condition` is `SUSPECT`."

        Design: Corner/RBAC/a_customer_account_is_scoped_to_its_own_agreement_and_invoices
        """
        built = self._millside()

        assert_loop_state(read_loop(built["loop"]["id"]), committed_reserved_kw=240.0)


class TestAStaleLoopVersionRefusesPlanCreation:
    """A version read before somebody else's activation no longer opens a plan."""

    def _kingsway(self):
        set_clock()
        loop = create_loop(
            code="LOOP-K",
            name="Kingsway Loop K",
            service_mode="HEATING",
            design_supply_temp_c=90.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=6000.0,
        )
        observed = read_loop(loop["id"], DISPATCH_OPERATOR)
        gas = create_fuel_contract(
            supplier_code="FC-KGAS",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=30000.0,
            price_per_mwh=27.00,
            delivery_firmness="FIRM",
        )
        biomass = create_fuel_contract(
            supplier_code="FC-KBIO",
            fuel_type="BIOMASS",
            contracted_energy_mwh_per_year=8000.0,
            price_per_mwh=30.00,
            delivery_firmness="FIRM",
        )
        create_asset(
            loop["id"],
            fuel_contract_id=gas["id"],
            code="K_G",
            asset_type="BOILER",
            rated_capacity_kw=400.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=30.00,
            emission_factor_kg_per_mwh=220.0,
        )
        create_asset(
            loop["id"],
            fuel_contract_id=biomass["id"],
            code="K_B",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=500.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=32.00,
            emission_factor_kg_per_mwh=30.0,
        )
        tariff = university_rate_schedule()
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Kingsway University",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
            service_mode="HEATING",
        )
        forecast = published_forecast(loop["id"], SERVICE_DATE)
        return {
            "loop": loop,
            "stale_version": observed["version"],
            "agreement": agreement,
            "forecast": forecast,
        }

    def test_the_version_read_before_the_activation_is_refused_and_opens_nothing(self):
        """The activation moved the loop under the dispatcher, so the create is stale.

        PRD: "Plan creation legitimately supersedes every non-terminal plan already on
        the loop, so if another writer has advanced the loop's `version` since the
        client read it — by activating an agreement, by driving a cascade, by creating
        a plan of its own — the create would silently discard a plan the client has
        never seen. Instead, when `expected_loop_version` does not equal the loop's
        current `version`, the request is rejected with `ERR_STALE_LOOP_VERSION` and
        HTTP 412."

        Design: Corner/Cross-Cutting Complexity Layers/a_loop_version_read_before_an_activation_is_stale_for_plan_creation
        """
        built = self._kingsway()
        loop_id = built["loop"]["id"]

        assert built["loop"]["version"] == 1
        assert built["loop"]["committed_reserved_kw"] == 0.0
        assert built["stale_version"] == 1
        assert built["agreement"]["contract_state"] == "ACTIVE"
        assert built["forecast"]["coincident_demand_kw"] == 756.00

        validate_error(
            api_client.create_dispatch_plan(
                dispatch_plan_payload(
                    loop_id, built["forecast"]["id"], built["stale_version"]
                ),
                DISPATCH_OPERATOR,
            ),
            ApiErrorId.STALE_LOOP_VERSION,
        )
        assert _count(api_client.list_dispatch_plans(DISPATCH_OPERATOR, {"loop_id": loop_id})) == 0

        assert_loop_state(read_loop(loop_id), committed_reserved_kw=1000.0, version=2)

    def test_the_retry_with_the_refreshed_version_steps_the_plan_once_per_write(self):
        """The accepted create opens at version 1 and the optimise run advances it.

        PRD: "Most resources additionally carry `updated_at` — an ISO 8601 UTC
        timestamp with three fractional digits, refreshed on every mutation — and
        `version`, an integer that starts at 1 when the resource is created and is
        incremented by 1 on every mutation."

        Design: Corner/Cross-Cutting Complexity Layers/a_loop_version_read_before_an_activation_is_stale_for_plan_creation
        """
        built = self._kingsway()
        loop_id = built["loop"]["id"]
        refreshed = read_loop(loop_id, DISPATCH_OPERATOR)

        plan = create_plan(loop_id, built["forecast"]["id"], refreshed["version"])
        assert plan["version"] == 1
        assert_plan_metrics(plan, plan_state="DRAFT", allocated_capacity_kw=0.0)

        optimized = optimize_plan(plan["id"])
        assert optimized["version"] == 2
        assert_plan_metrics(
            optimized, plan_state="DRAFT", allocated_capacity_kw=756.00, unserved_demand_kw=0.0
        )


class TestAStaleAgreementVersionRefusesInvoiceCreation:
    """The same guard fires twice on one agreement, for two different writes."""

    def _greenfield(self):
        set_clock()
        loop = create_loop(
            code="LOOP-G",
            name="Greenfield Loop G",
            service_mode="HEATING",
            design_supply_temp_c=88.0,
            max_pressure_kpa=1300.0,
            rated_capacity_kw=10000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-G1",
            length_m=400.0,
            diameter_mm=150,
            install_year=2018,
            insulation_class="A",
            buried_depth_m=1.1,
        )
        tariff = residential_rate_schedule()
        drafted = create_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Greenfield Houses",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
            service_mode="HEATING",
        )
        point = commissioned_point(drafted["id"], segment["id"], code="MP-G1")
        add_readings(
            point["id"],
            [
                {
                    "read_at": JUNE_START,
                    "cumulative_energy_mwh": 10.000,
                    "peak_demand_kw": 55.0,
                },
                {
                    "read_at": JUNE_MID,
                    "cumulative_energy_mwh": 14.000,
                    "peak_demand_kw": 60.0,
                },
            ],
        )
        activated = activate_agreement(drafted["id"])
        return {
            "loop": loop,
            "drafted_version": drafted["version"],
            "agreement": activated,
        }

    def test_the_version_read_before_the_activation_bills_nothing(self):
        """Activation rewrote the determinants, so the create is refused with 412.

        PRD: "When `expected_agreement_version` does not equal the agreement's current
        `version`, the request is rejected with `ERR_STALE_AGREEMENT_VERSION` and HTTP
        412, rather than billing against determinants the client never observed."

        Design: Corner/Cross-Cutting Complexity Layers/an_agreement_version_read_before_activation_or_issue_is_stale_for_invoice_creation
        """
        built = self._greenfield()
        agreement_id = built["agreement"]["id"]

        assert built["drafted_version"] == 1
        assert built["agreement"]["contract_state"] == "ACTIVE"
        assert built["agreement"]["version"] == 2

        validate_error(
            api_client.create_invoice(
                invoice_payload(
                    agreement_id,
                    JUNE_START,
                    JUNE_END,
                    "ACTUAL_TRUE_UP",
                    built["drafted_version"],
                ),
                BILLING_ANALYST,
            ),
            ApiErrorId.STALE_AGREEMENT_VERSION,
        )
        assert _count(api_client.list_invoices(BILLING_ANALYST, {"agreement_id": agreement_id})) == 0
        assert agreement_version(agreement_id) == 2

    def test_the_accepted_creation_touches_the_agreement_it_read(self):
        """The retry bills 3000.00 and moves the agreement to version 3.

        PRD: "A newly created invoice opens at `invoice_state` `DRAFT` with
        `paid_amount` 0.0, and creation increments the owning agreement's `version` by
        1 — the calculation read the agreement's determinants, so the agreement is
        considered touched even though none of its own stored values changed."

        Design: Corner/Cross-Cutting Complexity Layers/an_agreement_version_read_before_activation_or_issue_is_stale_for_invoice_creation
        """
        built = self._greenfield()
        agreement_id = built["agreement"]["id"]

        invoice = create_invoice(agreement_id, JUNE_START, JUNE_END, "ACTUAL_TRUE_UP", 2)
        assert_invoice_determinants(
            invoice, total_amount=3000.00, invoice_state="DRAFT", paid_amount=0.0
        )
        assert agreement_version(agreement_id) == 3

    def test_issuing_writes_the_ledger_and_moves_the_agreement_again(self):
        """The issue lands the balance and the ratchet and reaches version 4.

        PRD: "**Issuing** advances a `DRAFT` invoice to `ISSUED` and is the moment
        money becomes owed: it raises the agreement's `billed_demand_ratchet_kw` to
        this invoice's `billed_demand_kw` when the invoice's figure is higher — the
        ratchet is only ever raised, never lowered, and only on this one edge —
        recomputes the agreement's `balance_due`, cascades the billing dimension from
        `CURRENT` to `IN_ARREARS` when the recomputed balance exceeds the arrears
        threshold, and increments both the agreement's and the invoice's `version` by
        1."

        Design: Corner/Cross-Cutting Complexity Layers/an_agreement_version_read_before_activation_or_issue_is_stale_for_invoice_creation
        """
        built = self._greenfield()
        agreement_id = built["agreement"]["id"]

        invoice = create_invoice(agreement_id, JUNE_START, JUNE_END, "ACTUAL_TRUE_UP", 2)
        issued = issue_invoice(invoice["id"])
        assert_invoice_determinants(issued, invoice_state="ISSUED", total_amount=3000.00)
        assert_agreement_state(
            read_agreement(agreement_id),
            billing_state="CURRENT",
            balance_due=3000.00,
            billed_demand_ratchet_kw=60.0,
        )
        assert agreement_version(agreement_id) == 4

    def test_the_stale_guard_answers_before_the_register_data_rule(self):
        """A July period with no reads still reports the version it was given.

        PRD: "**The order matters and is asserted**: a request that would fail several
        checks fails on the earliest one, so a caller with a bad role never learns
        whether its body was well formed, and a caller acting on a wrongly-stated
        version never learns whether the target's state permitted the action."

        Design: Corner/Cross-Cutting Complexity Layers/an_agreement_version_read_before_activation_or_issue_is_stale_for_invoice_creation
        """
        built = self._greenfield()
        agreement_id = built["agreement"]["id"]
        invoice = create_invoice(agreement_id, JUNE_START, JUNE_END, "ACTUAL_TRUE_UP", 2)
        issue_invoice(invoice["id"])

        validate_error(
            api_client.create_invoice(
                invoice_payload(agreement_id, JUNE_END, JULY_END, "ACTUAL_TRUE_UP", 2),
                BILLING_ANALYST,
            ),
            ApiErrorId.STALE_AGREEMENT_VERSION,
        )
        assert _count(api_client.list_invoices(BILLING_ANALYST, {"agreement_id": agreement_id})) == 1


class TestTheArrearsCeilingIsAStrictComparison:
    """Two bills one cent apart, both pinned by their own minimum-bill floor."""

    def _threshold_pair(self):
        set_clock()
        loop = create_loop(
            code="LOOP-T",
            name="Threshold Loop T",
            service_mode="HEATING",
            design_supply_temp_c=88.0,
            max_pressure_kpa=1300.0,
            rated_capacity_kw=4000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-T1",
            length_m=250.0,
            diameter_mm=125,
            install_year=2019,
            insulation_class="A",
            buried_depth_m=1.0,
        )
        floor_on_the_ceiling = create_rate_schedule(
            "COMMERCIAL_OFFICE",
            code="RS-T1",
            fixed_service_charge=100.00,
            demand_charge_per_kw=5.00,
            minimum_bill_amount=25000.00,
            tiers=[{"load_factor_max": 100.0, "energy_rate_per_mwh": 70.00}],
        )
        floor_one_cent_above = create_rate_schedule(
            "COMMERCIAL_OFFICE",
            code="RS-T2",
            fixed_service_charge=100.00,
            demand_charge_per_kw=5.00,
            minimum_bill_amount=25000.01,
            tiers=[{"load_factor_max": 100.0, "energy_rate_per_mwh": 70.00}],
        )
        drafted_one = create_agreement(
            loop["id"],
            floor_on_the_ceiling["id"],
            customer_name="Threshold Offices One",
            customer_class="COMMERCIAL_OFFICE",
            reserved_capacity_kw=100.0,
            service_mode="HEATING",
        )
        one = activate_agreement(drafted_one["id"])
        two = active_agreement(
            loop["id"],
            floor_one_cent_above["id"],
            customer_name="Threshold Offices Two",
            customer_class="COMMERCIAL_OFFICE",
            reserved_capacity_kw=100.0,
            service_mode="HEATING",
        )
        for agreement, code in ((one, "MP-T1"), (two, "MP-T2")):
            point = commissioned_point(agreement["id"], segment["id"], code=code)
            add_readings(
                point["id"],
                [
                    {
                        "read_at": JUNE_START,
                        "cumulative_energy_mwh": 0.000,
                        "peak_demand_kw": 40.0,
                    },
                    {
                        "read_at": JUNE_MID,
                        "cumulative_energy_mwh": 1.000,
                        "peak_demand_kw": 45.0,
                    },
                ],
            )
        return {
            "drafted_one": drafted_one,
            "one": one,
            "two": two,
            "invoice_one": create_invoice(one["id"], JUNE_START, JUNE_END, "ACTUAL_TRUE_UP"),
            "invoice_two": create_invoice(two["id"], JUNE_START, JUNE_END, "ACTUAL_TRUE_UP"),
        }

    def test_the_floor_replaces_the_computed_subtotal_on_both_bills(self):
        """A 420.00 subtotal is lifted to 25000.00 and to 25000.01 respectively.

        PRD: "The three charges are added and the sum rounded half-up to two decimal
        places to give a subtotal, and **the subtotal is rounded before the
        minimum-bill comparison**. If that subtotal is strictly less than the tariff's
        `minimum_bill_amount`, `total_amount` becomes the `minimum_bill_amount` and
        `minimum_bill_applied` is set to true; otherwise `total_amount` is the subtotal
        and `minimum_bill_applied` is false."

        Design: Corner/Cross-Cutting Complexity Layers/arrears_threshold_fires_only_strictly_above_the_ceiling_and_resets_on_payment
        """
        built = self._threshold_pair()

        assert built["drafted_one"]["billing_state"] == "CURRENT"
        assert_invoice_determinants(
            built["invoice_one"],
            billed_energy_mwh=1.000,
            billed_demand_kw=50.00,
            load_factor_pct=2.78,
            total_amount=25000.00,
            minimum_bill_applied=True,
        )
        assert_invoice_determinants(
            built["invoice_two"], total_amount=25000.01, minimum_bill_applied=True
        )

    def test_the_cascade_needs_a_balance_strictly_above_the_ceiling(self):
        """25000.00 stays CURRENT while 25000.01 flips to IN_ARREARS.

        PRD: "The arrears threshold is 25,000.00 currency units, and the two
        comparisons are deliberately asymmetric: the billing dimension enters
        `IN_ARREARS` only when the balance is **strictly greater than** the threshold,
        and returns to `CURRENT` when the balance is **at or below** it, so a balance
        sitting exactly on 25,000.00 is `CURRENT`."

        Design: Corner/Cross-Cutting Complexity Layers/arrears_threshold_fires_only_strictly_above_the_ceiling_and_resets_on_payment
        """
        built = self._threshold_pair()

        issue_invoice(built["invoice_one"]["id"])
        assert_agreement_state(
            read_agreement(built["one"]["id"]),
            contract_state="ACTIVE",
            billing_state="CURRENT",
            balance_due=25000.00,
        )

        issue_invoice(built["invoice_two"]["id"])
        assert_agreement_state(
            read_agreement(built["two"]["id"]),
            contract_state="ACTIVE",
            billing_state="IN_ARREARS",
            balance_due=25000.01,
        )

    def test_paying_the_larger_bill_in_full_resets_the_threshold(self):
        """The balance returns to 0.00 and the billing dimension to CURRENT.

        PRD: "It is permitted from `ISSUED` and from `ADJUSTED` and from no other
        state — paying a `DRAFT`, `PAID` or `VOID` invoice is rejected with
        `ERR_INVOICE_STATE_INVALID` — and both permitted edges behave identically: the
        acting `X-User-ID` must equal the invoice's `agreement_id`, the `amount` must
        equal the invoice's `total_amount` exactly — a partial or excess payment is
        refused with `ERR_PAYMENT_AMOUNT_MISMATCH`, so there are no partial
        settlements — and on success `paid_amount` is set to the amount,
        `invoice_state` becomes the terminal `PAID`, the agreement's `balance_due` is
        recomputed, the billing dimension is cascaded from `IN_ARREARS` back to
        `CURRENT` when the recomputed balance is at or below the arrears threshold, and
        both the agreement's and the invoice's `version` are incremented by 1."

        Design: Corner/Cross-Cutting Complexity Layers/arrears_threshold_fires_only_strictly_above_the_ceiling_and_resets_on_payment
        """
        built = self._threshold_pair()
        issue_invoice(built["invoice_one"]["id"])
        issue_invoice(built["invoice_two"]["id"])

        paid = pay_invoice(built["invoice_two"]["id"], 25000.01, built["two"]["id"])
        assert_invoice_determinants(paid, invoice_state="PAID", paid_amount=25000.01)
        assert_agreement_state(
            read_agreement(built["two"]["id"]), billing_state="CURRENT", balance_due=0.00
        )
        assert_invoice_determinants(
            read_invoice(built["invoice_one"]["id"]),
            invoice_state="ISSUED",
            paid_amount=0.00,
        )


class TestEveryCascadeIsVisibleOnTheFirstRead:
    """Nothing lags: the write's own response and the next read already agree."""

    def _immediate(self):
        set_clock()
        loop = create_loop(
            code="LOOP-I",
            name="Immediate Loop I",
            service_mode="HEATING",
            design_supply_temp_c=90.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=5000.0,
        )
        segment = create_segment(
            loop["id"],
            code="SEG-I1",
            length_m=350.0,
            diameter_mm=150,
            install_year=2016,
            insulation_class="A",
            buried_depth_m=1.0,
        )
        tariff = commercial_rate_schedule()
        drafted = create_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Immediate Offices",
            customer_class="COMMERCIAL_OFFICE",
            reserved_capacity_kw=600.0,
            service_mode="HEATING",
        )
        order = work_order_in_state(
            "SCHEDULED",
            segment["id"],
            loop["id"],
            WINDOW_START,
            WINDOW_END,
            work_type="LEAK_REPAIR",
            requires_isolation=True,
        )
        return {"loop": loop, "segment": segment, "drafted": drafted, "order": order}

    def test_the_activation_response_and_the_next_loop_read_already_agree(self):
        """The reservation and the loop version have both moved by the first read.

        PRD: "When the sweep clears, the agreement becomes `ACTIVE`, the loop's
        `committed_reserved_kw` is increased by the agreement's `reserved_capacity_kw`,
        and both the loop's and the agreement's `version` are incremented by 1."

        Design: Corner/Consistency Model/every_cascade_of_a_write_is_already_visible_in_that_write_s_response
        """
        built = self._immediate()
        assert built["loop"]["version"] == 1
        assert built["segment"]["condition"] == "SOUND"
        assert built["order"]["work_state"] == "SCHEDULED"

        activated = activate_agreement(built["drafted"]["id"])
        assert_agreement_state(activated, contract_state="ACTIVE")
        assert activated["version"] == 2

        assert_loop_state(
            read_loop(built["loop"]["id"]), committed_reserved_kw=600.0, version=2
        )

    def test_the_excavation_response_already_carries_the_segment_cascade(self):
        """One request moves the order and the segment it opened together.

        PRD: "On success the order becomes `EXCAVATING` and the segment's `condition`
        is cascaded to `UNDER_REPAIR` with the segment's `version` incremented by 1,
        from whichever band it held: `SOUND → UNDER_REPAIR` and `MONITORED →
        UNDER_REPAIR` move only the segment, while `SUSPECT → UNDER_REPAIR`
        additionally decrements the loop's `suspect_segment_count` by 1 and increments
        the loop's `version` by 1, because the segment has left the suspect
        population."

        Design: Corner/Consistency Model/every_cascade_of_a_write_is_already_visible_in_that_write_s_response
        """
        built = self._immediate()
        activate_agreement(built["drafted"]["id"])

        excavating = begin_excavation(built["order"]["id"])
        assert excavating["work_state"] == "EXCAVATING"

        assert_segment_condition(_read_segment(built["segment"]["id"]), condition="UNDER_REPAIR")

    def test_the_first_loop_read_after_the_excavation_shows_the_isolation(self):
        """Posture, isolation counter and version have all moved already.

        PRD: "When `requires_isolation` is true the loop's `posture` is additionally
        cascaded to `ISOLATED`, its `open_isolation_count` incremented by 1 and its
        `version` incremented by 1."

        Design: Corner/Consistency Model/every_cascade_of_a_write_is_already_visible_in_that_write_s_response
        """
        built = self._immediate()
        activate_agreement(built["drafted"]["id"])
        begin_excavation(built["order"]["id"])

        assert_loop_state(
            read_loop(built["loop"]["id"]),
            posture="ISOLATED",
            open_isolation_count=1,
            version=3,
        )

    def test_a_repeated_read_of_the_isolated_loop_returns_the_same_values(self):
        """No second read is needed, and no second read changes anything.

        PRD: "Every posture change and every counter change increments the loop's
        `version` by 1 and refreshes its `updated_at`."

        Design: Corner/Consistency Model/every_cascade_of_a_write_is_already_visible_in_that_write_s_response
        """
        built = self._immediate()
        activate_agreement(built["drafted"]["id"])
        begin_excavation(built["order"]["id"])

        first = read_loop(built["loop"]["id"])
        second = read_loop(built["loop"]["id"])
        for field in ("posture", "open_isolation_count", "suspect_segment_count", "version"):
            assert second[field] == first[field]
