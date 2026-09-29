"""Which identifier answers a refusal, and which gate fires before the others."""

from test_helpers import (
    API_PREFIX,
    ApiErrorId,
    BILLING_ANALYST,
    CTRL_1,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    NETWORK_ENGINEER,
    NON_EXISTENT_UUID,
    ROLE_SYSTEM_CONTROLLER,
    SYSTEM_CONTROLLER,
    active_agreement,
    add_reading,
    agreement_version,
    api_client,
    assert_agreement_state,
    assert_dispatch_order,
    assert_invoice_determinants,
    assert_loop_state,
    assert_plan_metrics,
    assert_project_economics,
    begin_excavation,
    commercial_rate_schedule,
    commissioned_point,
    connection_agreement_payload,
    create_asset,
    create_fuel_contract,
    create_invoice,
    create_loop,
    create_plan,
    create_project,
    create_segment,
    create_work_order,
    decide_permit,
    dispatch_plan_payload,
    get_success_data,
    invoice_adjust_payload,
    invoice_payload,
    issue_invoice,
    loop_version,
    make_headers,
    meter_reading_payload,
    network_loop_payload,
    plan_in_state,
    plan_orders,
    plan_review_payload,
    project_decision_payload,
    published_forecast,
    read_asset,
    read_invoice,
    read_plan,
    read_project,
    residential_rate_schedule,
    set_availability,
    set_clock,
    single_asset_stack,
    size_project,
    submit_permit,
    university_rate_schedule,
    validate_error,
    validate_paginated,
    validate_success,
    void_invoice,
)

# A caller that supplies an identifier but omits the role header entirely.
ROLELESS_HEADERS = {"X-User-ID": CTRL_1, "Content-Type": "application/json"}


def _count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


def _read_loop(loop_id):
    return get_success_data(api_client.get_network_loop(loop_id, SYSTEM_CONTROLLER))


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


def _read_point(point_id):
    return get_success_data(api_client.get_metering_point(point_id, FIELD_TECHNICIAN))


def _read_agreement(agreement_id):
    return get_success_data(
        api_client.get_connection_agreement(agreement_id, BILLING_ANALYST)
    )


class TestEveryFamilyOwnsItsNotFoundIdentifier:
    """Twelve unknown path ids answer with twelve different error ids."""

    def test_the_network_and_plant_reads_report_their_own_identifiers(self):
        """Segment, contract, asset, forecast and order do not share a code.

        PRD: "Each path identifier resolves, or the corresponding 404:
        `ERR_LOOP_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_FUEL_CONTRACT_NOT_FOUND`,
        `ERR_ASSET_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_RATE_SCHEDULE_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_METERING_POINT_NOT_FOUND`,
        `ERR_READING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND` or
        `ERR_PROJECT_NOT_FOUND`."

        Design: Corner/Errors/every_remaining_not_found_error_id_is_reachable_with_an_unknown_path_id
        """
        set_clock()

        validate_error(
            api_client.get_pipe_segment(NON_EXISTENT_UUID, NETWORK_ENGINEER),
            ApiErrorId.SEGMENT_NOT_FOUND,
        )
        validate_error(
            api_client.get_fuel_supply_contract(NON_EXISTENT_UUID, SYSTEM_CONTROLLER),
            ApiErrorId.FUEL_CONTRACT_NOT_FOUND,
        )
        validate_error(
            api_client.get_production_asset(NON_EXISTENT_UUID, SYSTEM_CONTROLLER),
            ApiErrorId.ASSET_NOT_FOUND,
        )
        validate_error(
            api_client.get_load_forecast(NON_EXISTENT_UUID, DISPATCH_OPERATOR),
            ApiErrorId.FORECAST_NOT_FOUND,
        )
        validate_error(
            api_client.get_dispatch_order(NON_EXISTENT_UUID, DISPATCH_OPERATOR),
            ApiErrorId.ORDER_NOT_FOUND,
        )

    def test_the_commercial_reads_report_their_own_identifiers(self):
        """Tariff, agreement, point, reading and invoice each answer separately.

        PRD: "The loop error guards the single-loop read and the loop emissions
        summary; the segment error guards the single-segment read and the condition
        assessment; the fuel-contract error guards the single-contract read and the
        contract status change; the asset error guards the single-asset read and the
        availability change; the forecast error guards the single-forecast read and
        publication; the plan error guards the single-plan read and every plan action;
        the order, rate-schedule and reading errors guard their single-resource reads;
        the agreement error guards the single-agreement read, activation and status
        change; the metering-point error guards the single-point read, the point's
        register-read listing, commissioning, removal and register-read recording; and
        the invoice, work-order and project errors each guard their single-resource read
        and every action on that resource."

        Design: Corner/Errors/every_remaining_not_found_error_id_is_reachable_with_an_unknown_path_id
        """
        set_clock()

        validate_error(
            api_client.get_rate_schedule(NON_EXISTENT_UUID, BILLING_ANALYST),
            ApiErrorId.RATE_SCHEDULE_NOT_FOUND,
        )
        validate_error(
            api_client.get_connection_agreement(NON_EXISTENT_UUID, BILLING_ANALYST),
            ApiErrorId.AGREEMENT_NOT_FOUND,
        )
        validate_error(
            api_client.get_metering_point(NON_EXISTENT_UUID, FIELD_TECHNICIAN),
            ApiErrorId.METERING_POINT_NOT_FOUND,
        )
        validate_error(
            api_client.get_meter_reading(NON_EXISTENT_UUID, FIELD_TECHNICIAN),
            ApiErrorId.READING_NOT_FOUND,
        )
        validate_error(
            api_client.get_invoice(NON_EXISTENT_UUID, BILLING_ANALYST),
            ApiErrorId.INVOICE_NOT_FOUND,
        )

    def test_the_maintenance_and_expansion_reads_report_their_own_identifiers(self):
        """The last two families close the set of twelve distinct codes.

        PRD: "Each path identifier resolves, or the corresponding 404:
        `ERR_LOOP_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_FUEL_CONTRACT_NOT_FOUND`,
        `ERR_ASSET_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_RATE_SCHEDULE_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_METERING_POINT_NOT_FOUND`,
        `ERR_READING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND` or
        `ERR_PROJECT_NOT_FOUND`."

        Design: Corner/Errors/every_remaining_not_found_error_id_is_reachable_with_an_unknown_path_id
        """
        set_clock()

        validate_error(
            api_client.get_work_order(NON_EXISTENT_UUID, FIELD_TECHNICIAN),
            ApiErrorId.WORK_ORDER_NOT_FOUND,
        )
        validate_error(
            api_client.get_expansion_project(NON_EXISTENT_UUID, NETWORK_ENGINEER),
            ApiErrorId.PROJECT_NOT_FOUND,
        )


