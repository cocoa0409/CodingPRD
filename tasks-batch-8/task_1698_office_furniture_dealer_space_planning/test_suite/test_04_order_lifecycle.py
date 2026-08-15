"""Order lifecycle: submit gauntlet, revise, acknowledge, cancel, close."""
from test_helpers import (
    ApiErrorId,
    assert_order_totals_invariants,
    fixtures as fx,
    validate_error,
    validate_success,
    AE,
    APPROVER,
    CO,
    DESIGNER,
    FINANCE,
    PM,
    REP,
)


class TestSubmitContractGate:
    def test_order_submit_requires_contract_active_draft(self, api):
        """PRD section 3.4: "the contract must be `ACTIVE` with the current UTC
        date inside its inclusive effectiveness window, else
        `ERR_CONTRACT_NOT_EFFECTIVE`" — a contract still in `DRAFT` fails the
        gate.

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_contract_active
        """
        ctx = fx.setup_draft_order(activate=False)
        resp = api.submit_order(ctx.order["id"], AE)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EFFECTIVE)

    def test_order_submit_requires_contract_active_terminated(self, api):
        """PRD section 3.4: "the contract must be `ACTIVE` with the current UTC
        date inside its inclusive effectiveness window, else
        `ERR_CONTRACT_NOT_EFFECTIVE`" — a `TERMINATED` contract is not
        `ACTIVE`.
        PRD section 3.3: "A `ContractsOfficer` may also terminate a contract
        from either `DRAFT` or `ACTIVE`, moving it to the terminal `TERMINATED`
        state."

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_contract_active
        """
        ctx = fx.setup_draft_order()
        validate_success(api.terminate_contract(ctx.contract["id"], CO))
        resp = api.submit_order(ctx.order["id"], AE)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EFFECTIVE)


class TestSubmitPlanGate:
    def test_submit_with_draft_plan_rejected(self, api):
        """PRD section 3.4: "the plan must be `APPROVED` with its
        `approved_version` equal to its current `version` — a plan that is not
        approved yields `ERR_PLAN_NOT_APPROVED`".

        Design: Corner/validations/submit_with_draft_plan_rejected
        """
        ctx = fx.setup_draft_order(approve_plan=False)
        resp = api.submit_order(ctx.order["id"], AE)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED)

    def test_temporal_beats_referential_on_submit(self, api):
        """PRD section 2.8: "(6) contract effectiveness, including
        pinned-contract-version freshness at acknowledgment; (7)
        referenced-object freshness and linkage" — the temporal contract check
        (6) is evaluated before the plan-freshness check (7), so an order whose
        contract has expired AND whose plan was superseded surfaces
        `ERR_CONTRACT_NOT_EFFECTIVE`, not `ERR_PLAN_SUPERSEDED`.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_submit
        """
        ctx = fx.setup_draft_order(
            contract_overrides={"effective_from": "2026-08-01",
                                "effective_to": "2026-08-10"},
        )
        # A successor plan approved against plan A pushes A to SUPERSEDED.
        _plan_b, _t = fx.create_approved_plan(
            ctx.customer["id"],
            {"name": "HQ Floor 3 v2", "supersedes_plan_id": ctx.plan["id"]},
            {"code": "WS-A"},
        )
        fx.set_clock("2026-08-12T00:00:00Z")  # sweeps the contract to EXPIRED
        resp = api.submit_order(ctx.order["id"], AE)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EFFECTIVE)

    def test_temporal_pair_isolated_plan_superseded(self, api):
        """PRD section 3.4: "the plan must be `APPROVED` with its
        `approved_version` equal to its current `version` — a plan that is not
        approved yields `ERR_PLAN_NOT_APPROVED`, while a stale approval anchor
        (for example because the plan was revised after approval, or
        superseded) yields `ERR_PLAN_SUPERSEDED`". With the contract healthy,
        the superseded plan's stale anchor surfaces alone.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_submit
        """
        ctx = fx.setup_draft_order()
        _plan_b, _t = fx.create_approved_plan(
            ctx.customer["id"],
            {"name": "HQ Floor 3 v2", "supersedes_plan_id": ctx.plan["id"]},
            {"code": "WS-A"},
        )
        resp = api.submit_order(ctx.order["id"], AE)
        validate_error(resp, ApiErrorId.ERR_PLAN_SUPERSEDED)


