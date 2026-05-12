"""Refund requests, fulfillment events, and the refundable-remainder cap.

PRD references:
  - §3.7 Fulfillment, Partial Shipments, and the Refund Remainder
  - §3.8 Refund Requests: Submission, Decision, and Execution
  - §3.10 Commission, Channel Fees, Refund Reversals, and Per-Order Pinning
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    approve_refund,
    assert_refund_request,
    create_refund_request,
    create_refund_request_payload,
    current_clock_iso,
    emit_logistics,
    execute_refund,
    get_order,
    get_refund,
    list_escrow_ledger,
    make_backer_headers,
    make_platform_admin_headers,
    setup_charged_order,
    setup_charged_order_for_full_refund,
    shipment_line,
    validate_error,
    validate_success,
)


class TestRefundCreation:
    def test_refund_request_persists_pending_review(self, api):
        """PRD §3.8: 'The new request is persisted with status
        PENDING_REVIEW, approved_amount_cents null, rejection_reason null,
        and triggered_by set to BACKER, INITIATOR, or PLATFORM_AUTO per
        the originator.'

        Claim: backer-created refund → PENDING_REVIEW with triggered_by=BACKER.
        """
        _, _, _, backer, charged = setup_charged_order(
            category="TECH", reward_pledge_cents=10_000,
            funding_target_cents=1, with_tax_id=True,
        )
        res = api.create_refund_request(
            create_refund_request_payload(
                order_id=charged["id"],
                reason="DISPUTE",
                requested_amount_cents=2_000,
            ),
            make_backer_headers(backer["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_refund_request(data)
        assert data["status"] == "PENDING_REVIEW"
        assert data["triggered_by"] == "BACKER"
        assert data["approved_amount_cents"] in (None,)

    def test_refund_request_exceeds_remainder_rejected(self, api):
        """PRD §3.8: 'If the requested amount exceeds the linked order's
        current refundable_remainder_cents either at create time or at
        approve time, the request is rejected with
        ERR_REFUND_EXCEEDS_REMAINDER.'

        Claim: requested > order_total_cents → ERR_REFUND_EXCEEDS_REMAINDER.
        """
        _, _, _, backer, charged = setup_charged_order(
            category="TECH", reward_pledge_cents=10_000,
            funding_target_cents=1, with_tax_id=True,
        )
        res = api.create_refund_request(
            create_refund_request_payload(
                order_id=charged["id"],
                reason="DISPUTE",
                requested_amount_cents=charged["order_total_cents"] + 1,
            ),
            make_backer_headers(backer["id"]),
        )
        validate_error(res, "ERR_REFUND_EXCEEDS_REMAINDER")


class TestRefundApprove:
    def test_approve_sets_approved_amount(self, api, platform_admin_headers):
        """PRD §3.8: 'On approval, approved_amount_cents is set equal to
        requested_amount_cents, the request moves to APPROVED'.

        Claim: approve transitions PENDING_REVIEW → APPROVED with
        approved_amount_cents = requested_amount_cents.
        """
        _, _, _, backer, charged = setup_charged_order(
            category="TECH", reward_pledge_cents=10_000,
            funding_target_cents=1, with_tax_id=True,
        )
        refund = create_refund_request(
            order=charged, backer=backer,
            requested_amount_cents=3_000, reason="DISPUTE",
        )
        res = api.approve_refund(refund["id"], platform_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "APPROVED"
        assert data["approved_amount_cents"] == 3_000


class TestRefundExecutePartial:
    def test_execute_partial_refund_marks_order_partially_refunded(self, api):
        """PRD §3.8: 'otherwise — when approved_amount_cents is strictly
        less than the order's order_total_cents — the order moves to
        PARTIALLY_REFUNDED and refundable_remainder_cents is decreased by
        approved_amount_cents'.

        Claim: execute partial refund (<order_total) → order
        PARTIALLY_REFUNDED.
        """
        _, _, _, backer, charged = setup_charged_order(
            category="TECH", reward_pledge_cents=10_000,
            funding_target_cents=1, with_tax_id=True,
        )
        order_total = charged["order_total_cents"]
        refund = create_refund_request(
            order=charged, backer=backer,
            requested_amount_cents=4_000, reason="DISPUTE",
        )
        approve_refund(refund["id"])
        execute_refund(refund["id"])
        order_after = get_order(charged["id"])
        assert order_after["payment_status"] == "PARTIALLY_REFUNDED"
        assert order_after["refundable_remainder_cents"] == order_total - 4_000


class TestRefundExecuteFull:
    def test_execute_full_refund_transitions_to_refunded(self, api):
        """PRD §3.8: 'from CHARGED, when approved_amount_cents equals the
        order's refundable_remainder_cents and that remainder still
        equals the full order_total_cents (no shipments yet), the order
        moves to REFUNDED and refundable_remainder_cents is set to zero'.

        Claim: full refund of unshipped order → REFUNDED, remainder=0.
        """
        ctx = setup_charged_order_for_full_refund(
            category="ART", order_total_cents=10_000,
        )
        backer, charged = ctx["backer"], ctx["order"]
        refund = create_refund_request(
            order=charged, backer=backer,
            requested_amount_cents=charged["order_total_cents"],
            reason="DISPUTE",
        )
        approve_refund(refund["id"])
        execute_refund(refund["id"])
        order_after = get_order(charged["id"])
        assert order_after["payment_status"] == "REFUNDED"
        assert order_after["refundable_remainder_cents"] == 0

    def test_execute_full_refund_writes_refund_out_and_commission_reversal(
        self, api,
    ):
        """PRD §3.8: 'Two EscrowLedgerEntry records are written: a
        REFUND_OUT for the cash that leaves escrow, and a
        COMMISSION_REVERSAL whose magnitude is determined by the
        refund-commission-reversal calculation.'

        Claim: after executing a full refund, ledger has both REFUND_OUT
        and COMMISSION_REVERSAL entries for the order.
        """
        ctx = setup_charged_order_for_full_refund(
            category="ART", order_total_cents=10_000,
        )
        backer, charged, project = ctx["backer"], ctx["order"], ctx["project"]
        refund = create_refund_request(
            order=charged, backer=backer,
            requested_amount_cents=charged["order_total_cents"],
            reason="DISPUTE",
        )
        approve_refund(refund["id"])
        execute_refund(refund["id"])
        ledger = list_escrow_ledger(project["id"])
        order_id = charged["id"]
        types_for_order = {
            e["entry_type"] for e in ledger
            if e.get("order_id") == order_id
        }
        assert "REFUND_OUT" in types_for_order, (
            "PRD §3.8: REFUND_OUT must be written on refund execute."
        )
        assert "COMMISSION_REVERSAL" in types_for_order, (
            "PRD §3.8: COMMISSION_REVERSAL must be written on refund execute."
        )


class TestRefundReject:
    def test_reject_requires_rejection_reason(self, api,
                                              platform_admin_headers):
        """PRD §3.8: 'Rejection is also a PlatformAdmin operation and
        requires that the request is PENDING_REVIEW and that
        rejection_reason is provided; the request moves to terminal
        REJECTED with the supplied reason recorded'.

        Claim: reject with rejection_reason → status REJECTED, reason set.
        """
        _, _, _, backer, charged = setup_charged_order(
            category="TECH", reward_pledge_cents=10_000,
            funding_target_cents=1, with_tax_id=True,
        )
        refund = create_refund_request(
            order=charged, backer=backer,
            requested_amount_cents=2_000, reason="DISPUTE",
        )
        res = api.reject_refund(
            refund["id"], {"rejection_reason": "Beyond review window"},
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "Beyond review window"


class TestFulfillment:
    def test_partial_shipment_recomputes_remainder(self, api):
        """PRD §3.7: 'Once shipments arrive, the system aggregates the
        value of shipped lines for the order and resets
        refundable_remainder_cents to the maximum of zero and the order's
        order_total_cents minus the total shipped value.'

        Claim: shipment of 4000-value line on a 10000 order → remainder
        becomes 6000.
        """
        _, _, _, _, charged = setup_charged_order(
            category="TECH", reward_pledge_cents=10_000,
            funding_target_cents=1, with_tax_id=True,
        )
        emit_logistics(charged["id"], [shipment_line(4_000)])
        o = get_order(charged["id"])
        assert o["refundable_remainder_cents"] == 6_000
