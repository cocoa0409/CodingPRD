"""Validation precedence pairs, numeric boundary precision, and the two delivery-run
overlap semantics (buffered driver, half-open bay).

Queue A: priority_pair_validation_conflict, boundary_precision_check,
resource_temporal_overlap.
"""
from test_helpers import (
    validate_error, get_success_data, api_client,
    setup_open_wholesale_order_with_line, setup_allocated_wholesale_order,
    setup_allocated_hotshot_order, allocate, ship, current_version,
    create_price_tier, create_part, create_stocked_part, create_account,
    create_open_order, add_line, create_driver, create_bay, schedule_run,
    allocate_payload, create_order_line_payload, create_account_payload,
    create_part_payload, create_sales_order_payload,
    ApiErrorId, TEST_USERS,
)
from test_helpers import validate_paginated

REP = TEST_USERS["wholesale_rep_headers"]
INV = TEST_USERS["inventory_manager_headers"]


def _reorders_for_part(part_id):
    data, _ = validate_paginated(api_client.list_reorder_requests(REP, params={"part_id": part_id}))
    return data


def _runs_for_driver(driver_id):
    data, _ = validate_paginated(api_client.list_delivery_runs(REP, params={"driver_id": driver_id}))
    return data


def _runs_for_bay(bay_id):
    data, _ = validate_paginated(api_client.list_delivery_runs(REP, params={"bay_id": bay_id}))
    return data


# ─── priority_pair_validation_conflict: ppvc_state_beats_fiscal_on_invoice ────

class TestStateBeatsFiscalOnInvoice:
    """An allocated-not-shipped order over its credit limit returns the state error."""

    def test_not_shipped_reported_over_credit_limit(self, api):
        """PRD §3.5: "Invoicing requires the order's fulfillment_status to be SHIPPED
        (otherwise ERR_NOT_SHIPPED) and its settlement_status to be UNBILLED
        (otherwise ERR_ALREADY_INVOICED). For a wholesale buyer, the credit check of
        §2.10 applies".
        PRD §2.8: "an operation's own checks are evaluated in the order their
        narratives describe".

        An ALLOCATED (not shipped) order whose total also exceeds a tiny credit
        limit returns the narrative-first ERR_NOT_SHIPPED, not the later credit error.

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_invoice
        """
        tier = create_price_tier()
        part = create_stocked_part(qty=5, description="Alternator", list_price_cents=8000,
                                   cost_cents=3000, core_charge_cents=0, is_rebuildable=False,
                                   warranty_days=30, stockable=True, reorder_point=0, reorder_qty=0)
        acct = create_account(tier["id"], name="WS Tight", account_type="WHOLESALE",
                              credit_limit_cents=100)
        order = create_open_order(acct["id"], channel="WHOLESALE")
        add_line(order["id"], part["id"], 1)
        allocate(order["id"])  # now ALLOCATED, not SHIPPED
        resp = api.invoice_order(order["id"], REP)
        validate_error(resp, ApiErrorId.ERR_NOT_SHIPPED.value)

    def test_settlement_unchanged_after_state_rejection(self, api):
        """PRD §3.5: "Invoicing requires the order's fulfillment_status to be SHIPPED
        (otherwise ERR_NOT_SHIPPED) and its settlement_status to be UNBILLED
        (otherwise ERR_ALREADY_INVOICED). For a wholesale buyer, the credit check of
        §2.10 applies".
        PRD §2.8: "an operation's own checks are evaluated in the order their
        narratives describe".

        Because the narrative-first ERR_NOT_SHIPPED fires, the order's
        settlement_status stays UNBILLED (the later credit check never charges A/R).

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_invoice
        """
        tier = create_price_tier()
        part = create_stocked_part(qty=5, description="Alternator", list_price_cents=8000,
                                   cost_cents=3000, core_charge_cents=0, is_rebuildable=False,
                                   warranty_days=30, stockable=True, reorder_point=0, reorder_qty=0)
        acct = create_account(tier["id"], name="WS Tight2", account_type="WHOLESALE",
                              credit_limit_cents=100)
        order = create_open_order(acct["id"], channel="WHOLESALE")
        add_line(order["id"], part["id"], 1)
        allocate(order["id"])
        api.invoice_order(order["id"], REP)
        after = get_success_data(api_client.get_sales_order(order["id"], REP))
        assert after["settlement_status"] == "UNBILLED", "rejected invoice must not advance settlement"
        acct_after = get_success_data(api_client.get_account(acct["id"], REP))
        assert acct_after["ar_balance_cents"] == 0, "no A/R charged when the state check pre-empts"


# ─── priority_pair_validation_conflict: ppvc_state_beats_referential_on_order_line_create ─