class TestContractEffectiveWindow:
    def test_contract_window_inclusive_boundaries(self, api):
        """PRD section 3.4: "the contract must be `ACTIVE` with the current UTC
        date inside its inclusive effectiveness window, else
        `ERR_CONTRACT_NOT_EFFECTIVE`" — both window bounds are inclusive.
        PRD section 2.7: "Before any call to set it, the logical clock reads
        exactly `2026-08-01T00:00:00Z`".

        Design: Corner/validations/contract_window_inclusive_boundaries
        """
        ctx = fx.setup_catalog(
            contract_overrides={"effective_from": "2026-09-01",
                                "effective_to": "2026-09-30"},
        )
        orders = []
        for _ in range(3):
            order = fx.create_order(
                ctx.customer["id"], ctx.contract["id"], ctx.plan["id"]
            )
            fx.add_line(order["id"], ctx.series["id"], {"quantity": 1})
            orders.append(order)
        # Default clock 2026-08-01 is before effective_from.
        resp = api.submit_order(orders[0]["id"], AE)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EFFECTIVE)
        fx.set_clock("2026-09-01T00:00:00Z")
        ok1 = validate_success(api.submit_order(orders[0]["id"], AE))
        assert ok1["status"] == "SUBMITTED"
        fx.set_clock("2026-09-30T00:00:00Z")
        ok2 = validate_success(api.submit_order(orders[1]["id"], AE))
        assert ok2["status"] == "SUBMITTED"
        fx.set_clock("2026-10-01T00:00:00Z")  # past effective_to; swept EXPIRED
        resp = api.submit_order(orders[2]["id"], AE)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EFFECTIVE)


class TestCustomerStandingGate:
    def test_customer_on_hold_blocks_order_create(self, api):
        """PRD section 3.2: "A customer that is not `ACTIVE` cannot have new
        orders created for it nor orders submitted — both reject with
        `ERR_CUSTOMER_NOT_ACTIVE`."

        Design: Corner/validations/customer_on_hold_blocks_order_create
        """
        ctx = fx.setup_catalog()
        validate_success(api.hold_customer(ctx.customer["id"], AE))
        resp = api.create_project_order(
            {
                "customer_id": ctx.customer["id"],
                "contract_id": ctx.contract["id"],
                "space_plan_id": ctx.plan["id"],
            },
            AE,
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)
        validate_success(api.release_customer_hold(ctx.customer["id"], AE))
        ok = api.create_project_order(
            {
                "customer_id": ctx.customer["id"],
                "contract_id": ctx.contract["id"],
                "space_plan_id": ctx.plan["id"],
            },
            AE,
        )
        assert validate_success(ok, 201)["id"]


class TestReviseAndCancel:
    def test_order_revise_clears_pins_and_reopens_lines(self, api):
        """PRD section 3.4: "revising it returns the order from `SUBMITTED` to
        `DRAFT`: both pinned versions are cleared and every `PLACED` line
        returns to `OPEN`". Submit had captured the pins: "On a successful
        submit the order captures `pinned_contract_version` from the contract's
        current `version` and `pinned_plan_version` from the plan's
        `approved_version`".

        Design: Corner/state_machines/order_revise_clears_pins_and_reopens_lines
        """
        ctx = fx.setup_draft_order()
        assert ctx.line["status"] == "OPEN"
        submitted = validate_success(api.submit_order(ctx.order["id"], AE))
        assert submitted["pinned_contract_version"] is not None
        assert submitted["pinned_plan_version"] is not None
        line_mid = validate_success(api.get_order_line(ctx.line["id"], AE))
        assert line_mid["status"] == "PLACED"
        revised = validate_success(api.revise_order(ctx.order["id"], AE))
        assert revised["status"] == "DRAFT"
        assert revised.get("pinned_contract_version") is None
        assert revised.get("pinned_plan_version") is None
        line_after = validate_success(api.get_order_line(ctx.line["id"], AE))
        assert line_after["status"] == "OPEN"

    def test_restocking_fee_on_acknowledged_cancel(self, api):
        """PRD section 3.6: "From `ACKNOWLEDGED` a restocking fee applies: the
        unreceived net is the sum of `line_total_cents` over lines that are
        `ACKNOWLEDGED` with `received_units` of zero; the `cancel_fee_cents` is
        the greater of a minimum fee of two hundred fifty dollars (25,000
        cents) and twenty percent of that unreceived net, the latter rounded
        half-up to whole cents." and "Cancellation from `ACKNOWLEDGED` also
        moves each `ACKNOWLEDGED` line to `CANCELLED` and each `RESERVED`
        staging reservation for those lines to `CANCELLED`."

        Design: Corner/calculations/restocking_fee_on_acknowledged_cancel
        """
        ctx = fx.setup_acknowledged_order(
            contract_overrides={
                "pricing_tiers": [
                    {"category": "SEATING", "min_qty": 1, "discount_pct": 40},
                    {"category": "SEATING", "min_qty": 25, "discount_pct": 45},
                ]
            },
            series_overrides={
                "option_catalog": [
                    {"option_code": "ARMS", "price_uplift_pct": 10,
                     "extra_lead_days": 5}
                ]
            },
            line_overrides={"quantity": 25, "selected_options": ["ARMS"]},
        )
        # unit net 60500 x 25 = 1512500 unreceived net; 20% = 302500 > 25000
        fx.add_staging_reservation(ctx, {"units": 5})
        cancelled = validate_success(api.cancel_order(ctx.order["id"], AE))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_fee_cents"] == 302_500
        reservation = validate_success(
            api.get_staging_reservation(ctx.reservation["id"], PM)
        )
        assert reservation["status"] == "CANCELLED"


