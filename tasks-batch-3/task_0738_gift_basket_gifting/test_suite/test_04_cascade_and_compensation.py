"""Transitive cascades and compensating invariants: approval fan-out (depth 3),
last-task-complete fan-out (depth 2), inventory-unit compensation on cancel,
and ytd_spend_cents refund on approved-order cancel.

Translations of Difficulty/transitive_cascade (2) and
Difficulty/compensating_invariant (2).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    factories, fixtures,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
WH = TEST_USERS["warehouse_ops_headers"]


class TestApproveCascadeDepth3:
    """One APPROVE call triggers a depth-3 cascade: reservation → task → order
    production_status, each hop caused transitively by the previous."""

    def test_reservation_becomes_allocated_after_approve(self, api):
        """PRD §3.6: "Hop one, caused directly by the APPROVE decision: every
        InventoryReservation belonging to this order's recipients moves from
        RESERVED to ALLOCATED"

        Design: Difficulty/transitive_cascade/approve_cascade_reservation_to_assembly_task_to_production_status_depth3
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Tote Basket", base_price_cents=4000))
        p = fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="cascade@example.com", quantity=5)])
        reservation = fixtures.find_reservation_for_recipient(
            api, recipient_id=p["recipients"][0]["id"])
        assert reservation is not None
        assert reservation["status"] == "ALLOCATED"

    def test_assembly_task_created_queued_and_production_status_assembling(self, api):
        """PRD §3.6: "Hop two, caused by hop one's ALLOCATED reservations now
        existing — not by the approval event itself: exactly one AssemblyTask
        is created per Recipient on the order, starting QUEUED, carrying the
        station_id and scheduled_date supplied on the approval call and a
        quantity mirroring that recipient's own."
        PRD §3.6: "Hop three, caused by hop two's new AssemblyTask rows now
        existing — again, not directly by the approval event: the order's
        production_status advances from DRAFT to ASSEMBLING."

        Design: Difficulty/transitive_cascade/approve_cascade_reservation_to_assembly_task_to_production_status_depth3
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Tote Basket", base_price_cents=4000))
        p = fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="cascade2@example.com", quantity=5)],
            scheduled_date="2026-03-04T00:00:00Z")
        task = fixtures.find_task_for_recipient(
            api, recipient_id=p["recipients"][0]["id"])
        assert task is not None
        assert task["status"] == "QUEUED"
        assert task["station_id"] == base["station"]["id"]
        assert task["scheduled_date"] == "2026-03-04T00:00:00Z"
        assert task["quantity"] == 5
        order = validate_success(api.get_order(p["order"]["id"], ADMIN))
        assert order["production_status"] == "ASSEMBLING"


class TestLastAssemblyTaskCompleteCascadeDepth2:
    """The order's last AssemblyTask reaching COMPLETE cascades to
    READY_TO_SHIP, which in turn moves still-ALLOCATED reservations to
    ASSEMBLED."""

    def test_production_status_becomes_ready_to_ship_after_last_task_complete(self, api):
        """PRD §3.7: "Completing the very last outstanding AssemblyTask among an
        order's recipients triggers a two-hop cascade of its own. Hop one is
        the completing task's own transition to COMPLETE, driven by a
        WarehouseOps call — a different trigger from the approval event that
        drives the cascade in §3.6."

        Design: Difficulty/transitive_cascade/last_assembly_task_complete_cascades_to_ready_to_ship_and_bulk_assembled_depth2
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1000)
        p = fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="lasttask@example.com", quantity=3)])
        task = fixtures.find_task_for_recipient(
            api, recipient_id=p["recipients"][0]["id"])
        fixtures.advance_assembly_task(api, task_id=task["id"],
                                       target_status="IN_PROGRESS")
        fixtures.advance_assembly_task(api, task_id=task["id"],
                                       target_status="COMPLETE")
        order = validate_success(api.get_order(p["order"]["id"], ADMIN))
        assert order["production_status"] == "READY_TO_SHIP"

    def test_allocated_reservation_becomes_assembled_after_ready_to_ship(self, api):
        """PRD §3.7: "Hop two, caused by hop one only once it makes the order's
        production_status reach READY_TO_SHIP (not caused directly by the task
        completion itself): every InventoryReservation belonging to the order's
        recipients that is still ALLOCATED moves to ASSEMBLED."

        Design: Difficulty/transitive_cascade/last_assembly_task_complete_cascades_to_ready_to_ship_and_bulk_assembled_depth2
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1000)
        p = fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="lasttask2@example.com", quantity=3)])
        task = fixtures.find_task_for_recipient(
            api, recipient_id=p["recipients"][0]["id"])
        reservation = fixtures.find_reservation_for_recipient(
            api, recipient_id=p["recipients"][0]["id"])
        fixtures.advance_assembly_task(api, task_id=task["id"],
                                       target_status="IN_PROGRESS")
        fixtures.advance_assembly_task(api, task_id=task["id"],
                                       target_status="COMPLETE")
        got = validate_success(
            api.get_inventory_reservation(reservation["id"], WH))
        assert got["status"] == "ASSEMBLED"


class TestOrderCancelReleasesInventoryReservation:
    """Cancelling an order compensates the inventory ledger: reservations still
    in {RESERVED, ALLOCATED} move to RELEASED, restoring SKU availability."""

    def test_probe_import_rejected_while_reservation_active(self, api):
        """PRD §3.4: "for every sku_id in the template's components, the
        forward-looking variant of the component-availability calculation (§3.6)
        must show at least as many available units as components[sku].quantity
        multiplied by the row's own quantity — a shortfall is rejected with
        ERR_INSUFFICIENT_INVENTORY_FORWARD (422)"
        PRD §3.4: "After every row in the batch has been evaluated this way,
        if not a single row was accepted, the entire batch call fails with
        ERR_IMPORT_BATCH_ALL_ROWS_REJECTED (422)."

        Design: Difficulty/compensating_invariant/order_cancel_releases_reservation_restoring_available_inventory_units
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(
            api, name="Wine Glass Set", unit_cost_cents=1200,
            is_perishable=False, on_hand_qty=5)
        template = fixtures.create_template(
            api, name="Glassware Basket", category="CLIENT_APPRECIATION",
            base_price_cents=4000, sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station S", daily_capacity=1000)
        base = {"account": account, "sku": sku, "template": template, "station": station}
        # Order_A reserves all 5 on-hand units and is APPROVED.
        fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="reserveall@example.com", quantity=5)],
            occasion="CLIENT_APPRECIATION",
            approver_user_id="fin-appr-16",
            requested_by_user_id="emp-req-16")
        # Probe order: import a single row for 5 units. All 5 on-hand are tied
        # up by Order_A → the single row is REJECTED → accepted_rows=0 → the
        # whole batch call fails with ERR_IMPORT_BATCH_ALL_ROWS_REJECTED (422).
        account = fixtures.get_account(api, account_id=account["id"])
        order_probe = fixtures.create_order(
            api, account=account, template_id=template["id"],
            occasion="CLIENT_APPRECIATION")
        from test_helpers.test_users import make_account_manager_headers
        hdrs = make_account_manager_headers(account["id"])
        resp = api.import_recipients(
            order_probe["id"],
            {"rows": [factories.recipient_row(
                email="probebefore@example.com", quantity=5)]},
            hdrs)
        validate_error(resp, "ERR_IMPORT_BATCH_ALL_ROWS_REJECTED")

    def test_probe_import_accepted_after_cancel_releases_reservation(self, api):
        """PRD §3.9: "every InventoryReservation belonging to the order's
        recipients that is still RESERVED or ALLOCATED moves to RELEASED,
        which removes it from the active-status filter that the availability
        calculations in §3.6 use — the SKU's available quantity returns to
        exactly what it was before the reservation existed."

        Design: Difficulty/compensating_invariant/order_cancel_releases_reservation_restoring_available_inventory_units
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(
            api, name="Wine Glass Set", unit_cost_cents=1200,
            is_perishable=False, on_hand_qty=5)
        template = fixtures.create_template(
            api, name="Glassware Basket", category="CLIENT_APPRECIATION",
            base_price_cents=4000, sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station S", daily_capacity=1000)
        base = {"account": account, "sku": sku, "template": template, "station": station}
        p_a = fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="reserveall2@example.com",
                                          quantity=5)],
            occasion="CLIENT_APPRECIATION",
            approver_user_id="fin-appr-16",
            requested_by_user_id="emp-req-16")
        account = fixtures.get_account(api, account_id=account["id"])
        order_probe = fixtures.create_order(
            api, account=account, template_id=template["id"],
            occasion="CLIENT_APPRECIATION")
        # Cancel Order_A to release its reservation.
        from test_helpers.test_users import make_account_manager_headers
        hdrs = make_account_manager_headers(account["id"])
        validate_success(api.cancel_order(p_a["order"]["id"], hdrs))
        # Now the second order's import can consume the 5 restored units.
        rows_after = validate_success(api.import_recipients(
            order_probe["id"],
            {"rows": [factories.recipient_row(email="probeafter@example.com",
                                              quantity=5)]},
            hdrs), 201)
        assert rows_after[0]["import_row_status"] == "ACCEPTED"


class TestOrderCancelRefundsYtdSpendCents:
    """Cancelling an APPROVED order runs the reverse leg of ytd_spend recompute:
    total_cost_cents is credited back to the account, restoring the pre-approval
    figure."""

    def test_ytd_spend_recorded_after_approve(self, api):
        """PRD §3.2: "It only ever moves in two circumstances: it increases by
        an order's total_cost_cents the moment that order is approved, and it
        decreases by the same amount if that already-approved order is later
        cancelled"

        Design: Difficulty/compensating_invariant/order_cancel_refunds_ytd_spend_cents_after_approval
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=200_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Organizer Basket",
                                 base_price_cents=4000))
        p = fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="refund@example.com", quantity=10)],
            requested_by_user_id="emp-req-17",
            approver_user_id="fin-appr-17")
        # 10 × 4000 = 40000 subtotal; TIER_0; remaining_budget=200000 < GOLD
        # so 0% loyalty (STANDARD tier < SILVER too since 200000 < 250000);
        # total=40000, ytd = 40000.
        acct = validate_success(api.get_account(base["account"]["id"], ADMIN))
        assert acct["ytd_spend_cents"] == 40000

    def test_ytd_spend_refunded_to_zero_after_cancel(self, api):
        """PRD §3.9: "if order.approval_status was already APPROVED at the
        moment of cancellation (meaning its cost had already been counted), the
        reverse leg of the year-to-date spend recompute runs, subtracting
        total_cost_cents back out of ytd_spend_cents"

        Design: Difficulty/compensating_invariant/order_cancel_refunds_ytd_spend_cents_after_approval
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=200_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Organizer Basket",
                                 base_price_cents=4000))
        p = fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="refund2@example.com", quantity=10)],
            requested_by_user_id="emp-req-17",
            approver_user_id="fin-appr-17")
        from test_helpers.test_users import make_account_manager_headers
        hdrs = make_account_manager_headers(base["account"]["id"])
        validate_success(api.cancel_order(p["order"]["id"], hdrs))
        acct = validate_success(api.get_account(base["account"]["id"], ADMIN))
        assert acct["ytd_spend_cents"] == 0
