"""Cross-entity state gates, validation precedence, and numeric boundary precision.

Covers Queue A difficulty rules priority_pair_validation_conflict, boundary_precision_check,
and cross_entity_state_dependency, plus the validation-section corner instances PRD prose
uniquely determines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_manager_headers, make_cashier_headers, make_loyalty_member_headers,
    ApiErrorId,
    factories as f,
)
import test_helpers.fixtures as fx

MANAGER = make_manager_headers()
CASHIER = make_cashier_headers("cash1")


class TestValidationPrecedence:
    def test_shift_not_open_beats_payment_not_captured(self, api):
        """PRD §2.8: "(7) the referenced shift being `OPEN` where required
        (`ERR_SHIFT_NOT_OPEN`); (8) the fuel transaction being captured before settlement
        (`ERR_PAYMENT_NOT_CAPTURED`)"
        PRD §2.8: "A higher-priority failure always surfaces first and masks lower-priority
        ones."
        PRD §3.6: "A settle is permitted only when `payment_status` is `CAPTURED` (otherwise
        `ERR_PAYMENT_NOT_CAPTURED`), `settlement_status` is `UNSETTLED` (otherwise
        `ERR_INVALID_STATE`), and the referenced shift is `OPEN` (otherwise
        `ERR_SHIFT_NOT_OPEN`)"

        Design: Difficulty/priority_pair_validation_conflict/shift_not_open_beats_payment_not_captured
        """
        s = fx.setup_stocked_station(price_cents=419)
        station_id, pump_id, shift_id = s["station"]["id"], s["pump"]["id"], s["shift"]["id"]
        # AUTHORIZED (uncaptured) txn.
        txn = fx.authorize_fuel(station_id, pump_id, shift_id, gallons=12, tender="CASH")
        # Advance shift to COUNTING (no longer OPEN).
        counting = get_success_data(api.begin_count_shift(shift_id, CASHIER))
        # Settle: both shift-not-open (prio 7) and not-captured (prio 8) apply; prio 7 wins.
        validate_error(api.settle_fuel_transaction(
            txn["id"], f.settle_fuel_payload(counting["version"]), CASHIER),
            ApiErrorId.ERR_SHIFT_NOT_OPEN)

    def test_age_failure_fires_its_own_category_gate(self, api):
        """PRD §3.8: "When any line item has a `min_age` greater than 0, the operator-supplied
        `verified_buyer_age` (from an ID scan) must be provided and must be at least the
        largest `min_age` among the restricted line items; if it is missing or below that
        required age, the sale is rejected with `ERR_AGE_VERIFICATION_FAILED`."

        Design: Difficulty/priority_pair_validation_conflict/age_failure_beats_pump_unavailable_category_pair
        """
        station = fx.create_station()
        shift = fx.open_shift(station["id"])
        cig = f.line_item(sku="CIG", name="Cigarettes", category="TOBACCO",
                          unit_price_cents=900, qty=1, taxable=True, min_age=21)
        validate_error(api.create_store_transaction(
            f.create_store_transaction_payload(station["id"], shift["id"],
                                               line_items=[cig], tender="CASH"), CASHIER),
            ApiErrorId.ERR_AGE_VERIFICATION_FAILED)


class TestCrossEntityStateGates:
    def test_fuel_settle_requires_shift_open(self, api):
        """PRD §3.6: "A settle is permitted only when `payment_status` is `CAPTURED` (otherwise
        `ERR_PAYMENT_NOT_CAPTURED`), `settlement_status` is `UNSETTLED` (otherwise
        `ERR_INVALID_STATE`), and the referenced shift is `OPEN` (otherwise
        `ERR_SHIFT_NOT_OPEN`)"
        PRD §3.5: "Once a shift is in `COUNTING`, no further transactions may settle into it —
        settlement attempts against a non-open shift are rejected with `ERR_SHIFT_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/fuel_settle_requires_shift_open
        """
        s = fx.setup_stocked_station(price_cents=419)
        station_id, pump_id, shift_id = s["station"]["id"], s["pump"]["id"], s["shift"]["id"]
        txn = fx.authorize_fuel(station_id, pump_id, shift_id, gallons=12, tender="CARD")
        fx.capture_fuel(txn["id"])
        counting = get_success_data(api.begin_count_shift(shift_id, CASHIER))
        validate_error(api.settle_fuel_transaction(
            txn["id"], f.settle_fuel_payload(counting["version"]), CASHIER),
            ApiErrorId.ERR_SHIFT_NOT_OPEN)
        after = get_success_data(api.get_fuel_transaction(txn["id"], MANAGER))
        assert after["settlement_status"] == "UNSETTLED"

    def test_delivery_post_requires_tank_active(self, api):
        """PRD §3.3: "A post is allowed only when the delivery is in `DRAFT` (otherwise
        `ERR_INVALID_STATE`) and the target tank is `ACTIVE` (otherwise `ERR_TANK_DOWN`)."

        Design: Difficulty/cross_entity_state_dependency/delivery_post_requires_tank_active
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        delivery = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        down = get_success_data(api.take_down_tank(tank["id"], MANAGER))
        validate_error(api.post_delivery(
            delivery["id"], f.post_delivery_payload(down["version"]), MANAGER),
            ApiErrorId.ERR_TANK_DOWN)
        assert get_success_data(api.get_delivery(delivery["id"], MANAGER))["status"] == "DRAFT"

    def test_pump_unavailable_when_tank_down(self, api):
        """PRD §3.6: "Authorization is allowed only when the pump's tank is `ACTIVE` and the
        pump itself is not `OUT_OF_SERVICE`; otherwise the authorization is rejected with
        `ERR_PUMP_UNAVAILABLE`."

        Design: Corner/validations/pump_unavailable_when_tank_down
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        get_success_data(api.take_down_tank(tank["id"], MANAGER))
        shift = fx.open_shift(station["id"])
        validate_error(api.create_fuel_transaction(
            f.create_fuel_transaction_payload(station["id"], pump["id"], shift["id"],
                                              gallons=12, tender="CARD"), CASHIER),
            ApiErrorId.ERR_PUMP_UNAVAILABLE)


class TestBoundaryPrecision:
    def test_cash_variance_tolerance_exact_boundary_balanced(self, api):
        """PRD §3.5: "the shift is `BALANCED` when the absolute value of the variance is less
        than or equal to the tolerance (a variance exactly at the tolerance is `BALANCED`),
        `OVER` when the variance is greater than the tolerance, and `SHORT` when the variance
        is less than the negative of the tolerance."
        PRD §3.1: "`cash_variance_tolerance_cents`, the absolute drawer variance in cents
        within which a closing shift is judged `BALANCED`, defaults to 200 (two dollars)."

        Design: Difficulty/boundary_precision_check/cash_variance_tolerance_exact_boundary_balanced
        """
        station = fx.create_station()
        counting = fx.open_shift_counting(station["id"], opening_float_cents=20000)
        # expected drawer 20000; counted 20200 -> variance +200 == tolerance -> BALANCED.
        closed = validate_success(api.close_shift(
            counting["id"], f.close_shift_payload(20200, counting["version"]), CASHIER), 200)
        assert closed["variance_cents"] == 200
        assert closed["reconcile_status"] == "BALANCED", "200 <= 200 inclusive boundary"

    def test_tank_reorder_point_lowstock_inclusive_boundary(self, api):
        """PRD §3.2: "The `low_stock` flag is true precisely when `volume_gallons` is less
        than or equal to `reorder_point_gallons`, and it is recomputed every time the volume
        moves."

        Design: Difficulty/boundary_precision_check/tank_reorder_point_lowstock_inclusive_boundary
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000,
                              reorder_point_gallons=5000)
        delivery = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        fx.post_delivery(delivery["id"], tank["version"])
        after = get_success_data(api.get_tank(tank["id"], MANAGER))
        assert after["volume_gallons"] == 5000
        assert after["low_stock"] is True, "5000 <= 5000 inclusive boundary"


class TestTankCapacityAndUniqueness:
    def test_tank_capacity_aggregate_overflow_rejected(self, api):
        """PRD §3.3: "The post must not overfill the tank: the tank's current volume plus the
        delivery's net gallons must be less than or equal to the tank's `capacity_gallons`, or
        the post is rejected with `ERR_TANK_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/tank_capacity_aggregate_overflow_strict
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000,
                              reorder_point_gallons=1500)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=3000, unit_cost_cents=300)
        # volume now 8000; a third 3000 gal -> 11000 > 10000 capacity -> reject.
        tank_now = get_success_data(api.get_tank(tank["id"], MANAGER))
        d3 = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=3000, unit_cost_cents=290)
        validate_error(api.post_delivery(
            d3["id"], f.post_delivery_payload(tank_now["version"]), MANAGER),
            ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED)
        assert get_success_data(api.get_tank(tank["id"], MANAGER))["volume_gallons"] == 8000

    def test_duplicate_pump_number_per_station_rejected(self, api):
        """PRD §2.9: "A pump's `number` must be unique among the pumps of its station; a
        duplicate is rejected with `ERR_DUPLICATE_PUMP`."

        Design: Difficulty/resource_temporal_overlap/shift_uniqueness_pump_number_per_station
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        fx.create_pump(station["id"], tank["id"], number=1)
        validate_error(api.create_pump(
            f.create_pump_payload(station["id"], tank["id"], number=1), MANAGER),
            ApiErrorId.ERR_DUPLICATE_PUMP)


class TestOtherValidations:
    def test_age_verification_pass_when_buyer_old_enough(self, api):
        """PRD §3.8: "When any line item has a `min_age` greater than 0, the operator-supplied
        `verified_buyer_age` (from an ID scan) must be provided and must be at least the
        largest `min_age` among the restricted line items"
        PRD §3.8: "The `total_cents` is the subtotal plus the tax."

        Design: Corner/validations/age_verification_pass_when_buyer_old_enough
        """
        station = fx.create_station()
        shift = fx.open_shift(station["id"])
        cig = f.line_item(sku="CIG", name="Cigarettes", category="TOBACCO",
                          unit_price_cents=900, qty=1, taxable=True, min_age=21)
        st = validate_success(api.create_store_transaction(
            f.create_store_transaction_payload(station["id"], shift["id"], line_items=[cig],
                                               tender="CASH", verified_buyer_age=21), CASHIER), 201)
        # subtotal 900; tax round(900*825/10000)=round(74.25)=74; total 974
        assert st["total_cents"] == 974, f"got {st['total_cents']}"

    def test_list_limit_out_of_range_returns_validation(self, api):
        """PRD §2.3: "A list request whose `limit` is below 1 or above 100, or whose `offset`
        is negative, is rejected with `ERR_VALIDATION`."

        Design: Corner/validations/list_limit_out_of_range_returns_validation
        """
        station = fx.create_station()
        validate_error(api.list_fuel_grades(MANAGER, params={"station_id": station["id"], "limit": 500}),
                       ApiErrorId.ERR_VALIDATION)

    def test_insufficient_points_redemption_rejected(self, api):
        """PRD §3.7: "The requested `points` to redeem must not exceed the account's
        `point_balance`, or the redemption is rejected with `ERR_INSUFFICIENT_POINTS`."

        Design: Corner/validations/insufficient_points_redemption_rejected
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        shift = fx.open_shift(station["id"])
        member = fx.seed_gold_member(station["id"], shift["id"], name="Gold")
        # Drain the 5000 seeded points so only fuel accrual remains as balance.
        get_success_data(api.redeem_points(member["id"], f.redeem_points_payload(5000), CASHIER))
        # GOLD 12gal fuel accrual: floor(120*1.5) = 180 balance.
        fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=12,
                                         tender="CARD", loyalty_account_id=member["id"])
        after = get_success_data(api.get_loyalty_account(member["id"], CASHIER))
        assert after["point_balance"] == 180, f"got {after['point_balance']}"
        # Redeem 200 > 180 -> reject.
        validate_error(api.redeem_points(
            member["id"], f.redeem_points_payload(200), make_loyalty_member_headers(member["id"])),
            ApiErrorId.ERR_INSUFFICIENT_POINTS)
