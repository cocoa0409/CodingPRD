"""State-machine transitions and hierarchical side-effect cascades.

Covers Queue A difficulty rules non_linear_state_machine and transitive_cascade, plus
the state-machine and endpoint-cascade corner instances PRD prose uniquely determines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_manager_headers, make_cashier_headers,
    ApiErrorId,
    factories as f,
)
import test_helpers.fixtures as fx

MANAGER = make_manager_headers()
CASHIER = make_cashier_headers("cash1")


class TestTankCycle:
    def test_tank_cycle_active_down_active_pump_cascade(self, api):
        """PRD §3.2: "Taking a tank down cascades to its pumps: every pump drawing from that
        tank whose status is not already `OUT_OF_SERVICE` is forced to `OUT_OF_SERVICE`, so
        none of them can dispense."
        PRD §3.2: "The manager later restores a tank when it is `DOWN`, advancing `status`
        from `DOWN` back to `ACTIVE`"
        PRD §3.2: "Restoring reverses the cascade: every pump on that tank that is currently
        `OUT_OF_SERVICE` is returned to `IDLE`."

        Design: Difficulty/non_linear_state_machine/tank_cycle_active_down_active
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)

        down = validate_success(api.take_down_tank(tank["id"], MANAGER), 200)
        assert down["status"] == "DOWN"
        pump_down = get_success_data(api.get_pump(pump["id"], MANAGER))
        assert pump_down["status"] == "OUT_OF_SERVICE"

        restored = validate_success(api.restore_tank(tank["id"], MANAGER), 200)
        assert restored["status"] == "ACTIVE", "ACTIVE reachable again after the cycle"
        pump_back = get_success_data(api.get_pump(pump["id"], MANAGER))
        assert pump_back["status"] == "IDLE"

    def test_take_down_cascades_all_pumps_out_of_service(self, api):
        """PRD §3.2: "Taking a tank down cascades to its pumps: every pump drawing from that
        tank whose status is not already `OUT_OF_SERVICE` is forced to `OUT_OF_SERVICE`, so
        none of them can dispense."

        Design: Difficulty/transitive_cascade/take_down_pump_out_of_service_cascade_depth2
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        pump1 = fx.create_pump(station["id"], tank["id"], number=1)
        pump2 = fx.create_pump(station["id"], tank["id"], number=2)

        down = validate_success(api.take_down_tank(tank["id"], MANAGER), 200)
        assert down["status"] == "DOWN"
        assert get_success_data(api.get_pump(pump1["id"], MANAGER))["status"] == "OUT_OF_SERVICE"
        assert get_success_data(api.get_pump(pump2["id"], MANAGER))["status"] == "OUT_OF_SERVICE"


class TestShiftParallelAxes:
    def test_close_resolves_both_axes_balanced(self, api):
        """PRD §2.11: "A `Shift` carries a `lifecycle_status` axis (`OPEN` → `COUNTING` →
        `CLOSED`) and a separate `reconcile_status` axis (`PENDING` → one of `BALANCED`,
        `OVER`, or `SHORT`); the reconcile axis stays `PENDING` until close, where the single
        close operation resolves both axes at once."
        PRD §3.5: "the shift is `BALANCED` when the absolute value of the variance is less
        than or equal to the tolerance (a variance exactly at the tolerance is `BALANCED`)"

        Design: Difficulty/non_linear_state_machine/shift_parallel_lifecycle_reconcile_axes
        """
        station = fx.create_station()
        counting = fx.open_shift_counting(station["id"], opening_float_cents=20000)
        assert counting["lifecycle_status"] == "COUNTING"
        assert counting["reconcile_status"] == "PENDING"

        closed = validate_success(api.close_shift(
            counting["id"], f.close_shift_payload(20000, counting["version"]), CASHIER), 200)
        assert closed["lifecycle_status"] == "CLOSED"
        assert closed["reconcile_status"] == "BALANCED"
        assert closed["variance_cents"] == 0


class TestDeliveryPostCascade:
    def test_post_delivery_volume_lowstock_wac_cascade(self, api):
        """PRD §3.3: "the tank's `volume_gallons` increases by the net gallons and its
        `low_stock` is recomputed, the grade's `weighted_avg_cost_cents` is recomputed across
        all posted deliveries to that grade's tanks"
        PRD §3.2: "The `low_stock` flag is true precisely when `volume_gallons` is less than
        or equal to `reorder_point_gallons`, and it is recomputed every time the volume moves."

        Design: Difficulty/transitive_cascade/delivery_post_tank_wac_lowstock_cascade_depth3
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000,
                              reorder_point_gallons=6000)
        delivery = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000,
                                            unit_cost_cents=280)
        fx.post_delivery(delivery["id"], tank["version"])

        tank_after = get_success_data(api.get_tank(tank["id"], MANAGER))
        assert tank_after["volume_gallons"] == 5000, "hop 1: volume += net gallons"
        assert tank_after["low_stock"] is True, "hop 2: 5000 <= 6000 reorder point"
        grade_after = get_success_data(api.get_fuel_grade(grade["id"], MANAGER))
        assert grade_after["weighted_avg_cost_cents"] == 280, "hop 3: WAC of the single posted lot"


