"""Order drafting rules, submission gates (PO, backorder, sourcing capability),
and allocation outcomes."""
from test_helpers import (
    ApiErrorId,
    add_line,
    assert_order,
    assert_order_line,
    create_account,
    create_draft_order,
    create_inventory,
    create_product_payload,
    create_stock_product,
    create_warehouse,
    get_success_data,
    make_buyer_headers,
    set_clock,
    setup_submitted_stock_order,
    setup_warehouse_and_account,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
OPS = TEST_USERS["warehouse_ops_headers"]


class TestOrderInitialState:
    def test_new_order_is_draft_and_lines_freeze_after_submit(self, api):
        """PRD section 3.4: "The order is born `DRAFT` with all computed totals
        at zero and `invoice_status` `OPEN`."
        PRD section 3.4: "Order lines are added while the order remains a
        draft"
        PRD section 2.9: "the requested transition must exist from the target
        resource's current state, including terminal-state lockdown
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/order_initial_state_draft_and_line_immutability_after_submit
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="E-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        create_inventory(prod["id"], wh["id"], 100)
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        assert_order(order)
        assert order["status"] == "DRAFT"
        assert order["version"] == 1
        assert order["subtotal_cents"] == 0
        assert order["invoice_status"] == "OPEN"

        add_line(order["id"], acct["id"], prod["id"], 1)
        validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))

        resp = api.add_order_line(order["id"], {"product_id": prod["id"], "qty": 2},
                                  make_buyer_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCaseQty:
    def test_case_uom_line_qty_must_be_case_multiple(self, api):
        """PRD section 3.4: "When the product sells by the case, the quantity
        must be a whole multiple of the product's `case_qty`, or the line is
        rejected with `ERR_CASE_QTY_MISMATCH` (HTTP 422) — this holds both when
        the line is added and when it is later updated."

        Design: Corner/validations/error_case_qty_mismatch_on_case_uom
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="M-1", base_price_cents=100, uom="CASE",
                                    case_qty=5, pallet_qty=50, weight_lbs_per_unit=5)
        create_inventory(prod["id"], wh["id"], 100)
        order = create_draft_order(acct["id"], ship_zone=5)

        bad = api.add_order_line(order["id"], {"product_id": prod["id"], "qty": 7},
                                 make_buyer_headers(acct["id"]))
        validate_error(bad, ApiErrorId.ERR_CASE_QTY_MISMATCH)

        ok = validate_success(api.add_order_line(
            order["id"], {"product_id": prod["id"], "qty": 10},
            make_buyer_headers(acct["id"])), expected_status=201)
        assert_order_line(ok)
        assert ok["qty"] == 10


