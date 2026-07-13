"""Payment rules and the dispute lifecycle: the NEEDS_INFO revision cycle, the
buyer-favor refund/reversal cascade, and conservation of the seller payout
split across a post-settle reversal.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    operator_headers, make_buyer_headers, assert_payout_split_invariant,
    new_verified_buyer, get_order, create_dispute_payload,
    setup_closed_with_order, setup_paid_order, setup_dispute,
    setup_paid_order_with_extra_passed_lot,
)

OP = operator_headers()


# ==========================================================================
# Dispute NEEDS_INFO -> UNDER_REVIEW revision cycle (buyer step)
# ==========================================================================
class TestDisputeReviewCycle:
    def test_buyer_moves_needs_info_back_to_under_review(self, api):
        """PRD §3.8: "When a dispute is in NEEDS_INFO, the owning buyer — and only
        the buyer who owns the disputed order — moves it back NEEDS_INFO →
        UNDER_REVIEW, forming a revision cycle."

        Design: Difficulty/non_linear_state_machine/dispute_needs_info_review_cycle
        """
        s = setup_dispute(api, status="NEEDS_INFO")
        dispute = validate_success(
            api.update_dispute(s["dispute"]["id"],
                               {"status": "UNDER_REVIEW", "resolution_note": "photos"},
                               make_buyer_headers(s["buyer"]["id"])))
        assert dispute["status"] == "UNDER_REVIEW"

    def test_review_cycle_does_not_touch_payment(self, api):
        """PRD §3.8: "When a dispute is in NEEDS_INFO, the owning buyer — and only
        the buyer who owns the disputed order — moves it back NEEDS_INFO →
        UNDER_REVIEW, forming a revision cycle."

        Design: Difficulty/non_linear_state_machine/dispute_needs_info_review_cycle
        """
        s = setup_dispute(api, status="NEEDS_INFO")
        validate_success(
            api.update_dispute(s["dispute"]["id"], {"status": "UNDER_REVIEW"},
                               make_buyer_headers(s["buyer"]["id"])))
        order = get_order(api, s["order"]["id"])
        assert order["payment_status"] == "PAID"


# ==========================================================================
# Buyer-favor resolution: four-hop refund/reversal cascade
# ==========================================================================
class TestDisputeRefundCascade:
    def test_resolve_refunds_order_and_reverts_lot(self, api):
        """PRD §3.8: "First, the order moves PAID → REFUNDED and a REFUND Payment
        is appended equal to the disputed lot's share of the invoice — its
        hammer_price_cents plus that lot's portion of the premium and tax — and
        the order's amount_paid_cents is recomputed."
        PRD §3.8: "Second, the disputed lot moves SOLD → PASSED: its
        hammer_price_cents is cleared to null, its winning_order_id is cleared,
        and its winning bid's is_winning becomes false."

        Design: Difficulty/transitive_cascade/dispute_refund_cascade_order_lot_estate
        """
        s = setup_dispute(api, status="UNDER_REVIEW", settled=True)
        validate_success(api.update_dispute(
            s["dispute"]["id"], {"status": "RESOLVED", "outcome": "BUYER_FAVOR"}, OP))
        order = get_order(api, s["order"]["id"])
        assert order["payment_status"] == "REFUNDED"
        lot = validate_success(api.get_lot(s["lot"]["id"], OP))
        assert lot["status"] == "PASSED"
        assert lot["hammer_price_cents"] is None

    def test_resolve_removes_lot_and_reprices_order(self, api):
        """PRD §3.8: "Third, the lot is removed from the order's lot_ids, the
        order's subtotal_cents, buyer_premium_cents, sales_tax_cents, and
        total_cents are recomputed as in §3.4, and the buyer's gross_owed_cents
        and net_owed_cents are recomputed."

        Design: Difficulty/transitive_cascade/dispute_refund_cascade_order_lot_estate
        """
        s = setup_dispute(api, status="UNDER_REVIEW", settled=True)
        validate_success(api.update_dispute(
            s["dispute"]["id"], {"status": "RESOLVED", "outcome": "BUYER_FAVOR"}, OP))
        order = get_order(api, s["order"]["id"])
        assert s["lot"]["id"] not in order["lot_ids"]
        assert order["subtotal_cents"] == 0
        assert order["total_cents"] == 0


# ==========================================================================
# Payout split conserved across a post-settle buyer-favor reversal
# ==========================================================================
class TestPayoutSplitConserved:
    def test_reversal_rederives_estate_gross_to_zero(self, api):
        """PRD §3.8: "Fourth, if the estate is already SETTLED, its
        gross_sales_cents, commission_cents, and seller_payout_cents are
        re-derived from the reduced gross so that the
        payout-plus-commission-equals-gross identity continues to hold exactly."

        Design: Difficulty/compensating_invariant/payout_split_conserved_across_dispute_reversal
        """
        s = setup_dispute(api, status="UNDER_REVIEW", settled=True)
        # Before: gross 10000, commission 3500, payout 6500.
        validate_success(api.update_dispute(
            s["dispute"]["id"], {"status": "RESOLVED", "outcome": "BUYER_FAVOR"}, OP))
        estate = validate_success(api.get_estate(s["estate"]["id"], OP))
        assert estate["gross_sales_cents"] == 0
        assert estate["commission_cents"] == 0
        assert estate["seller_payout_cents"] == 0

    def test_payout_split_identity_holds_after_reversal(self, api):
        """PRD §3.7: "Because commission is the rounded term and the payout is the
        exact residual, the identity that the seller payout plus the commission
        equals the gross sales always holds exactly, and it is preserved whenever
        a later dispute reversal changes the gross (see §3.8)."

        Design: Difficulty/compensating_invariant/payout_split_conserved_across_dispute_reversal
        """
        s = setup_dispute(api, status="UNDER_REVIEW", settled=True)
        validate_success(api.update_dispute(
            s["dispute"]["id"], {"status": "RESOLVED", "outcome": "BUYER_FAVOR"}, OP))
        estate = validate_success(api.get_estate(s["estate"]["id"], OP))
        assert_payout_split_invariant(estate)


# ==========================================================================
# Payment corner cases
# ==========================================================================
def test_pay_insufficient_amount_rejected(api):
    """PRD §3.5: "The payload carries amount_cents, which must be greater than or
    equal to the order's total_cents; a short payment is rejected with
    ERR_INSUFFICIENT_PAYMENT (402)."

    Design: Corner/errors/pay_insufficient_amount
    """
    s = setup_closed_with_order(api, amount=10000)  # total 12690, UNPAID
    resp = api.pay_order(s["order"]["id"], {"amount_cents": 12000},
                         make_buyer_headers(s["buyer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PAYMENT.value)
    order = get_order(api, s["order"]["id"])
    assert order["payment_status"] == "UNPAID"


def test_pay_already_paid_order_rejected(api):
    """PRD §3.5: "Paying an order that is not in UNPAID payment status is
    rejected with ERR_ORDER_ALREADY_PAID (409)."

    Design: Corner/errors/pay_already_paid_order
    """
    s = setup_paid_order(api)
    resp = api.pay_order(s["order"]["id"], {"amount_cents": s["order"]["total_cents"]},
                         make_buyer_headers(s["buyer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_PAID.value)


def test_dispute_lot_not_in_order_rejected(api):
    """PRD §3.8: "The disputed lot must actually be part of that order — its
    lot_id must appear in the order's lot_ids — or the filing is rejected with
    ERR_LOT_NOT_IN_ORDER (409)."

    Design: Corner/errors/dispute_lot_not_in_order
    """
    s = setup_paid_order_with_extra_passed_lot(api)  # Lx not in order.lot_ids
    resp = api.create_dispute(
        create_dispute_payload(s["order"]["id"], s["lx"]["id"], reason="wrong lot"),
        make_buyer_headers(s["buyer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_IN_ORDER.value)


def test_buyer_cannot_pay_others_order(api):
    """PRD §2.1: "a mismatch between X-User-ID and the buyer_id of a bid or order
    (or the buyer_id of the order behind a dispute) is rejected with
    ERR_CROSS_OWNER (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_pay_others_order
    """
    s = setup_closed_with_order(api, amount=10000)  # order owned by B1, UNPAID
    b2 = new_verified_buyer(api, "B2", "b2@x.com")
    resp = api.pay_order(s["order"]["id"], {"amount_cents": s["order"]["total_cents"]},
                         make_buyer_headers(b2["id"]))
    validate_error(resp, ApiErrorId.ERR_CROSS_OWNER.value)
    order = get_order(api, s["order"]["id"])
    assert order["payment_status"] == "UNPAID"