class TestStateBeatsReferentialOnLineCreate:
    """Adding a discontinued part to an ALLOCATED order returns the open-state error."""

    def test_order_not_open_reported_over_part_discontinued(self, api):
        """PRD §3.3: "Adding a line requires the parent order's fulfillment_status to
        be OPEN; adding a line to any other state is rejected with ERR_ORDER_NOT_OPEN."
        PRD §3.3: "The referenced part must be ACTIVE; attempting to line up a
        discontinued part is rejected with ERR_PART_DISCONTINUED."
        PRD §2.8: "an operation's own checks are evaluated in the order their
        narratives describe".

        A line create against an ALLOCATED order naming a DISCONTINUED part returns
        the narrative-first ERR_ORDER_NOT_OPEN.

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_referential_on_order_line_create
        """
        tier = create_price_tier()
        stock_part = create_stocked_part(qty=5, description="Stock part", list_price_cents=5000,
                                         cost_cents=2000, stockable=True,
                                         reorder_point=0, reorder_qty=0)
        disc_part = create_part(description="Discontinued part", list_price_cents=4000,
                                cost_cents=1500, stockable=True, reorder_point=0, reorder_qty=0)
        get_success_data(api_client.discontinue_part(disc_part["id"], INV))
        acct = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
        order = create_open_order(acct["id"], channel="WHOLESALE")
        add_line(order["id"], stock_part["id"], 1)
        allocate(order["id"])  # order no longer OPEN
        resp = api.create_order_line(
            create_order_line_payload(order["id"], disc_part["id"], 1), REP)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_OPEN.value)

    def test_no_line_added_when_state_check_preempts(self, api):
        """PRD §3.3: "Adding a line requires the parent order's fulfillment_status to
        be OPEN; adding a line to any other state is rejected with ERR_ORDER_NOT_OPEN."
        PRD §2.8: "an operation's own checks are evaluated in the order their
        narratives describe".

        The rejected line create adds nothing to the ALLOCATED order; it still has
        exactly its one original line.

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_referential_on_order_line_create
        """
        tier = create_price_tier()
        stock_part = create_stocked_part(qty=5, description="Stock part", list_price_cents=5000,
                                         cost_cents=2000, stockable=True,
                                         reorder_point=0, reorder_qty=0)
        disc_part = create_part(description="Discontinued part", list_price_cents=4000,
                                cost_cents=1500, stockable=True, reorder_point=0, reorder_qty=0)
        get_success_data(api_client.discontinue_part(disc_part["id"], INV))
        acct = create_account(tier["id"], name="WS Shop2", account_type="WHOLESALE")
        order = create_open_order(acct["id"], channel="WHOLESALE")
        add_line(order["id"], stock_part["id"], 1)
        allocate(order["id"])
        api.create_order_line(create_order_line_payload(order["id"], disc_part["id"], 1), REP)
        data, _ = validate_paginated(
            api_client.list_order_lines(REP, params={"order_id": order["id"]}))
        assert len(data) == 1, f"rejected line must not be added; expected 1 line, got {len(data)}"


# ─── boundary_precision_check: bpc_reorder_point_at_or_below_boundary ──────────

class TestReorderPointBoundary:
    """available == reorder_point triggers; available == reorder_point + 1 does not."""

    def test_ship_to_exact_reorder_point_triggers(self, api):
        """PRD §2.6: "The threshold is inclusive: an available quantity equal to the
        reorder point triggers a suggestion, while an available quantity of one unit
        above the reorder point does not."

        Pads on_hand 5, reorder_point 2; ship qty 3 -> available exactly 2 -> one
        SUGGESTED reorder.

        Design: Difficulty/boundary_precision_check/bpc_reorder_point_at_or_below_boundary
        """
        part, account, order, line = setup_allocated_wholesale_order(
            qty=3, stock_qty=5,
            part_overrides=dict(description="Brake pads", list_price_cents=6000, cost_cents=2500,
                                core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                                stockable=True, reorder_point=2, reorder_qty=4))
        ship(order["id"])
        final = get_success_data(api_client.get_part(part["id"], REP))
        assert final["available_qty"] == 2
        suggested = [r for r in _reorders_for_part(part["id"]) if r["status"] == "SUGGESTED"]
        assert len(suggested) == 1, "available == reorder_point must trigger a suggestion"

    def test_ship_to_one_above_reorder_point_does_not_trigger(self, api):
        """PRD §2.6: "The threshold is inclusive: an available quantity equal to the
        reorder point triggers a suggestion, while an available quantity of one unit
        above the reorder point does not."

        Pads on_hand 5, reorder_point 2; ship qty 2 -> available 3 (reorder_point+1)
        -> no reorder suggested.

        Design: Difficulty/boundary_precision_check/bpc_reorder_point_at_or_below_boundary
        """
        part, account, order, line = setup_allocated_wholesale_order(
            qty=2, stock_qty=5,
            part_overrides=dict(description="Brake pads", list_price_cents=6000, cost_cents=2500,
                                core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                                stockable=True, reorder_point=2, reorder_qty=4))
        ship(order["id"])
        final = get_success_data(api_client.get_part(part["id"], REP))
        assert final["available_qty"] == 3
        suggested = [r for r in _reorders_for_part(part["id"]) if r["status"] == "SUGGESTED"]
        assert len(suggested) == 0, "available == reorder_point + 1 must NOT trigger a suggestion"


