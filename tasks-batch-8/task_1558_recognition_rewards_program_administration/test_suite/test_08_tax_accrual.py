"""Tax treatment (de-minimis, gross-up variants) and the monthly accrual /
chargeback / tax-year finalization cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_accrual_year,
    create_accrual_run_payload,
    create_and_activate_program,
    create_budget,
    create_catalog_item,
    create_department,
    create_employee,
    create_reconcile_close_run,
    create_vendor,
    deliver_redemption_order,
    get_success_data,
    make_employee_headers,
    setup_program_with_budget,
    submit_and_approve_nomination,
    validate_error,
    validate_success,
)

FIN = TEST_USERS["finance_admin_headers"]
VOPS = TEST_USERS["vendor_ops_headers"]


def _deliver_tax_record(api, ctx, employee, item, idempotency_key,
                        hr_admin_headers):
    """Deliver one unit of the item and return the delivery's TaxRecord."""
    order = deliver_redemption_order(item["id"], employee,
                                     idempotency_key=idempotency_key)
    assert order["tax_record_id"]
    return validate_success(api.get_tax_record(order["tax_record_id"], hr_admin_headers), 200)


class TestDeMinimisExclusion:
    def test_cap_is_all_or_nothing_across_deliveries(self, api, hr_admin_headers):
        """PRD §3.6: "When the item is `de_minimis_eligible`, is not a
        `GIFT_CARD`, and the employee's `ytd_de_minimis_cents` plus the order
        value — the item's `cash_value_cents` multiplied by `quantity` — stays
        at or below the annual cap of 10000 cents (one hundred dollars), the
        award is excluded: `taxable_value_cents` records 0,
        `de_minimis_applied` records true, and the employee's
        `ytd_de_minimis_cents` grows by the order value. Reaching exactly the
        cap still excludes. Otherwise — ineligible item, gift card, or one
        cent over the cap — the order is fully taxable with no partial
        exclusion: `taxable_value_cents` is the whole order value."

        Design: Corner/calculations/de_minimis_cap_all_or_nothing
        """
        ctx = setup_program_with_budget(
            program_overrides={"grossup_enabled": True}, allocated_points=100000,
        )
        employee = ctx["employee"]
        vendor = create_vendor()
        item = create_catalog_item(
            vendor["id"], sku="PLQ", name="Plaque", point_cost=2000,
            cash_value_cents=6000, taxable_class="MERCHANDISE",
            de_minimis_eligible=True,
        )
        submit_and_approve_nomination(
            ctx["program"]["id"], employee["id"], ctx["manager"], 4000,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="calc-dm-1",
        )
        first = _deliver_tax_record(api, ctx, employee, item, "calc-dm-r1", hr_admin_headers)
        second = _deliver_tax_record(api, ctx, employee, item, "calc-dm-r2", hr_admin_headers)

        # 6000 <= 10000: fully excluded; 6000 + 6000 > 10000: fully taxable.
        assert first["taxable_value_cents"] == 0
        assert first["de_minimis_applied"] is True
        assert first["estimated_gross_up_cents"] == 0
        assert second["taxable_value_cents"] == 6000
        assert second["de_minimis_applied"] is False
        # 6000 x (0.22 + 0.093 + 0.0765) / (1 - 0.3895) = 3828.01 -> 3828.
        assert second["estimated_gross_up_cents"] == 3828

        refreshed = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert refreshed["ytd_de_minimis_cents"] == 6000

    def test_gift_card_never_de_minimis_eligible(self, api, hr_admin_headers):
        """PRD §3.5: "a `taxable_class` of `MERCHANDISE`, `GIFT_CARD`, or
        `EXPERIENCE` — gift cards are never de-minimis eligible".
        PRD §3.6: "Otherwise — ineligible item, gift card, or one cent over
        the cap — the order is fully taxable with no partial exclusion".

        Design: Corner/calculations/gift_card_never_de_minimis
        """
        ctx = setup_program_with_budget(
            program_overrides={"grossup_enabled": True,
                               "state_rate_map": {"TX": 0.0}},
            allocated_points=100000, employee_defaults={"state_code": "TX"},
        )
        employee = ctx["employee"]
        vendor = create_vendor(supported_categories=["GIFTCARD"])
        item = create_catalog_item(
            vendor["id"], sku="GC25", name="Gift Card 25", category="GIFTCARD",
            point_cost=500, cash_value_cents=2500, taxable_class="GIFT_CARD",
            de_minimis_eligible=True,
        )
        submit_and_approve_nomination(
            ctx["program"]["id"], employee["id"], ctx["manager"], 1000,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="calc-gc-1",
        )
        record = _deliver_tax_record(api, ctx, employee, item, "calc-gc-r1", hr_admin_headers)
        assert record["taxable_value_cents"] == 2500
        assert record["de_minimis_applied"] is False
        # 2500 x (0.22 + 0.0 + 0.0765) / (1 - 0.2965) = 1053.66 -> 1054.
        assert record["estimated_gross_up_cents"] == 1054


