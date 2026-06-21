"""Compensating invariants (void/reverse), optimistic concurrency, immediate consistency.

Covers Queue A difficulty rule compensating_invariant, plus the OCC, consistency-model,
and error-section corner instances PRD prose uniquely determines.
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


class TestCompensatingInvariants:
    def test_delivery_void_restores_tank_volume(self, api):
        """PRD §3.3: "A successful void moves `POSTED → VOIDED`, decreases the tank's
        `volume_gallons` by the net gallons and recomputes `low_stock`"
        PRD §3.4: "It increases by a delivery's net gallons when that delivery is posted and
        decreases by the same net gallons when the delivery is voided."

        Design: Difficulty/compensating_invariant/delivery_void_restores_tank_volume_invariant
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000,
                              reorder_point_gallons=1500)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        # second posted delivery raises volume to 10000
        tank_now = get_success_data(api.get_tank(tank["id"], MANAGER))
        d2 = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        fx.post_delivery(d2["id"], tank_now["version"])
        assert get_success_data(api.get_tank(tank["id"], MANAGER))["volume_gallons"] == 10000

        voided = validate_success(api.void_delivery(d2["id"], MANAGER), 200)
        assert voided["status"] == "VOIDED"
        # volume_after_void == volume_before_post (5000)
        assert get_success_data(api.get_tank(tank["id"], MANAGER))["volume_gallons"] == 5000

    def test_fuel_reverse_restores_shift_cash(self, api):
        """PRD §3.6: "On reversal the tank's `volume_gallons` increases by the dispensed
        gallons again; if the tender is CASH, the shift's `cash_sales_cents` decreases by
        `total_cents` and `expected_drawer_cents` is recomputed as the compensating inverse;
        if a loyalty account is attached, exactly the points that were accrued are subtracted
        from both `lifetime_points` and `point_balance` and the tier is recomputed;
        `settlement_status` becomes `REVERSED` and `payment_status` becomes `REFUNDED`."
        PRD §3.5: "The shift's `expected_drawer_cents` is always the opening float plus
        accumulated cash sales, minus accumulated cash payouts, minus accumulated cash drops."

        Design: Difficulty/compensating_invariant/fuel_reverse_restores_shift_cash_invariant
        """
        s = fx.setup_stocked_station(price_cents=419, opening_float_cents=20000)
        station_id, pump_id, shift_id = s["station"]["id"], s["pump"]["id"], s["shift"]["id"]
        # BRONZE guest CASH sale: round(12*419)=5028.
        txn = fx.authorize_capture_settle_fuel(station_id, pump_id, shift_id, gallons=12, tender="CASH")
        before = get_success_data(api.get_shift(shift_id, MANAGER))
        assert before["cash_sales_cents"] == 5028
        assert before["expected_drawer_cents"] == 25028

        reversed_txn = validate_success(api.reverse_fuel_transaction(txn["id"], CASHIER), 200)
        assert reversed_txn["settlement_status"] == "REVERSED"
        assert reversed_txn["payment_status"] == "REFUNDED"
        after = get_success_data(api.get_shift(shift_id, MANAGER))
        assert after["cash_sales_cents"] == 0
        assert after["expected_drawer_cents"] == 20000, "== opening float"