class TestParallelDimensions:
    def test_order_parallel_dimensions_delivery_leaves_posture(self, api):
        """PRD section 3.5: "When every non-`CANCELLED` line of an acknowledged
        order has reached `RECEIVED`, the order itself transitions from
        `ACKNOWLEDGED` to `DELIVERED` without any explicit request."
        PRD section 3.6: "Otherwise, when any event is `IN_PROGRESS`, the
        posture is `IN_PROGRESS`; when any event is `CONFIRMED`, it is
        `SCHEDULED`" — receipt moves the commercial status while the confirmed
        event keeps the posture at `SCHEDULED`.

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions
        """
        ctx = fx.setup_acknowledged_order(line_overrides={"quantity": 5})
        fx.add_confirmed_event(ctx)
        mid = validate_success(api.get_project_order(ctx.order["id"], PM))
        assert mid["status"] == "ACKNOWLEDGED"
        assert mid["install_posture"] == "SCHEDULED"
        fx.add_staging_reservation(ctx, {"units": 5})
        fx.receive_units(ctx, received_units=5)
        after = validate_success(api.get_project_order(ctx.order["id"], PM))
        assert after["status"] == "DELIVERED"
        assert after["install_posture"] == "SCHEDULED"

    def test_order_parallel_dimensions_completion_advances_installed(self, api):
        """PRD section 3.6: "Otherwise, when the order has at least one
        non-`CANCELLED` install event and every such event is `COMPLETED`, the
        posture is `COMPLETE`." and "completion recomputes the order's
        `install_posture`, and if the posture becomes `COMPLETE` while the
        order is `DELIVERED`, the order automatically advances to `INSTALLED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions
        """
        ctx = fx.setup_installed_order(line_overrides={"quantity": 5})
        assert ctx.order["status"] == "INSTALLED"
        assert ctx.order["install_posture"] == "COMPLETE"


