"""Difficulty-design coverage: Rule 3 — Non-linear state machines.

Two instances:
  - after_sales_evidence_loop
  - order_parallel_payment_fulfillment
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_picked_up_order, setup_paid_succeeded_order,
    file_after_sales, start_review,
    plan_shipments_for_order,
    ADMIN, CS_AGENT, make_customer_headers, make_supplier_headers,
    create_resolve_payload,
)


class TestAfterSalesEvidenceLoop:
    """# difficulty: non_linear_state_machine/after_sales_evidence_loop"""

    def _setup_to_evidence_round_2(self):
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        order = sc["order"]
        # File after-sales for full settled total
        case = file_after_sales(order["id"], sc["customer"]["id"],
                                "REFUND_ONLY", order["settled_total_cents"])
        case = start_review(case["id"])
        # Round 1
        case = get_success_data(api_client.request_evidence(case["id"], CS_AGENT))
        case = get_success_data(api_client.submit_evidence(case["id"],
                                                            make_customer_headers(sc["customer"]["id"])))
        # Round 2
        case = get_success_data(api_client.request_evidence(case["id"], CS_AGENT))
        case = get_success_data(api_client.submit_evidence(case["id"],
                                                            make_customer_headers(sc["customer"]["id"])))
        return sc, case

    def test_third_evidence_request_rejected_after_two_cycles(self, api):
        """PRD §3.8: "Evidence requests require the case's evidence_round to
        currently be below 2; a third request is rejected with ERR_INVALID_STATE."

        Claim: after two complete UNDER_REVIEW↔EVIDENCE_REQUESTED cycles
        (evidence_round=2), a third request-evidence call is rejected with
        ERR_INVALID_STATE.
        """
        sc, case = self._setup_to_evidence_round_2()
        assert case["evidence_round"] == 2
        assert case["status"] == "UNDER_REVIEW"
        res = api.request_evidence(case["id"], CS_AGENT)
        validate_error(res, "ERR_INVALID_STATE")

    def test_after_rejected_third_request_case_state_unchanged(self, api):
        """PRD §3.8: "Evidence requests require the case's evidence_round to
        currently be below 2; a third request is rejected with ERR_INVALID_STATE."

        Claim: when the third request-evidence is rejected, the case stays
        in UNDER_REVIEW with evidence_round still at 2.
        """
        sc, case = self._setup_to_evidence_round_2()
        api.request_evidence(case["id"], CS_AGENT)  # rejected
        case_after = validate_success(api.get_after_sales_case(case["id"], ADMIN), 200)
        assert case_after["status"] == "UNDER_REVIEW"
        assert case_after["evidence_round"] == 2


class TestOrderParallelPaymentFulfillment:
    """# difficulty: non_linear_state_machine/order_parallel_payment_fulfillment"""

    def test_settled_payment_with_planned_fulfillment_after_plan_shipments(self, api):
        """PRD §2.7 / §3.6: "The Order row carries two parallel state
        dimensions: payment_status and fulfillment_status evolve on
        independent rails, and a single mutation may advance one without
        touching the other."

        Claim: after pay+close, payment_status=SETTLED, fulfillment_status=NOT_PLANNED.
        After plan-shipments, payment_status remains SETTLED while
        fulfillment_status advances to PLANNED.
        """
        sc = setup_paid_succeeded_order(unit_price_cents=100, quantity=1)
        order_before = sc["order"]
        assert order_before["payment_status"] == "SETTLED"
        assert order_before["fulfillment_status"] == "NOT_PLANNED"

        plan_shipments_for_order(
            order_before["id"], sc["supplier"]["id"], sc["pickup_point"]["id"],
            line_units=[{"sku": "SKUA", "quantity": 1}],
        )
        order_after = validate_success(api.get_order(order_before["id"], ADMIN), 200)
        assert order_after["payment_status"] == "SETTLED"
        assert order_after["fulfillment_status"] == "PLANNED"

    def test_payment_status_unaffected_by_fulfillment_progression(self, api):
        """PRD §2.7: "The Order row carries two parallel state dimensions:
        payment_status and fulfillment_status evolve on independent rails,
        and a single mutation may advance one without touching the other."

        Claim: after a SETTLED order's full fulfillment progression to
        PICKED_UP, payment_status remains SETTLED — the fulfillment rail
        does not subsume the payment rail.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        order = sc["order"]
        assert order["fulfillment_status"] == "PICKED_UP"
        assert order["payment_status"] == "SETTLED"