class TestGrossUpClosedForm:
    def _two_state_scenario(self, api, hr_admin_headers):
        """CA + TX employees each granted 8000 and each delivered a
        25000-cent item under a grossup-enabled program."""
        ctx = setup_program_with_budget(
            program_overrides={"grossup_enabled": True,
                               "state_rate_map": {"CA": 0.093, "TX": 0.0}},
            allocated_points=100000,
        )
        program_id = ctx["program"]["id"]
        dept, manager = ctx["dept"], ctx["manager"]
        emp_ca = ctx["employee"]
        emp_tx = create_employee(dept["id"], employee_ref="EMPTX", full_name="Emp TX",
                                 manager_id=manager["id"], hire_date="2022-01-10",
                                 state_code="TX")
        submit_and_approve_nomination(program_id, emp_ca["id"], manager, 8000,
                                      type="MANAGER", reason_code="DELIVERY",
                                      idempotency_key="cf1-n1")
        submit_and_approve_nomination(program_id, emp_tx["id"], manager, 8000,
                                      type="MANAGER", reason_code="DELIVERY",
                                      idempotency_key="cf1-n2")
        vendor = create_vendor()
        item = create_catalog_item(
            vendor["id"], sku="WATCH1", name="Watch", point_cost=8000,
            cash_value_cents=25000, taxable_class="MERCHANDISE",
            de_minimis_eligible=False,
        )
        return ctx, emp_ca, emp_tx, item

    def test_gross_up_uses_closed_form_not_naive_multiplication(
        self, api, hr_admin_headers
    ):
        """PRD §3.6: "The gross-up is the `taxable_value_cents` multiplied by
        the combined rate and divided by one minus the combined rate, rounded
        half-up to integer cents in a single rounding applied to the whole
        expression — no intermediate rounding of the rate."
        PRD §3.6: "The delivery-period chargeback basis is
        `employer_cost_cents`, the sum of `taxable_value_cents` and
        `estimated_gross_up_cents`."

        Design: Difficulty/combinatorial_formula/gross_up_tax_on_tax_closed_form
        """
        ctx, emp_ca, _, item = self._two_state_scenario(api, hr_admin_headers)
        record = _deliver_tax_record(api, ctx, emp_ca, item, "cf1-r1", hr_admin_headers)
        assert record["taxable_value_cents"] == 25000
        # Closed form: 25000 x 0.3895 / (1 - 0.3895) = 15950.04 -> 15950.
        assert record["estimated_gross_up_cents"] == 15950
        # A naive single-pass multiplication would give 9738 — a different
        # number, proving the recursion was resolved in closed form.
        assert record["estimated_gross_up_cents"] != 9738
        assert record["employer_cost_cents"] == 40950

    def test_missing_state_key_defaults_rate_to_zero(self, api, hr_admin_headers):
        """PRD §3.6: "The federal rate is 0.37 when the employee's
        `ytd_supplemental_wages_cents` exceeds 100000000 cents (one million
        dollars) and 0.22 otherwise; the state rate is the program's
        `state_rate_map` lookup for the employee's `state_code`, defaulting to
        0.0 when the key is missing; the combined rate adds those two plus the
        FICA rate of 0.0765."

        Design: Difficulty/combinatorial_formula/gross_up_tax_on_tax_closed_form
        """
        ctx, _, emp_tx, item = self._two_state_scenario(api, hr_admin_headers)
        record = _deliver_tax_record(api, ctx, emp_tx, item, "cf1b-r1", hr_admin_headers)
        assert record["federal_rate_applied"] == 0.22
        assert record["state_rate_applied"] == 0.0
        # 25000 x 0.2965 / (1 - 0.2965) = 10536.89 -> 10537.
        assert record["estimated_gross_up_cents"] == 10537


