"""Production holds and laminate date-code traceability (PRD §3.5, §3.6)."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId,
    assert_lot_conservation,
    setup_in_production, get_laminate_lot,
    TEST_USERS,
)

PLANNER = TEST_USERS["production_planner_headers"]


class TestHoldUnholdCycle:
    def test_hold_unhold_cycle_returns_to_in_production(self, api):
        """PRD §3.6: "A `ProductionPlanner` may place an `IN_PRODUCTION` order
        `ON_HOLD` and later release the hold. Lifting a hold branches on
        material reality: if the order already has `CONSUMED` reservations, it
        returns to `IN_PRODUCTION`".

        Design: Corner/state_machines/hold_unhold_cycle
        """
        ctx = setup_in_production(
            company_name="Hold Co", contact_email="hold@co.example",
            lot_code="LOT-H1",
        )
        assert ctx["order"]["fab_status"] == "IN_PRODUCTION"

        order = get_success_data(api.hold_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "ON_HOLD"

        order = get_success_data(api.unhold_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "IN_PRODUCTION", (
            "the order holds CONSUMED reservations, so unhold must return it to "
            f"IN_PRODUCTION, got {order['fab_status']}"
        )


class TestLaminateLotCodesTraceability:
    def test_laminate_lot_codes_after_production_start(self, api):
        """PRD §3.5: "each order exposes `laminate_lot_codes`: the distinct
        `lot_code` values of the order's `CONSUMED` reservations, sorted in
        ascending order, providing the date-code lineage of the panels that
        actually went into the board." PRD §3.6: "every `RESERVED` reservation
        of the order becomes `CONSUMED`, and for each one the lot's
        `panels_reserved` decreases by the reservation's `panels_allocated`
        while its `panels_consumed` increases by the same amount".

        Design: Corner/entities/laminate_lot_codes_traceability
        """
        ctx = setup_in_production(
            company_name="Trace Co", contact_email="trace@co.example",
            lot_code="LOT-W1",
        )
        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["laminate_lot_codes"] == ["LOT-W1"], (
            f"the consumed lot's code must appear, got {order['laminate_lot_codes']}"
        )

        lot = get_laminate_lot(ctx["lot"]["id"])
        assert_lot_conservation(lot)
        assert lot["panels_consumed"] == 34
        assert lot["panels_reserved"] == 0
        assert lot["panels_available"] == 66
