"""Inventory availability, stock conservation across submit/cancel, and the
back-in-stock replenishment signal."""
from test_helpers import (
    OPS,
    ApiErrorId,
    add_line,
    assert_inventory,
    assert_order,
    assert_restock_notification,
    create_draft_order,
    create_inventory,
    create_stock_product,
    create_warehouse,
    create_subscription,
    get_success_data,
    instants_equal,
    make_buyer_headers,
    set_clock,
    setup_submitted_stock_order,
    setup_warehouse_and_account,
    validate_error,
    validate_success,
)

NOTIF_CLOCK = "2026-08-03T10:00:00Z"


def _setup_subscription_below_reorder_point(api):
    """Inventory on_hand 10 / reorder 5 with an ACTIVE subscription, then a
    6-unit order submission driving available below the threshold."""
    wh, acct = setup_warehouse_and_account()
    prod = create_stock_product(sku="TP-100", name="Packing Tape", category="TAPE")
    inv = create_inventory(prod["id"], wh["id"], 10, reorder_point_qty=5)
    notif = create_subscription(acct["id"], prod["id"])
    set_clock(NOTIF_CLOCK)
    order = create_draft_order(acct["id"], ship_zone=5)
    add_line(order["id"], acct["id"], prod["id"], 6)
    submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
    return wh, acct, prod, inv, notif, submitted