class TestGrossUpVariantDivergence:
    def _divergence_scenario(self, api, hr_admin_headers, payroll_headers):
        """Deliver a 25000-cent order with ytd wages 90M, then adjust to 120M
        and close all twelve 2026 accrual runs. Returns (ctx, tax_record_id)."""
        ctx = setup_program_with_budget(
            program_overrides={"grossup_enabled": True,
                               "state_rate_map": {"CA": 0.093, "TX": 0.0},
                               "accrual_method": "STRAIGHT_LINE"},
            allocated_points=1000000,
        )
        program_id = ctx["program"]["id"]
        employee = ctx["employee"]
        get_success_data(api.create_compensation_adjustment(
            employee["id"], 90000000, payroll_headers
        ))
        submit_and_approve_nomination(program_id, employee["id"], ctx["manager"], 8000,
                                      type="MANAGER", reason_code="DELIVERY",
                                      idempotency_key="dv1-n1")
        vendor = create_vendor()
        item = create_catalog_item(
            vendor["id"], sku="WATCH1", name="Watch", point_cost=8000,
            cash_value_cents=25000, taxable_class="MERCHANDISE",
        )
        delivered = deliver_redemption_order(item["id"], employee,
                                             idempotency_key="dv1-r1")
        # Intervening compensation adjustment crosses the 1M-dollar tier.
        get_success_data(api.create_compensation_adjustment(
            employee["id"], 120000000, payroll_headers
        ))
        close_accrual_year(program_id, 2026)
        return ctx, delivered["tax_record_id"]

    def test_finalize_response_summarizes_the_divergence(
        self, api, hr_admin_headers, payroll_specialist_headers
    ):
        """PRD §3.6: "On success, every `ESTIMATED` record of that `tax_year`
        moves to `FINALIZED` with its final gross-up recomputed, and the
        response summarizes the run with `finalized_count`, the affected
        `records`, and `total_delta_cents`."
        PRD §3.6: "The final variant reruns at tax-year finalization using the
        employee's final `ytd_supplemental_wages_cents` after all compensation
        adjustments, storing `final_gross_up_cents`".

        Design: Difficulty/dual_variant_calc/gross_up_provisional_vs_final_divergence
        """
        ctx, tax_record_id = self._divergence_scenario(
            api, hr_admin_headers, payroll_specialist_headers
        )
        result = validate_success(api.finalize_tax_year(
            ctx["program"]["id"], 2026, payroll_specialist_headers
        ), 200)
        assert result["finalized_count"] == 1
        assert result["total_delta_cents"] == 13339

        record = validate_success(api.get_tax_record(tax_record_id, hr_admin_headers), 200)
        assert record["status"] == "FINALIZED"
        assert record["estimated_gross_up_cents"] == 15950
        assert record["final_gross_up_cents"] == 29289
        assert record["delta_cents"] == 13339

    def test_provisional_and_final_read_different_wage_snapshots(
        self, api, hr_admin_headers, payroll_specialist_headers
    ):
        """PRD §3.6: "The provisional variant runs at delivery, uses the
        employee's `ytd_supplemental_wages_cents` as recorded at that moment,
        and stores its result in `estimated_gross_up_cents`". "identical
        inputs would produce identical outputs, but intervening compensation
        adjustments make the results diverge, and `delta_cents` records
        `final_gross_up_cents` minus `estimated_gross_up_cents`."

        Design: Difficulty/dual_variant_calc/gross_up_provisional_vs_final_divergence
        """
        ctx, tax_record_id = self._divergence_scenario(
            api, hr_admin_headers, payroll_specialist_headers
        )
        # Before finalization: provisional at the 0.22 tier; finals empty.
        before = validate_success(api.get_tax_record(tax_record_id, hr_admin_headers), 200)
        assert before["status"] == "ESTIMATED"
        assert before["estimated_gross_up_cents"] == 15950
        assert before["federal_rate_applied"] == 0.22
        assert before["final_gross_up_cents"] is None
        assert before["delta_cents"] is None

        validate_success(api.finalize_tax_year(
            ctx["program"]["id"], 2026, payroll_specialist_headers
        ), 200)
        after = validate_success(api.get_tax_record(tax_record_id, hr_admin_headers), 200)
        # Final variant at the 0.37 tier: 25000 x 0.5395 / (1 - 0.5395).
        assert after["final_gross_up_cents"] == 29289
        assert after["delta_cents"] == after["final_gross_up_cents"] - after["estimated_gross_up_cents"]