# ─── boundary_precision_check: bpc_credit_limit_at_limit_passes_one_over_fails ─

class TestCreditLimitBoundary:
    """order_total == credit_limit passes; credit_limit one under fails."""

    def _shipped_clutch_order(self, credit_limit):
        tier = create_price_tier(name="T20", discount_pct=0.20, core_discount_pct=0.00,
                                 min_margin_pct=0.10)
        part = create_stocked_part(qty=10, description="Clutch", list_price_cents=5000,
                                   cost_cents=2000, core_charge_cents=0, is_rebuildable=False,
                                   warranty_days=30, stockable=True, reorder_point=0, reorder_qty=0)
        acct = create_account(tier["id"], name="WS Credit", account_type="WHOLESALE",
                              credit_limit_cents=credit_limit)
        order = create_open_order(acct["id"], channel="WHOLESALE")
        add_line(order["id"], part["id"], 1)
        allocate(order["id"])
        ship(order["id"])
        return acct, order

    def test_invoice_succeeds_at_exact_limit(self, api):
        """PRD §2.10: "an order may be invoiced only if the account's current
        ar_balance_cents plus the order's order_total_cents would remain at or below
        the account's credit_limit_cents; otherwise the invoice is rejected with
        ERR_CREDIT_LIMIT_EXCEEDED (HTTP 402)."

        Clutch order_total 4000 with credit_limit exactly 4000: invoice succeeds
        (<= boundary passes) and A/R == 4000.

        Design: Difficulty/boundary_precision_check/bpc_credit_limit_at_limit_passes_one_over_fails
        """
        acct, order = self._shipped_clutch_order(credit_limit=4000)
        invoiced = get_success_data(api_client.invoice_order(order["id"], REP))
        assert invoiced["order_total_cents"] == 4000
        assert invoiced["settlement_status"] == "INVOICED"
        acct_after = get_success_data(api_client.get_account(acct["id"], REP))
        assert acct_after["ar_balance_cents"] == 4000

    def test_invoice_rejected_one_under_limit(self, api):
        """PRD §2.10: "an order may be invoiced only if the account's current
        ar_balance_cents plus the order's order_total_cents would remain at or below
        the account's credit_limit_cents; otherwise the invoice is rejected with
        ERR_CREDIT_LIMIT_EXCEEDED (HTTP 402)."

        Same 4000 order_total with credit_limit 3999: invoice rejected
        ERR_CREDIT_LIMIT_EXCEEDED (HTTP 402).

        Design: Difficulty/boundary_precision_check/bpc_credit_limit_at_limit_passes_one_over_fails
        """
        acct, order = self._shipped_clutch_order(credit_limit=3999)
        resp = api.invoice_order(order["id"], REP)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# ─── resource_temporal_overlap: rto_driver_buffered_window_conflict ───────────

