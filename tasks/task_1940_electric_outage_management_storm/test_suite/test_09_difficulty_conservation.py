"""Difficulty tests — compensating_invariant rule.

Covers stock-unit conservation across stage/cancel and ledger-cents
conservation across issue/return.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_stock_conservation,
    create_material_requisition_payload,
    create_material_stock_payload,
    create_ready_work_order,
    create_requisition,
    create_staged_requisition,
    create_stock,
    get_success_data,
    set_clock,
    setup_outage_with_accepted_assessment,
    validate_paginated,
)

DISP = TEST_USERS["dispatcher_headers"]
MM = TEST_USERS["materials_manager_headers"]


class TestMaterialStageCancelConservesStockUnits:
    """Stage then cancel leaves on_hand + reserved invariant at every step."""

    def test_stage_moves_units_to_reserved_without_leaving_warehouse(self, api):
        """PRD §3.8: "Staging reserves the material: it requires
        `quantity_available` to be at least the requested `quantity` —
        equality is allowed, a shortfall is rejected with
        `ERR_INSUFFICIENT_MATERIAL` — and adds the quantity to the pool's
        `quantity_reserved`, incrementing the `version` of both requisition
        and stock."

        Design: Difficulty/compensating_invariant/material_stage_cancel_conserves_stock_units
        """
        _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
        wo = create_ready_work_order(ot["id"])
        ms = create_stock(
            warehouse_code="W1",
            material_sku="SKU-1",
            quantity_on_hand=100,
            unit_cost_cents=500,
        )
        mr = create_requisition(wo["id"], ms["id"], quantity=10)
        # Baseline invariant: on_hand + reserved == 100.
        stock = get_success_data(api.get_material_stock(ms["id"], MM))
        assert_stock_conservation(stock, expected_total=100)

        get_success_data(api.stage_material_requisition(mr["id"], MM))
        staged = get_success_data(api.get_material_stock(ms["id"], MM))
        assert staged["quantity_on_hand"] == 100
        assert staged["quantity_reserved"] == 10
        assert staged["quantity_available"] == 90
        assert_stock_conservation(staged, expected_total=100)

    def test_cancel_releases_reservation_and_restores_available(self, api):
        """PRD §3.8: "A requisition in `REQUESTED` or `STAGED` may be
        cancelled to `CANCELLED`; cancelling a `STAGED` one subtracts its
        quantity from `quantity_reserved`."

        Design: Difficulty/compensating_invariant/material_stage_cancel_conserves_stock_units
        """
        _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
        wo = create_ready_work_order(ot["id"])
        ms = create_stock(
            warehouse_code="W1",
            material_sku="SKU-1",
            quantity_on_hand=100,
            unit_cost_cents=500,
        )
        mr = create_staged_requisition(wo["id"], ms["id"], quantity=10)

        cancelled = get_success_data(api.cancel_material_requisition(mr["id"], MM))
        assert cancelled["requisition_status"] == "CANCELLED"
        stock = get_success_data(api.get_material_stock(ms["id"], MM))
        assert stock["quantity_on_hand"] == 100
        assert stock["quantity_reserved"] == 0
        assert stock["quantity_available"] == 100
        assert_stock_conservation(stock, expected_total=100)


class TestLedgerIssueReturnNetsZeroCents:
    """Issue posts +X; return posts -X pinned to the original via reversal."""

    def test_issue_then_return_nets_to_zero_on_ledger_and_rollup(self, api):
        """PRD §3.8: "Issuing moves `STAGED` to `ISSUED`, subtracts the
        quantity from both `quantity_reserved` and `quantity_on_hand`, and
        posts a `MATERIAL` ledger entry for the quantity times the stock's
        `unit_cost_cents`" and "Returning an `ISSUED` requisition moves it to
        `RETURNED`, adds the quantity back to `quantity_on_hand`, and posts a
        reversal `MATERIAL` entry whose amount is the negation of the
        original issue amount with `reversed_entry_id` referencing the issue
        entry."

        Design: Difficulty/compensating_invariant/ledger_issue_return_nets_zero_cents
        """
        _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
        wo = create_ready_work_order(ot["id"])
        ms = create_stock(
            warehouse_code="W1",
            material_sku="SKU-1",
            quantity_on_hand=100,
            unit_cost_cents=500,
        )
        mr = create_staged_requisition(wo["id"], ms["id"], quantity=10)

        get_success_data(api.issue_material_requisition(mr["id"], MM))
        entries, _meta = validate_paginated(
            api.list_cost_ledger_entries(MM, params={"work_order_id": wo["id"]})
        )
        assert len(entries) == 1
        issue_entry = entries[0]
        assert issue_entry["amount_cents"] == 5000
        assert issue_entry["entry_type"] == "MATERIAL"

        get_success_data(api.return_material_requisition(mr["id"], MM))
        entries, _meta = validate_paginated(
            api.list_cost_ledger_entries(MM, params={"work_order_id": wo["id"]})
        )
        assert len(entries) == 2
        reversal = entries[1]
        assert reversal["amount_cents"] == -5000
        assert reversal["reversed_entry_id"] == issue_entry["id"]
        # Invariant: forward + reversal net to zero on the per-work-order sum.
        assert issue_entry["amount_cents"] + reversal["amount_cents"] == 0

        # Stock restored.
        stock = get_success_data(api.get_material_stock(ms["id"], MM))
        assert stock["quantity_on_hand"] == 100
        assert stock["quantity_reserved"] == 0

        # Event rollup nets to zero.
        ev_final = get_success_data(api.get_storm_event(_ev["id"], MM))
        assert ev_final["total_material_cents"] == 0
        assert ev_final["total_event_cost_cents"] == 0

    def test_ledger_conservation_via_per_requisition_sum(self, api):
        """PRD §2.10: "Reversals never delete history: a reversal is a new
        entry carrying the negated amount, so originals and reversals
        coexist."

        Design: Difficulty/compensating_invariant/ledger_issue_return_nets_zero_cents
        """
        _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
        wo = create_ready_work_order(ot["id"])
        ms = create_stock(
            warehouse_code="W1",
            material_sku="SKU-1",
            quantity_on_hand=100,
            unit_cost_cents=500,
        )
        mr = create_staged_requisition(wo["id"], ms["id"], quantity=10)
        get_success_data(api.issue_material_requisition(mr["id"], MM))
        get_success_data(api.return_material_requisition(mr["id"], MM))

        entries, _meta = validate_paginated(
            api.list_cost_ledger_entries(MM, params={"work_order_id": wo["id"]})
        )
        # Both entries remain on the ledger (no delete-on-reverse).
        assert len(entries) == 2
        total = sum(e["amount_cents"] for e in entries)
        assert total == 0, f"per-requisition ledger sum must net to 0; got {total}"