class TestAccrualVariants:
    def _two_program_scenario(self, api, finance_admin_headers):
        """Two ACTIVE programs (STRAIGHT_LINE vs UTILIZATION_WEIGHTED) sharing
        one department, each with a 120000-point budget at 0.5 cents/point."""
        prog_sl = create_and_activate_program(name="ProgSL", accrual_method="STRAIGHT_LINE")
        prog_uw = create_and_activate_program(name="ProgUW", accrual_method="UTILIZATION_WEIGHTED")
        dept = create_department()
        create_employee(dept["id"], employee_ref="E-ACC")
        for prog in (prog_sl, prog_uw):
            create_budget(prog["id"], dept["id"], allocated_points=120000)
        return prog_sl, prog_uw

    def test_straight_line_accrues_one_twelfth(self, api, finance_admin_headers):
        """PRD §3.7: "`STRAIGHT_LINE` accrues one twelfth of that annual
        figure, rounded half-up to integer cents."

        Design: Difficulty/dual_variant_calc/accrual_straight_line_vs_utilization_weighted
        """
        prog_sl, _ = self._two_program_scenario(api, finance_admin_headers)
        run = validate_success(api.create_accrual_run(
            create_accrual_run_payload(prog_sl["id"], 2026, 8), finance_admin_headers
        ), 201)
        assert run["accrual_method_used"] == "STRAIGHT_LINE"
        # 120000 points x 0.5 cents = 60000 cents annually; / 12 = 5000.
        assert run["department_breakdown"][0]["accrual_cents"] == 5000

    def test_utilization_weighted_applies_curve_weight(
        self, api, finance_admin_headers
    ):
        """PRD §3.7: "`UTILIZATION_WEIGHTED` multiplies the annual figure by
        a redemption curve — 0.07 for each of months 1 through 11 and 0.23 for
        month 12, summing to exactly 1.00 — again rounded half-up."

        Design: Difficulty/dual_variant_calc/accrual_straight_line_vs_utilization_weighted
        """
        prog_sl, prog_uw = self._two_program_scenario(api, finance_admin_headers)
        run_sl = validate_success(api.create_accrual_run(
            create_accrual_run_payload(prog_sl["id"], 2026, 8), finance_admin_headers
        ), 201)
        run_uw = validate_success(api.create_accrual_run(
            create_accrual_run_payload(prog_uw["id"], 2026, 8), finance_admin_headers
        ), 201)
        assert run_uw["accrual_method_used"] == "UTILIZATION_WEIGHTED"
        # 60000 x 0.07 = 4200 for month 8 — diverges from straight-line 5000.
        assert run_uw["department_breakdown"][0]["accrual_cents"] == 4200
        assert run_sl["department_breakdown"][0]["accrual_cents"] != \
            run_uw["department_breakdown"][0]["accrual_cents"]