class TestCustomLineArtwork:
    def test_missing_artwork_and_out_of_band_tolerance_rejected(self, api):
        """PRD section 3.4: "A line on a custom-print product must supply a
        `print_artwork_ref` and an `over_under_tolerance_pct` between 0 and 20
        inclusive; a missing artwork reference or an out-of-range tolerance at
        line-add time is rejected with `ERR_ARTWORK_REQUIRED` (HTTP 422), while
        an out-of-range tolerance on a subsequent line update is a
        malformed-payload `ERR_INVALID_REQUEST`."

        Design: Corner/validations/error_artwork_required_for_custom_line
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="N-1", category="LABELS", base_price_cents=100,
                                    pallet_qty=10, weight_lbs_per_unit=1,
                                    is_custom_print=True, lead_time_days=2)
        order = create_draft_order(acct["id"], ship_zone=5)

        missing = api.add_order_line(
            order["id"],
            {"product_id": prod["id"], "qty": 5, "over_under_tolerance_pct": 10},
            make_buyer_headers(acct["id"]))
        validate_error(missing, ApiErrorId.ERR_ARTWORK_REQUIRED)

        out_of_band = api.add_order_line(
            order["id"],
            {"product_id": prod["id"], "qty": 5, "print_artwork_ref": "art-n",
             "over_under_tolerance_pct": 21},
            make_buyer_headers(acct["id"]))
        validate_error(out_of_band, ApiErrorId.ERR_ARTWORK_REQUIRED)


class TestDuplicatePo:
    def test_po_uniqueness_is_per_account(self, api):
        """PRD section 3.4: "The gate checks fire in the order of §2.9: the
        account must be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), at least one
        line must be `OPEN` (else `ERR_ORDER_EMPTY`, HTTP 422), a `CORPORATE`
        account with `po_required` set must have a `po_number` on the order
        (else `ERR_PO_REQUIRED`, HTTP 422), and that `po_number` must be unique
        among the account's non-draft orders (else `ERR_DUPLICATE_PO`,
        HTTP 409)."
        PRD section 3.4: "A `Buyer` opens an **Order** for their account by
        supplying `account_id`, a destination `ship_zone` from 1 through 8, and
        optionally a `po_number`, which must be unique among the account's
        orders."

        Design: Corner/validations/error_duplicate_po_per_account
        """
        wh = create_warehouse(code="ATL", zone=2)
        a1 = create_account(company_name="Acme One", po_required=True)
        a2 = create_account(company_name="Acme Two", po_required=True)
        prod = create_stock_product(sku="O-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        create_inventory(prod["id"], wh["id"], 500)
        set_clock("2026-08-03T10:00:00Z")

        o1 = create_draft_order(a1["id"], ship_zone=5, po_number="PO-DUP")
        add_line(o1["id"], a1["id"], prod["id"], 1)
        first = validate_success(api.submit_order(o1["id"], make_buyer_headers(a1["id"])))
        assert first["status"] == "STOCK_RESERVED"

        o2 = create_draft_order(a1["id"], ship_zone=5, po_number="PO-DUP")
        add_line(o2["id"], a1["id"], prod["id"], 1)
        dup = api.submit_order(o2["id"], make_buyer_headers(a1["id"]))
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_PO)

        # The same po_number on a different account is accepted.
        o3 = create_draft_order(a2["id"], ship_zone=5, po_number="PO-DUP")
        add_line(o3["id"], a2["id"], prod["id"], 1)
        other = validate_success(api.submit_order(o3["id"], make_buyer_headers(a2["id"])))
        assert other["status"] == "STOCK_RESERVED"


class TestBackorderNotAllowed:
    def test_short_non_backorderable_line_rejects_whole_submit(self, api, warehouse_ops_headers,
                                                               platform_admin_headers):
        """PRD section 3.4: "A short line remains `OPEN` for the split check:
        if the inventory row at its selected warehouse is `backorderable`, the
        line becomes `BACKORDERED`; if not, the entire submit is rejected with
        `ERR_BACKORDER_NOT_ALLOWED` (HTTP 422) and no reservations persist at
        all."

        Design: Corner/validations/error_backorder_not_allowed_rejects_whole_submit
        """
        wh, acct = setup_warehouse_and_account()
        prod_a = create_stock_product(sku="Q-1", base_price_cents=100, pallet_qty=10,
                                      weight_lbs_per_unit=1)
        prod_b = create_stock_product(sku="Q-2", base_price_cents=200, pallet_qty=10,
                                      weight_lbs_per_unit=1)
        inv_a = create_inventory(prod_a["id"], wh["id"], 10)
        create_inventory(prod_b["id"], wh["id"], 2, backorderable=False)
        order = create_draft_order(acct["id"], ship_zone=5)
        add_line(order["id"], acct["id"], prod_a["id"], 4)
        add_line(order["id"], acct["id"], prod_b["id"], 5)

        resp = api.submit_order(order["id"], make_buyer_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_BACKORDER_NOT_ALLOWED)

        inv_a_after = validate_success(api.get_inventory(inv_a["id"], warehouse_ops_headers))
        assert inv_a_after["reserved_qty"] == 0, "no partial reservation may leak"
        order_after = validate_success(api.get_order(order["id"], platform_admin_headers))
        assert order_after["status"] == "DRAFT"


class TestSplitAllocation:
    def test_short_backorderable_line_partially_backorders_then_ships_covered(self, api,
                                                                              platform_admin_headers):
        """PRD section 3.4: "A short line remains `OPEN` for the split check:
        if the inventory row at its selected warehouse is `backorderable`, the
        line becomes `BACKORDERED`; if not, the entire submit is rejected with
        `ERR_BACKORDER_NOT_ALLOWED` (HTTP 422) and no reservations persist at
        all."
        PRD section 3.4: "any custom line puts the order in
        `CUSTOM_PRODUCTION`; otherwise any `BACKORDERED` line puts it in
        `PARTIALLY_BACKORDERED`; otherwise it lands in `STOCK_RESERVED`."
        PRD section 3.7: "From `PARTIALLY_BACKORDERED`, every line that is not
        `BACKORDERED` must be `ALLOCATED`; backordered lines stay
        `BACKORDERED`, hold no reservation, and simply do not ship in this pass
        — the platform ships the covered portion and leaves the remainder for
        a later receipt-driven allocation."

        Design: Corner/state_machines/split_allocation_partially_backordered_when_backorderable
        """
        wh, acct = setup_warehouse_and_account()
        prod_a = create_stock_product(sku="I-1", base_price_cents=100, pallet_qty=10,
                                      weight_lbs_per_unit=1)
        prod_b = create_stock_product(sku="I-2", base_price_cents=200, pallet_qty=10,
                                      weight_lbs_per_unit=1)
        create_inventory(prod_a["id"], wh["id"], 10)
        create_inventory(prod_b["id"], wh["id"], 2, backorderable=True)
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        line_a = add_line(order["id"], acct["id"], prod_a["id"], 4)
        line_b = add_line(order["id"], acct["id"], prod_b["id"], 5)

        submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        assert submitted["status"] == "PARTIALLY_BACKORDERED"

        shipped = validate_success(api.ship_order(order["id"], OPS))
        assert shipped["status"] == "SHIPPED"

        la = validate_success(api.get_order_line(line_a["id"], platform_admin_headers))
        lb = validate_success(api.get_order_line(line_b["id"], platform_admin_headers))
        assert la["status"] == "SHIPPED" and la["shipped_qty"] == 4
        assert lb["status"] == "BACKORDERED" and lb["shipped_qty"] == 0


class TestWarehouseStateGatesAllocation:
    def test_submit_fails_when_sole_stocking_warehouse_inactive(self, api):
        """PRD section 3.3: "Warehouses start `ACTIVE`; deactivation moves one
        to `INACTIVE`, which excludes it from every future sourcing candidate
        set while leaving existing reservations untouched, and activation
        restores it."
        PRD section 3.4: "An empty candidate set rejects the submit with
        `ERR_NO_WAREHOUSE_CAPABLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_by_warehouse_active_state
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="BX-100")
        create_inventory(prod["id"], wh["id"], 100)
        validate_success(api.deactivate_warehouse(wh["id"], ADMIN))
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        add_line(order["id"], acct["id"], prod["id"], 1)

        resp = api.submit_order(order["id"], make_buyer_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_WAREHOUSE_CAPABLE)

    def test_reactivation_restores_sourcing_and_allocation(self, api, platform_admin_headers):
        """PRD section 3.3: "Warehouses start `ACTIVE`; deactivation moves one
        to `INACTIVE`, which excludes it from every future sourcing candidate
        set while leaving existing reservations untouched, and activation
        restores it."
        PRD section 3.4: "A covered line becomes `ALLOCATED` and the chosen
        row's `reserved_qty` increases by the line quantity."

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_by_warehouse_active_state
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="BX-100")
        create_inventory(prod["id"], wh["id"], 100)
        validate_success(api.deactivate_warehouse(wh["id"], ADMIN))
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        line = add_line(order["id"], acct["id"], prod["id"], 1)
        validate_error(api.submit_order(order["id"], make_buyer_headers(acct["id"])),
                       ApiErrorId.ERR_NO_WAREHOUSE_CAPABLE)

        validate_success(api.activate_warehouse(wh["id"], ADMIN))
        submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        assert submitted["status"] == "STOCK_RESERVED"

        line_after = validate_success(api.get_order_line(line["id"], platform_admin_headers))
        assert line_after["status"] == "ALLOCATED"
        assert line_after["allocated_warehouse_id"] == wh["id"]


class TestSuspendedAccountPriority:
    def _setup_suspended_po_account_without_po(self, api):
        wh, acct = setup_warehouse_and_account(po_required=True)
        prod = create_stock_product(sku="BX-100")
        create_inventory(prod["id"], wh["id"], 100)
        validate_success(api.suspend_account(acct["id"], ADMIN))
        order = create_draft_order(acct["id"], ship_zone=5)  # no po_number
        add_line(order["id"], acct["id"], prod["id"], 1)
        return acct, order

    def test_suspended_account_error_outranks_missing_po(self, api):
        """PRD section 2.9: "Only then do the domain rules fire, in this
        relative order: suspended-account gating (`ERR_ACCOUNT_SUSPENDED`),
        empty-order gating (`ERR_ORDER_EMPTY`), purchase-order presence
        (`ERR_PO_REQUIRED`), purchase-order uniqueness (`ERR_DUPLICATE_PO`)"
        PRD section 3.1: "A suspended account is blocked from submitting orders
        and from approving purchase-order reviews — both attempts fail with
        `ERR_ACCOUNT_SUSPENDED` (HTTP 409) — while its existing in-flight
        orders are left untouched."

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_missing_po
        """
        acct, order = self._setup_suspended_po_account_without_po(api)
        resp = api.submit_order(order["id"], make_buyer_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    def test_missing_po_surfaces_once_suspension_clears(self, api):
        """PRD section 2.9: "Only then do the domain rules fire, in this
        relative order: suspended-account gating (`ERR_ACCOUNT_SUSPENDED`),
        empty-order gating (`ERR_ORDER_EMPTY`), purchase-order presence
        (`ERR_PO_REQUIRED`), purchase-order uniqueness (`ERR_DUPLICATE_PO`)"
        PRD section 3.4: "a `CORPORATE` account with `po_required` set must
        have a `po_number` on the order (else `ERR_PO_REQUIRED`, HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_missing_po
        """
        acct, order = self._setup_suspended_po_account_without_po(api)
        validate_error(api.submit_order(order["id"], make_buyer_headers(acct["id"])),
                       ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        validate_success(api.reactivate_account(acct["id"], ADMIN))
        resp = api.submit_order(order["id"], make_buyer_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_PO_REQUIRED)