class TestDriverBufferedConflict:
    """Driver windows are buffered by turnaround_min; adjacency within the buffer collides."""

    def test_adjacent_within_buffer_conflicts(self, api):
        """PRD §2.11: "the runs must be separated by a gap of at least the turnaround
        minutes; any closer - including touching or near-touching within the buffer -
        is a conflict and is rejected with ERR_DRIVER_WINDOW_CONFLICT."

        Driver turnaround 30; existing run [60,120); a second run [120,180) on the
        same driver has a 0-minute gap (< 30) and is rejected.

        Design: Difficulty/resource_temporal_overlap/rto_driver_buffered_window_conflict
        """
        part1, acct1, ord1, line1 = setup_allocated_hotshot_order(qty=1, special=True)
        driver = create_driver(name="Dave", turnaround_min=30)
        bay_a = create_bay()
        bay_b = create_bay()
        schedule_run(ord1["id"], driver["id"], bay_a["id"], 60, 120)
        # second allocated order on same driver, different bay
        order2 = create_open_order(acct1["id"], channel="WHOLESALE", hotshot_requested=True)
        add_line(order2["id"], part1["id"], 1)
        allocate(order2["id"])
        resp = api.create_delivery_run(
            {"order_id": order2["id"], "driver_id": driver["id"], "bay_id": bay_b["id"],
             "window_start_min": 120, "window_end_min": 180}, REP)
        validate_error(resp, ApiErrorId.ERR_DRIVER_WINDOW_CONFLICT.value)

    def test_only_first_run_persists_after_conflict(self, api):
        """PRD §2.11: "the runs must be separated by a gap of at least the turnaround
        minutes; any closer - including touching or near-touching within the buffer -
        is a conflict and is rejected with ERR_DRIVER_WINDOW_CONFLICT."

        The rejected second run is not created, so the driver still has exactly one
        non-cancelled run.

        Design: Difficulty/resource_temporal_overlap/rto_driver_buffered_window_conflict
        """
        part1, acct1, ord1, line1 = setup_allocated_hotshot_order(qty=1, special=True)
        driver = create_driver(name="Dave2", turnaround_min=30)
        bay_a = create_bay()
        bay_b = create_bay()
        schedule_run(ord1["id"], driver["id"], bay_a["id"], 60, 120)
        order2 = create_open_order(acct1["id"], channel="WHOLESALE", hotshot_requested=True)
        add_line(order2["id"], part1["id"], 1)
        allocate(order2["id"])
        api.create_delivery_run(
            {"order_id": order2["id"], "driver_id": driver["id"], "bay_id": bay_b["id"],
             "window_start_min": 120, "window_end_min": 180}, REP)
        runs = [r for r in _runs_for_driver(driver["id"]) if r["status"] != "CANCELLED"]
        assert len(runs) == 1, f"driver should retain exactly one run, got {len(runs)}"


# ─── resource_temporal_overlap: rto_bay_halfopen_adjacency_allowed ────────────

class TestBayHalfOpenAdjacency:
    """Bay windows are half-open; exact adjacency does not collide."""

    def test_adjacent_runs_on_same_bay_allowed(self, api):
        """PRD §2.11: "Exact adjacency, where one run's end equals the next run's
        start, does not conflict; a positive overlap is rejected with
        ERR_BAY_WINDOW_CONFLICT."

        Two zero-turnaround drivers sharing one bay: run [60,120) then [120,180)
        touch exactly at 120 and the second run is accepted (SCHEDULED).

        Design: Difficulty/resource_temporal_overlap/rto_bay_halfopen_adjacency_allowed
        """
        part1, acct1, ord1, line1 = setup_allocated_hotshot_order(qty=1, special=True)
        drv1 = create_driver(name="Drv1", turnaround_min=0)
        drv2 = create_driver(name="Drv2", turnaround_min=0)
        bay = create_bay()
        schedule_run(ord1["id"], drv1["id"], bay["id"], 60, 120)
        order2 = create_open_order(acct1["id"], channel="WHOLESALE", hotshot_requested=True)
        add_line(order2["id"], part1["id"], 1)
        allocate(order2["id"])
        run2 = get_success_data(api.create_delivery_run(
            {"order_id": order2["id"], "driver_id": drv2["id"], "bay_id": bay["id"],
             "window_start_min": 120, "window_end_min": 180}, REP))
        assert run2["status"] == "SCHEDULED", "adjacency at 120 must be allowed on a half-open bay"

    def test_both_runs_present_on_bay_after_adjacency(self, api):
        """PRD §2.11: "Exact adjacency, where one run's end equals the next run's
        start, does not conflict; a positive overlap is rejected with
        ERR_BAY_WINDOW_CONFLICT."

        Both adjacent runs persist on the shared bay.

        Design: Difficulty/resource_temporal_overlap/rto_bay_halfopen_adjacency_allowed
        """
        part1, acct1, ord1, line1 = setup_allocated_hotshot_order(qty=1, special=True)
        drv1 = create_driver(name="Drv1b", turnaround_min=0)
        drv2 = create_driver(name="Drv2b", turnaround_min=0)
        bay = create_bay()
        schedule_run(ord1["id"], drv1["id"], bay["id"], 60, 120)
        order2 = create_open_order(acct1["id"], channel="WHOLESALE", hotshot_requested=True)
        add_line(order2["id"], part1["id"], 1)
        allocate(order2["id"])
        schedule_run(order2["id"], drv2["id"], bay["id"], 120, 180)
        runs = [r for r in _runs_for_bay(bay["id"]) if r["status"] != "CANCELLED"]
        assert len(runs) == 2, f"bay should hold two adjacent runs, got {len(runs)}"
