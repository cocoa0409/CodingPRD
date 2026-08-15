"""Allocation pools, order fulfillment/billing dimensions, and list pagination."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, make_contractor_headers, TEST_USERS, ApiErrorId,
    make_contractor, make_model, make_pool, get_pool, make_prebuy_program,
    create_draft_order, add_line, submit_order, ship_order, deliver_order,
    get_order, get_contractor, set_clock, seed_delivered_volume,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


class TestAllocationZeroBoundary:
    """Pool of 2: an order for exactly 2 allocates; a further order for 1 backorders."""

    def _setup_pool_and_first_order(self):
        set_clock("2026-08-05T00:00:00Z")
        contractor = make_contractor(license_number="LIC-012")
        model = make_model(model_number="CU-M12", refrigerant_type="R454B",
                           family_code="FAM-O", list_price_cents=600_000)
        pool = make_pool(family_code="FAM-O", total_qty=2)
        order_a = create_draft_order(contractor)
        add_line(order_a["id"], contractor, equipment_model_id=model["id"], quantity=2)
        order_a = submit_order(order_a["id"], contractor)
        return contractor, model, pool, order_a

    def test_available_equal_to_quantity_allocates(self, api):
        """PRD §3.4: "Where a pool is selected, the check is all-or-nothing per line: if the pool's available quantity — its `total_qty` minus `reserved_qty` minus `committed_qty` — is at least the line's quantity (equality suffices), the line's quantity is added to `reserved_qty`; otherwise nothing is reserved for that line and the order is marked for backorder."
        PRD §3.4: "When every line is either unrestricted or fully reserved, the order advances `SUBMITTED` → `ALLOCATED` and each reservation converts, the quantity leaving `reserved_qty` and entering `committed_qty`."

        Design: Difficulty/boundary_precision_check/allocation_availability_zero_boundary
        """
        _, _, pool, order_a = self._setup_pool_and_first_order()
        assert order_a["status"] == "ALLOCATED", (
            f"available == quantity must satisfy the inclusive boundary, got {order_a['status']}")
        pool = get_pool(pool["id"])
        assert pool["committed_qty"] == 2
        assert pool["reserved_qty"] == 0

    def test_available_zero_backorders_next_order(self, api):
        """PRD §3.4: "Where a pool is selected, the check is all-or-nothing per line: if the pool's available quantity — its `total_qty` minus `reserved_qty` minus `committed_qty` — is at least the line's quantity (equality suffices), the line's quantity is added to `reserved_qty`; otherwise nothing is reserved for that line and the order is marked for backorder."

        Design: Difficulty/boundary_precision_check/allocation_availability_zero_boundary
        """
        contractor, model, pool, order_a = self._setup_pool_and_first_order()
        order_b = create_draft_order(contractor)
        add_line(order_b["id"], contractor, equipment_model_id=model["id"], quantity=1)
        order_b = submit_order(order_b["id"], contractor)
        assert order_b["status"] == "BACKORDERED", (
            f"available == 0 < 1 must backorder, got {order_b['status']}")
        pool = get_pool(pool["id"])
        assert pool["committed_qty"] == 2
        assert pool["reserved_qty"] == 0, "all-or-nothing: the short line reserves nothing"


class TestPoolConservationAcrossSubmitCancel:
    """Conserved quantity: pool reserved + committed units across a submit-then-cancel pair."""

    def _setup_backordered_order(self):
        """Pool total 3; O1 qty 2 -> ALLOCATED; O2 (qty 1 + qty 2) -> BACKORDERED
        holding a partial reservation of 1. Returns (contractor, pool, o1, o2)."""
        set_clock("2026-08-05T00:00:00Z")
        contractor = make_contractor(license_number="LIC-015")
        model = make_model(model_number="CU-O15", refrigerant_type="R454B",
                           family_code="FAM-L", list_price_cents=600_000)
        pool = make_pool(family_code="FAM-L", total_qty=3)
        order1 = create_draft_order(contractor)
        add_line(order1["id"], contractor, equipment_model_id=model["id"], quantity=2)
        order1 = submit_order(order1["id"], contractor)
        assert order1["status"] == "ALLOCATED", "setup: first order must allocate"
        order2 = create_draft_order(contractor)
        add_line(order2["id"], contractor, equipment_model_id=model["id"], quantity=1)
        add_line(order2["id"], contractor, equipment_model_id=model["id"], quantity=2)
        order2 = submit_order(order2["id"], contractor)
        assert order2["status"] == "BACKORDERED", "setup: second order must backorder"
        return contractor, pool, order1, order2

    def test_cancel_of_backordered_order_releases_partial_reservation(self, api):
        """PRD §3.4: "Cancelling releases every pool reservation the order holds, decrementing `reserved_qty` by the reserved quantities and `committed_qty` by any quantities committed to it, so that the pool's reserved-plus-committed conservation is preserved across a submit-then-cancel pair; the provisional accrual is recomputed as well."
        PRD §3.4: "Cancellation is available to the `ContractorUser` while the order is `DRAFT`, `SUBMITTED`, or `BACKORDERED` — and, beyond `DRAFT`, only while the billing dimension is still `UNBILLED` or `DEPOSIT_INVOICED`."

        Design: Difficulty/compensating_invariant/pool_quantity_conserved_across_submit_cancel
        """
        contractor, pool, _, order2 = self._setup_backordered_order()
        pool_before = get_pool(pool["id"])
        assert pool_before["reserved_qty"] == 1 and pool_before["committed_qty"] == 2, (
            "setup: backordered order holds its fully-reservable line's reservation")
        cancelled = validate_success(api.cancel_order(
            order2["id"], make_contractor_headers(contractor["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        pool_after = get_pool(pool["id"])
        assert pool_after["reserved_qty"] == 0 and pool_after["committed_qty"] == 2, (
            f"cancel must release the partial reservation: reserved={pool_after['reserved_qty']} "
            f"committed={pool_after['committed_qty']}")

    def test_pool_close_reverts_backorder_to_submitted_then_cancel(self, api):
        """PRD §3.4: "Conversely, if the pool whose shortage caused the backorder closes, the order reverts `BACKORDERED` → `SUBMITTED` and the partial reservations it held are released; the cycle `BACKORDERED` → `SUBMITTED` → `BACKORDERED` is reachable across successive pool open-and-close epochs."
        PRD §3.4: "Cancelling releases every pool reservation the order holds, decrementing `reserved_qty` by the reserved quantities and `committed_qty` by any quantities committed to it, so that the pool's reserved-plus-committed conservation is preserved across a submit-then-cancel pair; the provisional accrual is recomputed as well."

        Design: Difficulty/compensating_invariant/pool_quantity_conserved_across_submit_cancel
        """
        contractor, pool, _, order2 = self._setup_backordered_order()
        validate_success(api.close_allocation_pool(pool["id"], ADMIN), 200)
        reverted = get_order(order2["id"])
        assert reverted["status"] == "SUBMITTED", (
            f"pool close must revert the backordered order to SUBMITTED, got {reverted['status']}")
        pool_mid = get_pool(pool["id"])
        assert pool_mid["reserved_qty"] == 0 and pool_mid["committed_qty"] == 2, (
            "reversion must release the partial reservation")
        cancelled = validate_success(api.cancel_order(
            order2["id"], make_contractor_headers(contractor["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        pool_after = get_pool(pool["id"])
        assert pool_after["reserved_qty"] == 0 and pool_after["committed_qty"] == 2


def test_backordered_order_recovers_by_tier_priority_on_pool_open(api):
    """PRD §3.4: "When availability reopens for the short family — a pool is created or its `total_qty` grows — a re-reservation sweep re-evaluates `BACKORDERED` orders in priority order: `PLATINUM` contractors first, then `GOLD`, then `SILVER`, then `STANDARD`; within a tier, earlier `submitted_at` wins; remaining ties break by earlier order `created_at`."
    PRD §3.4: "For each line, the server looks for a pool whose `family_code` matches the component's family, whose `status` is `OPEN`, and whose season covers the logical clock; among candidates it picks the pool whose `season_start` is most recent, breaking ties by earliest `created_at`."

    Design: Corner/cross_cutting_layers/backordered_order_recovers_on_pool_reopen
    """
    set_clock("2026-08-05T00:00:00Z")
    gold = make_contractor(license_number="LIC-C801")
    standard = make_contractor(license_number="LIC-802")
    # Seed GOLD: one delivered 20,000,000-cent order on an unrelated family.
    seed_model = make_model(model_number="CU-GOLD-SEED", family_code="FAM-P0",
                            list_price_cents=20_000_000)
    seed_order = create_draft_order(gold)
    add_line(seed_order["id"], gold, equipment_model_id=seed_model["id"], quantity=1)
    submit_order(seed_order["id"], gold)
    ship_order(seed_order["id"])
    deliver_order(seed_order["id"])
    assert get_contractor(gold["id"])["tier"] == "GOLD", "setup: contractor must be GOLD"

    model = make_model(model_number="CU-Q9", refrigerant_type="R454B",
                       family_code="FAM-Q9", list_price_cents=600_000)
    pool1 = make_pool(family_code="FAM-Q9", total_qty=1,
                      season_start="2026-08-01T00:00:00Z", season_end="2026-09-01T00:00:00Z")

    def order_qty1(contractor):
        order = create_draft_order(contractor)
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        return submit_order(order["id"], contractor)

    o_g1 = order_qty1(gold)
    assert o_g1["status"] == "ALLOCATED", "setup: GOLD's first order takes the single unit"
    o_s1 = order_qty1(standard)
    assert o_s1["status"] == "BACKORDERED", "setup: STANDARD order must backorder"
    o_g2 = order_qty1(gold)
    assert o_g2["status"] == "BACKORDERED", "setup: GOLD's second order must backorder"

    # A second pool opens with a strictly later season_start, so it becomes the
    # selected candidate; its single unit re-reserves by tier priority.
    pool2 = validate_success(api.create_allocation_pool(
        {"family_code": "FAM-Q9", "season_start": "2026-08-05T00:00:00Z",
         "season_end": "2026-09-01T00:00:00Z", "total_qty": 1}, ADMIN), 201)

    assert get_order(o_g2["id"])["status"] == "ALLOCATED", (
        "GOLD outranks STANDARD in the re-reservation sweep")
    assert get_order(o_s1["id"])["status"] == "BACKORDERED", (
        "STANDARD's older order stays backordered behind GOLD's")
    assert get_order(o_g1["id"])["status"] == "ALLOCATED"
    assert get_pool(pool1["id"])["committed_qty"] == 1
    assert get_pool(pool2["id"])["committed_qty"] == 1


class TestCancelAndTerminalLockdown:
    def _setup_shipped_order(self, license_number):
        contractor = make_contractor(license_number=license_number)
        model = make_model(family_code="FAM-J", list_price_cents=500_000)
        order = create_draft_order(contractor)
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        submit_order(order["id"], contractor)
        ship_order(order["id"])
        return contractor, order

    def test_cancel_from_shipped_rejected(self, api):
        """PRD §3.4: "An order in `ALLOCATED`, `SHIPPED`, or any later state cannot be cancelled — such attempts are rejected with `ERR_INVALID_STATE` (409) — and `DELIVERED` and `CANCELLED` are terminal, with further transitions rejected under the terminal lockdown."

        Design: Corner/state_machines/order_cancel_from_shipped_returns_invalid_state
        """
        contractor, order = self._setup_shipped_order("LIC-C200")
        res = api.cancel_order(order["id"], make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "SHIPPED"

    def test_delivered_order_rejects_further_transitions(self, api, admin_headers):
        """PRD §3.4: "An order in `ALLOCATED`, `SHIPPED`, or any later state cannot be cancelled — such attempts are rejected with `ERR_INVALID_STATE` (409) — and `DELIVERED` and `CANCELLED` are terminal, with further transitions rejected under the terminal lockdown."
        PRD §2.8: "5. **From-state legality** — the target resource must be in a legal from-state for the requested transition; failures yield `ERR_INVALID_STATE` (409)."
        PRD §2.8: "The from-state check runs before this one, so a request failing both reports `ERR_INVALID_STATE`."

        Design: Corner/state_machines/order_terminal_delivered_lockdown
        """
        contractor, order = self._setup_shipped_order("LIC-C201")
        deliver_order(order["id"])
        assert get_order(order["id"])["status"] == "DELIVERED"
        res = api.ship_order(order["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "DELIVERED"


class TestParallelBillingDimension:
    def _setup_deposit_paid_prebuy_order(self):
        contractor = make_contractor(license_number="LIC-006")
        model = make_model(model_number="CU-Z6", refrigerant_type="R454B",
                           family_code="FAM-V", list_price_cents=1_000_000)
        program = make_prebuy_program(name="P6", family_code="FAM-V")
        order = create_draft_order(contractor, prebuy_program_id=program["id"])
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        order = submit_order(order["id"], contractor)
        assert order["status"] == "ALLOCATED", "setup: unrestricted order allocates"
        validate_success(api_client.post_billing_event(
            order["id"], {"event_type": "INVOICE_DEPOSIT"}, ADMIN), 200)
        order = validate_success(api_client.post_billing_event(
            order["id"], {"event_type": "PAY_DEPOSIT"},
            make_contractor_headers(contractor["id"])), 200)
        assert order["billing_status"] == "DEPOSIT_PAID", "setup: deposit must be paid"
        return contractor, order

    def test_final_invoice_before_ship_rejected_on_prebuy_track(self, api):
        """PRD §3.5: "Once the order is `SHIPPED`, a final invoice moves `DEPOSIT_PAID` → `FINAL_INVOICED` for the order's `total_cents` minus the deposit already due."
        PRD §3.5: "An event that does not correspond to a legal transition from the current `billing_status` is rejected with `ERR_INVALID_STATE`, and `PAID` and `FORFEITED` accept no further events under the terminal lockdown."

        Design: Difficulty/non_linear_state_machine/order_parallel_billing_and_fulfillment_dimensions
        """
        contractor, order = self._setup_deposit_paid_prebuy_order()
        res = api_client.post_billing_event(order["id"], {"event_type": "INVOICE_FINAL"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        current = get_order(order["id"])
        assert current["status"] == "ALLOCATED"
        assert current["billing_status"] == "DEPOSIT_PAID"

    def test_final_invoice_succeeds_once_shipped_parallel_dimensions(self, api):
        """PRD §3.5: "The billing dimension evolves **in parallel** with fulfillment, on the same order resource, through billing events carrying an `event_type`."
        PRD §3.5: "Once the order is `SHIPPED`, a final invoice moves `DEPOSIT_PAID` → `FINAL_INVOICED` for the order's `total_cents` minus the deposit already due."

        Design: Difficulty/non_linear_state_machine/order_parallel_billing_and_fulfillment_dimensions
        """
        contractor, order = self._setup_deposit_paid_prebuy_order()
        shipped = ship_order(order["id"])
        assert shipped["status"] == "SHIPPED"
        assert shipped["billing_status"] == "DEPOSIT_PAID", (
            "shipping advances fulfillment only; billing stays DEPOSIT_PAID")
        invoiced = validate_success(api_client.post_billing_event(
            order["id"], {"event_type": "INVOICE_FINAL"}, ADMIN), 200)
        assert invoiced["status"] == "SHIPPED"
        assert invoiced["billing_status"] == "FINAL_INVOICED"


def test_final_invoice_before_ship_rejected_on_non_prebuy_track(api):
    """PRD §3.5: "A **non-pre-buy order** bills once: from `UNBILLED` straight to `FINAL_INVOICED` once the order is `SHIPPED`, for the full `total_cents`."
    PRD §3.5: "An event that does not correspond to a legal transition from the current `billing_status` is rejected with `ERR_INVALID_STATE`, and `PAID` and `FORFEITED` accept no further events under the terminal lockdown."

    Design: Corner/endpoints/billing_event_premature_final_invoice_rejected
    """
    contractor = make_contractor(license_number="LIC-C502")
    model = make_model(model_number="CU-B502", family_code="FAM-W6",
                       list_price_cents=500_000)
    order = create_draft_order(contractor)
    add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
    order = submit_order(order["id"], contractor)
    assert order["billing_status"] == "UNBILLED", "setup: order must be UNBILLED"
    res = api_client.post_billing_event(order["id"], {"event_type": "INVOICE_FINAL"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestListPagination:
    def test_orders_list_pagination_envelope(self, api, admin_headers):
        """PRD §2.3: "List responses carry four pagination fields in the response envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter bounds the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0."

        Design: Corner/entities/order_lines_list_pagination_envelope
        """
        contractor = make_contractor(license_number="LIC-C103")
        for _ in range(3):
            create_draft_order(contractor)
        data, meta = validate_paginated(api.list_orders(
            admin_headers, params={"contractor_id": contractor["id"], "limit": 2, "offset": 0}))
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2
        data2, meta2 = validate_paginated(api.list_orders(
            admin_headers, params={"contractor_id": contractor["id"], "limit": 2, "offset": 2}))
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(data2) == 1

    def test_filtered_list_recounts_after_transition(self, api, admin_headers):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit` parameter bounds the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0."
        PRD §3.4: "Cancellation is available to the `ContractorUser` while the order is `DRAFT`, `SUBMITTED`, or `BACKORDERED` — and, beyond `DRAFT`, only while the billing dimension is still `UNBILLED` or `DEPOSIT_INVOICED`."
        PRD §3.4: "Orders and lines are browsable through list endpoints filtered by `contractor_id`, `prebuy_program_id`, `status`, `ahri_rating_id`, `equipment_model_id`, or `order_id` as appropriate to each listing."

        Design: Corner/cross_cutting_layers/pagination_filter_interaction_under_mutation
        """
        contractor = make_contractor(license_number="LIC-C803")
        headers = make_contractor_headers(contractor["id"])
        orders = [create_draft_order(contractor) for _ in range(3)]
        data, meta = validate_paginated(api.list_orders(
            admin_headers, params={"contractor_id": contractor["id"], "status": "DRAFT",
                                   "limit": 10, "offset": 0}))
        assert meta["total_count"] == 3, "setup: three DRAFT orders must match the filter"
        validate_success(api.cancel_order(orders[0]["id"], headers), 200)
        data, meta = validate_paginated(api.list_orders(
            admin_headers, params={"contractor_id": contractor["id"], "status": "DRAFT",
                                   "limit": 10, "offset": 0}))
        assert meta["total_count"] == 2, (
            "the cancelled order left the DRAFT filter set; offset pagination re-evaluates")
        assert meta["has_more"] is False
        assert all(o["status"] == "DRAFT" for o in data)