class TestAvailableQty:
    def test_available_qty_computed_on_read(self, api, warehouse_ops_headers):
        """PRD section 3.3: "an `available_qty` that is always computed on read
        as the on-hand quantity minus the reserved quantity, never stored
        divergently."
        PRD section 3.4: "A covered line becomes `ALLOCATED` and the chosen
        row's `reserved_qty` increases by the line quantity."

        Design: Corner/entities/entity_inventory_available_qty_computed_not_stored
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="C-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        inv = create_inventory(prod["id"], wh["id"], 10)
        set_clock(NOTIF_CLOCK)
        order = create_draft_order(acct["id"], ship_zone=5)
        add_line(order["id"], acct["id"], prod["id"], 6)
        validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))

        data = validate_success(api.get_inventory(inv["id"], warehouse_ops_headers))
        assert_inventory(data)
        assert data["on_hand_qty"] == 10
        assert data["reserved_qty"] == 6
        assert data["available_qty"] == 4


class TestSubmitCancelStockConservation:
    def test_submit_reserves_without_touching_on_hand(self, api, warehouse_ops_headers):
        """PRD section 3.4: "A covered line becomes `ALLOCATED` and the chosen
        row's `reserved_qty` increases by the line quantity."
        PRD section 3.3: "an `available_qty` that is always computed on read as
        the on-hand quantity minus the reserved quantity, never stored
        divergently."

        Design: Difficulty/compensating_invariant/submit_cancel_stock_units_conserved
        """
        ctx = setup_submitted_stock_order(qty=30, on_hand=100)
        data = validate_success(api.get_inventory(ctx["inventory"]["id"], warehouse_ops_headers))
        assert data["on_hand_qty"] == 100
        assert data["reserved_qty"] == 30
        assert data["available_qty"] == 70

    def test_cancel_restores_exact_pre_submit_stock(self, api, warehouse_ops_headers):
        """PRD section 3.7: "Cancellation releases every allocated line's
        reservation (each affected row's `reserved_qty` drops, the lines become
        `CANCELLED`, the freed stock raises `available_qty` and runs the
        replenishment threshold check), scraps every still-`QUEUED` print job,
        sets `invoice_status` to `VOID`, refreshes the receivable, and
        increments `version`."

        Design: Difficulty/compensating_invariant/submit_cancel_stock_units_conserved
        """
        ctx = setup_submitted_stock_order(qty=30, on_hand=100)
        cancelled = validate_success(api.cancel_order(
            ctx["order"]["id"], {}, ctx["buyer_headers"]))
        assert_order(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["invoice_status"] == "VOID"

        data = validate_success(api.get_inventory(ctx["inventory"]["id"], warehouse_ops_headers))
        assert_inventory(data)
        assert data["on_hand_qty"] == 100, "on_hand must be bit-identical to pre-submit"
        assert data["reserved_qty"] == 0
        assert data["available_qty"] == 100


class TestCancelReleaseFiresNotification:
    def test_cancel_release_flips_subscription_to_notified(self, api, platform_admin_headers):
        """PRD section 3.9: "Whenever a stock movement at any warehouse — a
        receipt, an adjustment, a reservation release on cancellation, or a
        return restock — lifts the row's `available_qty` from strictly below
        its `reorder_point_qty` to at or above it, every `ACTIVE` subscription
        watching that product fires exactly once: the status becomes `NOTIFIED`
        and `notified_at` is stamped from the logical clock."

        Design: Difficulty/transitive_cascade/cancel_release_fires_restock_notification
        """
        wh, acct, prod, inv, notif, submitted = _setup_subscription_below_reorder_point(api)
        validate_success(api.cancel_order(submitted["id"], {}, make_buyer_headers(acct["id"])))

        data = validate_success(api.get_restock_notification(notif["id"], platform_admin_headers))
        assert_restock_notification(data)
        assert data["status"] == "NOTIFIED", "release crossing 4 -> 10 >= 5 must fire"
        assert instants_equal(data["notified_at"], NOTIF_CLOCK)

    def test_cancel_also_voids_invoice_and_clears_receivable(self, api, platform_admin_headers,
                                                             warehouse_ops_headers):
        """PRD section 3.7: "Cancellation releases every allocated line's
        reservation (each affected row's `reserved_qty` drops, the lines become
        `CANCELLED`, the freed stock raises `available_qty` and runs the
        replenishment threshold check), scraps every still-`QUEUED` print job,
        sets `invoice_status` to `VOID`, refreshes the receivable, and
        increments `version`."
        PRD section 3.1: "cancelled and returned orders carry invoices in
        `VOID` status; all are excluded"

        Design: Difficulty/transitive_cascade/cancel_release_fires_restock_notification
        """
        wh, acct, prod, inv, notif, submitted = _setup_subscription_below_reorder_point(api)
        cancelled = validate_success(api.cancel_order(
            submitted["id"], {}, make_buyer_headers(acct["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["invoice_status"] == "VOID"

        inv_data = validate_success(api.get_inventory(inv["id"], warehouse_ops_headers))
        assert inv_data["reserved_qty"] == 0
        assert inv_data["available_qty"] == 10

        acct_data = validate_success(api.get_account(acct["id"], platform_admin_headers))
        assert acct_data["open_receivable_cents"] == 0


class TestReceiveCrossing:
    def test_receive_crossing_fires_active_subscription(self, api, platform_admin_headers,
                                                        warehouse_ops_headers):
        """PRD section 3.3: "Receiving stock adds the supplied `qty` to
        `on_hand_qty` and increments the row's `version`."
        PRD section 3.9: "Whenever a stock movement at any warehouse — a
        receipt, an adjustment, a reservation release on cancellation, or a
        return restock — lifts the row's `available_qty` from strictly below
        its `reorder_point_qty` to at or above it, every `ACTIVE` subscription
        watching that product fires exactly once: the status becomes `NOTIFIED`
        and `notified_at` is stamped from the logical clock."

        Design: Corner/endpoints/endpoint_inventory_receive_crossing_fires_notification
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="V-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        inv = create_inventory(prod["id"], wh["id"], 0, reorder_point_qty=5)
        notif = create_subscription(acct["id"], prod["id"])
        set_clock("2026-08-05T09:00:00Z")

        data = validate_success(api.receive_inventory(inv["id"], {"qty": 7}, warehouse_ops_headers))
        assert_inventory(data)
        assert data["on_hand_qty"] == 7
        assert data["available_qty"] == 7

        n = validate_success(api.get_restock_notification(notif["id"], platform_admin_headers))
        assert n["status"] == "NOTIFIED"
        assert instants_equal(n["notified_at"], "2026-08-05T09:00:00Z")