class TestMissingAuthHeadersAnswerBeforeRoleAndExistence:
    """Rung one of the ladder does not care what the rest of the request says."""

    def _a_single_loop(self):
        set_clock()
        return create_loop(
            code="LOOP-Q",
            name="Quay Loop Q",
            service_mode="HEATING",
            design_supply_temp_c=90.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=6000.0,
        )

    def test_a_roleless_read_of_a_real_loop_is_rejected_at_rung_one(self):
        """The path resolves and the reader would be authorised, but the role is absent.

        PRD: "**Header presence.** Both `X-User-Role` and `X-User-ID` present and
        non-empty, or `ERR_MISSING_AUTH_HEADERS` (401)."

        Design: Corner/Errors/a_request_with_missing_auth_headers_is_rejected_before_role_and_existence
        """
        loop = self._a_single_loop()

        response = api_client._request(
            "GET", f"{API_PREFIX}/network-loops/{loop['id']}", None, ROLELESS_HEADERS
        )

        validate_error(response, ApiErrorId.MISSING_AUTH_HEADERS)

    def test_a_roleless_read_of_an_unknown_loop_still_answers_401(self):
        """Header presence outranks path existence, so 401 beats 404.

        PRD: "a request that would fail several checks fails on the earliest one, so a
        caller with a bad role never learns whether its body was well formed, and a
        caller acting on a wrongly-stated version never learns whether the target's
        state permitted the action."

        Design: Corner/Errors/a_request_with_missing_auth_headers_is_rejected_before_role_and_existence
        """
        self._a_single_loop()

        response = api_client._request(
            "GET", f"{API_PREFIX}/network-loops/{NON_EXISTENT_UUID}", None, ROLELESS_HEADERS
        )

        validate_error(response, ApiErrorId.MISSING_AUTH_HEADERS)

    def test_an_empty_user_identifier_counts_as_absent_and_writes_nothing(self):
        """A blank identifier fails presence, so the second loop is never created.

        PRD: "**Header presence.** Both `X-User-Role` and `X-User-ID` present and
        non-empty, or `ERR_MISSING_AUTH_HEADERS` (401)."

        Design: Corner/Errors/a_request_with_missing_auth_headers_is_rejected_before_role_and_existence
        """
        self._a_single_loop()

        response = api_client.create_network_loop(
            network_loop_payload(
                code="LOOP-Q2",
                name="Quay Loop Q2",
                service_mode="HEATING",
                design_supply_temp_c=90.0,
                max_pressure_kpa=1400.0,
                rated_capacity_kw=6000.0,
            ),
            make_headers(ROLE_SYSTEM_CONTROLLER, ""),
        )

        validate_error(response, ApiErrorId.MISSING_AUTH_HEADERS)
        assert _count(api_client.list_network_loops(SYSTEM_CONTROLLER)) == 1, (
            "the refused create must leave the loop population untouched"
        )