class TestChargebackRounding:
    def _rounding_scenario(self, api, hr_admin_headers):
        """One employee holding 101 + 103 granted points; two delivered orders
        of 101 and 103 points at 0.5 cents/point, both in August 2026."""
        ctx = setup_program_with_budget(allocated_points=100000)
        program_id = ctx["program"]["id"]
        employee, manager = ctx["employee"], ctx["manager"]
        submit_and_approve_nomination(program_id, employee["id"], manager, 101,
                                      type="MANAGER", reason_code="TEAMWORK",
                                      idempotency_key="cf2-n1")
        submit_and_approve_nomination(program_id, employee["id"], manager, 103,
                                      type="MANAGER", reason_code="INNOVATION",
                                      idempotency_key="cf2-n2")
        vendor = create_vendor()
        item_a = create_catalog_item(vendor["id"], sku="MUG", name="Mug",
                                     point_cost=101, cash_value_cents=1000)
        item_b = create_catalog_item(vendor["id"], sku="SHIRT", name="Shirt",
                                     point_cost=103, cash_value_cents=1000)
        deliver_redemption_order(item_a["id"], employee, idempotency_key="cf2-r1")
        deliver_redemption_order(item_b["id"], employee, idempotency_key="cf2-r2")
        return ctx

    def test_chargeback_rounds_per_settled_line_then_sums(
        self, api, finance_admin_headers, hr_admin_headers
    ):
        """PRD §3.7: "The per-line rounding order is pinned: round each
        settled order line first, then sum; summing first and rounding once
        produces a different number and is forbidden."

        Design: Difficulty/combinatorial_formula/chargeback_per_line_then_sum_rounding
        """
        ctx = self._rounding_scenario(api, hr_admin_headers)
        run = validate_success(api.create_accrual_run(
            create_accrual_run_payload(ctx["program"]["id"], 2026, 8),
            finance_admin_headers,
        ), 201)
        breakdown = run["department_breakdown"][0]
        # round_half_up(101 x 0.5) + round_half_up(103 x 0.5) = 51 + 52 = 103;
        # the forbidden sum-then-round gives 102.
        assert breakdown["redemption_cost_cents"] == 103
        assert breakdown["redemption_cost_cents"] != 102

    def test_net_chargeback_equals_line_rounded_redemption_cost(
        self, api, finance_admin_headers, hr_admin_headers
    ):
        """PRD §3.7: "A department's `net_chargeback_cents` is its redemption
        cost plus its gross-up expense minus its forfeiture credit".

        Design: Difficulty/combinatorial_formula/chargeback_per_line_then_sum_rounding
        """
        ctx = self._rounding_scenario(api, hr_admin_headers)
        run = validate_success(api.create_accrual_run(
            create_accrual_run_payload(ctx["program"]["id"], 2026, 8),
            finance_admin_headers,
        ), 201)
        breakdown = run["department_breakdown"][0]
        # Gross-up disabled and no forfeitures: net == redemption cost.
        assert breakdown["gross_up_expense_cents"] == 0
        assert breakdown["forfeiture_credit_cents"] == 0
        assert breakdown["net_chargeback_cents"] == 103


