"""Initial states, refused edges, terminal lock-outs and posture cascades."""

from test_helpers import (
    ApiErrorId,
    BILLING_ANALYST,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    FIELD_TECHNICIAN_ALT,
    NETWORK_ENGINEER,
    SYSTEM_CONTROLLER,
    active_agreement,
    add_reading,
    agreement_version,
    api_client,
    assert_agreement_state,
    assert_invoice_determinants,
    assert_loop_state,
    assert_plan_metrics,
    assert_segment_condition,
    assess_segment,
    backfill_work_order,
    begin_excavation,
    begin_repair,
    campus_dispatch_stack,
    commercial_rate_schedule,
    commission_point,
    commissioned_point,
    complete_work_order,
    create_agreement,
    create_asset,
    create_forecast,
    create_fuel_contract,
    create_invoice,
    create_loop,
    create_plan,
    create_point,
    create_project,
    create_segment,
    create_work_order,
    decide_permit,
    get_success_data,
    issue_invoice,
    make_customer_account_headers,
    optimize_plan,
    payment_payload,
    published_forecast,
    read_agreement,
    read_asset,
    read_invoice,
    read_loop,
    read_plan,
    review_plan,
    set_clock,
    set_fuel_contract_status,
    submit_permit,
    submit_plan,
    university_rate_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


def _read_point(point_id):
    return get_success_data(api_client.get_metering_point(point_id, FIELD_TECHNICIAN))


def _order_count(plan_id):
    _, meta = validate_paginated(
        api_client.list_dispatch_orders(DISPATCH_OPERATOR, {"plan_id": plan_id})
    )
    return meta["total_count"]


class TestDeclaredInitialStates:
    """Five machines, each with a state no create endpoint accepts as input."""

    def test_a_new_segment_contract_and_forecast_open_where_declared(self):
        """Three unrelated machines all report their declared opening state.

        PRD: "A draft opens at `forecast_state` `DRAFT` with `variant_applied` null,
        `coincident_demand_kw` 0.0, `projected_energy_mwh` 0.0 and
        `contributing_agreement_count` 0."

        Design: Corner/State Machines/newly_created_rows_start_in_their_declared_initial_states
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)

        segment = create_segment(loop["id"], code="SEG-Z1")
        contract = create_fuel_contract(supplier_code="FCG-Z")
        forecast = create_forecast(loop["id"], "2026-08-05T00:00:00Z")

        assert segment["condition"] == "SOUND"
        assert contract["status"] == "ACTIVE"
        assert forecast["forecast_state"] == "DRAFT"
        assert forecast["variant_applied"] is None
        assert forecast["coincident_demand_kw"] == 0.0
        assert forecast["contributing_agreement_count"] == 0

    def test_a_new_plan_opens_as_an_unreviewed_draft_over_a_full_day(self):
        """The dispatch block is fixed at a full day and no metric is filled in yet.

        PRD: "A new plan opens at `plan_state` `DRAFT` with `block_hours` fixed at
        24.0 — the dispatch block is always the full day — and with
        `authored_by_user_id` taken from the acting `X-User-ID`,
        `reviewed_by_user_id` null, and `allocated_capacity_kw`,
        `unserved_demand_kw`, `total_dispatch_cost`, `total_emissions_kg`,
        `reserve_margin_pct` and `fuel_diversity_hhi` all at 0.0."

        Design: Corner/State Machines/newly_created_rows_start_in_their_declared_initial_states
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        tariff = commercial_rate_schedule(code="RS-Z1")
        active_agreement(loop["id"], tariff["id"], customer_name="Zone One Tower")
        create_asset(loop["id"], code="Z_B1")
        forecast = published_forecast(loop["id"], "2026-08-05T00:00:00Z")

        plan = create_plan(loop["id"], forecast["id"])

        assert plan["block_hours"] == 24.0
        assert plan["reviewed_by_user_id"] is None
        assert_plan_metrics(
            plan,
            plan_state="DRAFT",
            allocated_capacity_kw=0.0,
            unserved_demand_kw=0.0,
            total_dispatch_cost=0.0,
            total_emissions_kg=0.0,
            reserve_margin_pct=0.0,
            fuel_diversity_hhi=0.0,
        )

    def test_a_new_work_order_and_expansion_project_open_where_declared(self):
        """A raised job waits on a pending permit; a screened project has no size yet.

        PRD: "The order opens in `DRAFT` with `permit_decision` `PENDING`,
        `reported_by_user_id` taken from the acting `X-User-ID` and
        `completed_by_user_id` null."

        Design: Corner/State Machines/newly_created_rows_start_in_their_declared_initial_states
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        segment = create_segment(loop["id"], code="SEG-Z1")
        tariff = commercial_rate_schedule(code="RS-Z1")

        order = create_work_order(
            segment["id"],
            loop["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T16:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
        )
        project = create_project(loop["id"], tariff["id"])

        assert order["work_state"] == "DRAFT"
        assert order["permit_decision"] == "PENDING"
        assert order["completed_by_user_id"] is None
        assert project["project_state"] == "SCREENING"
        assert project["selected_diameter_mm"] is None
        assert project["npv"] == 0.0


class TestPlanEdgesRefusedFromDraft:
    """DRAFT offers only optimise and submit; the three later actions are refused."""

    def _untouched_draft_plan(self):
        set_clock()
        loop = create_loop(
            code="LOOP-P",
            name="Parkside Loop P",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
        tariff = university_rate_schedule(code="RS-P")
        active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Parkside University",
            customer_class="UNIVERSITY",
            reserved_capacity_kw=1000.0,
        )
        create_asset(loop["id"], code="P_G1")
        forecast = published_forecast(loop["id"], "2026-08-05T00:00:00Z")
        plan = create_plan(loop["id"], forecast["id"])
        return {"loop": loop, "forecast": forecast, "plan": plan}

    def test_committing_a_draft_plan_reports_the_plan_state(self):
        """Commitment declares APPROVED as its only from-state.

        PRD: "Three preconditions apply: the plan is `APPROVED`, the loop's
        `posture` is exactly `NORMAL` — not `CONSTRAINED` and not `ISOLATED`, or the
        commit is refused with `ERR_LOOP_NOT_NORMAL`".

        Design: Corner/State Machines/commit_on_a_draft_plan_is_rejected_as_an_invalid_from_state
        """
        stack = self._untouched_draft_plan()

        response = api_client.commit_dispatch_plan(
            stack["plan"]["id"], {}, DISPATCH_OPERATOR
        )

        validate_error(response, ApiErrorId.PLAN_STATE_INVALID)

    def test_reviewing_and_reconciling_a_draft_plan_report_the_plan_state(self):
        """Review demands SUBMITTED and reconciliation demands COMMITTED.

        PRD: "A `SystemController` may move a `COMMITTED` plan to `RECONCILED` only
        when the forecast the plan serves has a `variant_applied` of
        `ACTUAL_WEIGHTED_FINAL`".

        Design: Corner/State Machines/commit_on_a_draft_plan_is_rejected_as_an_invalid_from_state
        """
        stack = self._untouched_draft_plan()

        review = api_client.review_dispatch_plan(
            stack["plan"]["id"], {"decision": "APPROVE"}, SYSTEM_CONTROLLER
        )
        reconcile = api_client.reconcile_dispatch_plan(
            stack["plan"]["id"], {}, SYSTEM_CONTROLLER
        )

        validate_error(review, ApiErrorId.PLAN_STATE_INVALID)
        validate_error(reconcile, ApiErrorId.PLAN_STATE_INVALID)

    def test_three_refused_actions_leave_the_plan_a_draft_with_no_orders(self):
        """None of the refused edges recorded a reviewer or built an order set.

        PRD: "**Optimising** the plan is a self-loop from `DRAFT` back to `DRAFT`
        that may be run as often as the operator likes; each run deletes every
        dispatch order the plan currently owns and rebuilds the set from scratch."

        Design: Corner/State Machines/commit_on_a_draft_plan_is_rejected_as_an_invalid_from_state
        """
        stack = self._untouched_draft_plan()
        api_client.commit_dispatch_plan(stack["plan"]["id"], {}, DISPATCH_OPERATOR)
        api_client.review_dispatch_plan(
            stack["plan"]["id"], {"decision": "APPROVE"}, SYSTEM_CONTROLLER
        )
        api_client.reconcile_dispatch_plan(stack["plan"]["id"], {}, SYSTEM_CONTROLLER)

        assert_plan_metrics(
            read_plan(stack["plan"]["id"]),
            plan_state="DRAFT",
            reviewed_by_user_id=None,
        )
        assert _order_count(stack["plan"]["id"]) == 0


class TestActivationIsNotIdempotent:
    """Repeating a successful activation must not reserve the capacity twice."""

    def _activated_customer(self):
        set_clock()
        loop = create_loop(
            code="LOOP-P",
            name="Parkside Loop P",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
        tariff = commercial_rate_schedule(code="RS-P")
        agreement = create_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Parkside Offices",
            reserved_capacity_kw=1000.0,
        )
        return {"loop": loop, "agreement": agreement}

    def test_the_second_activate_call_reports_the_agreement_state(self):
        """Activation declares PENDING_CAPACITY as its only from-state.

        PRD: "It requires that the agreement be in `PENDING_CAPACITY`, that the
        loop's `posture` not be `ISOLATED` — an activation attempted on an isolated
        loop is refused with `ERR_LOOP_ISOLATED` — and that a reservation sweep
        across the loop's whole reservation calendar find no breach."

        Design: Corner/State Machines/second_activate_on_an_already_active_agreement_is_rejected
        """
        stack = self._activated_customer()

        first = validate_success(
            api_client.activate_connection_agreement(
                stack["agreement"]["id"], {}, BILLING_ANALYST
            )
        )
        second = api_client.activate_connection_agreement(
            stack["agreement"]["id"], {}, BILLING_ANALYST
        )

        assert_agreement_state(first, contract_state="ACTIVE")
        validate_error(second, ApiErrorId.AGREEMENT_STATE_INVALID)

    def test_the_refused_repeat_neither_bumps_the_version_nor_double_reserves(self):
        """The loop still carries one thousand kilowatts, not two thousand.

        PRD: "When the sweep clears, the agreement becomes `ACTIVE`, the loop's
        `committed_reserved_kw` is increased by the agreement's
        `reserved_capacity_kw`, and both the loop's and the agreement's `version`
        are incremented by 1."

        Design: Corner/State Machines/second_activate_on_an_already_active_agreement_is_rejected
        """
        stack = self._activated_customer()
        api_client.activate_connection_agreement(
            stack["agreement"]["id"], {}, BILLING_ANALYST
        )
        version_after_first = agreement_version(stack["agreement"]["id"])

        api_client.activate_connection_agreement(
            stack["agreement"]["id"], {}, BILLING_ANALYST
        )

        assert agreement_version(stack["agreement"]["id"]) == version_after_first
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=1000.0)


class TestCommissioningAcrossAnOpenExcavation:
    """The meter's own state is fine; the segment it taps is dug up."""

    def _meter_on_an_excavated_segment(self):
        set_clock("2026-09-01T09:00:00Z")
        loop = create_loop(
            code="LOOP-P",
            name="Parkside Loop P",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
        segment = create_segment(
            loop["id"], code="SEG-P1", install_year=2012, insulation_class="A"
        )
        tariff = commercial_rate_schedule(code="RS-P")
        agreement = active_agreement(
            loop["id"], tariff["id"], customer_name="Parkside Offices"
        )
        point = create_point(agreement["id"], segment["id"], code="MP-P1")
        order = create_work_order(
            segment["id"],
            loop["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T16:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="LEAK_REPAIR",
            requires_isolation=False,
        )
        submit_permit(order["id"], FIELD_TECHNICIAN)
        decide_permit(order["id"], "GRANTED", decision_note="leak repair permitted")
        begin_excavation(order["id"], FIELD_TECHNICIAN)
        return {
            "loop": loop,
            "segment": segment,
            "agreement": agreement,
            "point": point,
            "order": order,
        }

    def test_commissioning_onto_a_dug_up_segment_is_refused(self):
        """The cross-entity precondition on the host segment fails.

        PRD: "It requires the point to be `INSTALLED` and additionally requires that
        the referenced pipe segment's `condition` not be `UNDER_REPAIR` — a meter
        cannot be brought into service on a segment that is currently dug up. A
        commissioning attempt that fails either test is rejected with
        `ERR_METER_STATE_INVALID`."

        Design: Corner/State Machines/metering_point_commission_blocked_while_its_segment_is_under_repair
        """
        stack = self._meter_on_an_excavated_segment()
        assert_segment_condition(
            _read_segment(stack["segment"]["id"]), condition="UNDER_REPAIR"
        )

        response = api_client.commission_metering_point(
            stack["point"]["id"], {}, FIELD_TECHNICIAN
        )

        validate_error(response, ApiErrorId.METER_STATE_INVALID)
        assert _read_point(stack["point"]["id"])["meter_state"] == "INSTALLED"

    def test_closing_the_ground_lets_the_identical_commission_call_through(self):
        """Sign-off rebands the segment out of repair and reopens the meter.

        PRD: "Commissioning advances the point from `INSTALLED` to `COMMISSIONED`
        and is the gate on billable reads."

        Design: Corner/State Machines/metering_point_commission_blocked_while_its_segment_is_under_repair
        """
        stack = self._meter_on_an_excavated_segment()
        api_client.commission_metering_point(stack["point"]["id"], {}, FIELD_TECHNICIAN)
        begin_repair(stack["order"]["id"], FIELD_TECHNICIAN)
        backfill_work_order(stack["order"]["id"], FIELD_TECHNICIAN)

        completed = complete_work_order(
            stack["order"]["id"],
            completion_note="joint replaced",
            completer_headers=FIELD_TECHNICIAN_ALT,
        )

        assert completed["work_state"] == "COMPLETED"
        assert_segment_condition(
            _read_segment(stack["segment"]["id"]),
            condition="SOUND",
            leak_risk_score=16.33,
            historical_leak_count=1,
        )
        commissioned = commission_point(stack["point"]["id"])
        assert commissioned["meter_state"] == "COMMISSIONED"


class TestExpiredContractIsTerminal:
    """An expired supply cannot be revived and its machine stays out of service."""

    def _expired_supply(self):
        set_clock()
        loop = create_loop(
            code="LOOP-P",
            name="Parkside Loop P",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
        contract = create_fuel_contract(supplier_code="FCG-P")
        asset = create_asset(loop["id"], code="P_G1", fuel_contract_id=contract["id"])
        return {"loop": loop, "contract": contract, "asset": asset}

    def test_expiry_pulls_every_asset_on_the_contract_into_outage(self):
        """The expiry cascade ignores whatever availability the asset held.

        PRD: "`ACTIVE → EXPIRED` sets `status` to `EXPIRED` and cascades every
        production asset whose `fuel_contract_id` names this contract to `OUTAGE`,
        regardless of the availability state each asset held."

        Design: Corner/State Machines/fuel_contract_expired_is_terminal_and_locks_out_every_status_change
        """
        stack = self._expired_supply()

        expired = set_fuel_contract_status(
            stack["contract"]["id"], "EXPIRED", reason="term ended"
        )

        assert expired["status"] == "EXPIRED"
        assert read_asset(stack["asset"]["id"])["availability_state"] == "OUTAGE"

    def test_neither_reinstatement_nor_suspension_can_leave_expired(self):
        """Both attempted edges out of the terminal state are refused.

        PRD: "Any requested edge that is not one of these six — or any attempt to
        move a fuel contract out of `EXPIRED`, which is terminal — is rejected with
        `ERR_AVAILABILITY_STATE_INVALID`."

        Design: Corner/State Machines/fuel_contract_expired_is_terminal_and_locks_out_every_status_change
        """
        stack = self._expired_supply()
        set_fuel_contract_status(stack["contract"]["id"], "EXPIRED", reason="term ended")

        back_to_active = api_client.set_fuel_contract_status(
            stack["contract"]["id"], {"status": "ACTIVE"}, SYSTEM_CONTROLLER
        )
        to_suspended = api_client.set_fuel_contract_status(
            stack["contract"]["id"], {"status": "SUSPENDED"}, SYSTEM_CONTROLLER
        )

        validate_error(back_to_active, ApiErrorId.AVAILABILITY_STATE_INVALID)
        validate_error(to_suspended, ApiErrorId.AVAILABILITY_STATE_INVALID)
        contract = get_success_data(
            api_client.get_fuel_supply_contract(stack["contract"]["id"], SYSTEM_CONTROLLER)
        )
        assert contract["status"] == "EXPIRED"
        assert read_asset(stack["asset"]["id"])["availability_state"] == "OUTAGE"


class TestPermitDenialAndCancellation:
    """A denied permit reopens the job; a cancellation closes it for good."""

    def _order_awaiting_a_permit(self):
        set_clock()
        loop = create_loop(
            code="LOOP-P",
            name="Parkside Loop P",
            service_mode="HEATING",
            rated_capacity_kw=5000.0,
        )
        segment = create_segment(loop["id"], code="SEG-P1")
        order = create_work_order(
            segment["id"],
            loop["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T16:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
        )
        submit_permit(order["id"], FIELD_TECHNICIAN)
        return {"loop": loop, "segment": segment, "order": order}

    def test_a_denied_permit_returns_the_order_to_draft(self):
        """The decision is recorded even though the job goes backwards.

        PRD: "`PERMIT_PENDING → DRAFT` stores `permit_decision` as `DENIED` and
        returns `work_state` to `DRAFT`, from which the technician may change the
        window and re-submit; the two branches are otherwise symmetric and each
        increments the order's `version` by 1."

        Design: Corner/State Machines/permit_denial_returns_the_work_order_to_draft_and_cancel_then_locks_it
        """
        stack = self._order_awaiting_a_permit()

        decided = decide_permit(
            stack["order"]["id"], "DENIED", decision_note="street closure refused"
        )

        assert decided["work_state"] == "DRAFT"
        assert decided["permit_decision"] == "DENIED"
        refused_dig = api_client.begin_excavation(
            stack["order"]["id"], {}, FIELD_TECHNICIAN
        )
        validate_error(refused_dig, ApiErrorId.WORK_ORDER_STATE_INVALID)

    def test_cancelling_the_reopened_order_locks_out_a_fresh_permit_request(self):
        """CANCELLED is terminal, so the job cannot be resubmitted.

        PRD: "**Cancellation** is available with an optional `reason` from any state
        where the ground has not yet been opened, and the three edges behave
        identically: `DRAFT → CANCELLED`, `PERMIT_PENDING → CANCELLED` and
        `SCHEDULED → CANCELLED` each set `work_state` to the terminal `CANCELLED`
        and increment the order's `version` by 1, with no segment or loop cascade."

        Design: Corner/State Machines/permit_denial_returns_the_work_order_to_draft_and_cancel_then_locks_it
        """
        stack = self._order_awaiting_a_permit()
        decide_permit(
            stack["order"]["id"], "DENIED", decision_note="street closure refused"
        )

        cancelled = get_success_data(
            api_client.cancel_work_order(
                stack["order"]["id"], {"reason": "work deferred"}, FIELD_TECHNICIAN
            )
        )

        assert cancelled["work_state"] == "CANCELLED"
        again = api_client.submit_work_order_permit(
            stack["order"]["id"], {}, FIELD_TECHNICIAN
        )
        validate_error(again, ApiErrorId.WORK_ORDER_STATE_INVALID)
        assert_segment_condition(
            _read_segment(stack["segment"]["id"]), condition="SOUND"
        )
        assert_loop_state(read_loop(stack["loop"]["id"]), open_isolation_count=0)


class TestInvoiceAndBalanceLedger:
    """Issuing owes money, an exact payment settles it and a cent short does not."""

    PERIOD_START = "2026-06-01T00:00:00Z"
    PERIOD_END = "2026-07-01T00:00:00Z"

    def _billed_customer(self):
        set_clock()
        loop = create_loop(
            code="LOOP-N",
            name="Northbank Loop N",
            service_mode="DUAL",
            rated_capacity_kw=8000.0,
        )
        segment = create_segment(loop["id"], code="SEG-N1")
        tariff = commercial_rate_schedule(code="RS-C")
        agreement = active_agreement(
            loop["id"],
            tariff["id"],
            customer_name="Northbank Offices",
            reserved_capacity_kw=4000.0,
        )
        point = commissioned_point(agreement["id"], segment["id"], code="MP-N1")
        add_reading(point["id"], "2026-06-01T00:00:00Z", 1000.000, 1500.0)
        add_reading(point["id"], "2026-06-30T00:00:00Z", 1432.000, 1500.0)
        return {
            "loop": loop,
            "tariff": tariff,
            "agreement": agreement,
            "point": point,
        }

    def test_the_created_invoice_carries_every_determinant(self):
        """Half the reserved capacity outbids the metered peak as billed demand.

        PRD: "The reserved floor is the agreement's `reserved_capacity_kw`
        multiplied by 0.50 — half the reserved capacity is billable whether the
        customer draws it or not — rounded half-up to two decimal places."

        Design: Corner/State Machines/invoice_issue_and_payment_keep_the_agreement_balance_ledger_in_sync
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
            invoice_state="DRAFT",
        )

    def test_issuing_owes_the_money_raises_the_ratchet_and_trips_arrears(self):
        """A 62816.00 bill is far past the 25000.00 arrears threshold.

        PRD: "it raises the agreement's `billed_demand_ratchet_kw` to this invoice's
        `billed_demand_kw` when the invoice's figure is higher — the ratchet is only
        ever raised, never lowered, and only on this one edge — recomputes the
        agreement's `balance_due`, cascades the billing dimension from `CURRENT` to
        `IN_ARREARS` when the recomputed balance exceeds the arrears threshold".

        Design: Corner/State Machines/invoice_issue_and_payment_keep_the_agreement_balance_ledger_in_sync
        """
        stack = self._billed_customer()
        invoice = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )

        issued = issue_invoice(invoice["id"])

        assert_invoice_determinants(
            issued, invoice_state="ISSUED", total_amount=62816.00
        )
        assert_agreement_state(
            read_agreement(stack["agreement"]["id"]),
            billing_state="IN_ARREARS",
            balance_due=62816.00,
            billed_demand_ratchet_kw=2000.00,
        )

    def test_a_payment_one_cent_short_is_refused(self):
        """There are no partial settlements, so 62815.99 does not clear the bill.

        PRD: "the `amount` must equal the invoice's `total_amount` exactly — a
        partial or excess payment is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`, so
        there are no partial settlements".

        Design: Corner/State Machines/invoice_issue_and_payment_keep_the_agreement_balance_ledger_in_sync
        """
        stack = self._billed_customer()
        invoice = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )
        issue_invoice(invoice["id"])

        response = api_client.pay_invoice(
            invoice["id"],
            payment_payload(62815.99),
            make_customer_account_headers(stack["agreement"]["id"]),
        )

        validate_error(response, ApiErrorId.PAYMENT_AMOUNT_MISMATCH)
        assert read_invoice(invoice["id"])["invoice_state"] == "ISSUED"
        assert_agreement_state(
            read_agreement(stack["agreement"]["id"]),
            billing_state="IN_ARREARS",
            balance_due=62816.00,
        )

    def test_an_exact_payment_settles_the_balance_and_clears_the_arrears(self):
        """A paid invoice leaves the balance sum, so the ledger returns to zero.

        PRD: "`balance_due` is the sum of `total_amount` across every invoice of
        this agreement whose `invoice_state` is `ISSUED` or `ADJUSTED`, rounded
        half-up to two decimal places."

        Design: Corner/State Machines/invoice_issue_and_payment_keep_the_agreement_balance_ledger_in_sync
        """
        stack = self._billed_customer()
        invoice = create_invoice(
            stack["agreement"]["id"], self.PERIOD_START, self.PERIOD_END, "ESTIMATED"
        )
        issue_invoice(invoice["id"])

        paid = get_success_data(
            api_client.pay_invoice(
                invoice["id"],
                payment_payload(62816.00),
                make_customer_account_headers(stack["agreement"]["id"]),
            )
        )

        assert_invoice_determinants(
            paid, invoice_state="PAID", paid_amount=62816.00
        )
        assert_agreement_state(
            read_agreement(stack["agreement"]["id"]),
            billing_state="CURRENT",
            balance_due=0.00,
        )


class TestPostureRecoveryEdges:
    """CONSTRAINED lifts only on approval; ISOLATED picks its exit on the counters."""

    def _constrained_campus(self):
        stack = campus_dispatch_stack(plan_state="APPROVED")
        set_fuel_contract_status(
            stack["gas_contract"]["id"], "SUSPENDED", reason="supplier force majeure"
        )
        return stack

    def test_reinstating_the_supply_restores_the_asset_but_not_the_posture(self):
        """Reinstatement is deliberately not a posture recovery.

        PRD: "Reinstatement deliberately does **not** un-revert the dispatch plans
        that suspension pushed back to `DRAFT`, and does not itself restore a loop
        to `NORMAL`; that only happens when a fresh plan is approved."

        Design: Corner/State Machines/plan_approval_lifts_a_constrained_loop_back_to_normal
        """
        stack = self._constrained_campus()

        set_fuel_contract_status(
            stack["gas_contract"]["id"], "ACTIVE", reason="supply restored"
        )

        assert read_asset(stack["chp"]["id"])["availability_state"] == "AVAILABLE"
        assert_loop_state(read_loop(stack["loop"]["id"]), posture="CONSTRAINED")
        assert_plan_metrics(read_plan(stack["plan"]["id"]), plan_state="DRAFT")

    def test_re_approving_the_re_optimised_plan_lifts_the_loop_to_normal(self):
        """The CONSTRAINED to NORMAL edge fires only as an approval cascade.

        PRD: "When both gates pass the plan becomes `APPROVED`, and if the loop is
        sitting in `CONSTRAINED` with an `open_isolation_count` of 0 the loop is
        restored to `NORMAL` with its `version` incremented by 1."

        Design: Corner/State Machines/plan_approval_lifts_a_constrained_loop_back_to_normal
        """
        stack = self._constrained_campus()
        set_fuel_contract_status(
            stack["gas_contract"]["id"], "ACTIVE", reason="supply restored"
        )

        optimize_plan(stack["plan"]["id"])
        submit_plan(stack["plan"]["id"], "resubmitted after supply restored")
        approved = review_plan(stack["plan"]["id"], "APPROVE", "supply confirmed")

        assert_plan_metrics(
            approved,
            plan_state="APPROVED",
            allocated_capacity_kw=2527.20,
            total_dispatch_cost=1584.36,
            reserve_margin_pct=46.41,
            fuel_diversity_hhi=0.5489,
        )
        assert_loop_state(
            read_loop(stack["loop"]["id"]), posture="NORMAL", open_isolation_count=0
        )

    def _isolated_loop_with_a_second_suspect_segment(self):
        set_clock("2026-09-01T09:00:00Z")
        loop = create_loop(
            code="LOOP-Q",
            name="Quayside Loop Q",
            service_mode="HEATING",
            rated_capacity_kw=6000.0,
        )
        healthy = create_segment(
            loop["id"], code="SEG-Q1", install_year=2012, insulation_class="A"
        )
        ailing = create_segment(
            loop["id"], code="SEG-Q2", install_year=1976, insulation_class="C"
        )
        assessed = assess_segment(ailing["id"], 0.05, 3, "C")
        order = create_work_order(
            healthy["id"],
            loop["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T16:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="INSPECTION",
            requires_isolation=True,
        )
        submit_permit(order["id"], FIELD_TECHNICIAN)
        decide_permit(order["id"], "GRANTED", decision_note="inspection permitted")
        begin_excavation(order["id"], FIELD_TECHNICIAN)
        begin_repair(order["id"], FIELD_TECHNICIAN)
        backfill_work_order(order["id"], FIELD_TECHNICIAN)
        return {
            "loop": loop,
            "healthy": healthy,
            "ailing": ailing,
            "assessed": assessed,
            "order": order,
        }

    def test_the_untouched_segment_holds_the_loop_in_the_suspect_population(self):
        """A fifty-year-old class C run with three leaks scores 91.92.

        PRD: "`SOUND → SUSPECT` and `MONITORED → SUSPECT` each increment the loop's
        `suspect_segment_count` by 1 and increment the loop's `version` by 1."

        Design: Corner/State Machines/loop_falls_back_to_constrained_when_another_segment_is_still_suspect
        """
        stack = self._isolated_loop_with_a_second_suspect_segment()

        assert_segment_condition(
            stack["assessed"], condition="SUSPECT", leak_risk_score=91.92
        )
        assert_loop_state(
            read_loop(stack["loop"]["id"]),
            posture="ISOLATED",
            open_isolation_count=1,
            suspect_segment_count=1,
        )

    def test_sign_off_lands_on_constrained_rather_than_normal(self):
        """The ground is closed but the loop still owns a suspect segment.

        PRD: "`ISOLATED → CONSTRAINED` fires under the same completion trigger when,
        after the cascade, `open_isolation_count` is 0 but `suspect_segment_count` is
        greater than 0 — the ground is closed but the loop still owns at least one
        suspect segment."

        Design: Corner/State Machines/loop_falls_back_to_constrained_when_another_segment_is_still_suspect
        """
        stack = self._isolated_loop_with_a_second_suspect_segment()

        completed = complete_work_order(
            stack["order"]["id"],
            completion_note="inspection closed",
            completer_headers=FIELD_TECHNICIAN_ALT,
        )

        assert completed["work_state"] == "COMPLETED"
        assert_segment_condition(
            _read_segment(stack["healthy"]["id"]),
            condition="SOUND",
            leak_risk_score=9.67,
            historical_leak_count=0,
        )
        assert_loop_state(
            read_loop(stack["loop"]["id"]),
            posture="CONSTRAINED",
            open_isolation_count=0,
            suspect_segment_count=1,
        )