class TestNotificationSingleFire:
    def test_notified_is_terminal_and_not_overwritten(self, api, platform_admin_headers,
                                                      warehouse_ops_headers):
        """PRD section 3.9: "every `ACTIVE` subscription watching that product
        fires exactly once: the status becomes `NOTIFIED` and `notified_at` is
        stamped from the logical clock."
        PRD section 3.9: "`NOTIFIED` and `CANCELLED` are terminal."
        PRD section 2.9: "the requested transition must exist from the target
        resource's current state, including terminal-state lockdown
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/restock_notification_idempotent_single_fire
        """
        wh, acct, prod, inv, notif, submitted = _setup_subscription_below_reorder_point(api)
        validate_success(api.cancel_order(submitted["id"], {}, make_buyer_headers(acct["id"])))
        set_clock("2026-08-04T10:00:00Z")

        # A second-day receipt must not re-fire or overwrite the first firing.
        validate_success(api.receive_inventory(inv["id"], {"qty": 5}, warehouse_ops_headers))
        n = validate_success(api.get_restock_notification(notif["id"], platform_admin_headers))
        assert n["status"] == "NOTIFIED"
        assert instants_equal(n["notified_at"], NOTIF_CLOCK)

        resp = api.cancel_restock_notification(notif["id"], make_buyer_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDuplicateSubscription:
    def test_duplicate_active_subscription_rejected_then_allowed_after_cancel(self, api):
        """PRD section 3.9: "Only one `ACTIVE` subscription may exist per
        (account, product) pair; a duplicate is rejected with
        `ERR_DUPLICATE_SUBSCRIPTION` (HTTP 409)."
        PRD section 3.9: "A `Buyer` may cancel an `ACTIVE` subscription, but
        only one belonging to their own account; acting on another account's
        subscription is `ERR_UNAUTHORIZED`."

        Design: Corner/validations/error_duplicate_restock_subscription
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="P-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        first = create_subscription(acct["id"], prod["id"])
        assert first["status"] == "ACTIVE"

        dup = api.create_restock_notification(
            {"account_id": acct["id"], "product_id": prod["id"]},
            make_buyer_headers(acct["id"]))
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION)

        validate_success(api.cancel_restock_notification(first["id"], make_buyer_headers(acct["id"])))
        second = validate_success(api.create_restock_notification(
            {"account_id": acct["id"], "product_id": prod["id"]},
            make_buyer_headers(acct["id"])), expected_status=201)
        assert_restock_notification(second)
        assert second["status"] == "ACTIVE"


class TestInventoryAdjustOcc:
    def test_stale_adjust_rejected_fresh_adjust_applies(self, api, warehouse_ops_headers):
        """PRD section 2.7: "The cycle-count adjustment of an inventory row
        likewise requires `expected_inventory_version`; because another writer
        may have just received stock or a reservation may have moved the
        reserved quantity, a mismatch with the row's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412) instead of applying the
        delta to a stale baseline."
        PRD section 3.3: "A cycle-count adjustment adds `delta_qty` — which may
        be negative, provided the resulting on-hand quantity stays at or above
        the current `reserved_qty`, otherwise the adjustment is rejected as
        `ERR_INVALID_REQUEST` — records an optional free-text `reason`, and
        also increments `version`"

        Design: Corner/cross_cutting_layers/occ_inventory_adjust_stale_version_rejected
        """
        wh = create_warehouse(code="ATL", zone=2)
        prod = create_stock_product(sku="AA-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        inv = create_inventory(prod["id"], wh["id"], 10)
        observed_v = inv["version"]

        # An intervening receive advances the row's version.
        validate_success(api.receive_inventory(inv["id"], {"qty": 5}, warehouse_ops_headers))

        stale = api.adjust_inventory(
            inv["id"],
            {"expected_inventory_version": observed_v, "delta_qty": 3, "reason": "cycle count"},
            warehouse_ops_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_inventory(inv["id"], warehouse_ops_headers))
        assert after["on_hand_qty"] == 15, "the rejected adjust must leave on_hand untouched"
        fresh_v = after["version"]

        applied = validate_success(api.adjust_inventory(
            inv["id"],
            {"expected_inventory_version": fresh_v, "delta_qty": 3, "reason": "cycle count"},
            warehouse_ops_headers))
        assert applied["on_hand_qty"] == 18
        assert applied["version"] == fresh_v + 1, "adjust increments version by exactly 1"