class TestOptimisticConcurrency:
    def test_stale_tank_version_on_delivery_post_rejected(self, api):
        """PRD §2.10: "Posting a delivery is guarded against a stale `Tank`. The post request
        must carry `expected_tank_version`, which must equal the target tank's current
        `version`. If another delivery post or a tank take-down has advanced the tank's
        version since the client last read it, the client's capacity and weighted-average-cost
        view is stale, and the post is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_tank_version_on_delivery_post
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        stale_version = tank["version"]
        d1 = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=1000, unit_cost_cents=280)
        fx.post_delivery(d1["id"], stale_version)  # advances tank version
        d2 = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=1000, unit_cost_cents=280)
        # d2 still carries the now-stale version.
        validate_error(api.post_delivery(
            d2["id"], f.post_delivery_payload(stale_version), MANAGER),
            ApiErrorId.ERR_STALE_VERSION)

    def test_stale_shift_version_on_settle_rejected(self, api):
        """PRD §2.10: "Settling a fuel transaction is guarded against a stale `Shift`. The
        settle request must carry `expected_shift_version`, which must equal the referenced
        shift's current `version`. If another settlement or a cash-paid delivery post has
        advanced the shift's version since the client last read it, the client's view of the
        drawer is stale, and the settle is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_shift_version_on_settle
        """
        s = fx.setup_stocked_station(price_cents=419, opening_float_cents=20000)
        station_id, pump_id, shift_id = s["station"]["id"], s["pump"]["id"], s["shift"]["id"]
        shift = get_success_data(api.get_shift(shift_id, MANAGER))
        stale_v = shift["version"]

        t1 = fx.authorize_fuel(station_id, pump_id, shift_id, gallons=12, tender="CASH")
        fx.capture_fuel(t1["id"])
        t2 = fx.authorize_fuel(station_id, pump_id, shift_id, gallons=10, tender="CASH")
        fx.capture_fuel(t2["id"])
        # Settle t1 with the captured stale version (still valid here -> advances shift).
        validate_success(api.settle_fuel_transaction(
            t1["id"], f.settle_fuel_payload(stale_v), CASHIER), 200)
        # Settle t2 with the SAME (now stale) version -> reject.
        validate_error(api.settle_fuel_transaction(
            t2["id"], f.settle_fuel_payload(stale_v), CASHIER),
            ApiErrorId.ERR_STALE_VERSION)


class TestImmediateConsistency:
    def test_settle_immediately_visible_in_shift_drawer(self, api):
        """PRD §3.6: "If the tender is CASH, the shift's `cash_sales_cents` increases by
        `total_cents` and `expected_drawer_cents` is recomputed."
        PRD §3.5: "The shift's `expected_drawer_cents` is always the opening float plus
        accumulated cash sales, minus accumulated cash payouts, minus accumulated cash drops."

        Design: Corner/consistency_model/settle_immediately_visible_in_shift_drawer
        """
        s = fx.setup_stocked_station(price_cents=419, opening_float_cents=20000)
        station_id, pump_id, shift_id = s["station"]["id"], s["pump"]["id"], s["shift"]["id"]
        fx.authorize_capture_settle_fuel(station_id, pump_id, shift_id, gallons=12, tender="CASH")
        # Immediately readable.
        shift = get_success_data(api.get_shift(shift_id, CASHIER))
        assert shift["cash_sales_cents"] == 5028
        assert shift["expected_drawer_cents"] == 25028


class TestUniquenessAndVolumeErrors:
    def test_duplicate_fuel_grade_code_rejected(self, api):
        """PRD §2.9: "A fuel grade's `code` must be unique among the grades of its station; a
        duplicate is rejected with `ERR_DUPLICATE_GRADE`."

        Design: Corner/errors/duplicate_fuel_grade_code_rejected
        """
        station = fx.create_station()
        fx.create_grade(station["id"], code="REGULAR")
        validate_error(api.create_fuel_grade(
            f.create_fuel_grade_payload(station["id"], code="REGULAR", octane=87), MANAGER),
            ApiErrorId.ERR_DUPLICATE_GRADE)

    def test_duplicate_loyalty_phone_rejected(self, api):
        """PRD §2.9: "A loyalty account's `phone` must be unique among the accounts enrolled
        at its station; a duplicate is rejected with `ERR_DUPLICATE_PHONE`."

        Design: Corner/errors/duplicate_loyalty_phone_rejected
        """
        station = fx.create_station()
        fx.enroll_member(station["id"], phone="5550900", name="A")
        validate_error(api.create_loyalty_account(
            f.create_loyalty_account_payload(station["id"], phone="5550900", name="B"), CASHIER),
            ApiErrorId.ERR_DUPLICATE_PHONE)

    def test_negative_volume_void_rejected(self, api):
        """PRD §3.3: "A void is permitted only when the delivery is `POSTED` (otherwise
        `ERR_INVALID_STATE`) and only when removing the gallons would not drive the tank
        negative — the tank's current volume minus the net gallons must be greater than or
        equal to 0, or the void is rejected with `ERR_NEGATIVE_VOLUME`."

        Design: Corner/errors/negative_volume_void_rejected
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        d1 = fx.create_draft_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        fx.post_delivery(d1["id"], tank["version"])  # volume 5000
        shift = fx.open_shift(station["id"])
        # Dispense 4990 via a settled sale -> volume 10.
        fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=4990, tender="CARD")
        assert get_success_data(api.get_tank(tank["id"], MANAGER))["volume_gallons"] == 10
        # Voiding the 5000 delivery would drive volume to -4990 -> reject.
        validate_error(api.void_delivery(d1["id"], MANAGER), ApiErrorId.ERR_NEGATIVE_VOLUME)
