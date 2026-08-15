"""Broker commission tiering, installment splits, and the dispute loop
(PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_commission_invoice,
    assert_installment_conservation,
    get_invoices_for_loi,
    setup_executed_loi,
    validate_error,
    validate_success,
)

LM = TEST_USERS["leasing_manager_headers"]


class TestInstallmentRoundingOrder:
    """Nested rounding with a pinned order: tiers rounded before summing, the
    side-split remainder pinned to LANDLORD_REP, the installment remainder
    pinned to installment 2 (PRD §3.7)."""

    def test_invoice_literal_amounts(self, api):
        """PRD §3.7: "tier one is five percent of the basis up to a
        five-hundred-thousand-dollar cap, rounded half-up to cents; tier two
        is three percent of whatever basis exceeds that cap — zero when it
        does not — rounded half-up to cents; and the combined commission is
        the sum of the two rounded tiers, tiers always rounded before
        summing, never after. The tenant-side invoice's `total_commission` is
        one half of the combined amount, rounded half-up to cents; the
        landlord-side invoice's `total_commission` is the combined amount
        minus the tenant side, pinning any half-cent remainder to
        `LANDLORD_REP`."

        Design: Difficulty/combinatorial_formula/commission_installment_rounding_order
        """
        bundle = setup_executed_loi(commission_basis="GROSS_AGGREGATE")
        tenant_inv, landlord_inv = get_invoices_for_loi(bundle["loi"]["id"])
        for inv in (tenant_inv, landlord_inv):
            assert_commission_invoice(inv)
            assert inv["commission_basis_amount"] == pytest.approx(
                4247308.65, abs=0.005
            )
            # tier1 25000.00 + tier2 112419.26 = 137419.26 combined; half is
            # 68709.63 for each side here (combined is even at the cent).
            assert inv["total_commission"] == pytest.approx(
                68709.63, abs=0.005
            ), (
                f"{inv['broker_side']} total_commission must be 68709.63, "
                f"got {inv['total_commission']}"
            )
            assert inv["installment_1_amount"] == pytest.approx(
                34354.82, abs=0.005
            )
            assert inv["installment_2_amount"] == pytest.approx(
                34354.81, abs=0.005
            )

    def test_installment_remainder_pinned_forward(self, api):
        """PRD §3.7: "Each invoice splits its `total_commission` into two
        installments with the remainder pinned forward: `installment_1_amount`
        is one half of `total_commission`, rounded half-up to cents, and falls
        due at lease execution; `installment_2_amount` is `total_commission`
        minus `installment_1_amount` and falls due only at rent commencement".

        Design: Difficulty/combinatorial_formula/commission_installment_rounding_order
        """
        bundle = setup_executed_loi(commission_basis="GROSS_AGGREGATE")
        tenant_inv, landlord_inv = get_invoices_for_loi(bundle["loi"]["id"])
        for inv in (tenant_inv, landlord_inv):
            i1 = inv["installment_1_amount"]
            i2 = inv["installment_2_amount"]
            total = inv["total_commission"]
            assert i1 + i2 == pytest.approx(total, abs=0.0001), (
                f"installment_1 + installment_2 must equal total_commission "
                f"exactly (no cent drift): {i1} + {i2} != {total}"
            )
            assert i1 - i2 == pytest.approx(0.01, abs=0.0001), (
                "The half-cent remainder of the installment split is pinned "
                "to the second installment"
            )


class TestDisputeLoopConservation:
    """Money is conserved across the issue -> dispute -> re-issue cycle
    (PRD §3.7)."""

    def _setup_paid_tenant_invoice(self, api):
        bundle = setup_executed_loi(commission_basis="GROSS_AGGREGATE")
        tenant_inv, landlord_inv = get_invoices_for_loi(bundle["loi"]["id"])
        validate_success(api.issue_commission_invoice(tenant_inv["id"], LM))
        paid = validate_success(
            api.pay_commission_invoice(
                tenant_inv["id"], {"installment_number": 1}, LM
            )
        )
        assert paid["status"] == "PARTIALLY_PAID"
        return bundle, paid, landlord_inv

    def test_dispute_reissue_preserves_amounts(self, api):
        """PRD §3.7: "re-issuing a disputed invoice returns it `DISPUTED` →
        `INVOICED`, clears `dispute_reason` to null, and leaves every amount
        unchanged, so the dispute loop may repeat."

        Design: Difficulty/compensating_invariant/commission_installment_split_conservation
        """
        _bundle, _tenant_paid, landlord_inv = self._setup_paid_tenant_invoice(api)
        validate_success(api.issue_commission_invoice(landlord_inv["id"], LM))
        disputed = validate_success(
            api.dispute_commission_invoice(
                landlord_inv["id"], {"reason": "basis should be net effective"}, LM
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "basis should be net effective"

        reissued = validate_success(
            api.issue_commission_invoice(landlord_inv["id"], LM)
        )
        assert reissued["status"] == "INVOICED"
        assert reissued.get("dispute_reason") is None, (
            "Re-issuing a disputed invoice must clear dispute_reason to null"
        )
        assert reissued["total_commission"] == pytest.approx(68709.63, abs=0.005)
        assert reissued["installment_1_amount"] == pytest.approx(
            34354.82, abs=0.005
        )
        assert reissued["installment_2_amount"] == pytest.approx(
            34354.81, abs=0.005
        )
        assert_installment_conservation(reissued)

    def test_no_cross_talk_between_invoices(self, api):
        """PRD §3.7: "Commission amounts are computed exactly once, at
        execution, from the LOI's final terms, and they never recompute
        afterward." and "re-issuing a disputed invoice ... leaves every amount
        unchanged".

        Design: Difficulty/compensating_invariant/commission_installment_split_conservation
        """
        bundle, tenant_paid, landlord_inv = self._setup_paid_tenant_invoice(api)
        validate_success(api.issue_commission_invoice(landlord_inv["id"], LM))
        validate_success(
            api.dispute_commission_invoice(
                landlord_inv["id"], {"reason": "basis should be net effective"}, LM
            )
        )
        validate_success(api.issue_commission_invoice(landlord_inv["id"], LM))

        tenant_after = validate_success(
            api.get_commission_invoice(tenant_paid["id"], LM)
        )
        assert tenant_after["status"] == "PARTIALLY_PAID", (
            "A dispute on the LANDLORD_REP invoice must not disturb the "
            "TENANT_REP invoice"
        )
        assert tenant_after["installment_1_paid"] is True
        assert tenant_after["total_commission"] == pytest.approx(
            68709.63, abs=0.005
        )
        landlord_after = validate_success(
            api.get_commission_invoice(landlord_inv["id"], LM)
        )
        combined = tenant_after["total_commission"] + landlord_after[
            "total_commission"
        ]
        assert combined == pytest.approx(137419.26, abs=0.005), (
            f"The two sides must sum to the tiered combined commission "
            f"137419.26, got {combined}"
        )


class TestInstallmentDueGate:
    def test_installment_2_pay_before_due_returns_409(self, api):
        """PRD §3.7: "installment 2 is accepted only from `PARTIALLY_PAID` —
        attempting it before installment 1 has landed fails the state check
        with `ERR_INVALID_STATE` — and only once `installment_2_due` is true,
        otherwise `ERR_INSTALLMENT_NOT_DUE` (409)".

        Design: Corner/validations/installment_2_pay_before_due_returns_409
        """
        bundle = setup_executed_loi(commission_basis="GROSS_AGGREGATE")
        tenant_inv, _landlord_inv = get_invoices_for_loi(bundle["loi"]["id"])
        validate_success(api.issue_commission_invoice(tenant_inv["id"], LM))
        validate_success(
            api.pay_commission_invoice(
                tenant_inv["id"], {"installment_number": 1}, LM
            )
        )
        # The site is COMMITTED, not yet LEASED, so installment_2_due is false.
        resp = api.pay_commission_invoice(
            tenant_inv["id"], {"installment_number": 2}, LM
        )
        validate_error(resp, ApiErrorId.ERR_INSTALLMENT_NOT_DUE)
        after = validate_success(api.get_commission_invoice(tenant_inv["id"], LM))
        assert after["status"] == "PARTIALLY_PAID"
        assert after["installment_2_paid"] is False