class TestServiceModeAndForecastLoopMismatchesAreDistinct:
    """Two cross-row compatibility failures, two different identifiers."""

    SERVICE_START = "2026-09-01T00:00:00Z"
    SERVICE_END = "2027-09-01T00:00:00Z"

    def _a_heating_loop_beside_a_dual_loop(self):
        set_clock()
        heating = create_loop(
            code="LOOP-B",
            name="Bayside Loop B",
            service_mode="HEATING",
            design_supply_temp_c=92.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=6000.0,
        )
        dual = create_loop(
            code="LOOP-Z1",
            name="Zenith Loop Z1",
            service_mode="DUAL",
            design_supply_temp_c=92.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=9000.0,
        )
        tariff = university_rate_schedule()
        active_agreement(
            dual["id"],
            tariff["id"],
            customer_name="Zenith College",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
            service_mode="HEATING",
        )
        forecast = published_forecast(
            dual["id"], "2026-08-06T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        return {
            "heating": heating,
            "dual": dual,
            "tariff": tariff,
            "forecast": forecast,
        }

    def _cooling_customer(self, loop_id, tariff_id, customer_name):
        return api_client.create_connection_agreement(
            connection_agreement_payload(
                loop_id,
                tariff_id,
                customer_name=customer_name,
                customer_class="UNIVERSITY",
                reserved_capacity_kw=400.0,
                service_mode="COOLING",
                service_start_date=self.SERVICE_START,
                service_end_date=self.SERVICE_END,
            ),
            BILLING_ANALYST,
        )

    def test_a_cooling_customer_on_a_heating_loop_is_refused(self):
        """The classes agree, so only the thermal service can be the problem.

        PRD: "and the agreement's `service_mode` must be compatible with the loop's
        `service_mode`, meaning either identical to it or permitted because the loop is
        `DUAL`, or the create is rejected with `ERR_SERVICE_MODE_MISMATCH`."

        Design: Corner/Errors/service_mode_and_forecast_loop_mismatches_are_reported_by_distinct_error_ids
        """
        stack = self._a_heating_loop_beside_a_dual_loop()
        assert stack["forecast"]["coincident_demand_kw"] == 756.00

        response = self._cooling_customer(
            stack["heating"]["id"], stack["tariff"]["id"], "Bayside Chillers"
        )

        validate_error(response, ApiErrorId.SERVICE_MODE_MISMATCH)

    def test_a_plan_quoting_another_loops_forecast_is_refused_after_the_version_gate(self):
        """The loop version is freshly read, so the mismatch is what answers.

        PRD: "The forecast must belong to the same loop as the plan, or the create is
        rejected with `ERR_FORECAST_LOOP_MISMATCH`."

        Design: Corner/Errors/service_mode_and_forecast_loop_mismatches_are_reported_by_distinct_error_ids
        """
        stack = self._a_heating_loop_beside_a_dual_loop()
        heating_id = stack["heating"]["id"]

        response = api_client.create_dispatch_plan(
            dispatch_plan_payload(
                heating_id, stack["forecast"]["id"], loop_version(heating_id)
            ),
            DISPATCH_OPERATOR,
        )

        validate_error(response, ApiErrorId.FORECAST_LOOP_MISMATCH)
        assert _count(
            api_client.list_dispatch_plans(DISPATCH_OPERATOR, {"loop_id": heating_id})
        ) == 0, "the refused create must leave the heating loop without plans"

    def test_the_same_cooling_customer_is_admitted_on_a_dual_loop(self):
        """A DUAL loop serves both services, so the identical body succeeds.

        PRD: "A new agreement opens with `contract_state` `PENDING_CAPACITY`,
        `billing_state` `CURRENT`, `billed_demand_ratchet_kw` 0.0 and `balance_due`
        0.0."

        Design: Corner/Errors/service_mode_and_forecast_loop_mismatches_are_reported_by_distinct_error_ids
        """
        stack = self._a_heating_loop_beside_a_dual_loop()

        response = self._cooling_customer(
            stack["dual"]["id"], stack["tariff"]["id"], "Zenith Chillers"
        )

        drafted = validate_success(response, expected_status=201)
        assert drafted["service_mode"] == "COOLING"
        assert_agreement_state(
            drafted, contract_state="PENDING_CAPACITY", billing_state="CURRENT"
        )


class TestRegisterAdvanceAndVariantAdmissibility:
    """A register may only go forwards, and a true-up needs two metered reads."""

    PERIOD_START = "2026-06-01T00:00:00Z"
    PERIOD_END = "2026-07-01T00:00:00Z"

    def _a_meter_with_one_metered_read(self):
        set_clock()
        loop = create_loop(
            code="LOOP-M",
            name="Maple Loop M",
            service_mode="HEATING",
            design_supply_temp_c=85.0,
            max_pressure_kpa=1200.0,
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(loop["id"], code="SEG-M1")
        tariff = residential_rate_schedule()
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Maple Court Apartments",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
            service_mode="HEATING",
        )
        point = commissioned_point(agreement["id"], segment["id"], code="MP-M1")
        add_reading(point["id"], self.PERIOD_START, 10.000, 55.0)
        return {"loop": loop, "agreement": agreement, "point": point}

    def test_a_read_that_goes_backwards_in_energy_is_refused(self):
        """A later instant cannot carry a lower cumulative register value.

        PRD: "Readings are append-only and per point strictly ordered: a new reading's
        `cumulative_energy_mwh` must be greater than or equal to the point's
        `last_reading_energy_mwh`, and its `read_at` must be strictly after the
        `read_at` of the newest existing reading for that point."

        Design: Corner/Errors/register_reads_must_advance_and_a_variant_needs_two_admissible_reads
        """
        stack = self._a_meter_with_one_metered_read()

        response = api_client.create_meter_reading(
            stack["point"]["id"],
            meter_reading_payload("2026-06-15T00:00:00Z", 9.000, 57.0),
            FIELD_TECHNICIAN,
        )

        validate_error(response, ApiErrorId.READING_NOT_MONOTONIC)
        assert _read_point(stack["point"]["id"])["reading_count"] == 1

    def test_a_read_repeating_an_existing_instant_is_refused(self):
        """The energy advances but the instant does not, which is equally illegal.

        PRD: "A register that goes backwards in either dimension is rejected with
        `ERR_READING_NOT_MONOTONIC`."

        Design: Corner/Errors/register_reads_must_advance_and_a_variant_needs_two_admissible_reads
        """
        stack = self._a_meter_with_one_metered_read()

        response = api_client.create_meter_reading(
            stack["point"]["id"],
            meter_reading_payload(self.PERIOD_START, 12.000, 57.0),
            FIELD_TECHNICIAN,
        )

        validate_error(response, ApiErrorId.READING_NOT_MONOTONIC)
        assert _read_point(stack["point"]["id"])["last_reading_energy_mwh"] == 10.000

    def test_a_synthesised_read_still_advances_the_register(self):
        """An estimate is a real register row: it banks and bumps the counters.

        PRD: "Recording a reading raises the point's `last_reading_energy_mwh` to the
        new `cumulative_energy_mwh`, increments `reading_count` by 1 and increments the
        point's `version` by 1."

        Design: Corner/Errors/register_reads_must_advance_and_a_variant_needs_two_admissible_reads
        """
        stack = self._a_meter_with_one_metered_read()

        estimated = add_reading(
            stack["point"]["id"],
            "2026-06-20T00:00:00Z",
            13.000,
            58.0,
            read_type="ESTIMATED",
        )

        assert estimated["read_type"] == "ESTIMATED"
        point = _read_point(stack["point"]["id"])
        assert point["reading_count"] == 2
        assert point["last_reading_energy_mwh"] == 13.000

    def test_the_true_up_is_starved_while_the_estimate_bills_the_same_period(self):
        """One metered read is not a delta; admitting the estimate makes it two.

        PRD: "If fewer than two reads are admitted, the calculation cannot produce a
        consumption delta and the request fails with `ERR_INSUFFICIENT_METER_DATA`."

        Design: Corner/Errors/register_reads_must_advance_and_a_variant_needs_two_admissible_reads
        """
        stack = self._a_meter_with_one_metered_read()
        agreement_id = stack["agreement"]["id"]
        add_reading(
            stack["point"]["id"],
            "2026-06-20T00:00:00Z",
            13.000,
            58.0,
            read_type="ESTIMATED",
        )

        refused = api_client.create_invoice(
            invoice_payload(
                agreement_id,
                self.PERIOD_START,
                self.PERIOD_END,
                "ACTUAL_TRUE_UP",
                agreement_version(agreement_id),
            ),
            BILLING_ANALYST,
        )
        billed = create_invoice(
            agreement_id, self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )

        validate_error(refused, ApiErrorId.INSUFFICIENT_METER_DATA)
        assert_invoice_determinants(
            billed,
            billed_energy_mwh=3.000,
            billed_demand_kw=60.00,
            load_factor_pct=6.94,
            energy_charge=330.00,
            total_amount=3000.00,
            minimum_bill_applied=True,
            variant_applied="ESTIMATED",
        )


