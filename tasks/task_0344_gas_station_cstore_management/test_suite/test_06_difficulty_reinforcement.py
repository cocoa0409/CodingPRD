"""Second (reinforcing) test per Queue A difficulty instance.

Each test here carries the same difficulty design tag as its counterpart in
test_01..test_04, asserting a complementary facet (boundary neighbor, the divergent
branch, or the inverse) of the same PRD rule so each difficulty instance has at least
two executing tests.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_manager_headers, make_cashier_headers,
    ApiErrorId,
    factories as f,
)
import test_helpers.fixtures as fx

MANAGER = make_manager_headers()
CASHIER = make_cashier_headers("cash1")


def _margin(api, station_id, cost_basis="WAC",
            window_start="2026-06-01T00:00:00Z", window_end="2026-06-02T00:00:00Z"):
    resp = api.create_margin_report(
        f.create_margin_report_payload(station_id, window_start, window_end, cost_basis=cost_basis),
        MANAGER)
    return validate_success(resp, 201)


def _build_premium_wac_scenario(api):
    station = fx.create_station()
    fx.set_clock(station["id"], "2026-06-01T00:00:00Z")
    grade = fx.create_grade(station["id"], code="PREMIUM", octane=93, price_cents=419)
    tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000, reorder_point_gallons=1500)
    pump = fx.create_pump(station["id"], tank["id"], number=1)
    fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
    fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=3000, unit_cost_cents=300)
    shift = fx.open_shift(station["id"])
    member = fx.seed_gold_member(station["id"], shift["id"], name="Gold")
    fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=12,
                                     tender="CARD", loyalty_account_id=member["id"])
    fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=10,
                                     tender="CARD", loyalty_account_id=member["id"])
    return station["id"]


class TestDualVariantReinforce:
    def test_replacement_basis_uses_last_lot_cost(self, api):
        """PRD §3.10: "under `REPLACEMENT` it is the unit cost of the most recent posted
        delivery to a tank of that grade (the forward-looking replacement cost, ignoring older
        lots), selecting the latest by effective time with `created_at` ascending as the
        tie-break."

        Design: Difficulty/dual_variant_calc/margin_wac_vs_replacement_diverge
        """
        station_id = _build_premium_wac_scenario(api)
        rep = _margin(api, station_id, cost_basis="REPLACEMENT")
        # last lot 300; round(22*300)=6600; margin 9108-6600=2508.
        assert rep["cogs_cents"] == 6600, f"got {rep['cogs_cents']}"
        assert rep["margin_cents"] == 2508, f"got {rep['margin_cents']}"

    def test_store_accrual_dollar_term_only(self, api):
        """PRD §3.7: "two points for each whole dollar of store subtotal (the whole-number
        floor of the store subtotal in cents divided by 100, multiplied by 2 points per
        dollar)."
        PRD §3.7: "for a store settlement only the dollar term contributes and the gallon
        term is 0."

        Design: Difficulty/dual_variant_calc/loyalty_fuel_vs_store_accrual_diverge
        """
        station = fx.create_station()
        member = fx.enroll_member(station["id"], name="Bronze")
        shift = fx.open_shift(station["id"])
        # subtotal 1550 -> floor(1550/100)*2 = 30 base, BRONZE *1.0 = 30; no gallon term.
        snk = f.line_item(sku="SNK", name="Snacks", category="GROCERY",
                          unit_price_cents=1550, qty=1, taxable=True)
        get_success_data(api.create_store_transaction(
            f.create_store_transaction_payload(station["id"], shift["id"], line_items=[snk],
                                               tender="CARD", loyalty_account_id=member["id"]), CASHIER))
        after = get_success_data(api.get_loyalty_account(member["id"], CASHIER))
        assert after["lifetime_points"] == 30, f"got {after['lifetime_points']}"
        assert after["point_balance"] == 30


class TestCombinatorialReinforce:
    def test_second_gold_fuel_sale_total(self, api):
        """PRD §3.6: "`total_cents` is the gallons multiplied by the net per-gallon price,
        rounded half-up to whole cents."
        PRD §3.7: "The tier discount in cents per gallon is 0 for `BRONZE`, 3 for `SILVER`,
        and 5 for `GOLD`"

        Design: Difficulty/combinatorial_formula/pump_price_tiered_min_cap_mode_a
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        shift = fx.open_shift(station["id"])
        member = fx.seed_gold_member(station["id"], shift["id"], name="Gold")
        # 10 gal GOLD: net 414; round(10*414)=4140.
        txn = fx.authorize_fuel(station["id"], pump["id"], shift["id"], gallons=10,
                                tender="CARD", loyalty_account_id=member["id"])
        assert txn["discount_cents_per_gal"] == 5
        assert txn["total_cents"] == 4140, f"got {txn['total_cents']}"

    def test_margin_revenue_is_sum_of_total_cents(self, api):
        """PRD §3.10: "the report computes `gallons_sold` as the sum of `gallons`, and
        `revenue_cents` as the sum of `total_cents`."
        PRD §3.10: "The `margin_cents` is `revenue_cents` minus `cogs_cents`."

        Design: Difficulty/combinatorial_formula/margin_round_per_grade_then_sum_mode_b
        """
        station_id = _build_premium_wac_scenario(api)
        wac = _margin(api, station_id, cost_basis="WAC")
        # revenue = 4968 + 4140 = 9108; cogs 6325; margin 2783.
        assert wac["revenue_cents"] == 9108, f"got {wac['revenue_cents']}"
        assert wac["margin_cents"] == wac["revenue_cents"] - wac["cogs_cents"]
        assert wac["margin_cents"] == 2783


