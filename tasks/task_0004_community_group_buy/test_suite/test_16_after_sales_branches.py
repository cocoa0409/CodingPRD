"""After-sales: each resolution branch and re-open prevention."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_picked_up_order,
    file_after_sales, start_review, resolve_case,
    create_after_sales_payload,
    ADMIN, CS_AGENT, make_customer_headers,
)


class TestRefundOnlyResolution:

    def test_refund_only_advances_order_to_refund_pending(self, api):
        """PRD §3.8: "REFUND_ONLY ... synchronously advances the parent
        order's payment_status to REFUND_PENDING (the further REFUND_PENDING
        to REFUNDED transition is driven by the next payout-finalisation sweep)."

        Claim: resolving REFUND_ONLY moves the order's payment_status to
        REFUND_PENDING (not yet REFUNDED).
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        case = file_after_sales(sc["order"]["id"], sc["customer"]["id"], "REFUND_ONLY", 100)
        start_review(case["id"])
        resolve_case(case["id"], "REFUND_ONLY")
        order_after = validate_success(api.get_order(sc["order"]["id"], ADMIN), 200)
        assert order_after["payment_status"] == "REFUND_PENDING"


class TestPartialCompensationResolution:

    def test_partial_compensation_advances_to_partially_refunded(self, api):
        """PRD §3.8: "PARTIAL_COMPENSATION requires the case's case_type to
        be PARTIAL_COMPENSATION, sets resolved_amount_cents to the requested
        amount, advances the parent order's payment_status to
        PARTIALLY_REFUNDED, and increases the order's refunded_amount_cents
        by resolved_amount_cents."

        Claim: resolving PARTIAL_COMPENSATION moves the order to
        PARTIALLY_REFUNDED and increases refunded_amount_cents by the
        requested amount.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        order = sc["order"]
        before_refunded = order.get("refunded_amount_cents", 0)
        case = file_after_sales(order["id"], sc["customer"]["id"], "PARTIAL_COMPENSATION", 30)
        start_review(case["id"])
        resolve_case(case["id"], "PARTIAL_COMPENSATION")
        order_after = validate_success(api.get_order(order["id"], ADMIN), 200)
        assert order_after["payment_status"] == "PARTIALLY_REFUNDED"
        assert order_after["refunded_amount_cents"] == before_refunded + 30


class TestRejectResolution:

    def test_reject_sets_resolved_amount_zero_and_status_rejected(self, api):
        """PRD §3.8: "REJECT requires no case-type match; the case advances
        to REJECTED with resolved_amount_cents set to zero."

        Claim: resolving with outcome=REJECT sets the case's status to
        REJECTED and resolved_amount_cents to 0.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        case = file_after_sales(sc["order"]["id"], sc["customer"]["id"], "REFUND_ONLY", 100)
        start_review(case["id"])
        resolved = resolve_case(case["id"], "REJECT")
        assert resolved["status"] == "REJECTED"
        assert resolved["resolved_amount_cents"] == 0


class TestAlreadyOpenCase:

    def test_second_open_case_rejected_when_one_already_open(self, api):
        """PRD §3.8: "the order may carry at most one open (non-terminal)
        case at a time (a second filing while one is open is rejected with
        ERR_AFTER_SALES_ALREADY_OPEN)".

        Claim: filing a second case on the same order while the first is
        still non-terminal is rejected with ERR_AFTER_SALES_ALREADY_OPEN.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        file_after_sales(sc["order"]["id"], sc["customer"]["id"], "REFUND_ONLY", 50)
        res = api.file_after_sales(
            sc["order"]["id"],
            create_after_sales_payload("REFUND_ONLY", 30),
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, "ERR_AFTER_SALES_ALREADY_OPEN")