class TestOptimiseWithEveryMachineOutOfService:
    """The gate reads availability, not the mere existence of a machine."""

    def _a_loop_whose_only_asset_is_out(self):
        stack = single_asset_stack()
        out_of_service = set_availability(
            stack["asset"]["id"], "OUTAGE", reason="annual boiler overhaul"
        )
        forecast = published_forecast(
            stack["loop"]["id"], "2026-08-05T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        plan = create_plan(stack["loop"]["id"], forecast["id"])
        return {
            "loop": stack["loop"],
            "asset": out_of_service,
            "forecast": forecast,
            "plan": plan,
        }

    def test_the_plan_opens_at_its_creation_defaults(self):
        """Nothing is computed at creation, so every metric starts at zero.

        PRD: "A new plan opens at `plan_state` `DRAFT` with `block_hours` fixed at 24.0
        — the dispatch block is always the full day — and with `authored_by_user_id`
        taken from the acting `X-User-ID`, `reviewed_by_user_id` null, and
        `allocated_capacity_kw`, `unserved_demand_kw`, `total_dispatch_cost`,
        `total_emissions_kg`, `reserve_margin_pct` and `fuel_diversity_hhi` all at
        0.0."

        Design: Corner/Errors/optimize_refuses_a_loop_whose_only_asset_is_out_of_service
        """
        stack = self._a_loop_whose_only_asset_is_out()

        assert stack["asset"]["availability_state"] == "OUTAGE"
        assert stack["forecast"]["coincident_demand_kw"] == 756.00
        assert_plan_metrics(
            stack["plan"],
            plan_state="DRAFT",
            allocated_capacity_kw=0.00,
            unserved_demand_kw=0.00,
            total_dispatch_cost=0.00,
            reviewed_by_user_id=None,
        )

    def test_optimising_an_empty_eligible_set_is_refused_and_changes_nothing(self):
        """The one boiler is out, so the merit-order input set is empty.

        PRD: "If the eligible set is empty, optimisation fails with
        `ERR_NO_ELIGIBLE_ASSETS`."

        Design: Corner/Errors/optimize_refuses_a_loop_whose_only_asset_is_out_of_service
        """
        stack = self._a_loop_whose_only_asset_is_out()
        plan_id = stack["plan"]["id"]

        response = api_client.optimize_dispatch_plan(plan_id, {}, DISPATCH_OPERATOR)

        validate_error(response, ApiErrorId.NO_ELIGIBLE_ASSETS)
        assert_plan_metrics(
            read_plan(plan_id),
            plan_state="DRAFT",
            unserved_demand_kw=0.0,
            total_dispatch_cost=0.0,
        )
        assert _count(
            api_client.list_dispatch_orders(DISPATCH_OPERATOR, {"plan_id": plan_id})
        ) == 0, "a refused optimisation must not leave orders behind"


class TestInvoiceTransitionsOutsideTheDeclaredFromStates:
    """One identifier covers every wrong-from-state on the invoice machine."""

    PERIOD_START = "2026-06-01T00:00:00Z"
    PERIOD_END = "2026-07-01T00:00:00Z"

    def _a_draft_invoice(self):
        set_clock()
        loop = create_loop(
            code="LOOP-M",
            name="Maple Loop M",
            service_mode="HEATING",
            design_supply_temp_c=85.0,
            max_pressure_kpa=1200.0,
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(loop["id"], code="SEG-M1")
        tariff = residential_rate_schedule()
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Maple Court Apartments",
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=120.0,
            service_mode="HEATING",
        )
        point = commissioned_point(agreement["id"], segment["id"], code="MP-M1")
        add_reading(point["id"], self.PERIOD_START, 10.000, 55.0)
        add_reading(point["id"], "2026-06-28T00:00:00Z", 14.000, 60.0)
        invoice = create_invoice(
            agreement["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )
        return {"agreement": agreement, "invoice": invoice}

    def test_adjusting_a_draft_invoice_is_refused(self):
        """Adjustment starts at ISSUED, so a draft has nowhere to be adjusted from.

        PRD: "It is permitted from two source states, which behave identically apart
        from the state they land in: `ISSUED → ADJUSTED` moves the invoice to
        `ADJUSTED`, and `ADJUSTED → ADJUSTED` is a self-loop that leaves it there, so
        repeated re-adjustment is explicitly allowed and always recomputes from current
        readings rather than from the previously stored figures."

        Design: Corner/Errors/invoice_transitions_outside_the_declared_from_states_are_all_refused
        """
        stack = self._a_draft_invoice()
        assert stack["invoice"]["invoice_state"] == "DRAFT"
        assert stack["invoice"]["total_amount"] == 3000.00

        response = api_client.adjust_invoice(
            stack["invoice"]["id"], invoice_adjust_payload("ESTIMATED"), BILLING_ANALYST
        )

        validate_error(response, ApiErrorId.INVOICE_STATE_INVALID)
        assert read_invoice(stack["invoice"]["id"])["invoice_state"] == "DRAFT"

    def test_issuing_the_same_invoice_twice_is_refused(self):
        """The first issue moves the money and the second finds no draft.

        PRD: "**Issuing** advances a `DRAFT` invoice to `ISSUED` and is the moment money
        becomes owed: it raises the agreement's `billed_demand_ratchet_kw` to this
        invoice's `billed_demand_kw` when the invoice's figure is higher — the ratchet
        is only ever raised, never lowered, and only on this one edge — recomputes the
        agreement's `balance_due`, cascades the billing dimension from `CURRENT` to
        `IN_ARREARS` when the recomputed balance exceeds the arrears threshold, and
        increments both the agreement's and the invoice's `version` by 1."

        Design: Corner/Errors/invoice_transitions_outside_the_declared_from_states_are_all_refused
        """
        stack = self._a_draft_invoice()
        invoice_id = stack["invoice"]["id"]

        issued = issue_invoice(invoice_id)
        again = api_client.issue_invoice(invoice_id, {}, BILLING_ANALYST)

        assert issued["invoice_state"] == "ISSUED"
        assert_agreement_state(
            _read_agreement(stack["agreement"]["id"]),
            billing_state="CURRENT",
            balance_due=3000.00,
            billed_demand_ratchet_kw=60.00,
        )
        validate_error(again, ApiErrorId.INVOICE_STATE_INVALID)

    def test_adjusting_a_voided_invoice_is_refused(self):
        """Voiding clears the balance and closes the row to further adjustment.

        PRD: "**Voiding** takes an invoice to the terminal `VOID` with an optional
        `reason` and is permitted from exactly three source states — `DRAFT`, `ISSUED`
        and `ADJUSTED`; voiding an already `PAID` or `VOID` invoice is rejected with
        `ERR_INVOICE_STATE_INVALID`."

        Design: Corner/Errors/invoice_transitions_outside_the_declared_from_states_are_all_refused
        """
        stack = self._a_draft_invoice()
        invoice_id = stack["invoice"]["id"]
        issue_invoice(invoice_id)

        voided = void_invoice(invoice_id, reason="billed to the wrong customer")
        response = api_client.adjust_invoice(
            invoice_id, invoice_adjust_payload("ACTUAL_TRUE_UP"), BILLING_ANALYST
        )

        assert voided["invoice_state"] == "VOID"
        assert_agreement_state(
            _read_agreement(stack["agreement"]["id"]), balance_due=0.00
        )
        validate_error(response, ApiErrorId.INVOICE_STATE_INVALID)
        assert read_invoice(invoice_id)["invoice_state"] == "VOID"


class TestSizingAndApprovalRejectUnworkableCandidates:
    """A physical guard at sizing and a fiscal guard at approval."""

    def _two_screening_candidates(self):
        set_clock()
        loop = create_loop(
            code="LOOP-X",
            name="Expansion Loop X",
            service_mode="HEATING",
            design_supply_temp_c=95.0,
            max_pressure_kpa=1600.0,
            rated_capacity_kw=12000.0,
        )
        tariff = commercial_rate_schedule()
        oversized = create_project(
            loop["id"],
            tariff["id"],
            candidate_customer_name="Mega Process Park",
            requested_capacity_kw=40000.0,
            route_length_m=600.0,
            assumed_annual_energy_mwh=9000.0,
            assumed_marginal_cost_per_mwh=40.00,
            design_delta_t_c=10.0,
        )
        remote = create_project(
            loop["id"],
            tariff["id"],
            candidate_customer_name="Far Meadow Lodge",
            requested_capacity_kw=300.0,
            route_length_m=4500.0,
            assumed_annual_energy_mwh=500.0,
            assumed_marginal_cost_per_mwh=55.00,
            design_delta_t_c=30.0,
        )
        return {"loop": loop, "tariff": tariff, "oversized": oversized, "remote": remote}

    def test_a_flow_no_standard_diameter_can_carry_is_refused(self):
        """A 40000 kW draw at a 10 K drop busts both limits at every diameter.

        PRD: "`selected_diameter_mm` is the smallest feasible diameter; when no standard
        diameter satisfies both limits, sizing fails with `ERR_NO_FEASIBLE_PIPE_SIZE`."

        Design: Corner/Errors/expansion_sizing_and_approval_reject_infeasible_and_uneconomic_candidates
        """
        stack = self._two_screening_candidates()

        response = api_client.size_expansion_project(
            stack["oversized"]["id"], {}, NETWORK_ENGINEER
        )

        validate_error(response, ApiErrorId.NO_FEASIBLE_PIPE_SIZE)
        assert_project_economics(
            read_project(stack["oversized"]["id"]),
            project_state="SCREENING",
            selected_diameter_mm=None,
            npv=0.0,
        )

    def test_a_long_route_for_a_small_load_sizes_but_loses_money(self):
        """The smallest pipe carries the flow; the route cost sinks the case.

        PRD: "`estimated_capex` is the `selected_diameter_mm` multiplied by the
        `route_length_m` multiplied by a unit rate of 9.5 currency units per millimetre
        of diameter per metre of route, plus a fixed connection cost of 85,000.00,
        rounded half-up to two decimal places."

        Design: Corner/Errors/expansion_sizing_and_approval_reject_infeasible_and_uneconomic_candidates
        """
        stack = self._two_screening_candidates()

        sized = size_project(stack["remote"]["id"])

        assert_project_economics(
            sized,
            project_state="SIZED",
            design_flow_m3_per_h=8.598,
            selected_diameter_mm=80,
            estimated_capex=3505000.00,
            annual_net_margin=-31825.00,
            npv=-3870030.24,
        )

    def test_approval_is_refused_and_only_rejection_remains(self):
        """A negative present value cannot be approved, but it can be dropped.

        PRD: "Approval is legal only from `SIZED` and only when the project's `npv` is
        at or above 0.0; a negative net present value is refused with
        `ERR_PROJECT_NPV_NEGATIVE`, and a project can be re-sized on revised assumptions
        and re-decided."

        Design: Corner/Errors/expansion_sizing_and_approval_reject_infeasible_and_uneconomic_candidates
        """
        stack = self._two_screening_candidates()
        project_id = stack["remote"]["id"]
        size_project(project_id)

        refused = api_client.decide_expansion_project(
            project_id,
            project_decision_payload("APPROVE", decision_note="trying to force it through"),
            SYSTEM_CONTROLLER,
        )
        assert read_project(project_id)["project_state"] == "SIZED"
        rejected = validate_success(
            api_client.decide_expansion_project(
                project_id,
                project_decision_payload(
                    "REJECT", decision_note="route cost cannot be recovered"
                ),
                SYSTEM_CONTROLLER,
            )
        )

        validate_error(refused, ApiErrorId.PROJECT_NPV_NEGATIVE)
        assert rejected["project_state"] == "REJECTED"


class TestApprovalRefusesASingleFuelBlock:
    """Ample reserve does not excuse fuel concentration."""

    def _a_gas_heavy_fleet_awaiting_review(self):
        set_clock()
        loop = create_loop(
            code="LOOP-P",
            name="Parkside Loop P",
            service_mode="HEATING",
            design_supply_temp_c=92.0,
            max_pressure_kpa=1500.0,
            rated_capacity_kw=8000.0,
        )
        gas = create_fuel_contract(
            supplier_code="FC-PGAS",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=40000.0,
            price_per_mwh=28.00,
            delivery_firmness="FIRM",
        )
        biomass = create_fuel_contract(
            supplier_code="FC-PBIO",
            fuel_type="BIOMASS",
            contracted_energy_mwh_per_year=9000.0,
            price_per_mwh=86.00,
            delivery_firmness="INTERRUPTIBLE",
        )
        create_asset(
            loop["id"],
            code="P_G1",
            asset_type="BOILER",
            rated_capacity_kw=1000.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=30.00,
            emission_factor_kg_per_mwh=220.0,
            fuel_contract_id=gas["id"],
        )
        create_asset(
            loop["id"],
            code="P_G2",
            asset_type="BOILER",
            rated_capacity_kw=1000.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=31.00,
            emission_factor_kg_per_mwh=225.0,
            fuel_contract_id=gas["id"],
        )
        create_asset(
            loop["id"],
            code="P_B",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=1000.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=90.00,
            emission_factor_kg_per_mwh=30.0,
            fuel_contract_id=biomass["id"],
        )
        tariff = university_rate_schedule()
        active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Parkside Institute",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
            service_mode="HEATING",
        )
        forecast = published_forecast(
            loop["id"], "2026-08-06T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        plan = plan_in_state("SUBMITTED", loop["id"], forecast["id"])
        return {"loop": loop, "forecast": forecast, "plan": plan}

    def test_the_cheapest_boiler_covers_the_whole_block_alone(self):
        """One 1000 kW gas unit serves 756.00 kW, so the index reaches its maximum.

        PRD: "For each distinct fuel key, the energy dispatched under that key is summed
        and rounded half-up to three decimal places, divided by that plan total, and the
        quotient squared; the squares are added across all distinct keys and the sum
        rounded half-up to four decimal places to give `fuel_diversity_hhi`."

        Design: Corner/Errors/approval_refuses_a_plan_that_leans_on_a_single_fuel_even_with_ample_reserve
        """
        stack = self._a_gas_heavy_fleet_awaiting_review()

        assert stack["forecast"]["coincident_demand_kw"] == 756.00
        assert_plan_metrics(
            stack["plan"],
            plan_state="SUBMITTED",
            unserved_demand_kw=0.00,
            total_dispatch_cost=544.32,
            reserve_margin_pct=164.55,
            fuel_diversity_hhi=1.0000,
        )
        assert len(plan_orders(stack["plan"]["id"])) == 1

    def test_the_concentration_gate_refuses_the_approval(self):
        """The reserve margin is comfortable and the plan is still refused.

        PRD: "and its `fuel_diversity_hhi` must be at or below 0.55, or the approval is
        refused with `ERR_FUEL_DIVERSITY_BREACH`."

        Design: Corner/Errors/approval_refuses_a_plan_that_leans_on_a_single_fuel_even_with_ample_reserve
        """
        stack = self._a_gas_heavy_fleet_awaiting_review()
        plan_id = stack["plan"]["id"]

        response = api_client.review_dispatch_plan(
            plan_id,
            plan_review_payload("APPROVE", review_note="single-fuel block"),
            SYSTEM_CONTROLLER,
        )

        validate_error(response, ApiErrorId.FUEL_DIVERSITY_BREACH)
        assert_plan_metrics(
            read_plan(plan_id), plan_state="SUBMITTED", reviewed_by_user_id=None
        )
        assert _count(
            api_client.list_dispatch_orders(DISPATCH_OPERATOR, {"plan_id": plan_id})
        ) == 1, "the refused review must leave the single order in place"


class TestCommitRefusedByAnIsolatingExcavation:
    """The other half of the isolation interlock: dig first, then commit."""

    WINDOW_START = "2026-07-31T00:00:00Z"
    WINDOW_END = "2026-08-02T00:00:00Z"

    def _an_approved_plan_and_a_scheduled_isolation(self):
        set_clock()
        loop = create_loop(
            code="LOOP-W",
            name="Westgate Loop W",
            service_mode="HEATING",
            design_supply_temp_c=90.0,
            max_pressure_kpa=1400.0,
            rated_capacity_kw=6000.0,
        )
        segment = create_segment(loop["id"], code="SEG-W1")
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
            code="W_G",
            asset_type="BOILER",
            rated_capacity_kw=400.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=30.00,
            emission_factor_kg_per_mwh=220.0,
            fuel_contract_id=gas["id"],
        )
        create_asset(
            loop["id"],
            code="W_B",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=500.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=32.00,
            emission_factor_kg_per_mwh=30.0,
            fuel_contract_id=biomass["id"],
        )
        create_asset(
            loop["id"],
            code="W_S",
            asset_type="BOILER",
            rated_capacity_kw=2000.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=90.00,
            emission_factor_kg_per_mwh=260.0,
            fuel_contract_id=oil["id"],
        )
        tariff = university_rate_schedule()
        active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Westgate College",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
            service_mode="HEATING",
        )
        forecast = published_forecast(
            loop["id"], "2026-08-06T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        plan = plan_in_state("APPROVED", loop["id"], forecast["id"])
        order = create_work_order(
            segment["id"],
            loop["id"],
            self.WINDOW_START,
            self.WINDOW_END,
            work_type="LEAK_REPAIR",
            requires_isolation=True,
        )
        submit_permit(order["id"])
        scheduled = decide_permit(
            order["id"], "GRANTED", decision_note="isolation approved"
        )
        return {
            "loop": loop,
            "segment": segment,
            "plan": plan,
            "order": scheduled,
        }

    def test_the_plan_clears_both_resilience_gates_before_the_dig(self):
        """A two-fuel block on a spare-heavy fleet is approvable.

        PRD: "On `APPROVE`, two resilience gates are evaluated in that order before the
        plan may advance from `SUBMITTED` to `APPROVED`: the plan's
        `reserve_margin_pct` must be at or above 15.00 percent, or the approval is
        refused with `ERR_RESERVE_MARGIN_INSUFFICIENT`; and its `fuel_diversity_hhi`
        must be at or below 0.55, or the approval is refused with
        `ERR_FUEL_DIVERSITY_BREACH`."

        Design: Corner/Errors/commit_refuses_a_loop_that_an_isolating_excavation_took_out_of_normal
        """
        stack = self._an_approved_plan_and_a_scheduled_isolation()

        assert_plan_metrics(
            stack["plan"],
            plan_state="APPROVED",
            reserve_margin_pct=19.05,
            fuel_diversity_hhi=0.5017,
        )
        assert stack["order"]["work_state"] == "SCHEDULED"

    def test_the_dig_is_cleared_because_no_plan_is_committed_yet(self):
        """Only a COMMITTED plan blocks isolation, and this one is merely approved.

        PRD: "When `requires_isolation` is true the loop's `posture` is additionally
        cascaded to `ISOLATED`, its `open_isolation_count` incremented by 1 and its
        `version` incremented by 1."

        Design: Corner/Errors/commit_refuses_a_loop_that_an_isolating_excavation_took_out_of_normal
        """
        stack = self._an_approved_plan_and_a_scheduled_isolation()

        excavating = begin_excavation(stack["order"]["id"])

        assert excavating["work_state"] == "EXCAVATING"
        assert_loop_state(
            _read_loop(stack["loop"]["id"]), posture="ISOLATED", open_isolation_count=1
        )
        assert _read_segment(stack["segment"]["id"])["condition"] == "UNDER_REPAIR"

    def test_commitment_is_refused_while_the_loop_is_isolated(self):
        """The posture precondition is exact: CONSTRAINED and ISOLATED both fail.

        PRD: "Three preconditions apply: the plan is `APPROVED`, the loop's `posture` is
        exactly `NORMAL` — not `CONSTRAINED` and not `ISOLATED`, or the commit is
        refused with `ERR_LOOP_NOT_NORMAL` — and for every dispatch order whose
        `discharged_kwh` is greater than zero the referenced asset's
        `state_of_charge_kwh` is at or above that `discharged_kwh`, or the commit is
        refused with `ERR_STORAGE_ENERGY_INSUFFICIENT`."

        Design: Corner/Errors/commit_refuses_a_loop_that_an_isolating_excavation_took_out_of_normal
        """
        stack = self._an_approved_plan_and_a_scheduled_isolation()
        plan_id = stack["plan"]["id"]
        begin_excavation(stack["order"]["id"])

        response = api_client.commit_dispatch_plan(plan_id, {}, DISPATCH_OPERATOR)

        validate_error(response, ApiErrorId.LOOP_NOT_NORMAL)
        assert read_plan(plan_id)["plan_state"] == "APPROVED"
        assert _count(
            api_client.list_dispatch_orders(DISPATCH_OPERATOR, {"plan_id": plan_id})
        ) == 2, "the refused commit must leave both orders standing"


class TestCommitRefusedByTheLiveStateOfCharge:
    """Planning sizes the tank from nameplate; commitment reads the meter."""

    def _an_approved_plan_leaning_on_a_thin_tank(self):
        set_clock()
        loop = create_loop(
            code="LOOP-D",
            name="Dockyard Loop D",
            service_mode="HEATING",
            design_supply_temp_c=85.0,
            max_pressure_kpa=1200.0,
            rated_capacity_kw=5000.0,
        )
        gas = create_fuel_contract(
            supplier_code="FC-DGAS",
            fuel_type="NATURAL_GAS",
            contracted_energy_mwh_per_year=20000.0,
            price_per_mwh=42.00,
            delivery_firmness="FIRM",
        )
        biomass = create_fuel_contract(
            supplier_code="FC-DBIO",
            fuel_type="BIOMASS",
            contracted_energy_mwh_per_year=12000.0,
            price_per_mwh=48.00,
            delivery_firmness="FIRM",
        )
        oil = create_fuel_contract(
            supplier_code="FC-DOIL",
            fuel_type="FUEL_OIL",
            contracted_energy_mwh_per_year=3000.0,
            price_per_mwh=115.00,
            delivery_firmness="INTERRUPTIBLE",
        )
        storage = create_asset(
            loop["id"],
            code="D_STO",
            asset_type="THERMAL_STORAGE",
            rated_capacity_kw=200.0,
            min_stable_output_kw=0.0,
            marginal_cost_per_mwh=4.00,
            emission_factor_kg_per_mwh=0.0,
            storage_capacity_kwh=3200.0,
            state_of_charge_kwh=500.0,
        )
        create_asset(
            loop["id"],
            code="D_CHP",
            asset_type="CHP",
            rated_capacity_kw=380.0,
            min_stable_output_kw=100.0,
            marginal_cost_per_mwh=45.00,
            emission_factor_kg_per_mwh=200.0,
            fuel_contract_id=gas["id"],
        )
        create_asset(
            loop["id"],
            code="D_BIO",
            asset_type="BIOMASS_BOILER",
            rated_capacity_kw=1200.0,
            min_stable_output_kw=50.0,
            marginal_cost_per_mwh=50.00,
            emission_factor_kg_per_mwh=25.0,
            fuel_contract_id=biomass["id"],
        )
        create_asset(
            loop["id"],
            code="D_OIL",
            asset_type="BOILER",
            rated_capacity_kw=900.0,
            min_stable_output_kw=200.0,
            marginal_cost_per_mwh=120.00,
            emission_factor_kg_per_mwh=270.0,
            fuel_contract_id=oil["id"],
        )
        tariff = university_rate_schedule()
        active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Dockyard Polytechnic",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
            service_mode="HEATING",
        )
        forecast = published_forecast(
            loop["id"], "2026-08-06T00:00:00Z", occupancy_profile="WEEKDAY_FULL"
        )
        plan = plan_in_state("APPROVED", loop["id"], forecast["id"])
        return {"loop": loop, "storage": storage, "plan": plan}

    def test_the_storage_order_is_sized_from_the_nameplate_tank(self):
        """3200 kWh over four hours caps the 200 kW rating, so the order asks 800 kWh.

        PRD: "A `THERMAL_STORAGE` asset offers the lesser of its `rated_capacity_kw` and
        its `storage_capacity_kwh` divided by the four-hour storage discharge window,
        with that quotient rounded half-up to two decimal places; note carefully that
        the planning horizon sizes storage from nameplate `storage_capacity_kwh`,
        **not** from the live `state_of_charge_kwh`, which is checked only at
        commitment."

        Design: Corner/Errors/commit_refuses_a_storage_order_larger_than_the_live_state_of_charge
        """
        stack = self._an_approved_plan_leaning_on_a_thin_tank()

        assert stack["storage"]["state_of_charge_kwh"] == 500.0
        assert_plan_metrics(
            stack["plan"],
            plan_state="APPROVED",
            total_dispatch_cost=624.80,
            reserve_margin_pct=95.77,
            fuel_diversity_hhi=0.5081,
        )
        assert_dispatch_order(
            plan_orders(stack["plan"]["id"])[0],
            asset_id=stack["storage"]["id"],
            merit_rank=1,
            allocated_kw=200.0,
            discharged_kwh=800.00,
        )

    def test_commitment_is_refused_and_the_charge_ledger_is_untouched(self):
        """The tank holds 500 kWh against an 800 kWh instruction.

        PRD: "On success the plan becomes `COMMITTED`, and for every storage order the
        referenced asset's `state_of_charge_kwh` is decreased by that order's
        `discharged_kwh` with the asset's `version` incremented by 1."

        Design: Corner/Errors/commit_refuses_a_storage_order_larger_than_the_live_state_of_charge
        """
        stack = self._an_approved_plan_leaning_on_a_thin_tank()
        plan_id = stack["plan"]["id"]

        response = api_client.commit_dispatch_plan(plan_id, {}, DISPATCH_OPERATOR)

        validate_error(response, ApiErrorId.STORAGE_ENERGY_INSUFFICIENT)
        assert read_plan(plan_id)["plan_state"] == "APPROVED"
        assert read_asset(stack["storage"]["id"])["state_of_charge_kwh"] == 500.0