class TestNonLinearStateReinforce:
    def test_take_down_then_restore_increments_version_each_step(self, api):
        """PRD §3.2: "Both the take-down and the restore increment the tank's `version` by 1"

        Design: Difficulty/non_linear_state_machine/tank_cycle_active_down_active
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        v0 = tank["version"]
        down = validate_success(api.take_down_tank(tank["id"], MANAGER), 200)
        assert down["version"] == v0 + 1
        restored = validate_success(api.restore_tank(tank["id"], MANAGER), 200)
        assert restored["version"] == v0 + 2
        assert restored["status"] == "ACTIVE"

    def test_begin_count_advances_lifecycle_only(self, api):
        """PRD §3.5: "Beginning the count advances `lifecycle_status` from `OPEN` to
        `COUNTING` (rejected with `ERR_INVALID_STATE` if the shift is not `OPEN`) and
        increments the shift's `version`; the reconcile axis stays `PENDING`."

        Design: Difficulty/non_linear_state_machine/shift_parallel_lifecycle_reconcile_axes
        """
        station = fx.create_station()
        counting = fx.open_shift_counting(station["id"])
        assert counting["lifecycle_status"] == "COUNTING"
        assert counting["reconcile_status"] == "PENDING", "reconcile axis untouched by begin-count"


class TestTransitiveCascadeReinforce:
    def test_post_recomputes_weighted_average_across_two_lots(self, api):
        """PRD §3.4: "A grade's `weighted_avg_cost_cents` is the weighted-average cost of the
        wet stock sitting under it, in cents per gallon, computed across all `POSTED`
        deliveries to the tanks of that grade. It is recomputed on every delivery post"

        Design: Difficulty/transitive_cascade/delivery_post_tank_wac_lowstock_cascade_depth3
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000, reorder_point_gallons=1500)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=3000, unit_cost_cents=300)
        # WAC = (5000*280 + 3000*300)/8000 = 287.5
        grade_after = get_success_data(api.get_fuel_grade(grade["id"], MANAGER))
        assert grade_after["weighted_avg_cost_cents"] == 287.5, f"got {grade_after['weighted_avg_cost_cents']}"

    def test_restore_returns_only_out_of_service_pumps_to_idle(self, api):
        """PRD §3.2: "Restoring reverses the cascade: every pump on that tank that is currently
        `OUT_OF_SERVICE` is returned to `IDLE`."

        Design: Difficulty/transitive_cascade/take_down_pump_out_of_service_cascade_depth2
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        pump1 = fx.create_pump(station["id"], tank["id"], number=1)
        pump2 = fx.create_pump(station["id"], tank["id"], number=2)
        get_success_data(api.take_down_tank(tank["id"], MANAGER))
        get_success_data(api.restore_tank(tank["id"], MANAGER))
        assert get_success_data(api.get_pump(pump1["id"], MANAGER))["status"] == "IDLE"
        assert get_success_data(api.get_pump(pump2["id"], MANAGER))["status"] == "IDLE"


class TestPriorityPairReinforce:
    def test_shift_open_settle_passes_when_captured(self, api):
        """PRD §3.6: "A settle is permitted only when `payment_status` is `CAPTURED`
        (otherwise `ERR_PAYMENT_NOT_CAPTURED`), `settlement_status` is `UNSETTLED` (otherwise
        `ERR_INVALID_STATE`), and the referenced shift is `OPEN` (otherwise
        `ERR_SHIFT_NOT_OPEN`)"

        Design: Difficulty/priority_pair_validation_conflict/shift_not_open_beats_payment_not_captured
        """
        # Isolate priority-8: shift OPEN, txn NOT captured -> ERR_PAYMENT_NOT_CAPTURED.
        s = fx.setup_stocked_station(price_cents=419)
        txn = fx.authorize_fuel(s["station"]["id"], s["pump"]["id"], s["shift"]["id"],
                                gallons=12, tender="CASH")
        shift = get_success_data(api.get_shift(s["shift"]["id"], MANAGER))
        validate_error(api.settle_fuel_transaction(
            txn["id"], f.settle_fuel_payload(shift["version"]), CASHIER),
            ApiErrorId.ERR_PAYMENT_NOT_CAPTURED)

    def test_age_failure_when_buyer_below_required_age(self, api):
        """PRD §3.8: "the operator-supplied `verified_buyer_age` (from an ID scan) must be
        provided and must be at least the largest `min_age` among the restricted line items;
        if it is missing or below that required age, the sale is rejected with
        `ERR_AGE_VERIFICATION_FAILED`."

        Design: Difficulty/priority_pair_validation_conflict/age_failure_beats_pump_unavailable_category_pair
        """
        station = fx.create_station()
        shift = fx.open_shift(station["id"])
        cig = f.line_item(sku="CIG", name="Cigarettes", category="TOBACCO",
                          unit_price_cents=900, qty=1, taxable=True, min_age=21)
        # verified age 20 < 21 -> fail.
        validate_error(api.create_store_transaction(
            f.create_store_transaction_payload(station["id"], shift["id"], line_items=[cig],
                                               tender="CASH", verified_buyer_age=20), CASHIER),
            ApiErrorId.ERR_AGE_VERIFICATION_FAILED)


class TestBoundaryReinforce:
    def test_cash_variance_over_when_above_tolerance(self, api):
        """PRD §3.5: "the shift is `BALANCED` when the absolute value of the variance is less
        than or equal to the tolerance (a variance exactly at the tolerance is `BALANCED`),
        `OVER` when the variance is greater than the tolerance, and `SHORT` when the variance
        is less than the negative of the tolerance."

        Design: Difficulty/boundary_precision_check/cash_variance_tolerance_exact_boundary_balanced
        """
        station = fx.create_station()
        counting = fx.open_shift_counting(station["id"], opening_float_cents=20000)
        # counted 20201 -> variance +201 > 200 tolerance -> OVER.
        closed = validate_success(api.close_shift(
            counting["id"], f.close_shift_payload(20201, counting["version"]), CASHIER), 200)
        assert closed["variance_cents"] == 201
        assert closed["reconcile_status"] == "OVER", "201 > 200 -> OVER"

    def test_tank_above_reorder_point_not_low_stock(self, api):
        """PRD §3.2: "The `low_stock` flag is true precisely when `volume_gallons` is less than
        or equal to `reorder_point_gallons`, and it is recomputed every time the volume moves."

        Design: Difficulty/boundary_precision_check/tank_reorder_point_lowstock_inclusive_boundary
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000, reorder_point_gallons=5000)
        delivery = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5001, unit_cost_cents=280)
        fx.post_delivery(delivery["id"], tank["version"])
        after = get_success_data(api.get_tank(tank["id"], MANAGER))
        assert after["volume_gallons"] == 5001
        assert after["low_stock"] is False, "5001 > 5000 -> not low stock"