class TestReturnChargebackNeutrality:
    def _return_scenario(self, api):
        """1000-point order delivered then returned inside August 2026,
        vendor restocking 20%, gross-up disabled."""
        ctx = setup_program_with_budget(
            program_overrides={"grossup_enabled": False}, allocated_points=100000,
        )
        employee = ctx["employee"]
        submit_and_approve_nomination(
            ctx["program"]["id"], employee["id"], ctx["manager"], 1000,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="ci3-n1",
        )
        vendor = create_vendor(restocking_fee_percent=20)
        item = create_catalog_item(vendor["id"], sku="BAG", name="Bag",
                                   point_cost=1000, cash_value_cents=5000)
        delivered = deliver_redemption_order(item["id"], employee,
                                             idempotency_key="ci3-r1")
        get_success_data(api.request_redemption_order_return(
            delivered["id"], make_employee_headers(employee["id"]),
            reason="wrong size",
        ))
        completed = get_success_data(api.complete_redemption_order_return(
            delivered["id"], VOPS
        ))
        return ctx, delivered, completed

    def test_returned_order_contributes_only_its_fee(
        self, api, finance_admin_headers, hr_admin_headers
    ):
        """PRD §3.7: "where net settled points are the order's `points_total`
        when its escrow ended `SETTLED`, or only its `restocking_fee_points`
        when it ended `SETTLED_WITH_FEE`, because a returned order contributes
        only its fee."

        Design: Difficulty/compensating_invariant/settle_then_return_same_period_chargeback_neutral
        """
        ctx, delivered, completed = self._return_scenario(api)
        # floor(1000 x 20 / 100) = 200 points kept as the fee.
        assert completed["restocking_fee_points"] == 200
        assert completed["escrow_status"] == "SETTLED_WITH_FEE"

        record = validate_success(
            api.get_tax_record(delivered["tax_record_id"], hr_admin_headers), 200
        )
        assert record["status"] == "VOIDED"

        run = validate_success(api.create_accrual_run(
            create_accrual_run_payload(ctx["program"]["id"], 2026, 8),
            finance_admin_headers,
        ), 201)
        breakdown = run["department_breakdown"][0]
        # Only the fee settles fiscally: round_half_up(200 x 0.5) = 100.
        assert breakdown["redemption_cost_cents"] == 100
        assert breakdown["gross_up_expense_cents"] == 0
        assert breakdown["net_chargeback_cents"] == 100

    def test_return_completion_refunds_net_of_fee_without_restoring_inventory(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "Completion computes `restocking_fee_points` as the
        order's `points_total` multiplied by the vendor's
        `restocking_fee_percent` and divided by 100, floored to whole points;
        it writes two ledger entries — a `REFUND` crediting the employee's
        `available_points` with `points_total` minus `restocking_fee_points`,
        and a `RESTOCKING_FEE` debiting the fee, which counts toward
        `lifetime_redeemed_points`."

        Design: Difficulty/compensating_invariant/settle_then_return_same_period_chargeback_neutral
        """
        ctx, delivered, completed = self._return_scenario(api)
        assert completed["fulfillment_status"] == "RETURNED"
        refreshed = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        # 1000 granted; 800 refunded; 200 fee stays in lifetime redeemed.
        assert refreshed["available_points"] == 800
        assert refreshed["lifetime_redeemed_points"] == 200


class TestAccrualRunLifecycle:
    def test_close_requires_reconciled_first(self, api, finance_admin_headers):
        """PRD §3.7: "From there, closing the run moves it to `CLOSED`,
        making the period eligible for the tax-year finalization gate of §3.6;
        closing is allowed only from `RECONCILED`."

        Design: Corner/endpoints/close_run_requires_reconciled_first
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000,
        )
        run = validate_success(api.create_accrual_run(
            create_accrual_run_payload(ctx["program"]["id"], 2026, 8),
            finance_admin_headers,
        ), 201)
        res = api.close_accrual_run(run["id"], finance_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        get_success_data(api.reconcile_accrual_run(run["id"], finance_admin_headers))
        closed = validate_success(
            api.close_accrual_run(run["id"], finance_admin_headers), 200
        )
        assert closed["status"] == "CLOSED"

    def test_duplicate_run_rejected_until_first_is_voided(
        self, api, finance_admin_headers
    ):
        """PRD §3.7: "Only one non-`VOIDED` run may exist for a given
        program, year, and month; a duplicate is rejected with
        `ERR_DUPLICATE_ACCRUAL_RUN`."
        PRD §3.7: "a `VOIDED` run no longer counts toward the
        period-uniqueness check nor toward the finalization gate."

        Design: Corner/endpoints/duplicate_accrual_run_rejected
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000,
        )
        run = validate_success(api.create_accrual_run(
            create_accrual_run_payload(ctx["program"]["id"], 2026, 8),
            finance_admin_headers,
        ), 201)
        dupe = api.create_accrual_run(
            create_accrual_run_payload(ctx["program"]["id"], 2026, 8),
            finance_admin_headers,
        )
        validate_error(dupe, ApiErrorId.ERR_DUPLICATE_ACCRUAL_RUN)

        get_success_data(api.void_accrual_run(run["id"], finance_admin_headers))
        replacement = validate_success(api.create_accrual_run(
            create_accrual_run_payload(ctx["program"]["id"], 2026, 8),
            finance_admin_headers,
        ), 201)
        assert replacement["status"] == "OPEN"

    def test_late_settling_order_causes_variance_then_clean_rerun(
        self, api, finance_admin_headers, hr_admin_headers
    ):
        """PRD §3.7: "Reconciling an `OPEN` run recomputes the period's net
        chargeback from current data; when the recomputation differs from the
        posted `total_net_chargeback_cents` — for instance because an order
        settled into the period after the run was created — the nonzero
        difference is exposed as `variance_cents` and the reconcile is
        rejected with `ERR_ACCRUAL_VARIANCE`."

        Design: Corner/endpoints/accrual_variance_on_late_settling_order
        """
        ctx = setup_program_with_budget(allocated_points=10000)
        program_id = ctx["program"]["id"]
        employee = ctx["employee"]
        submit_and_approve_nomination(program_id, employee["id"], ctx["manager"], 400,
                                      type="MANAGER", reason_code="DELIVERY",
                                      idempotency_key="ep-var-1")
        vendor = create_vendor()
        item = create_catalog_item(vendor["id"], sku="M", name="Mug",
                                   point_cost=100, cash_value_cents=500)
        deliver_redemption_order(item["id"], employee, idempotency_key="ep-var-r1")
        run = validate_success(api.create_accrual_run(
            create_accrual_run_payload(program_id, 2026, 8), finance_admin_headers
        ), 201)

        # A second order settles into August after the run was posted.
        deliver_redemption_order(item["id"], employee, idempotency_key="ep-var-r2")

        res = api.reconcile_accrual_run(run["id"], finance_admin_headers)
        validate_error(res, ApiErrorId.ERR_ACCRUAL_VARIANCE)

        get_success_data(api.void_accrual_run(run["id"], finance_admin_headers))
        rerun = validate_success(api.create_accrual_run(
            create_accrual_run_payload(program_id, 2026, 8), finance_admin_headers
        ), 201)
        # Two settled 100-point orders x 0.5 cents = 50 + 50.
        assert rerun["total_net_chargeback_cents"] == 100
        reconciled = validate_success(
            api.reconcile_accrual_run(rerun["id"], finance_admin_headers), 200
        )
        assert reconciled["status"] == "RECONCILED"


class TestTaxYearFinalizationGate:
    def _finalize_scenario(self, api, hr_admin_headers):
        """One delivered 25000-cent order in August 2026 under a
        grossup-enabled program; all months except 8 CLOSED, month 8 OPEN."""
        ctx = setup_program_with_budget(
            program_overrides={"grossup_enabled": True,
                               "state_rate_map": {"CA": 0.093}},
            allocated_points=100000,
        )
        program_id = ctx["program"]["id"]
        employee = ctx["employee"]
        submit_and_approve_nomination(program_id, employee["id"], ctx["manager"], 8000,
                                      type="MANAGER", reason_code="DELIVERY",
                                      idempotency_key="ce3-n1")
        vendor = create_vendor()
        item = create_catalog_item(vendor["id"], sku="WATCH1", name="Watch",
                                   point_cost=8000, cash_value_cents=25000)
        delivered = deliver_redemption_order(item["id"], employee,
                                             idempotency_key="ce3-r1")
        for month in range(1, 13):
            if month == 8:
                open_run = validate_success(api.create_accrual_run(
                    create_accrual_run_payload(program_id, 2026, 8), FIN,
                ), 201)
            else:
                create_reconcile_close_run(program_id, 2026, month)
        return ctx, delivered["tax_record_id"], open_run

    def test_finalize_rejected_while_a_month_is_still_open(
        self, api, hr_admin_headers, payroll_specialist_headers
    ):
        """PRD §3.6: "Every month's accrual run for the program and that year
        — months 1 through 12 — must exist and be `CLOSED` or `VOIDED`; a
        missing, `OPEN`, or merely `RECONCILED` month fails the gate with
        `ERR_PERIODS_NOT_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/tax_finalize_gated_by_accrual_closure
        """
        ctx, _, _ = self._finalize_scenario(api, hr_admin_headers)
        res = api.finalize_tax_year(ctx["program"]["id"], 2026, payroll_specialist_headers)
        validate_error(res, ApiErrorId.ERR_PERIODS_NOT_CLOSED)

    def test_finalize_succeeds_after_closing_the_open_month(
        self, api, hr_admin_headers, payroll_specialist_headers, finance_admin_headers
    ):
        """PRD §3.6: "On success, every `ESTIMATED` record of that `tax_year`
        moves to `FINALIZED` with its final gross-up recomputed, and the
        response summarizes the run with `finalized_count`, the affected
        `records`, and `total_delta_cents`."

        Design: Difficulty/cross_entity_state_dependency/tax_finalize_gated_by_accrual_closure
        """
        ctx, tax_record_id, open_run = self._finalize_scenario(api, hr_admin_headers)
        res = api.finalize_tax_year(ctx["program"]["id"], 2026, payroll_specialist_headers)
        validate_error(res, ApiErrorId.ERR_PERIODS_NOT_CLOSED)

        get_success_data(api.reconcile_accrual_run(open_run["id"], finance_admin_headers))
        get_success_data(api.close_accrual_run(open_run["id"], finance_admin_headers))
        result = validate_success(api.finalize_tax_year(
            ctx["program"]["id"], 2026, payroll_specialist_headers
        ), 200)
        assert result["finalized_count"] == 1
        assert result["total_delta_cents"] == 0

        record = validate_success(api.get_tax_record(tax_record_id, hr_admin_headers), 200)
        assert record["status"] == "FINALIZED"
        # No intervening compensation change: final equals provisional.
        assert record["final_gross_up_cents"] == 15950
        assert record["delta_cents"] == 0

    def test_repeated_finalization_rejected(
        self, api, hr_admin_headers, payroll_specialist_headers
    ):
        """PRD §3.6: "Repeating a finalization for an already-finalized year
        is `ERR_TAX_YEAR_FINALIZED`."

        Design: Corner/endpoints/finalize_tax_year_repeat_rejected
        """
        ctx = setup_program_with_budget(
            program_overrides={"grossup_enabled": True,
                               "max_points_per_nomination": 1000},
            allocated_points=10000,
        )
        close_accrual_year(ctx["program"]["id"], 2026)
        validate_success(api.finalize_tax_year(
            ctx["program"]["id"], 2026, payroll_specialist_headers
        ), 200)
        res = api.finalize_tax_year(ctx["program"]["id"], 2026, payroll_specialist_headers)
        validate_error(res, ApiErrorId.ERR_TAX_YEAR_FINALIZED)

    def test_invalid_tax_year_rejected(self, api, payroll_specialist_headers):
        """PRD §3.6: "The request names a `tax_year` between 2000 and 2100
        inclusive (`ERR_INVALID_TAX_YEAR` otherwise)."

        Design: Corner/errors/invalid_tax_year_rejected
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000,
        )
        res = api.finalize_tax_year(ctx["program"]["id"], 1999, payroll_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_TAX_YEAR)
