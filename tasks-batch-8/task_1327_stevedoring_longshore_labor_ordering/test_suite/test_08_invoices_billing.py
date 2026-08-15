"""Invoicing: provisional vs final variants, line arithmetic, lifecycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjust_invoice,
    berth_vessel,
    book_equipment,
    check_in,
    complete_gang,
    create_invoice,
    create_shift,
    create_vessel,
    dispute_invoice,
    enter_submit_approve_timesheet,
    finalize_invoice,
    get_invoice,
    get_vessel,
    issue_invoice,
    list_assignments,
    open_shift,
    place_gang,
    record_moves,
    record_payment,
    register_unit,
    register_worker,
    register_workers,
    run_dispatch,
    setup_completed_vessel,
    setup_finalized_invoice,
    setup_issued_invoice,
    setup_placed_gang,
    start_gang_work,
    start_shift,
    validate_error,
    validate_success,
    api_client,
)

BILLING = TEST_USERS["billing_headers"]

HOLDMEN_2 = [
    {"full_name": "W One", "registration_number": "R001",
     "classification": "HOLDMAN", "registered_on": "2010-01-01",
     "base_hourly_rate_cents": 4000},
    {"full_name": "W Two", "registration_number": "R002",
     "classification": "HOLDMAN", "registered_on": "2015-06-01",
     "base_hourly_rate_cents": 4000},
]

FOUR_PERIODS_150_MOVES = [
    {"period_start_utc": s, "period_end_utc": e,
     "moves_count": 150, "tons_lifted": 100, "stoppage_minutes": 0}
    for s, e in [("2026-08-10T08:00:00Z", "2026-08-10T09:00:00Z"),
                 ("2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z"),
                 ("2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z"),
                 ("2026-08-10T11:00:00Z", "2026-08-10T12:00:00Z")]
]


class TestProvisionalVsFinalInvoice:

    def _provisional_scenario(self):
        """Vessel (600 moves / 400 tons planned) BERTHED; shift OPEN; gang
        headcount 2 placed; provisional DRAFT invoice created."""
        vessel = create_vessel(vessel_name="MV Variant", voyage_number="V-101",
                               planned_moves=600, planned_tons=400,
                               contracted_mph_target=25.0,
                               credit_limit_cents=500_000_000)
        berth_vessel(vessel["id"])
        shift = create_shift(vessel["id"])
        open_shift(shift["id"])
        gang = place_gang(shift["id"], gang_type="HOLD_GANG",
                          required_classification="HOLDMAN",
                          required_headcount=2,
                          required_equipment_type="RTG",
                          required_equipment_count=1)
        invoice = create_invoice(vessel["id"])
        return vessel, shift, gang, invoice

    def test_invoice_provisional_lines_price_the_plan(self, api):
        """PRD §3.9: "The new invoice is a `DRAFT` whose `rate_variant` reads `PROVISIONAL`, and its five lines price the plan rather than the reality: the container line runs the tiered schedule over `planned_moves`, the tonnage line prices `planned_tons`, the man-hour line assumes every current gang order's `required_headcount` workers each work a full 480-minute shift, and the equipment and stoppage-credit lines are both zero while the invoice remains a draft."
        PRD §3.9: "The container line is marginal and tiered: the first 500 moves are billed at 4,500 cents each, the next 500 moves — those from 501 through 1,000 — at 4,200 cents each, and every move beyond 1,000 at 3,900 cents each, the three tiers summing into the line. The tonnage line is the tons multiplied by 620 cents per ton, rounded half up."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        _vessel, _shift, _gang, invoice = self._provisional_scenario()
        assert invoice["status"] == "DRAFT"
        assert invoice["rate_variant"] == "PROVISIONAL"
        # container: 500*4500 + 100*4200 = 2,670,000
        assert invoice["container_line_cents"] == 2_670_000
        # tonnage: 400 * 620
        assert invoice["tonnage_line_cents"] == 248_000
        # manhour: 2 headcount * 480 min * 6500 / 60
        assert invoice["manhour_line_cents"] == 104_000
        assert invoice["equipment_line_cents"] == 0
        assert invoice["stoppage_credit_cents"] == 0
        assert invoice["subtotal_cents"] == 3_022_000
        # 3,022,000 >= 3,000,000 -> 5% discount
        assert invoice["discount_cents"] == 151_100
        assert invoice["total_cents"] == 2_870_900

    def test_invoice_final_lines_recompute_from_actuals(self, api):
        """PRD §3.9: "Finalization recomputes every line from actuals — `actual_moves` and `actual_tons` replace the plan, approved timesheets replace the assumed shifts, real equipment windows replace the zero line, and accumulated suspensions produce the credit — and `rate_variant` flips from `PROVISIONAL` to `FINAL`, moving the invoice from `DRAFT` to `FINALIZED`."
        PRD §3.9: "The equipment line bills per equipment type: billable minutes equal the full window minutes of that type's assignments in `ACTIVE` or `RELEASED` status plus one half of the window minutes of its assignments in `DOWN` status — a downed unit bills at half rate — and each type's charge is its billable minutes multiplied by the type's hourly rate and divided by sixty, rounded half up; the hourly rates are 25,000 cents for `SHIP_CRANE`, 12,000 for `RTG`, 6,000 for `FORKLIFT`, and 5,500 for `TRACTOR`, and the line is the sum of the per-type charges."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        vessel, shift, gang, invoice = self._provisional_scenario()
        provisional_total = invoice["total_cents"]

        workers = register_workers([dict(s) for s in HOLDMEN_2])
        unit = register_unit(unit_code="RTG-1", equipment_type="RTG")
        book_equipment(gang["id"], unit["id"])
        run_dispatch(gang["id"])
        start_shift(shift["id"])
        for a in list_assignments(gang_order_id=gang["id"]):
            check_in(a["id"])
        validate_success(start_gang_work(gang["id"], workers[0]["id"]))
        for mr in FOUR_PERIODS_150_MOVES:
            record_moves(gang["id"], workers[0]["id"], **mr)
        complete_gang(gang["id"], workers[0]["id"])
        for w in workers:
            enter_submit_approve_timesheet(gang["id"], w["id"], workers[0]["id"],
                                           work_minutes=480, meal_break_taken=True)
        validate_success(api_client.complete_vessel_call(vessel["id"],
                                                         TEST_USERS["superintendent_headers"]))

        finalized = finalize_invoice(invoice["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["rate_variant"] == "FINAL"
        # actuals match the plan: 600 moves / 400 tons.
        assert finalized["container_line_cents"] == 2_670_000
        assert finalized["tonnage_line_cents"] == 248_000
        # two approved 480-minute timesheets: 960 * 6500 / 60
        assert finalized["manhour_line_cents"] == 104_000
        # one 480-minute RTG window at 12,000/hour, billed full (RELEASED)
        assert finalized["equipment_line_cents"] == 96_000
        assert finalized["stoppage_credit_cents"] == 0
        assert finalized["subtotal_cents"] == 3_118_000
        assert finalized["discount_cents"] == 155_900
        assert finalized["total_cents"] == 2_962_100
        assert finalized["total_cents"] != provisional_total, (
            "the two variants diverge for identical vessel data lineage")


class TestManhourRounding:

    def _setup_77_113_scenario(self):
        """Vessel completed; one gang (headcount 2, no equipment) worked with
        zero move records; approved timesheets of 77 and 113 minutes."""
        ns = setup_completed_vessel(
            vessel_overrides={"vessel_name": "MV Rounding", "voyage_number": "R-401",
                              "planned_moves": 10, "planned_tons": 0,
                              "credit_limit_cents": 500_000_000},
            gang_overrides={"gang_type": "GENERAL",
                            "required_classification": "HOLDMAN",
                            "required_headcount": 2,
                            "required_equipment_type": "RTG",
                            "required_equipment_count": 0},
            worker_specs=[dict(s) for s in HOLDMEN_2],
            timesheets=[(0, {"work_minutes": 77, "meal_break_taken": True}),
                        (1, {"work_minutes": 113, "meal_break_taken": True})])
        ns.invoice = create_invoice(ns.vessel["id"])
        return ns

    def test_manhour_line_rounded_once_after_sum(self, api):
        """PRD §3.9: "The man-hour line sums the `work_minutes` of all `APPROVED` timesheets across the vessel's gang orders first, then multiplies by 6,500 cents per hour, divides by sixty, and rounds half up once."
        PRD §2.7: "invoice lines are each rounded half up to integer cents individually and only then summed — summing unrounded lines and rounding once at the end is not permitted"

        Design: Difficulty/combinatorial_formula/invoice_manhour_line_rounded_once_after_sum
        """
        ns = self._setup_77_113_scenario()
        finalized = finalize_invoice(ns.invoice["id"])
        # (77 + 113) * 6500 / 60 = 20583.33 -> 20583; per-entry rounding would
        # give 8342 + 12242 = 20584 and is forbidden.
        assert finalized["manhour_line_cents"] == 20_583

    def test_manhour_only_invoice_zeroes_other_lines(self, api):
        """PRD §3.9: "Rounding order is pinned: each of the five lines is computed unrounded, rounded half up to integer cents, and only then summed into `subtotal_cents`; summing unrounded lines and rounding once is forbidden."
        PRD §3.9: "`discount_cents` is the subtotal multiplied by the applicable rate, rounded half up to integer cents, and is zero whenever the subtotal is not positive. The invoice's `total_cents` is the subtotal minus the discount plus `adjustment_total_cents`, the running sum of manual adjustments, which starts at zero."

        Design: Difficulty/combinatorial_formula/invoice_manhour_line_rounded_once_after_sum
        """
        ns = self._setup_77_113_scenario()
        finalized = finalize_invoice(ns.invoice["id"])
        assert finalized["container_line_cents"] == 0
        assert finalized["tonnage_line_cents"] == 0
        assert finalized["equipment_line_cents"] == 0
        assert finalized["stoppage_credit_cents"] == 0
        assert finalized["subtotal_cents"] == 20_583
        assert finalized["discount_cents"] == 0
        assert finalized["total_cents"] == 20_583


class TestDiscountTierKeyedOnSubtotal:

    def _build_tier_invoice(self):
        """Actuals engineered so the pre-discount subtotal is exactly
        3,000,000: 600 moves (2,670,000) + 400 tons (248,000) + one approved
        480-minute timesheet (52,000) + one 150-minute RTG window (30,000)."""
        crane = {"full_name": "Crane Op", "registration_number": "R010",
                 "classification": "CRANE_OPERATOR", "registered_on": "2010-01-01",
                 "base_hourly_rate_cents": 5000}
        vessel = create_vessel(vessel_name="MV Tier", voyage_number="T-501",
                               planned_moves=600, planned_tons=400,
                               contracted_mph_target=25.0,
                               credit_limit_cents=500_000_000)
        berth_vessel(vessel["id"])
        shift = create_shift(vessel["id"])
        open_shift(shift["id"])
        gang = place_gang(shift["id"], gang_type="CRANE_GANG",
                          required_classification="CRANE_OPERATOR",
                          required_headcount=1,
                          required_equipment_type="RTG",
                          required_equipment_count=1)
        w1 = register_worker(**crane)
        unit = register_unit(unit_code="RTG-9", equipment_type="RTG")
        book_equipment(gang["id"], unit["id"],
                       window_start_utc="2026-08-10T08:00:00Z",
                       window_end_utc="2026-08-10T10:30:00Z")
        run_dispatch(gang["id"])
        start_shift(shift["id"])
        for a in list_assignments(gang_order_id=gang["id"]):
            check_in(a["id"])
        validate_success(start_gang_work(gang["id"], w1["id"]))
        for mr in FOUR_PERIODS_150_MOVES:
            record_moves(gang["id"], w1["id"], **mr)
        complete_gang(gang["id"], w1["id"])
        enter_submit_approve_timesheet(gang["id"], w1["id"], w1["id"],
                                       work_minutes=480, meal_break_taken=True)
        validate_success(api_client.complete_vessel_call(
            vessel["id"], TEST_USERS["superintendent_headers"]))
        invoice = create_invoice(vessel["id"])
        return finalize_invoice(invoice["id"])

    def test_subtotal_at_tier_boundary_earns_five_percent(self, api):
        """PRD §3.9: "Discounts key on the pre-discount subtotal, in that deliberately circular-looking order: a `subtotal_cents` of at least 6,000,000 cents earns a rate of 8 percent; at least 3,000,000 but below 6,000,000 earns 5 percent; below that, no discount."

        Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_prediscount_subtotal
        """
        finalized = self._build_tier_invoice()
        assert finalized["container_line_cents"] == 2_670_000
        assert finalized["tonnage_line_cents"] == 248_000
        assert finalized["manhour_line_cents"] == 52_000
        assert finalized["equipment_line_cents"] == 30_000, (
            "150 minutes at 12,000/hour")
        assert finalized["stoppage_credit_cents"] == 0
        assert finalized["subtotal_cents"] == 3_000_000, (
            "exactly the 5% tier threshold; 'at least' semantics apply")

    def test_discount_applies_even_when_total_falls_below_tier(self, api):
        """PRD §3.9: "Discounts key on the pre-discount subtotal, in that deliberately circular-looking order: a `subtotal_cents` of at least 6,000,000 cents earns a rate of 8 percent; at least 3,000,000 but below 6,000,000 earns 5 percent; below that, no discount. `discount_cents` is the subtotal multiplied by the applicable rate, rounded half up to integer cents, and is zero whenever the subtotal is not positive. The invoice's `total_cents` is the subtotal minus the discount plus `adjustment_total_cents`, the running sum of manual adjustments, which starts at zero."

        Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_prediscount_subtotal
        """
        finalized = self._build_tier_invoice()
        assert finalized["subtotal_cents"] == 3_000_000
        assert finalized["discount_cents"] == 150_000
        assert finalized["total_cents"] == 2_850_000, (
            "total falls below the tier threshold, yet the discount stands: "
            "the tier keys on the PRE-discount subtotal")


class TestFinalizeGate:

    def _setup_berthed_vessel_with_draft_invoice(self):
        vessel = create_vessel(vessel_name="MV XDep3", voyage_number="X-303",
                               planned_moves=100, planned_tons=50,
                               credit_limit_cents=500_000_000)
        berth_vessel(vessel["id"])
        invoice = create_invoice(vessel["id"])
        return vessel, invoice

    def test_invoice_finalize_requires_completed_vessel(self, api):
        """PRD §3.9: "Finalizing requires the vessel call to be `COMPLETED`; against any earlier vessel state the attempt is rejected with `ERR_INVOICE_NOT_FINALIZABLE` (409)."

        Design: Difficulty/cross_entity_state_dependency/invoice_finalize_requires_completed_vessel
        """
        vessel, invoice = self._setup_berthed_vessel_with_draft_invoice()
        assert get_vessel(vessel["id"])["status"] == "BERTHED"

        resp = api_client.finalize_invoice(invoice["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FINALIZABLE)

    def test_finalize_rejection_preserves_provisional_draft(self, api):
        """PRD §3.9: "The new invoice is a `DRAFT` whose `rate_variant` reads `PROVISIONAL`, and its five lines price the plan rather than the reality: the container line runs the tiered schedule over `planned_moves`, the tonnage line prices `planned_tons`, the man-hour line assumes every current gang order's `required_headcount` workers each work a full 480-minute shift, and the equipment and stoppage-credit lines are both zero while the invoice remains a draft."
        PRD §3.9: "Finalizing requires the vessel call to be `COMPLETED`; against any earlier vessel state the attempt is rejected with `ERR_INVOICE_NOT_FINALIZABLE` (409)."

        Design: Difficulty/cross_entity_state_dependency/invoice_finalize_requires_completed_vessel
        """
        _vessel, invoice = self._setup_berthed_vessel_with_draft_invoice()
        resp = api_client.finalize_invoice(invoice["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FINALIZABLE)

        after = get_invoice(invoice["id"])
        assert after["status"] == "DRAFT"
        assert after["rate_variant"] == "PROVISIONAL"


class TestInvoiceLifecycleCycle:

    def _timesheet_only_issued_invoice(self, credit_limit=1_000_000):
        """One approved 480-minute DAY timesheet at rate 4000 -> manhour line
        52,000; all other lines 0. Invoice ISSUED with total 52,000."""
        return setup_issued_invoice(
            vessel_overrides={"vessel_name": "MV Cycle2", "voyage_number": "S-107",
                              "planned_moves": 10, "planned_tons": 5,
                              "credit_limit_cents": credit_limit},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMEN_2[0])],
            timesheets=[(0, {"work_minutes": 480, "meal_break_taken": True})])

    def test_invoice_dispute_adjust_reissue_pay_cycle(self, api):
        """PRD §3.9: "Applied to a `DISPUTED` invoice, the adjustment resolves the dispute by returning the invoice to `FINALIZED`, from which it may be issued again — the `ISSUED` → `DISPUTED` → `FINALIZED` → `ISSUED` cycle may repeat until the balance is paid and the invoice rests in `PAID`."
        PRD §3.9: "Every accepted adjustment adds its `adjustment_cents` into `adjustment_total_cents`, recomputes the totals, and increments the invoice's `version` by one."
        PRD §3.9: "Each accepted payment adds to `amount_paid_cents`, the remaining balance recomputes, and the invoice moves to `PAID` exactly when the remaining balance reaches zero."

        Design: Corner/state_machines/invoice_dispute_adjust_reissue_pay_cycle
        """
        ns = self._timesheet_only_issued_invoice()
        invoice = ns.invoice
        assert invoice["status"] == "ISSUED"
        assert invoice["total_cents"] == 52_000

        disputed = dispute_invoice(invoice["id"],
                                   "Rate mismatch with service agreement")
        assert disputed["status"] == "DISPUTED"

        adjusted = validate_success(
            adjust_invoice(invoice["id"], -2_000, "Goodwill credit"))
        assert adjusted["status"] == "FINALIZED"
        assert adjusted["adjustment_total_cents"] == -2_000
        assert adjusted["total_cents"] == 50_000

        reissued = issue_invoice(invoice["id"])
        assert reissued["status"] == "ISSUED"

        paid = validate_success(record_payment(invoice["id"], 50_000))
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == 50_000
        assert paid["remaining_balance_cents"] == 0

    def test_issue_above_credit_limit_returns_402(self, api):
        """PRD §3.9: "Issuing a finalized invoice is gated by the credit ceiling: when `total_cents` exceeds the vessel call's `credit_limit_cents`, the issue is rejected with `ERR_INVOICE_CREDIT_LIMIT` (402); otherwise the invoice becomes `ISSUED`."

        Design: Corner/validations/issue_above_credit_limit_returns_402
        """
        ns = setup_finalized_invoice(
            vessel_overrides={"vessel_name": "MV Credit", "voyage_number": "V-307",
                              "planned_moves": 10, "planned_tons": 5,
                              "credit_limit_cents": 1_000},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMEN_2[0])],
            timesheets=[(0, {"work_minutes": 480, "meal_break_taken": True})])
        assert ns.invoice["total_cents"] == 52_000

        resp = api_client.issue_invoice(ns.invoice["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_CREDIT_LIMIT)
        assert get_invoice(ns.invoice["id"])["status"] == "FINALIZED"

    def test_overpayment_rejected_then_exact_payment_settles(self, api):
        """PRD §3.9: "A payment may not exceed `remaining_balance_cents` — an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (422). Each accepted payment adds to `amount_paid_cents`, the remaining balance recomputes, and the invoice moves to `PAID` exactly when the remaining balance reaches zero."

        Design: Corner/validations/overpayment_rejected_then_exact_payment_settles
        """
        ns = self._timesheet_only_issued_invoice(credit_limit=500_000_000)
        invoice = ns.invoice
        assert invoice["total_cents"] == 52_000

        over = record_payment(invoice["id"], 52_001)
        validate_error(over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
        after_over = get_invoice(invoice["id"])
        assert after_over["status"] == "ISSUED"
        assert after_over["amount_paid_cents"] == 0

        exact = validate_success(record_payment(invoice["id"], 52_000))
        assert exact["status"] == "PAID"
        assert exact["remaining_balance_cents"] == 0


class TestInvoiceCreateGate:

    def test_invoice_create_on_unberthed_vessel_returns_invalid_state(self, api):
        """PRD §3.9: "Billing opens early. Once a vessel call is `BERTHED` or later, a `BillingClerk` may create its invoice from the `vessel_call_id`; a call still `SCHEDULED` refuses the create with `ERR_INVALID_STATE`."

        Design: Corner/validations/invoice_create_on_unberthed_vessel_returns_invalid_state
        """
        vessel = create_vessel(vessel_name="MV Early", voyage_number="V-312")
        assert vessel["status"] == "SCHEDULED"
        resp = api_client.create_invoice({"vessel_call_id": vessel["id"]}, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestContainerTierStraddle:

    def _vessel_with_single_move_record(self, name, voyage, moves):
        """COMPLETED vessel whose only actuals are one 60-minute record of
        `moves` moves; returns its FINALIZED invoice."""
        # Drop the explicit registration_number so the factory auto-uniquifies
        # across the two invocations in the straddle test (same-test state).
        worker_spec = {k: v for k, v in HOLDMEN_2[0].items()
                       if k != "registration_number"}
        ns = setup_completed_vessel(
            vessel_overrides={"vessel_name": name, "voyage_number": voyage,
                              "planned_moves": moves, "planned_tons": 0,
                              "credit_limit_cents": 500_000_000},
            gang_overrides={"required_headcount": 1},
            worker_specs=[worker_spec],
            move_records=[{"period_start_utc": "2026-08-10T08:00:00Z",
                           "period_end_utc": "2026-08-10T09:00:00Z",
                           "moves_count": moves, "tons_lifted": 0,
                           "stoppage_minutes": 0}])
        invoice = create_invoice(ns.vessel["id"])
        return finalize_invoice(invoice["id"])

    def test_container_tier_straddle_at_500_moves(self, api):
        """PRD §3.9: "The container line is marginal and tiered: the first 500 moves are billed at 4,500 cents each, the next 500 moves — those from 501 through 1,000 — at 4,200 cents each, and every move beyond 1,000 at 3,900 cents each, the three tiers summing into the line."

        Design: Corner/calculations/container_tier_straddle_at_500_moves
        """
        inv500 = self._vessel_with_single_move_record(
            "MV FiveHundred", "C-209A", 500)
        assert inv500["container_line_cents"] == 2_250_000, (
            "exactly 500 moves price entirely in tier 1")

        inv501 = self._vessel_with_single_move_record(
            "MV FiveOhOne", "C-209B", 501)
        assert inv501["container_line_cents"] == 2_254_200, (
            "500*4500 + 1*4200: the 501st move bills at the tier-2 marginal rate")