class TestOrderClose:
    def test_order_close_happy_path(self, api):
        """PRD section 3.6: "Closing the order is a `ProjectManager` action
        available from either `DELIVERED` or `INSTALLED`, gated by two checks
        in order: the `install_posture` must be `COMPLETE`, else
        `ERR_INSTALL_NOT_COMPLETE`; and every punch item of the order must be
        `CLOSED`, else `ERR_ORDER_HAS_OPEN_PUNCH`. A successful close moves
        each `RECEIVED` line to `CLOSED` and the order to its terminal `CLOSED`
        state."

        Design: Corner/state_machines/order_close_happy_path
        """
        ctx = fx.setup_installed_order(line_overrides={"quantity": 5})
        closed = validate_success(api.close_order(ctx.order["id"], PM))
        assert closed["status"] == "CLOSED"
        line = validate_success(api.get_order_line(ctx.line["id"], PM))
        assert line["status"] == "CLOSED"

    def test_order_close_blocked_by_open_punch(self, api):
        """PRD section 3.6: "every punch item of the order must be `CLOSED`,
        else `ERR_ORDER_HAS_OPEN_PUNCH`".

        Design: Corner/validations/order_close_blocked_by_open_punch
        """
        ctx = fx.setup_installed_order(line_overrides={"quantity": 5})
        fx.add_punch(
            ctx,
            {"order_line_id": ctx.line["id"], "severity": "STANDARD",
             "description": "Scuff on panel", "affected_units": 1},
        )
        resp = api.close_order(ctx.order["id"], PM)
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_OPEN_PUNCH)

    def test_order_close_requires_install_complete(self, api):
        """PRD section 3.6: "Closing the order is a `ProjectManager` action
        available from either `DELIVERED` or `INSTALLED`, gated by two checks
        in order: the `install_posture` must be `COMPLETE`, else
        `ERR_INSTALL_NOT_COMPLETE`" — a `DELIVERED` order with no install
        events has posture `NOT_SCHEDULED` and cannot close.

        Design: Corner/validations/order_close_requires_install_complete
        """
        ctx = fx.setup_delivered_order(line_overrides={"quantity": 5})
        assert ctx.order["status"] == "DELIVERED"
        assert ctx.order["install_posture"] == "NOT_SCHEDULED"
        resp = api.close_order(ctx.order["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INSTALL_NOT_COMPLETE)


class TestLeadTimeDualVariant:
    OPTIONED_SERIES = {
        "option_catalog": [
            {"option_code": "ARMS", "price_uplift_pct": 10, "extra_lead_days": 5},
            {"option_code": "FABRIC3", "price_uplift_pct": 5, "extra_lead_days": 10},
        ]
    }

    def test_orderline_provisional_vs_confirmed_promise_provisional(self, api):
        """PRD section 3.4: "For a `STEELCASE` series, the
        `provisional_lead_time_days` is the series' `base_lead_time_days` plus
        the sum of the `extra_lead_days` of the selected options." and "The
        `provisional_promise_date` is the submit date plus the
        `provisional_lead_time_days` counted in calendar days." — 30 + 5 + 10
        = 45 days from submit on 2026-08-03 gives 2026-09-17.

        Design: Difficulty/dual_variant_calc/orderline_provisional_vs_confirmed_promise
        """
        ctx = fx.setup_draft_order(
            series_overrides=self.OPTIONED_SERIES,
            line_overrides={"quantity": 1, "selected_options": ["ARMS", "FABRIC3"]},
        )
        fx.set_clock("2026-08-03T00:00:00Z")
        validate_success(api.submit_order(ctx.order["id"], AE))
        line = validate_success(api.get_order_line(ctx.line["id"], AE))
        assert line["provisional_lead_time_days"] == 45
        assert line["provisional_promise_date"] == "2026-09-17"

    def test_orderline_provisional_vs_confirmed_promise_confirmed(self, api):
        """PRD section 3.4: "its `confirmed_lead_time_days` is set to the same
        day-count as the provisional computation — base plus the
        manufacturer-mode option days — but the `confirmed_promise_date`
        re-anchors to the acknowledgment date and advances in business days:
        only Monday through Friday count, the count starts the day after the
        acknowledgment date, and holidays are not modeled. Identical
        configuration data therefore yields a different promise date in the
        confirmed variant than in the provisional variant." — 45 business days
        from acknowledgment on 2026-08-05 gives 2026-10-07.

        Design: Difficulty/dual_variant_calc/orderline_provisional_vs_confirmed_promise
        """
        ctx = fx.setup_draft_order(
            series_overrides=self.OPTIONED_SERIES,
            line_overrides={"quantity": 1, "selected_options": ["ARMS", "FABRIC3"]},
        )
        fx.set_clock("2026-08-03T00:00:00Z")
        validate_success(api.submit_order(ctx.order["id"], AE))
        fx.set_clock("2026-08-05T00:00:00Z")
        validate_success(api.acknowledge_order(ctx.order["id"], REP))
        line = validate_success(api.get_order_line(ctx.line["id"], AE))
        assert line["confirmed_lead_time_days"] == 45
        assert line["confirmed_promise_date"] == "2026-10-07"
        assert line["confirmed_promise_date"] != line["provisional_promise_date"]

    def test_leadtime_millerknoll_bottleneck_mode(self, api):
        """PRD section 3.4: "For a `MILLERKNOLL` series, it is the base plus
        the maximum of the selected options' `extra_lead_days`, defaulting to
        zero when no options are selected." — 28 + max(7, 14) = 42 days from
        submit on 2026-08-03 gives 2026-09-14 (additive Steelcase semantics
        would give 49).

        Design: Corner/calculations/leadtime_millerknoll_bottleneck_mode
        """
        ctx = fx.setup_draft_order(
            contract_overrides={
                "pricing_tiers": [
                    {"category": "CASEGOODS", "min_qty": 1, "discount_pct": 40}
                ]
            },
            series_overrides={
                "manufacturer": "MILLERKNOLL",
                "category": "CASEGOODS",
                "series_code": "MK-CG",
                "base_list_price_cents": 80_000,
                "base_lead_time_days": 28,
                "option_catalog": [
                    {"option_code": "X", "price_uplift_pct": 5, "extra_lead_days": 7},
                    {"option_code": "Y", "price_uplift_pct": 5, "extra_lead_days": 14},
                ],
            },
            line_overrides={"quantity": 1, "selected_options": ["X", "Y"]},
        )
        fx.set_clock("2026-08-03T00:00:00Z")
        validate_success(api.submit_order(ctx.order["id"], AE))
        line = validate_success(api.get_order_line(ctx.line["id"], AE))
        assert line["provisional_lead_time_days"] == 42
        assert line["provisional_promise_date"] == "2026-09-14"