class TestCarWashCycle:
    def test_reissue_revives_expired_code(self, api):
        """PRD §3.9: "If the clock has reached or passed `expires_at`, the redeem attempt
        lazily flips the code's `status` to `EXPIRED` and is itself rejected with
        `ERR_CODE_EXPIRED`"
        PRD §3.9: "A `StationManager` may reissue a code that is `EXPIRED` (otherwise
        `ERR_INVALID_STATE`), which sets a fresh `expires_at` of the station's `current_utc`
        plus 30 days, returns `status` to `ISSUED`, and increments the `version` — the cyclic
        `ISSUED → EXPIRED → ISSUED` path."

        Design: Corner/state_machines/reissue_redeem_carwash_cycle_revives_expired
        """
        station = fx.create_station()
        fx.set_clock(station["id"], "2026-06-01T00:00:00Z")
        code = fx.issue_car_wash_code(station["id"], package="BASIC")
        fx.set_clock(station["id"], "2026-08-01T00:00:00Z")
        # Redeem past TTL -> ERR_CODE_EXPIRED and flips to EXPIRED.
        validate_error(api.redeem_car_wash_code(code["id"], CASHIER), ApiErrorId.ERR_CODE_EXPIRED)
        expired = get_success_data(api.get_car_wash_code(code["id"], MANAGER))
        assert expired["status"] == "EXPIRED"
        # Reissue -> ISSUED (cycle).
        reissued = validate_success(api.reissue_car_wash_code(code["id"], MANAGER), 200)
        assert reissued["status"] == "ISSUED"


class TestValidTransitionsAndStates:
    def test_capture_authorized_to_captured_pump_idle(self, api):
        """PRD §3.6: "Capturing payment advances the `payment_status` axis from `AUTHORIZED`
        to `CAPTURED` (rejected with `ERR_INVALID_STATE` if it is not `AUTHORIZED`), returns
        the pump to `IDLE`, and increments the transaction's `version`; the settlement axis is
        untouched."

        Design: Corner/state_machines/capture_fuel_transaction_valid_authorized_to_captured
        """
        s = fx.setup_stocked_station(price_cents=419)
        txn = fx.authorize_fuel(s["station"]["id"], s["pump"]["id"], s["shift"]["id"], gallons=12, tender="CARD")
        captured = validate_success(api.capture_fuel_transaction(txn["id"], CASHIER), 200)
        assert captured["payment_status"] == "CAPTURED"
        assert get_success_data(api.get_pump(s["pump"]["id"], MANAGER))["status"] == "IDLE"

    def test_new_fuel_transaction_initial_states(self, api):
        """PRD §3.6: "The transaction is created with `payment_status` `AUTHORIZED` and
        `settlement_status` `UNSETTLED`, and the pump moves to `DISPENSING`."

        Design: Corner/state_machines/new_fuel_transaction_initial_states
        """
        s = fx.setup_stocked_station(price_cents=419)
        txn = validate_success(api.create_fuel_transaction(
            f.create_fuel_transaction_payload(s["station"]["id"], s["pump"]["id"],
                                              s["shift"]["id"], gallons=12, tender="CARD"),
            CASHIER), 201)
        assert txn["payment_status"] == "AUTHORIZED"
        assert txn["settlement_status"] == "UNSETTLED"
        assert get_success_data(api.get_pump(s["pump"]["id"], MANAGER))["status"] == "DISPENSING"

    def test_redeem_already_redeemed_carwash_invalid_state(self, api):
        """PRD §3.9: "A successful redeem advances `status` from `ISSUED` to `REDEEMED`
        (terminal)"
        PRD §3.9: "A redeem is permitted only when the code is `ISSUED` (otherwise
        `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/redeem_carwash_from_redeemed_returns_invalid_state
        """
        station = fx.create_station()
        fx.set_clock(station["id"], "2026-06-01T00:00:00Z")
        code = fx.issue_car_wash_code(station["id"], package="BASIC")
        validate_success(api.redeem_car_wash_code(code["id"], CASHIER), 200)
        validate_error(api.redeem_car_wash_code(code["id"], CASHIER), ApiErrorId.ERR_INVALID_STATE)

    def test_post_rejected_delivery_invalid_state(self, api):
        """PRD §3.3: "Rejecting a draft delivery is the clean revert: it is permitted only
        from `DRAFT` (otherwise `ERR_INVALID_STATE`), moves the status to `REJECTED`, touches
        no wet stock and no drawer, and increments the delivery's `version`. Both `VOIDED` and
        `REJECTED` are terminal."
        PRD §3.3: "A post is allowed only when the delivery is in `DRAFT` (otherwise
        `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/reject_then_post_rejected_delivery_invalid_state
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        delivery = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        validate_success(api.reject_delivery(delivery["id"], MANAGER), 200)
        validate_error(api.post_delivery(
            delivery["id"], f.post_delivery_payload(tank["version"]), MANAGER),
            ApiErrorId.ERR_INVALID_STATE)
        assert get_success_data(api.get_tank(tank["id"], MANAGER))["volume_gallons"] == 0

    def test_begin_count_twice_invalid_state(self, api):
        """PRD §3.5: "Beginning the count advances `lifecycle_status` from `OPEN` to
        `COUNTING` (rejected with `ERR_INVALID_STATE` if the shift is not `OPEN`) and
        increments the shift's `version`"

        Design: Corner/state_machines/begin_count_twice_idempotency_rejected
        """
        station = fx.create_station()
        counting = fx.open_shift_counting(station["id"])
        validate_error(api.begin_count_shift(counting["id"], CASHIER), ApiErrorId.ERR_INVALID_STATE)
