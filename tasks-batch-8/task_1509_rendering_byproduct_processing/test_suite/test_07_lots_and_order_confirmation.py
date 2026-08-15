"""Product-lot grading and sales-order confirmation gates (PRD §3.7, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_contract,
    create_priced_order,
    get_lot_for_run,
    grade_lot,
    setup_completed_cook_run,
    setup_released_tallow_lot,
    validate_error,
    validate_success,
)

QL = TEST_USERS["quality_lab_tech_headers"]
PS = TEST_USERS["production_supervisor_headers"]
SM = TEST_USERS["sales_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestGradeBoundaries:
    def test_grade_boundary_inclusive_edges(self, api):
        """PRD §3.7: "Fats — `TALLOW` and `YELLOW_GREASE` — are judged on
        `lab_moisture_pct` and `lab_ffa_pct`: `PREMIUM` when moisture is at most 0.3 and FFA
        at most 2.0; otherwise `STANDARD` when moisture is at most 0.5 and FFA at most 4.0;
        otherwise `FEED_GRADE` when moisture is at most 1.0 and FFA at most 8.0; otherwise
        `OFF_SPEC`. Meals — `PROTEIN_MEAL` and `FEATHER_MEAL` — are judged on
        `lab_protein_pct` and `lab_moisture_pct`: `PREMIUM` when protein is at least 65 and
        moisture at most 8; otherwise `STANDARD` when protein is at least 60 and moisture at
        most 10; otherwise `FEED_GRADE` when protein is at least 55 and moisture at most 12;
        otherwise `OFF_SPEC`. All boundary comparisons are inclusive, exactly as written."

        Design: Corner/calculations/grade_boundary_inclusive_edges
        """
        ctx = setup_completed_cook_run()
        fat_lot = get_lot_for_run(ctx["run"]["id"], "TALLOW")
        meal_lot = get_lot_for_run(ctx["run"]["id"], "PROTEIN_MEAL")

        # TALLOW exactly at the PREMIUM boundary: moisture 0.3 <= 0.3, ffa 2.0 <= 2.0.
        graded_fat = grade_lot(fat_lot["id"], 0.3, 2.0, 0)
        assert graded_fat["grade"] == "PREMIUM"
        assert graded_fat["status"] == "GRADED"
        assert graded_fat["graded_by"] == "ql-1"

        # PROTEIN_MEAL exactly at the PREMIUM boundary: protein 65 >= 65, moisture 8 <= 8.
        graded_meal = grade_lot(meal_lot["id"], 8.0, 0, 65.0)
        assert graded_meal["grade"] == "PREMIUM"
        assert graded_meal["status"] == "GRADED"


class TestConfirmValidationPriority:
    def _setup_offspec_confirm(self, api):
        """FEED_GRADE TALLOW lot (moisture 0.9, ffa 6.0) RELEASED; FIXED contract (base 50,
        spec moisture <= 0.5 / ffa <= 4.0, floor 20.0); order 500 lbs priced FEED_GRADE.
        The lot fails the contract spec AND the margin (11.63%) is below the floor."""
        ctx = setup_released_tallow_lot(
            lab_moisture_pct=0.9, lab_ffa_pct=6.0, lab_protein_pct=0
        )
        assert ctx["lot"]["grade"] == "FEED_GRADE"
        assert ctx["lot"]["status"] == "RELEASED"
        contract = create_active_contract(ctx["plant"]["id"], margin_floor_pct=20.0)
        order = create_priced_order(contract, quantity_lbs=500, expected_grade="FEED_GRADE")
        # unit = round_half_up(50 * 0.85) = 43; margin = round_half_up((43-38)/43*100) = 11.63.
        assert order["unit_price_cents"] == 43
        assert order["margin_pct"] == pytest.approx(11.63, abs=1e-9)
        ctx["contract"] = contract
        ctx["order"] = order
        return ctx

    def test_confirm_offspec_lot_reports_spec_error(self, api):
        """PRD §3.8: "Specification safety is checked before any fiscal concern: every
        allocated lot must be `RELEASED`, its `product_type` must equal the contract's, its
        `lab_moisture_pct` must not exceed `spec_max_moisture_pct`, a fat lot's
        `lab_ffa_pct` must not exceed `spec_max_ffa_pct`, a meal lot's `lab_protein_pct`
        must be at least `spec_min_protein_pct`, and its grade must not be `OFF_SPEC` — any
        failure returns `ERR_SPEC_BELOW_CONTRACT_MIN`."
        PRD §3.8: "Finally the fiscal gate: the order's `margin_pct` must be at least the
        contract's `margin_floor_pct`, else `ERR_MARGIN_FLOOR_BREACH` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_offspec_lot_margin_breach
        """
        ctx = self._setup_offspec_confirm(api)
        res = api.confirm_order(
            ctx["order"]["id"],
            {"allocations": [{"lot_id": ctx["lot"]["id"], "quantity_lbs": 500}]},
            SM,
        )
        # Both failures are armed (spec moisture 0.9 > 0.5; margin 11.63 < floor 20.0);
        # the specification check is evaluated before any fiscal concern.
        validate_error(res, ApiErrorId.ERR_SPEC_BELOW_CONTRACT_MIN, expected_status=422)

    def test_rejected_confirm_leaves_order_and_lot_untouched(self, api):
        """PRD §3.8: "Specification safety is checked before any fiscal concern: ... any
        failure returns `ERR_SPEC_BELOW_CONTRACT_MIN`."
        PRD §3.8: "A confirmed order records its `allocations` and increases each allocated
        lot's `allocated_lbs` by its allocated quantity, decreasing `available_lbs`
        accordingly; the order is now `CONFIRMED`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_offspec_lot_margin_breach
        """
        ctx = self._setup_offspec_confirm(api)
        res = api.confirm_order(
            ctx["order"]["id"],
            {"allocations": [{"lot_id": ctx["lot"]["id"], "quantity_lbs": 500}]},
            SM,
        )
        validate_error(res, ApiErrorId.ERR_SPEC_BELOW_CONTRACT_MIN, expected_status=422)

        # A rejected confirm performs no allocation.
        order = validate_success(api.get_sales_order(ctx["order"]["id"], ANY), 200)
        assert order["status"] == "PRICED"
        lot = validate_success(api.get_product_lot(ctx["lot"]["id"], ANY), 200)
        assert lot["allocated_lbs"] == 0
        assert lot["available_lbs"] == 800


class TestConfirmGates:
    def test_margin_floor_exact_equality_passes(self, api):
        """PRD §3.8: "Finally the fiscal gate: the order's `margin_pct` must be at least the
        contract's `margin_floor_pct`, else `ERR_MARGIN_FLOOR_BREACH` (HTTP 402)."
        PRD §3.8: "Finally `margin_pct` is one hundred times the amount by which
        `unit_price_cents` exceeds the plant's `standard_cost_cents_per_lb`, divided by
        `unit_price_cents`, rounded half-up to two decimal places."

        Design: Corner/calculations/margin_floor_exact_equality_passes
        """
        ctx = setup_released_tallow_lot()  # PREMIUM TALLOW lot, 800 lbs
        contract = create_active_contract(ctx["plant"]["id"], margin_floor_pct=24.0)
        # STANDARD multiplier 1.00: unit 50; margin = (50-38)/50*100 = 24.0 == floor 24.0.
        order = create_priced_order(contract, quantity_lbs=100, expected_grade="STANDARD")
        assert order["margin_pct"] == pytest.approx(24.0, abs=1e-9)

        confirmed = validate_success(
            api.confirm_order(
                order["id"],
                {"allocations": [{"lot_id": ctx["lot"]["id"], "quantity_lbs": 100}]},
                SM,
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"

        lot = validate_success(api.get_product_lot(ctx["lot"]["id"], ANY), 200)
        assert lot["allocated_lbs"] == 100
        assert lot["available_lbs"] == 700

    def test_order_confirm_allocation_sum_mismatch_rejected(self, api):
        """PRD §3.8: "Then, in this order: the allocations must sum exactly to the order's
        `quantity_lbs` (`ERR_ALLOCATION_MISMATCH`), and only afterward is each lot's
        `available_lbs` checked for sufficiency (`ERR_INSUFFICIENT_LOT_QUANTITY`)."

        Design: Corner/validations/order_confirm_allocation_sum_mismatch_rejected
        """
        ctx = setup_released_tallow_lot()  # PREMIUM TALLOW lot, 800 lbs available
        contract = create_active_contract(ctx["plant"]["id"], margin_floor_pct=15.0)
        order = create_priced_order(contract, quantity_lbs=500, expected_grade="STANDARD")

        # 400 != 500: the sum check fails before availability is examined.
        res = api.confirm_order(
            order["id"],
            {"allocations": [{"lot_id": ctx["lot"]["id"], "quantity_lbs": 400}]},
            SM,
        )
        validate_error(res, ApiErrorId.ERR_ALLOCATION_MISMATCH, expected_status=422)

        order_after = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert order_after["status"] == "PRICED"
        lot = validate_success(api.get_product_lot(ctx["lot"]["id"], ANY), 200)
        assert lot["allocated_lbs"] == 0

    def test_order_confirm_lot_insufficient_rejected(self, api):
        """PRD §3.8: "Then, in this order: the allocations must sum exactly to the order's
        `quantity_lbs` (`ERR_ALLOCATION_MISMATCH`), and only afterward is each lot's
        `available_lbs` checked for sufficiency (`ERR_INSUFFICIENT_LOT_QUANTITY`)."

        Design: Corner/validations/order_confirm_lot_insufficient_rejected
        """
        ctx = setup_released_tallow_lot()  # PREMIUM TALLOW lot, 800 lbs available
        contract = create_active_contract(ctx["plant"]["id"], margin_floor_pct=15.0)
        order = create_priced_order(contract, quantity_lbs=900, expected_grade="STANDARD")

        # Sum matches (900 == 900), but the lot only holds 800 available lbs.
        res = api.confirm_order(
            order["id"],
            {"allocations": [{"lot_id": ctx["lot"]["id"], "quantity_lbs": 900}]},
            SM,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY, expected_status=422)

        order_after = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert order_after["status"] == "PRICED"

    def test_margin_floor_breach_rejected(self, api):
        """PRD §3.8: "Finally the fiscal gate: the order's `margin_pct` must be at least the
        contract's `margin_floor_pct`, else `ERR_MARGIN_FLOOR_BREACH` (HTTP 402)."

        Design: Corner/validations/margin_floor_breach_rejected
        """
        ctx = setup_released_tallow_lot()  # spec-compliant PREMIUM TALLOW lot
        contract = create_active_contract(ctx["plant"]["id"], margin_floor_pct=30.0)
        # unit 50, margin 24.0 < floor 30.0.
        order = create_priced_order(contract, quantity_lbs=100, expected_grade="STANDARD")
        assert order["margin_pct"] == pytest.approx(24.0, abs=1e-9)

        res = api.confirm_order(
            order["id"],
            {"allocations": [{"lot_id": ctx["lot"]["id"], "quantity_lbs": 100}]},
            SM,
        )
        validate_error(res, ApiErrorId.ERR_MARGIN_FLOOR_BREACH, expected_status=402)

        order_after = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert order_after["status"] == "PRICED"
        lot = validate_success(api.get_product_lot(ctx["lot"]["id"], ANY), 200)
        assert lot["allocated_lbs"] == 0