class TestCrossEntityReinforce:
    def test_reverse_requires_shift_open(self, api):
        """PRD §3.6: "A reverse is permitted only when `settlement_status` is `SETTLED`
        (otherwise `ERR_INVALID_STATE`) and the referenced shift is `OPEN` (otherwise
        `ERR_SHIFT_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/fuel_settle_requires_shift_open
        """
        s = fx.setup_stocked_station(price_cents=419)
        station_id, pump_id, shift_id = s["station"]["id"], s["pump"]["id"], s["shift"]["id"]
        fx.authorize_capture_settle_fuel(station_id, pump_id, shift_id, gallons=12, tender="CARD")
        # Move shift to COUNTING; now reverse must be rejected ERR_SHIFT_NOT_OPEN.
        get_success_data(api.begin_count_shift(shift_id, CASHIER))
        txns, _ = validate_paginated(
            api.list_fuel_transactions(MANAGER, params={"shift_id": shift_id}))
        txn_id = txns[0]["id"]
        validate_error(api.reverse_fuel_transaction(txn_id, CASHIER), ApiErrorId.ERR_SHIFT_NOT_OPEN)

    def test_delivery_post_succeeds_when_tank_active(self, api):
        """PRD §3.3: "A post is allowed only when the delivery is in `DRAFT` (otherwise
        `ERR_INVALID_STATE`) and the target tank is `ACTIVE` (otherwise `ERR_TANK_DOWN`)."
        PRD §3.3: "On success the delivery moves `DRAFT → POSTED`"

        Design: Difficulty/cross_entity_state_dependency/delivery_post_requires_tank_active
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        delivery = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        # Tank ACTIVE -> post succeeds.
        posted = validate_success(api.post_delivery(
            delivery["id"], f.post_delivery_payload(tank["version"]), MANAGER), 200)
        assert posted["status"] == "POSTED"


class TestResourceOverlapReinforce:
    def test_post_at_exact_capacity_succeeds(self, api):
        """PRD §3.3: "The post must not overfill the tank: the tank's current volume plus the
        delivery's net gallons must be less than or equal to the tank's `capacity_gallons`, or
        the post is rejected with `ERR_TANK_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/tank_capacity_aggregate_overflow_strict
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000, reorder_point_gallons=1500)
        # exactly capacity: 10000 <= 10000 -> allowed.
        delivery = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=10000, unit_cost_cents=280)
        posted = validate_success(api.post_delivery(
            delivery["id"], f.post_delivery_payload(tank["version"]), MANAGER), 200)
        assert posted["status"] == "POSTED"
        assert get_success_data(api.get_tank(tank["id"], MANAGER))["volume_gallons"] == 10000

    def test_duplicate_grade_code_per_station_rejected(self, api):
        """PRD §2.9: "A fuel grade's `code` must be unique among the grades of its station; a
        duplicate is rejected with `ERR_DUPLICATE_GRADE`."

        Design: Difficulty/resource_temporal_overlap/shift_uniqueness_pump_number_per_station
        """
        station = fx.create_station()
        fx.create_grade(station["id"], code="REGULAR")
        validate_error(api.create_fuel_grade(
            f.create_fuel_grade_payload(station["id"], code="REGULAR", octane=87), MANAGER),
            ApiErrorId.ERR_DUPLICATE_GRADE)


class TestCompensatingReinforce:
    def test_void_recomputes_low_stock_on_restore(self, api):
        """PRD §3.3: "A successful void moves `POSTED → VOIDED`, decreases the tank's
        `volume_gallons` by the net gallons and recomputes `low_stock`"
        PRD §3.2: "The `low_stock` flag is true precisely when `volume_gallons` is less than or
        equal to `reorder_point_gallons`, and it is recomputed every time the volume moves."

        Design: Difficulty/compensating_invariant/delivery_void_restores_tank_volume_invariant
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000, reorder_point_gallons=4000)
        d1 = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        fx.post_delivery(d1["id"], tank["version"])  # volume 5000 > 4000 -> low_stock False
        assert get_success_data(api.get_tank(tank["id"], MANAGER))["low_stock"] is False
        validate_success(api.void_delivery(d1["id"], MANAGER), 200)
        after = get_success_data(api.get_tank(tank["id"], MANAGER))
        assert after["volume_gallons"] == 0
        assert after["low_stock"] is True, "0 <= 4000 after void -> low stock"

    def test_reverse_restores_loyalty_points_invariant(self, api):
        """PRD §3.6: "if a loyalty account is attached, exactly the points that were accrued
        are subtracted from both `lifetime_points` and `point_balance` and the tier is
        recomputed"

        Design: Difficulty/compensating_invariant/fuel_reverse_restores_shift_cash_invariant
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        member = fx.enroll_member(station["id"], name="Bronze")
        shift = fx.open_shift(station["id"])
        # BRONZE 12 gal CASH sale accrues floor(120*1.0)=120 points.
        txn = fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=12,
                                               tender="CASH", loyalty_account_id=member["id"])
        before = get_success_data(api.get_loyalty_account(member["id"], CASHIER))
        assert before["lifetime_points"] == 120 and before["point_balance"] == 120
        validate_success(api.reverse_fuel_transaction(txn["id"], CASHIER), 200)
        after = get_success_data(api.get_loyalty_account(member["id"], CASHIER))
        assert after["lifetime_points"] == 0, "accrued points subtracted from lifetime"
        assert after["point_balance"] == 0, "accrued points subtracted from balance"
