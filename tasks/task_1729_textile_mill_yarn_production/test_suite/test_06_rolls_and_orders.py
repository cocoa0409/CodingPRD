"""Roll put-up, customer-order allocation, OCC on orders, and cancel cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_roll,
    approve_dye_lot,
    assert_customer_order,
    assert_finished_roll,
    create_customer_order,
    create_dye_lot,
    create_finished_roll,
    create_finished_roll_payload,
    create_customer_order_payload,
    get_success_data,
    setup_approved_dye_lot,
    setup_available_roll,
    setup_dye_lot_shade_pending,
    setup_order_with_allocated_roll,
    setup_yarn_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["spinning_supervisor_headers"]
OPERATOR = TEST_USERS["dye_house_operator_headers"]
REP = TEST_USERS["customer_service_rep_headers"]


class TestRollPutUpGate:
    def test_roll_create_rejected_when_dye_lot_submitted(self, api):
        """PRD §3.6: "Once a dye lot is `APPROVED`, the `DyeHouseOperator` cuts finished rolls from it; attempting put-up against a dye lot in any other state is a referential violation rejected with `ERR_REFERENTIAL_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_finished_roll_create
        """
        ctx = setup_yarn_lot()
        dye_lot = create_dye_lot(
            ctx["yarn_lot"]["id"], ctx["shade_band"]["id"], requested_yards=5000.0
        )
        assert dye_lot["status"] == "SUBMITTED"

        resp = api.create_finished_roll(
            create_finished_roll_payload(
                dye_lot["id"], put_up_yards=1000.0, actual_yards=1000.0
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_VIOLATION)
        _rolls, meta = validate_paginated(
            api.list_finished_rolls(OPERATOR, params={"dye_lot_id": dye_lot["id"]})
        )
        assert meta["total_count"] == 0, "No roll may be persisted by the violation"

    def test_roll_create_rejected_when_dye_lot_shade_pending(self, api):
        """PRD §3.6: "Once a dye lot is `APPROVED`, the `DyeHouseOperator` cuts finished rolls from it; attempting put-up against a dye lot in any other state is a referential violation rejected with `ERR_REFERENTIAL_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_finished_roll_create
        """
        ctx = setup_dye_lot_shade_pending()  # passing grade, awaiting adjudication
        assert ctx["dye_lot"]["status"] == "SHADE_PENDING"

        resp = api.create_finished_roll(
            create_finished_roll_payload(
                ctx["dye_lot"]["id"], put_up_yards=1000.0, actual_yards=1000.0
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_VIOLATION)


class TestRollDerivedFields:
    def test_yardage_deviation_computed(self, api):
        """PRD §3.6: "At creation the roll's `yardage_deviation_pct` is computed as the difference between actual and put-up yards, divided by the put-up yards, expressed as a percentage and rounded to 2 decimal places round half up."

        Design: Corner/entities/finished_roll_yardage_deviation_pct_computed
        """
        ctx = setup_approved_dye_lot()
        roll = create_finished_roll(
            ctx["dye_lot"]["id"], put_up_yards=1000.0, actual_yards=1020.0
        )
        assert_finished_roll(roll)
        assert roll["yardage_deviation_pct"] == pytest.approx(2.0), (
            "(1020 - 1000) / 1000 * 100 = 2.00"
        )


class TestOrderCreation:
    def test_order_default_tolerance(self, api):
        """PRD §3.7: "The `yardage_tolerance_pct` — the acceptable over/under-ship allowance — defaults to 2.0 percent when omitted and must lie between 0 and 10. Orders begin `OPEN`, and their `allocated_yards` starts at zero."

        Design: Corner/entities/customer_order_default_yardage_tolerance
        """
        order = validate_success(
            api.create_customer_order(
                create_customer_order_payload(
                    customer_code="ACME", color_code="NAVY-2B",
                    requested_yards=5000.0,
                ),
                REP,
            ),
            201,
        )
        assert_customer_order(order)
        assert order["yardage_tolerance_pct"] == pytest.approx(2.0)
        assert order["status"] == "OPEN"
        assert order["allocated_yards"] == pytest.approx(0.0)


class TestAllocation:
    def test_roll_allocation_side_effects(self, api):
        """PRD §3.7: "On success the roll moves from `AVAILABLE` to `ALLOCATED`, the roll's `actual_yards` is added to the order's `allocated_yards`, and the order's `version` increments. Status then follows the totals automatically: an order whose `allocated_yards` is above zero is at least `PARTIALLY_ALLOCATED`, and once `allocated_yards` reaches the fill threshold — the `requested_yards` reduced by the `yardage_tolerance_pct` allowance — it becomes `FULLY_ALLOCATED`."

        Design: Corner/endpoints/roll_allocation_increments_order_yards
        """
        ctx = setup_available_roll(put_up_yards=2000.0, actual_yards=2000.0)
        order = create_customer_order(requested_yards=5000.0)
        allocate_roll(order, ctx["roll"]["id"])

        after = validate_success(api.get_customer_order(order["id"], REP))
        assert after["allocated_yards"] == pytest.approx(2000.0)
        assert after["status"] == "PARTIALLY_ALLOCATED", (
            "2,000 of 5,000 requested yards is above zero but below the fill threshold"
        )
        roll = validate_success(api.get_finished_roll(ctx["roll"]["id"], REP))
        assert roll["status"] == "ALLOCATED"
        assert roll["allocated_order_id"] == order["id"]

    def test_order_fully_allocated_within_tolerance(self, api):
        """PRD §3.7: "Status then follows the totals automatically: an order whose `allocated_yards` is above zero is at least `PARTIALLY_ALLOCATED`, and once `allocated_yards` reaches the fill threshold — the `requested_yards` reduced by the `yardage_tolerance_pct` allowance — it becomes `FULLY_ALLOCATED`."

        Design: Corner/endpoints/order_fully_allocated_when_within_tolerance
        """
        ctx = setup_available_roll(put_up_yards=4950.0, actual_yards=4950.0)
        order = create_customer_order(requested_yards=5000.0,
                                      yardage_tolerance_pct=2.0)
        allocate_roll(order, ctx["roll"]["id"])

        after = validate_success(api.get_customer_order(order["id"], REP))
        assert after["allocated_yards"] == pytest.approx(4950.0)
        assert after["status"] == "FULLY_ALLOCATED", (
            "4,950 reaches the fill threshold 5,000 * (1 - 0.02) = 4,900"
        )

    def test_second_quality_roll_allocation_blocked(self, api):
        """PRD §3.7: "Four guards apply: the roll must be `AVAILABLE`; it must be first quality — a roll whose `is_second_quality` is true is rejected with `ERR_SECOND_QUALITY_NOT_ALLOCATABLE` and belongs to the close-out channel; the order must be `OPEN` or `PARTIALLY_ALLOCATED`; and the color must match — the `color_code` on the shade band of the roll's dye lot must equal the order's `color_code`."
        PRD §3.6: "The roll's `is_second_quality` flag is inherited from the parent dye lot's quality test: true when that test graded `SECOND_QUALITY`, marking the roll for the close-out channel rather than normal allocation."

        Design: Corner/endpoints/second_quality_roll_cannot_be_allocated_normally
        """
        ctx = setup_available_roll(second_quality=True, put_up_yards=1000.0,
                                   actual_yards=1000.0)
        assert ctx["roll"]["is_second_quality"] is True, (
            "The roll inherits SECOND_QUALITY from the dye lot's test"
        )
        order = create_customer_order(requested_yards=5000.0)
        current = validate_success(api.get_customer_order(order["id"], REP))
        resp = api.allocate_roll(
            order["id"],
            {"roll_id": ctx["roll"]["id"],
             "expected_order_version": current["version"]},
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_SECOND_QUALITY_NOT_ALLOCATABLE)

    def test_second_quality_roll_close_out(self, api):
        """PRD §3.7: "Second-quality rolls follow their own exit: a roll that is `AVAILABLE` and flagged `is_second_quality` can be routed to `CLOSE_OUT`."

        Design: Corner/endpoints/second_quality_roll_close_out_channel
        """
        ctx = setup_available_roll(second_quality=True, put_up_yards=1000.0,
                                   actual_yards=1000.0)
        assert ctx["roll"]["is_second_quality"] is True
        closed = validate_success(api.close_out_finished_roll(ctx["roll"]["id"], REP))
        assert closed["status"] == "CLOSE_OUT"


class TestCancelCascade:
    def test_cancel_releases_rolls(self, api):
        """PRD §3.7: "Cancelling is permitted while an order is `OPEN` or `PARTIALLY_ALLOCATED`: every roll allocated to the order cascades from `ALLOCATED` back to `AVAILABLE`, the order's `allocated_yards` is zeroed, its `version` increments, and the order lands in `CANCELLED`."

        Design: Difficulty/transitive_cascade/customer_order_cancel_cascade_rolls_released
        """
        ctx = setup_order_with_allocated_roll(
            requested_yards=5000.0, put_up_yards=2000.0, actual_yards=2000.0
        )
        assert ctx["order"]["status"] == "PARTIALLY_ALLOCATED"
        roll_id = ctx["roll"]["id"]

        cancelled = validate_success(
            api.cancel_customer_order(ctx["order"]["id"], REP)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["allocated_yards"] == pytest.approx(0.0)

        roll = validate_success(api.get_finished_roll(roll_id, REP))
        assert roll["status"] == "AVAILABLE", "The allocated roll cascades back"
        assert roll["allocated_order_id"] is None

    def test_cancel_open_order(self, api):
        """PRD §3.7: "Cancelling is permitted while an order is `OPEN` or `PARTIALLY_ALLOCATED`: every roll allocated to the order cascades from `ALLOCATED` back to `AVAILABLE`, the order's `allocated_yards` is zeroed, its `version` increments, and the order lands in `CANCELLED`."

        Design: Difficulty/transitive_cascade/customer_order_cancel_cascade_rolls_released
        """
        order = create_customer_order(requested_yards=5000.0)
        cancelled = validate_success(api.cancel_customer_order(order["id"], REP))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["allocated_yards"] == pytest.approx(0.0)


class TestOrderOptimisticConcurrency:
    def test_allocate_stale_version_rejected(self, api):
        """PRD §2.8: "Allocating a roll into a customer order likewise requires `expected_order_version` equal to the order's current `version`; a mismatch — the order's `allocated_yards` having been mutated by another allocation or release since the client last read it — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_order_allocate
        """
        ctx = setup_approved_dye_lot()
        roll_a = create_finished_roll(ctx["dye_lot"]["id"], 2000.0, 2000.0)
        roll_b = create_finished_roll(ctx["dye_lot"]["id"], 1500.0, 1500.0)
        order = create_customer_order(requested_yards=5000.0)
        observed_version = order["version"]

        allocate_roll(order, roll_a["id"])  # success mutates allocated_yards, bumps version

        resp = api.allocate_roll(
            order["id"],
            {"roll_id": roll_b["id"],
             "expected_order_version": observed_version},
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        roll_b_after = validate_success(api.get_finished_roll(roll_b["id"], REP))
        assert roll_b_after["status"] == "AVAILABLE", (
            "A stale allocation must not take effect"
        )


class TestImmediateConsistency:
    def test_allocation_visible_in_same_response(self, api):
        """PRD §2.6: "When an operation on one resource changes the facts another resource's state depends on, the system reconciles the dependent resource immediately — refreshing its `updated_at` and incrementing its `version` — without waiting for a separate client request."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/allocation_visible_in_same_response
        """
        ctx = setup_available_roll(put_up_yards=2000.0, actual_yards=2000.0)
        order = create_customer_order(requested_yards=5000.0)
        updated = allocate_roll(order, ctx["roll"]["id"])
        assert updated["allocated_yards"] == pytest.approx(2000.0), (
            "The allocation's effect is visible in the same response body"
        )
        assert updated["status"] == "PARTIALLY_ALLOCATED"


class TestDyeApproveCascade:
    def test_dye_approve_cascades_yarn_finished_and_unlocks_rolls(self, api):
        """PRD §3.5: "Approval moves the dye lot to `APPROVED`, advances the yarn lot from `DYEING` to `FINISHED`, increments the yarn lot's `version`, and makes finished-roll put-up permitted for that dye lot."

        Design: Difficulty/transitive_cascade/dye_lot_approve_cascade_yarn_finished_rolls_allowed
        """
        ctx = setup_dye_lot_shade_pending()
        yarn_before = validate_success(
            api.get_yarn_lot(ctx["yarn_lot"]["id"], SUPERVISOR)
        )
        assert yarn_before["status"] == "DYEING"

        approved = approve_dye_lot(ctx["dye_lot"]["id"])
        assert approved["status"] == "APPROVED"

        yarn_after = validate_success(
            api.get_yarn_lot(ctx["yarn_lot"]["id"], SUPERVISOR)
        )
        assert yarn_after["status"] == "FINISHED", (
            "The approval cascades the yarn lot DYEING -> FINISHED"
        )
        assert yarn_after["version"] > yarn_before["version"], (
            "The cascade increments the yarn lot's version"
        )

        roll = create_finished_roll(
            ctx["dye_lot"]["id"], put_up_yards=2000.0, actual_yards=2000.0
        )
        assert roll["status"] == "AVAILABLE", (
            "Finished-roll put-up becomes permitted once the dye lot is APPROVED"
        )

    def test_roll_putup_gated_until_approval(self, api):
        """PRD §3.6: "Once a dye lot is `APPROVED`, the `DyeHouseOperator` cuts finished rolls from it; attempting put-up against a dye lot in any other state is a referential violation rejected with `ERR_REFERENTIAL_VIOLATION`."
        PRD §3.5: "Approval moves the dye lot to `APPROVED`, advances the yarn lot from `DYEING` to `FINISHED`, increments the yarn lot's `version`, and makes finished-roll put-up permitted for that dye lot."

        Design: Difficulty/transitive_cascade/dye_lot_approve_cascade_yarn_finished_rolls_allowed
        """
        ctx = setup_dye_lot_shade_pending()
        blocked = api.create_finished_roll(
            create_finished_roll_payload(
                ctx["dye_lot"]["id"], put_up_yards=1500.0, actual_yards=1500.0
            ),
            OPERATOR,
        )
        validate_error(blocked, ApiErrorId.ERR_REFERENTIAL_VIOLATION)

        approve_dye_lot(ctx["dye_lot"]["id"])
        roll = create_finished_roll(
            ctx["dye_lot"]["id"], put_up_yards=1500.0, actual_yards=1500.0
        )
        assert roll["status"] == "AVAILABLE"
        assert roll["dye_lot_id"] == ctx["dye_lot"]["id"]


class TestAllocationRoundingOrder:
    def test_allocation_total_sum_then_round(self, api):
        """PRD §3.6: "Yardage aggregates follow two pinned orderings, and the mill keeps them distinct on purpose. Put-up totals used in variance reporting round each roll's `put_up_yards` to 2 decimal places first and then sum. Allocation totals that drive customer-order status do the opposite: they sum the raw `actual_yards` of the allocated rolls and round the aggregate to 2 decimal places, round half up."

        Design: Difficulty/combinatorial_formula/roll_yardage_round_per_roll_vs_sum_then_round
        """
        ctx = setup_approved_dye_lot()
        rolls = [
            create_finished_roll(ctx["dye_lot"]["id"], 100.004, 100.004)
            for _ in range(3)
        ]
        order = create_customer_order(requested_yards=5000.0)
        for roll in rolls:
            allocate_roll(order, roll["id"])

        after = validate_success(api.get_customer_order(order["id"], REP))
        # Sum-then-round: 3 * 100.004 = 300.012 -> 300.01.
        # Round-per-roll-first would give 3 * 100.00 = 300.00 — pinned against.
        assert after["allocated_yards"] == pytest.approx(300.01, abs=1e-9), (
            "Allocation totals sum raw actual_yards and round the aggregate"
        )

    def test_allocation_total_sum_then_round_half_cent(self, api):
        """PRD §3.6: "Allocation totals that drive customer-order status do the opposite: they sum the raw `actual_yards` of the allocated rolls and round the aggregate to 2 decimal places, round half up."

        Design: Difficulty/combinatorial_formula/roll_yardage_round_per_roll_vs_sum_then_round
        """
        ctx = setup_approved_dye_lot()
        rolls = [
            create_finished_roll(ctx["dye_lot"]["id"], 100.005, 100.005)
            for _ in range(2)
        ]
        order = create_customer_order(requested_yards=5000.0)
        for roll in rolls:
            allocate_roll(order, roll["id"])

        after = validate_success(api.get_customer_order(order["id"], REP))
        # Sum-then-round: 2 * 100.005 = 200.010 -> 200.01.
        # Round-per-roll-first (half-up) would give 2 * 100.01 = 200.02.
        assert after["allocated_yards"] == pytest.approx(200.01, abs=1e-9)
