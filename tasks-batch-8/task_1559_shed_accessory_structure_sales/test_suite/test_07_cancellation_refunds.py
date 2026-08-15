"""Cancellation refund waterfall and terminal-state lockdown (PRD §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_book, create_draft_order, record_order_payment,
    drive_order_to_scheduled, get_order,
    assert_cancellation_cash_conservation,
    DEPOSIT_10X12_WINDOW, PERMIT_FEE_120_SQFT,
    CANCEL_RETAINED_SCHEDULED, CANCEL_REFUND_SCHEDULED,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


class TestCancelRefundCashConservation:
    """10x12 [WINDOW] CASH order in SCHEDULED with collected 200000; cancelled."""

    def _scheduled_order_with_200000(self, api):
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        scheduled = drive_order_to_scheduled(order, deposit_cents=DEPOSIT_10X12_WINDOW)
        assert scheduled["status"] == "SCHEDULED"
        record_order_payment(order["id"], 79702, "pay-2", method="CASH")
        assert get_order(order["id"])["collected_cents"] == 200000
        return order

    def test_refund_waterfall_amounts(self, api):
        """PRD §3.6: "First, a $50.00 administrative fee is always retained. Second, when
        the order's latest permit application is still `SUBMITTED` or already `APPROVED`
        and the order is being cancelled from `PERMIT_REVIEW`, `READY_TO_SCHEDULE`, or
        `SCHEDULED`, that application's `fee_cents` is retained as a non-refundable
        permit fee. Third, cancelling from `READY_TO_SCHEDULE` or `SCHEDULED` adds a
        restocking fee of ten percent of `structure_price_cents`, rounded half-up to
        whole cents. The amount retained, stored as `retained_cents`, is the smaller of
        the collected amount and the sum of the three buckets; the remainder of
        `collected_cents` is the refund, so refund plus retained always equals the
        collected amount exactly."

        Design: Difficulty/compensating_invariant/cancel_refund_cash_conservation
        """
        order = self._scheduled_order_with_200000(api)
        cancelled = validate_success(
            api.cancel_order(order["id"], {"reason": "found a better offer"}, SALES), 200
        )
        assert cancelled["status"] == "CANCELLED"
        refreshed = validate_success(api.get_order(order["id"], FINANCE), 200)
        assert refreshed["collected_cents"] == 200000  # 120298 + 79702
        # admin 5000 + permit 21000 (APPROVED, cancel from SCHEDULED)
        #   + restock round(392000*0.10) = 39200
        assert refreshed["retained_cents"] == CANCEL_RETAINED_SCHEDULED
        assert refreshed["refunded_cents"] == CANCEL_REFUND_SCHEDULED
        assert_cancellation_cash_conservation(refreshed)

    def test_refund_payment_row_recorded(self, api):
        """PRD §3.6: "When the refund is positive, the system records a payment with a
        `kind` of `REFUND` and `refunded_cents` is updated accordingly."
        PRD §3.6: "The first payment recorded against an order takes a `kind` of
        `DEPOSIT`; every later one takes a `kind` of `BALANCE`."

        Design: Difficulty/compensating_invariant/cancel_refund_cash_conservation
        """
        order = self._scheduled_order_with_200000(api)
        validate_success(
            api.cancel_order(order["id"], {"reason": "found a better offer"}, SALES), 200
        )
        rows, meta = validate_paginated(api.list_order_payments(order["id"], FINANCE))
        assert meta["total_count"] == 3
        kinds = sorted(r["kind"] for r in rows)
        assert kinds == ["BALANCE", "DEPOSIT", "REFUND"]
        refund = next(r for r in rows if r["kind"] == "REFUND")
        assert refund["amount_cents"] == CANCEL_REFUND_SCHEDULED
        deposit = next(r for r in rows if r["kind"] == "DEPOSIT")
        assert deposit["amount_cents"] == DEPOSIT_10X12_WINDOW


def test_double_cancel_rejected(api):
    """PRD §3.6: "Cancellation is available to a `SalesRep` or the owning `Customer` from
    any state up through `SCHEDULED`, with an optional `reason`; cancelling an order that
    is `IN_PROGRESS`, `COMPLETED`, or `CLOSED` is rejected with `ERR_INVALID_STATE`."
    PRD §3.6: "When the refund is positive, the system records a payment with a `kind` of
    `REFUND` and `refunded_cents` is updated accordingly."

    Design: Corner/state_machines/order_double_cancel_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    first = validate_success(
        api.cancel_order(order["id"], {"reason": "first cancel"}, SALES), 200
    )
    assert first["status"] == "CANCELLED"
    res = api.cancel_order(order["id"], {"reason": "second cancel"}, SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    refreshed = validate_success(api.get_order(order["id"], SALES), 200)
    assert refreshed["status"] == "CANCELLED"
    assert refreshed["refunded_cents"] == 0, "nothing collected, so no refund rows"
