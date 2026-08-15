"""FEFO allocation, the backorder waterfall, cancellation cascades, and credit
exposure (PRD §3.5, §3.6, §2.9)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    PLANNER,
    ApiErrorId,
    assert_lot,
    assert_lot_conservation,
    create_active_clinic,
    create_approved_order,
    create_lot,
    create_order,
    create_product,
    create_shipment,
    create_stocked_product,
    create_submitted_order,
    deliver_shipment,
    dispatch_shipment,
    get_clinic,
    get_lot,
    get_order,
    get_order_line,
    get_success_data,
    make_clinic_buyer_headers,
    order_line_spec,
    set_clock,
    setup_shortage_scenario,
    sole_backorder,
    sole_line,
    submit_order,
    validate_error,
    validate_success,
)


class TestFefoAllocation:
    def test_fefo_selects_earliest_expiry_regardless_of_receipt_order(self, api):
        """PRD §3.5: "Among candidates the earliest `expiry_date` wins; ties
        break by the lot's earlier `created_at`, never by identifier."
        PRD §3.5: "A covered line moves `PENDING` → `ALLOCATED` with its
        `lot_id` set to the covering lot..."

        Design: Corner/calculations/fefo_selects_earliest_expiry_regardless_of_receipt_order
        """
        clinic = create_active_clinic(clinic_name="Clinic FE",
                                      license_number="LIC-FE")
        product = create_product(sku="CONS-FE", product_name="Suture Kit")
        # Received first but expires LATER.
        lot_late = create_lot(product["id"], lot_number="LOT-LATE-EXPIRY",
                              expiry_date="2027-08-31", qty_on_hand=10)
        # Received second but expires EARLIER — FEFO must pick this one.
        lot_early = create_lot(product["id"], lot_number="LOT-EARLY-EXPIRY",
                               expiry_date="2027-06-30", qty_on_hand=10)

        order = create_approved_order(clinic["id"], product["id"], 3)
        line = sole_line(order["id"])
        assert line["status"] == "ALLOCATED"
        assert line["lot_id"] == lot_early["id"], (
            "Expiry date dominates receipt order: the 2027-06-30 lot wins over "
            "the earlier-received 2027-08-31 lot")

        lot_late_after = get_lot(lot_late["id"])
        assert lot_late_after["qty_allocated"] == 0, (
            "The later-expiry lot is untouched")

    def test_fefo_shelf_life_excludes_short_lot_and_boundary_passes(self, api):
        """PRD §3.5: "candidate lots are those of the line's product that are
        `AVAILABLE`, can cover the full `qty_requested` from a single lot —
        allocation is all-or-nothing per line, never split — and whose
        `expiry_date` falls at least thirty days beyond the day the delivery
        window ends, so that product arrives with a minimum shelf life intact."
        PRD §3.5: "A line no single lot can cover moves `PENDING` →
        `BACKORDERED` and mints a BackorderLine whose `qty_open` equals the full
        `qty_requested`."

        Design: Corner/calculations/fefo_shelf_life_excludes_short_lot_and_boundary_passes
        """
        # Clinic A: only lot expires 2026-09-01, i.e. 29 days past the
        # 2026-08-03 window end -> invisible to allocation -> BACKORDERED.
        clinic_a = create_active_clinic(clinic_name="Clinic SL1",
                                        license_number="LIC-SL1",
                                        ship_to_address="38 Shelf St")
        product_a, _la = create_stocked_product(
            lot_qty=10, lot_expiry="2026-09-01",
            product_overrides={"sku": "CONS-SL1", "product_name": "Rapid Test A"})
        order_a = create_approved_order(clinic_a["id"], product_a["id"], 2)
        assert order_a["status"] == "BACKORDERED", (
            "2026-09-01 gives 29 days of shelf life past 2026-08-03 (< 30), so "
            "the lot is ineligible despite stock on hand")
        line_a = sole_line(order_a["id"])
        assert line_a["status"] == "BACKORDERED"
        backorder_a = sole_backorder(line_a["id"])
        assert backorder_a["status"] == "OPEN"
        assert backorder_a["qty_open"] == 2

        # Clinic B: lot expires exactly 2026-09-02, i.e. exactly 30 days past
        # the window end -> eligible ("at least thirty days").
        clinic_b = create_active_clinic(clinic_name="Clinic SL2",
                                        license_number="LIC-SL2",
                                        ship_to_address="39 Shelf St")
        product_b, _lb = create_stocked_product(
            lot_qty=10, lot_expiry="2026-09-02",
            product_overrides={"sku": "CONS-SL2", "product_name": "Rapid Test B"})
        order_b = create_approved_order(clinic_b["id"], product_b["id"], 2)
        assert order_b["status"] == "APPROVED", (
            "2026-09-02 gives exactly 30 days of shelf life — boundary inclusive")


class TestBackorderCycle:
    def test_order_approved_into_shortage_lands_backordered(self, api):
        """PRD §3.5: "when at least one line went to backorder, it moves
        `SUBMITTED` → `BACKORDERED` instead, with identical allocation and
        accrual side effects."
        PRD §3.5: "A line no single lot can cover moves `PENDING` →
        `BACKORDERED` and mints a BackorderLine whose `qty_open` equals the full
        `qty_requested`."

        Design: Difficulty/non_linear_state_machine/order_backorder_cycle_via_refill
        """
        s = setup_shortage_scenario(lot_qty=5, order_qty=5)
        order2 = get_order(s["order2"]["id"])
        assert order2["status"] == "BACKORDERED", (
            "The second order approved into shortage lands BACKORDERED")
        line2 = get_order_line(s["line2"]["id"])
        assert line2["status"] == "BACKORDERED"
        assert line2["lot_id"] is None
        backorder = sole_backorder(line2["id"])
        assert backorder["status"] == "OPEN"
        assert backorder["qty_open"] == 5

    def test_backorder_refill_cycles_order_back_to_approved(self, api):
        """PRD §3.6: "The waterfall wakes whenever new availability appears for
        a product: a lot receipt, and any allocation release..."
        PRD §3.6: "Each fill zeroes the backorder's `qty_open` and moves it to
        `FILLED`, moves its order line from `BACKORDERED` to `ALLOCATED` with
        `lot_id` set and `qty_allocated` restored to the full `qty_requested`..."
        PRD §3.6: "After the fills, each affected order recomputes: when its
        last `OPEN` backorder has been filled or cancelled and every remaining
        line is `ALLOCATED`, the order moves itself from `BACKORDERED` back to
        `APPROVED`."

        Design: Difficulty/non_linear_state_machine/order_backorder_cycle_via_refill
        """
        s = setup_shortage_scenario(lot_qty=5, order_qty=5)
        assert get_order(s["order2"]["id"])["status"] == "BACKORDERED"

        # New stock receipt wakes the waterfall for this product.
        new_lot = create_lot(s["product"]["id"], lot_number="LOT-B2",
                             expiry_date="2027-08-31", qty_on_hand=10)

        order2 = get_order(s["order2"]["id"])
        assert order2["status"] == "APPROVED", (
            "The receipt loops the backordered order back to APPROVED")
        line2 = get_order_line(s["line2"]["id"])
        assert line2["status"] == "ALLOCATED"
        assert line2["lot_id"] == new_lot["id"], (
            "The original lot is depleted; the new lot covers the fill")
        backorder = sole_backorder(line2["id"])
        assert backorder["status"] == "FILLED"
        assert backorder["qty_open"] == 0


class TestCancelReleaseCascade:
    def test_cancel_release_refill_depth3_cascade(self, api):
        """PRD §3.6: "Cancelling an `APPROVED` or `BACKORDERED` order fires the
        full release cascade: every `ALLOCATED` line moves to `CANCELLED` and
        releases its reservation, decrementing the covering lot's
        `qty_allocated` by the line's `qty_requested` — which may flip a
        `DEPLETED` lot back to `AVAILABLE`; the freed availability immediately
        runs the allocation waterfall for that product, which can fill other
        orders' backorders and move those orders from `BACKORDERED` to
        `APPROVED`..."

        Design: Difficulty/transitive_cascade/cancel_release_refill_depth3_cascade
        """
        s = setup_shortage_scenario(lot_qty=5, order_qty=5)
        lot_id = s["lot"]["id"]

        cancelled = validate_success(
            api.cancel_order(s["order1"]["id"], ACCOUNT_MANAGER))
        assert cancelled["status"] == "CANCELLED"

        # Link 2: the freed lot fills the waiting backorder.
        backorder = sole_backorder(s["line2"]["id"])
        assert backorder["status"] == "FILLED"
        assert backorder["qty_open"] == 0
        line2 = get_order_line(s["line2"]["id"])
        assert line2["status"] == "ALLOCATED"
        assert line2["lot_id"] == lot_id, (
            "The fill re-takes the very lot the cancel released")

        # Link 3: the fill — not the cancel itself — recomputes the parent.
        assert get_order(s["order2"]["id"])["status"] == "APPROVED"

    def test_cancel_release_cascade_lot_conservation(self, api):
        """PRD §3.2: "Lot bookkeeping obeys a conservation invariant at all
        times: `qty_on_hand` always equals `qty_allocated` plus `qty_available`,
        where `qty_allocated` counts the units reserved by `ALLOCATED` order
        lines."
        PRD §3.6: "the freed availability immediately runs the allocation
        waterfall for that product, which can fill other orders' backorders..."

        Design: Difficulty/transitive_cascade/cancel_release_refill_depth3_cascade
        """
        s = setup_shortage_scenario(lot_qty=5, order_qty=5)
        lot_id = s["lot"]["id"]

        mid = get_lot(lot_id)
        assert mid["qty_on_hand"] == 5
        assert mid["qty_allocated"] == 5
        assert mid["qty_available"] == 0
        assert mid["status"] == "DEPLETED", (
            "A lot drained to zero availability moves AVAILABLE -> DEPLETED")
        assert_lot_conservation(mid)

        get_success_data(api.cancel_order(s["order1"]["id"], ACCOUNT_MANAGER))

        end = get_lot(lot_id)
        # Released 5 by the cancel, re-taken 5 by the waterfall fill.
        assert end["qty_allocated"] == 5
        assert end["qty_available"] == 0
        assert end["qty_on_hand"] == 5
        assert_lot_conservation(end)


class TestClockSweepExpiryCascade:
    def _setup_allocated_order_with_expiring_lot(self, api):
        clinic = create_active_clinic(clinic_name="Clinic C2",
                                      license_number="LIC-C2")
        product, lot = create_stocked_product(
            lot_qty=4, lot_expiry="2026-09-30",
            product_overrides={"sku": "CONS-C2", "product_name": "Catheter Case",
                               "unit_price_cents": 10000})
        order = create_approved_order(clinic["id"], product["id"], 4)
        assert order["status"] == "APPROVED"
        return clinic, product, lot, order

    def test_clock_sweep_expires_lot_and_releases_allocation(self, api):
        """PRD §3.6: "When a lot's `expiry_date` falls strictly before the new
        current date, the lot moves to `EXPIRED` — terminal — whether it was
        `AVAILABLE` or `DEPLETED` (a depleted lot may still hold allocations)."
        PRD §3.6: "...the lot's own `qty_allocated` is zeroed..."

        Design: Difficulty/transitive_cascade/clock_sweep_expiry_depth3_cascade
        """
        _clinic, _product, lot, order = (
            self._setup_allocated_order_with_expiring_lot(api))

        set_clock("2026-10-01T00:00:00Z")

        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "EXPIRED"
        assert lot_after["qty_allocated"] == 0, "The sweep zeroes the reservation"
        assert lot_after["qty_on_hand"] == 4, (
            "Units never shipped; only the reservation was released")

    def test_clock_sweep_reverts_line_and_order_to_backordered(self, api):
        """PRD §3.6: "Every order line holding that lot in `ALLOCATED` reverts
        to `BACKORDERED` with `qty_allocated` zeroed and `lot_id` cleared, a
        fresh BackorderLine is minted per reverted line with `qty_open` equal to
        the full `qty_requested` and a fresh `allocation_sequence`, the lot's
        own `qty_allocated` is zeroed, and each order left holding at least one
        `BACKORDERED` line moves from `APPROVED` to `BACKORDERED`."

        Design: Difficulty/transitive_cascade/clock_sweep_expiry_depth3_cascade
        """
        _clinic, _product, lot, order = (
            self._setup_allocated_order_with_expiring_lot(api))
        line = sole_line(order["id"])
        assert line["status"] == "ALLOCATED"

        set_clock("2026-10-01T00:00:00Z")

        line_after = get_order_line(line["id"])
        assert line_after["status"] == "BACKORDERED"
        assert line_after["lot_id"] is None
        assert line_after["qty_allocated"] == 0

        backorders = get_success_data(
            api.list_backorder_lines(line["id"], ACCOUNT_MANAGER))
        fresh = [b for b in backorders if b["status"] == "OPEN"]
        assert len(fresh) == 1, "A fresh OPEN backorder is minted per reverted line"
        assert fresh[0]["qty_open"] == 4

        assert get_order(order["id"])["status"] == "BACKORDERED"


class TestLotConservationInvariant:
    def _setup_approved_order(self, api):
        clinic = create_active_clinic(clinic_name="Clinic I1",
                                      license_number="LIC-I1")
        product, lot = create_stocked_product(
            lot_qty=8,
            product_overrides={"sku": "CONS-I1", "product_name": "Bandage Roll",
                               "unit_price_cents": 10000})
        order = create_approved_order(clinic["id"], product["id"], 5)
        assert order["status"] == "APPROVED"
        return clinic, product, lot, order

    def test_lot_conservation_after_approve(self, api):
        """PRD §3.2: "Lot bookkeeping obeys a conservation invariant at all
        times: `qty_on_hand` always equals `qty_allocated` plus `qty_available`,
        where `qty_allocated` counts the units reserved by `ALLOCATED` order
        lines."
        PRD §3.5: "A covered line moves `PENDING` → `ALLOCATED` with its
        `lot_id` set to the covering lot, its `qty_allocated` set to the full
        `qty_requested`, and the lot's `qty_allocated` increased by the same
        amount."

        Design: Difficulty/compensating_invariant/lot_quantity_conservation_invariant
        """
        _clinic, _product, lot, _order = self._setup_approved_order(api)
        mid = get_lot(lot["id"])
        assert_lot(mid)
        assert (mid["qty_on_hand"], mid["qty_allocated"], mid["qty_available"]) == (8, 5, 3)
        assert_lot_conservation(mid)
        assert mid["status"] == "AVAILABLE"

    def test_lot_conservation_after_cancel_returns_to_zero_drift(self, api):
        """PRD §3.6: "Cancelling an `APPROVED` or `BACKORDERED` order fires the
        full release cascade: every `ALLOCATED` line moves to `CANCELLED` and
        releases its reservation, decrementing the covering lot's
        `qty_allocated` by the line's `qty_requested`..."
        PRD §3.2: "Lot bookkeeping obeys a conservation invariant at all
        times: `qty_on_hand` always equals `qty_allocated` plus
        `qty_available`..."

        Design: Difficulty/compensating_invariant/lot_quantity_conservation_invariant
        """
        _clinic, _product, lot, order = self._setup_approved_order(api)
        mid = get_lot(lot["id"])
        assert (mid["qty_allocated"], mid["qty_available"]) == (5, 3)

        get_success_data(api.cancel_order(order["id"], ACCOUNT_MANAGER))

        end = get_lot(lot["id"])
        assert (end["qty_on_hand"], end["qty_allocated"], end["qty_available"]) == (8, 0, 8), (
            "The allocate-then-release pair nets to zero drift")
        assert_lot_conservation(end)
        assert end["status"] == "AVAILABLE"


class TestLotReceiving:
    def test_lot_computed_fields_and_past_expiry_rejected(self, api):
        """PRD §3.2: "A fresh lot starts `AVAILABLE` with `qty_allocated` at
        zero and `qty_available` equal to `qty_on_hand`."
        PRD §3.2: "The expiry date must fall strictly after the current clock
        date at receiving; otherwise the receipt is rejected with
        `ERR_INVALID_LOT_EXPIRY`."
        PRD §2.4: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/entities/lot_computed_fields_and_past_expiry_rejected
        """
        product = create_product(sku="CONS-LF", product_name="Pad Case")

        good = validate_success(api.create_lot(
            {"product_id": product["id"], "lot_number": "LOT-OK",
             "expiry_date": "2027-01-31", "qty_on_hand": 7}, PLANNER), 201)
        assert_lot(good)
        assert good["qty_allocated"] == 0
        assert good["qty_available"] == 7
        assert good["status"] == "AVAILABLE"
        assert_lot_conservation(good)

        # 2026-07-15 is strictly before the startup clock date 2026-08-01.
        resp = api.create_lot(
            {"product_id": product["id"], "lot_number": "LOT-STALE",
             "expiry_date": "2026-07-15", "qty_on_hand": 7}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_LOT_EXPIRY)


class TestBackorderCancel:
    def test_backorder_cancel_terminal_and_order_recompute(self, api):
        """PRD §3.6: "A `ClinicBuyer` (for its own clinic) or an
        `AccountManager` may cancel an individual `OPEN` backorder; cancelling
        one in any other state fails with `ERR_BACKORDER_LINE_INVALID_STATE`."
        PRD §3.6: "Cancellation moves the BackorderLine to `CANCELLED` and its
        parent order line from `BACKORDERED` to `CANCELLED`, then recomputes the
        parent order: ... if every line is now `CANCELLED`, the order itself
        moves to `CANCELLED`, releasing its delivery window and recomputing the
        clinic's credit exposure."
        PRD §3.6: "...carries an `allocation_sequence` — a strictly
        monotonically increasing integer minted at creation, starting from 1..."

        Design: Corner/state_machines/backorder_cancel_terminal_and_order_recompute
        """
        clinic = create_active_clinic(clinic_name="Clinic BC",
                                      license_number="LIC-BC",
                                      minimum_order_value_cents=5000)
        product = create_product(sku="CONS-BC", product_name="Culture Tube")
        # No stock at all: approval backorders the whole line.
        order = create_approved_order(clinic["id"], product["id"], 2)
        assert order["status"] == "BACKORDERED"
        line = sole_line(order["id"])
        backorder = sole_backorder(line["id"])
        assert backorder["status"] == "OPEN"
        assert backorder["allocation_sequence"] == 1, (
            "The first backorder minted on a fresh database carries sequence 1")

        cancelled = validate_success(api.cancel_backorder_line(
            backorder["id"], make_clinic_buyer_headers(clinic["id"])))
        assert cancelled["status"] == "CANCELLED"

        # The only line cancelled -> the order itself cascades to CANCELLED.
        assert get_order(order["id"])["status"] == "CANCELLED"
        assert get_order_line(line["id"])["status"] == "CANCELLED"

        resp = api.cancel_backorder_line(backorder["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_BACKORDER_LINE_INVALID_STATE)


class TestCreditExposure:
    def test_credit_used_aggregation_tracks_order_lifecycle(self, api):
        """PRD §2.9: "Exposure is defined precisely: `credit_used_cents` is the
        sum of `total_cents` over the clinic's orders in `APPROVED`,
        `BACKORDERED`, or `SHIPPED` status. Orders in `DRAFT` or `SUBMITTED`
        have not yet committed funds; a `DELIVERED` order has left the counted
        set (invoicing is out of scope); `REJECTED` and `CANCELLED` orders are
        excluded."
        PRD §3.4: "Finally, `total_cents` is the merchandise net plus the
        equipment surcharge plus the freight fee." (4 x 2500 net + 2500 freight)

        Design: Corner/calculations/credit_used_aggregation_tracks_order_lifecycle
        """
        clinic = create_active_clinic(clinic_name="Clinic CU",
                                      license_number="LIC-CU",
                                      ship_to_address="40 Credit Ct",
                                      free_freight_threshold_cents=75000)
        product, _lot = create_stocked_product(
            product_overrides={"sku": "CONS-CU", "product_name": "Lube Bottle"})
        order = create_submitted_order(clinic["id"], product["id"], 4)
        assert order["total_cents"] == 12500, "10000 net + 2500 freight"
        assert get_clinic_credit(api, clinic["id"]) == 0, (
            "SUBMITTED has not committed funds")

        get_success_data(api.approve_order(order["id"], ACCOUNT_MANAGER))
        assert get_clinic_credit(api, clinic["id"]) == 12500, (
            "APPROVED enters the counted set")

        shipment = create_shipment(order["id"])
        dispatch_shipment(shipment["id"])
        assert get_clinic_credit(api, clinic["id"]) == 12500, (
            "SHIPPED still counts")

        deliver_shipment(shipment["id"])
        assert get_clinic_credit(api, clinic["id"]) == 0, (
            "DELIVERED leaves the counted set")

    def test_credit_limit_exceeded_standalone_and_equality_passes(self, api):
        """PRD §3.5: "Finally the fiscal gate: the clinic's `credit_used_cents`
        plus this order's `total_cents` must remain at or below
        `credit_limit_cents` — equality passes — otherwise
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/credit_limit_exceeded_standalone
        """
        clinic_a = create_active_clinic(clinic_name="Clinic CL1",
                                        license_number="LIC-CL1",
                                        credit_limit_cents=10000,
                                        free_freight_threshold_cents=75000)
        clinic_b = create_active_clinic(clinic_name="Clinic CL2",
                                        license_number="LIC-CL2",
                                        credit_limit_cents=12500,
                                        free_freight_threshold_cents=75000)
        product, _lot = create_stocked_product(
            lot_qty=20,
            product_overrides={"sku": "CONS-CL", "product_name": "Drape Sheet"})
        order_a = create_submitted_order(clinic_a["id"], product["id"], 4)
        order_b = create_submitted_order(clinic_b["id"], product["id"], 4)
        assert order_a["total_cents"] == 12500

        resp = api.approve_order(order_a["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_order(order_a["id"])["status"] == "SUBMITTED"

        approved_b = validate_success(api.approve_order(order_b["id"], ACCOUNT_MANAGER))
        assert approved_b["status"] == "APPROVED", (
            "0 used + 12500 total == 12500 limit: the credit check is inclusive")


def get_clinic_credit(api, clinic_id) -> int:
    """Read the clinic's current credit_used_cents."""
    return get_clinic(clinic_id)["credit_used_cents"]
