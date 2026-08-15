"""Panel-array yield mathematics, array release rules, OCC on the order, and
provisional pricing reconciliation (PRD §2.6, §3.3).

Note: the PRD narrates the pricing formula and pins its constants (2,500-cent
impedance line, 2,000-cent minimum lot charge) but never publishes the numeric
per-layer-count or per-finish rates, so no test here asserts an absolute cent
total — only PRD-derivable structure (field presence, the +2,500 delta on lock).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_panel_array,
    create_customer, create_order, create_panel_array, create_and_release_array,
    create_and_lock_stackup, add_spec_line, create_stackup,
    make_cam_operator_headers,
    TEST_USERS,
    G1_BOARDS_PER_PANEL, G1_ARRAY_YIELD, G1_GOOD_BOARDS_PER_PANEL,
    G1_PANELS_REQUIRED, G1_UTILIZATION_PCT, IMPEDANCE_LINE_FEE_CENTS,
)

CAM = TEST_USERS["cam_operator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


class TestArrayYieldFloorCeilInteraction:
    def test_array_yield_main_branch(self, api):
        """PRD §3.3: "The `array_yield` models defect density: it is one minus
        one-hundredth of the board area in square inches, floored so that it
        never drops below one-half, and is kept to four decimal places.
        Multiplying `boards_per_panel` by `array_yield` and rounding down to a
        whole board gives `good_boards_per_panel`; dividing the order's
        `quantity_boards` by that good-board count and rounding up gives
        `panels_required`. The array's `utilization_pct` expresses how much of
        the panel the boards cover: one hundred times `boards_per_panel` times
        the board area, divided by the panel area, rounded half-up to two
        decimal places." (2000x3000 board: yield 0.94 main branch.)

        Design: Difficulty/combinatorial_formula/array_yield_floor_ceil_interaction
        """
        cust = create_customer("Gamma Circuits", "ops@gamma.example", 1_000_000)
        order = create_order(cust["id"])  # 2000x3000, qty 100
        array = create_panel_array(order["id"])  # 2x2 on 5000x7000

        assert_panel_array(array)
        assert array["boards_per_panel"] == G1_BOARDS_PER_PANEL
        assert array["array_yield"] == pytest.approx(G1_ARRAY_YIELD, abs=1e-9), (
            f"main branch: 1 - 0.01*6 = 0.94, got {array['array_yield']}"
        )
        assert array["good_boards_per_panel"] == G1_GOOD_BOARDS_PER_PANEL, (
            "floor(4 * 0.94) = 3"
        )
        assert array["panels_required"] == G1_PANELS_REQUIRED, "ceil(100 / 3) = 34"
        assert array["utilization_pct"] == pytest.approx(G1_UTILIZATION_PCT, abs=1e-9), (
            f"round_half_up(100*4*6/35, 2) = 68.57, got {array['utilization_pct']}"
        )

    def test_array_yield_floor_branch(self, api):
        """PRD §3.3: "The `array_yield` models defect density: it is one minus
        one-hundredth of the board area in square inches, floored so that it
        never drops below one-half, and is kept to four decimal places."
        (10000x8000 board: raw yield 0.20 clamps to the 0.50 floor.)

        Design: Difficulty/combinatorial_formula/array_yield_floor_ceil_interaction
        """
        cust = create_customer("Gamma Floor", "floor@gamma.example", 1_000_000)
        order = create_order(
            cust["id"], board_x_mils=10000, board_y_mils=8000, quantity_boards=4,
        )
        array = create_panel_array(
            order["id"], array_x=2, array_y=2,
            panel_width_mils=22000, panel_height_mils=18000,
        )
        assert_panel_array(array)
        assert array["array_yield"] == pytest.approx(0.50, abs=1e-9), (
            f"raw 0.20 must clamp to the 0.50 floor, got {array['array_yield']}"
        )
        assert array["good_boards_per_panel"] == 2, "floor(4 * 0.50) = 2"
        assert array["panels_required"] == 2, "ceil(4 / 2) = 2"
        assert array["utilization_pct"] == pytest.approx(80.81, abs=1e-9), (
            f"round_half_up(100*4*80/396, 2) = 80.81, got {array['utilization_pct']}"
        )


class TestArrayCreateRules:
    def test_panel_array_ignores_client_supplied_computed_fields(self, api):
        """PRD §3.3: "The array's `boards_per_panel` is exactly `array_x`
        multiplied by `array_y`." — a client-supplied value is not honored.

        Design: Corner/entities/computed_array_fields_input_ignored
        """
        cust = create_customer("Comp Co", "comp@co.example", 1_000_000)
        order = create_order(cust["id"])
        array = create_panel_array(order["id"], extra_payload={"boards_per_panel": 99})
        assert array["boards_per_panel"] == 4, (
            f"server computes 2*2 = 4, ignoring the supplied 99; got {array['boards_per_panel']}"
        )

    def test_array_yield_zero_release_rejected(self, api):
        """PRD §3.3: "an array whose `good_boards_per_panel` computes to zero
        cannot be released at all: such a release is rejected with
        `ERR_ARRAY_YIELD_ZERO`, with the state guard taking precedence over the
        yield guard when both apply."

        Design: Corner/validations/array_yield_zero_rejected
        """
        cust = create_customer("Big Co", "big@co.example", 5000)
        # 12000x10000 mil board = 120 sqin; 1x1 array: yield floor 0.50,
        # good_boards_per_panel = floor(1 * 0.50) = 0.
        order = create_order(
            cust["id"], board_x_mils=12000, board_y_mils=10000, quantity_boards=2,
        )
        array = create_panel_array(
            order["id"], array_x=1, array_y=1,
            panel_width_mils=13000, panel_height_mils=11000,
        )
        assert array["good_boards_per_panel"] == 0

        resp = api.release_panel_array(array["id"], CAM)
        validate_error(resp, ApiErrorId.ERR_ARRAY_YIELD_ZERO)
        array = get_success_data(api.get_panel_array(array["id"], CAM))
        assert array["status"] == "DRAFT"

    def test_occ_panel_array_stale_version_rejected(self, api):
        """PRD §2.6: "Creating a panel array for an order requires
        `expected_fab_order_version` in the request body, carrying the `version`
        of the `FabOrder` the client last observed. ... if the order's current
        `version` has moved beyond the supplied value — because another writer
        created an array, or a stackup lock recomputed pricing, after the
        client's read — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_panel_array_stale_version_rejected
        """
        cust = create_customer("Occ Co", "occ@co.example", 1_000_000)
        order = create_order(cust["id"])
        stale_version = order["version"]

        # First create advances FabOrder.version past the captured value.
        create_panel_array(order["id"])

        resp = api.create_panel_array(
            order["id"],
            {
                "array_x": 3, "array_y": 3,
                "panel_width_mils": 7000, "panel_height_mils": 9000,
                "expected_fab_order_version": stale_version,
            },
            CAM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestProvisionalPricingStructure:
    def test_order_read_shows_computed_fields(self, api):
        """PRD §3.3: "Release supersedes any other `RELEASED` array on the order
        and triggers the provisional pricing run, storing the result on the
        order's `provisional_total_cents`". PRD §3.5: "each order exposes
        `laminate_lot_codes`: the distinct `lot_code` values of the order's
        `CONSUMED` reservations, sorted in ascending order".

        Design: Corner/endpoints/order_read_includes_computed_fields
        """
        cust = create_customer("Read Co", "read@co.example", 1_000_000)
        order = create_order(cust["id"])
        create_and_release_array(order["id"])

        order = get_success_data(api.get_fab_order(order["id"], PLANNER))
        assert isinstance(order["provisional_total_cents"], int), (
            "a released array must leave a non-null provisional price on the order"
        )
        assert order["laminate_lot_codes"] == [], (
            "no reservations have been consumed yet, so the traceability list is empty"
        )

    def test_provisional_price_recomputed_on_stackup_lock(self, api):
        """PRD §3.3: "the **impedance line** is a flat 2,500 cents for each
        impedance spec line on the order's currently `LOCKED` stackup (zero when
        no stackup is locked)". PRD §3.2: "if the order already has a released
        panel array, the order's provisional price is recomputed because the
        billable spec-line count may have changed."

        Design: Corner/cross_cutting_layers/derived_price_recomputed_on_stackup_lock
        """
        cust = create_customer("Recon Co", "recon@co.example", 1_000_000)
        order = create_order(cust["id"])
        create_and_release_array(order["id"])
        price_before = get_success_data(
            api.get_fab_order(order["id"], CAM)
        )["provisional_total_cents"]

        # Lock a stackup carrying exactly one impedance spec line.
        stackup = create_stackup(order["id"], impedance_controlled=True)
        add_spec_line(stackup["id"])
        get_success_data(api.lock_stackup(stackup["id"], TEST_USERS["process_engineer_headers"]))

        price_after = get_success_data(
            api.get_fab_order(order["id"], CAM)
        )["provisional_total_cents"]
        assert price_after == price_before + IMPEDANCE_LINE_FEE_CENTS, (
            f"locking a 1-line stackup must add exactly the 2,500-cent impedance "
            f"line fee: before {price_before}, after {price_after}"
        )
