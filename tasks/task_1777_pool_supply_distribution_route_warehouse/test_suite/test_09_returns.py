"""Returned goods and expired chemicals: request-time rejection of expired
chemical returns, the receive-time expiry re-check, and the OVERSTOCK
restocking-fee credit computed from the frozen historical unit price."""
from test_helpers import (
    ApiErrorId,
    MGR,
    complete_order_fully,
    create_confirmed_order,
    make_rma,
    order_line,
    set_clock,
    setup_branch_account_product_lot,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


def _completed_chemical_order(api, clock=None, sku="ALG-X", price=5000,
                              qty=1, lot_qty=5, expiry="2026-08-10",
                              pickup_slot="2026-08-01T13:00:00Z"):
    """Branch + account + expiry-tracked chemical + lot + one order driven to
    COMPLETED/PAID. Returns (branch, account, product, lot, order)."""
    if clock is not None:
        set_clock(clock, api)
    branch, account, product, lot = setup_branch_account_product_lot(
        api,
        branch_over={"branch_code": "PHX-12", "hazmat_storage_certified": True},
        product_over={
            "sku": sku, "product_family": "CHEMICAL", "base_price_cents": price,
            "expiry_tracked": True,
        },
        lot_over={"lot_code": "LX", "qty_on_hand": lot_qty, "expiry_date": expiry},
    )
    order = create_confirmed_order(
        api, branch_id=branch["id"], account_id=account["id"],
        requested_pickup_slot=pickup_slot,
        lines=[order_line(product["id"], qty)],
    )
    complete_order_fully(order["id"], "WILL_CALL", api)
    return branch, account, product, lot, order


class TestExpiredChemicalGate:
    def test_expired_chemical_rma_rejected_at_create(self, api):
        """PRD §3.9: "One rejection happens at request time rather than approval time: an `EXPIRED`-reason return of a `CHEMICAL` product whose lot's `expiry_date` is on or before the logical today is refused outright with `ERR_RETURN_EXPIRED_CHEMICAL` (HTTP 422), because expired chemicals are hazmat waste and cannot re-enter the branch."

        Design: Corner/validations/expired_chemical_rma_rejected_at_create
        """
        # Order flow runs while the lot (expiry 2026-07-01) is still unexpired.
        branch, account, product, lot, order = _completed_chemical_order(
            api, clock="2026-06-01T00:00:00Z", sku="ALG-20", price=3000,
            qty=1, lot_qty=5, expiry="2026-07-01",
            pickup_slot="2026-06-01T14:00:00Z",
        )
        # Advance past the lot's expiry before the return is requested.
        set_clock("2026-08-01T00:00:00Z", api)
        resp = api.create_return_authorization(
            {
                "account_id": account["id"], "order_id": order["id"],
                "product_id": product["id"], "lot_id": lot["id"],
                "qty": 1, "reason": "EXPIRED",
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_EXPIRED_CHEMICAL)
        data, meta = validate_paginated(
            api.list_return_authorizations(MGR, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0 and data == [], (
            f"refused at request time — no RMA row persists: {meta}"
        )

    def test_rma_receive_rejects_expired_chemical_since_request(self, api):
        """PRD §3.9: "For chemical products the lot's `expiry_date` must still be after the logical today at receipt, else `ERR_RMA_LOT_EXPIRED_SINCE_REQUEST`."
        PRD §3.9: "Physical receipt is a `WarehouseLead` act requiring `APPROVED` (`ERR_RMA_NOT_APPROVED`, HTTP 409)."

        Design: Corner/state_machines/rma_receive_rejects_expired_chemical_since_request
        """
        _branch, account, product, lot, order = _completed_chemical_order(
            api, sku="ALG-60", price=5000, qty=1, lot_qty=5, expiry="2026-08-10",
        )
        rma = make_rma(
            api, account_id=account["id"], order_id=order["id"],
            product_id=product["id"], lot_id=lot["id"], qty=1, reason="OVERSTOCK",
        )
        approved = validate_success(api.approve_return_authorization(rma["id"], MGR), 200)
        assert approved["status"] == "APPROVED"
        lot_before = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))

        # The lot expires between approval and physical receipt.
        set_clock("2026-08-11T00:00:00Z", api)
        resp = api.receive_return_authorization(rma["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_RMA_LOT_EXPIRED_SINCE_REQUEST)
        rma_after = validate_success(api.get_return_authorization(rma["id"], MGR))
        assert rma_after["status"] == "APPROVED", (
            f"rejected receipt leaves the RMA APPROVED: {rma_after}"
        )
        lot_after = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["qty_on_hand"] == lot_before["qty_on_hand"], (
            f"no restock happened: {lot_after}"
        )


class TestRmaCredit:
    def test_rma_credit_overstock_restocking_fee(self, api):
        """PRD §3.9: "The credit references the order line matching the RMA's order and product, choosing the earliest-created line when several match; the base is that line's frozen historical `unit_price_cents` — the tier-pinned price from the original confirmation, never current pricing — multiplied by the returned `qty`."
        PRD §3.9: "The fee percentage is decided before the credit: zero for `DEFECTIVE` and `WRONG_ITEM`, a 15% restocking fee for `OVERSTOCK`, and zero for `EXPIRED`."
        PRD §3.9: "The resulting `restocking_fee_pct` and `credit_cents` — the base reduced by the fee and rounded half up — are stored at approval, moving the RMA to `APPROVED`."

        Design: Corner/calculations/rma_credit_overstock_restocking_fee
        """
        _branch, account, product, lot, order = _completed_chemical_order(
            api, sku="TAB-1IN", price=8000, qty=4, lot_qty=20, expiry="2027-06-01",
        )
        # PRO tier, no commitment: the frozen historical unit price is 8,000c.
        rma = make_rma(
            api, account_id=account["id"], order_id=order["id"],
            product_id=product["id"], lot_id=lot["id"], qty=4, reason="OVERSTOCK",
        )
        approved = validate_success(api.approve_return_authorization(rma["id"], MGR), 200)
        assert approved["status"] == "APPROVED"
        assert approved["restocking_fee_pct"] == 0.15, (
            f"OVERSTOCK carries the 15% restocking fee: {approved}"
        )
        # round_half_up(4 x 8,000 x (1 - 0.15)) = 27,200
        assert approved["credit_cents"] == 27200, (
            f"credit uses the frozen historical unit price less the fee: {approved}"
        )
