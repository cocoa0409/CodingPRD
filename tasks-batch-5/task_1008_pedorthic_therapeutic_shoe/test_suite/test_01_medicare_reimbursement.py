"""Medicare reimbursement arithmetic: provisional-vs-final divergence, the nested-min
deductible absorption, and deductible reconciliation on a paid claim."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    assert_claim_reimbursement_invariant,
)
from test_helpers import fixtures as fx

BS = TEST_USERS["billing_specialist_headers"]


class TestProvisionalVsFinalReimbursement:
    """A single diabetic claim: the optimistic provisional (24000) diverges from the
    deductible-aware final medicare_paid (3440)."""

    def test_provisional_reimbursement_ignores_deductible(self, api):
        """PRD §3.6: "sets `allowed_amount_cents` to the lesser of `billed_amount_cents`
        and the product's `medicare_allowable_cents`, and computes the optimistic
        `provisional_reimbursement_cents` as `allowed_amount_cents` times 0.80 (that is,
        one minus the 20% coinsurance rate) rounded half up."

        Design: Difficulty/dual_variant_calc/medicare_provisional_vs_final_reimbursement
        """
        ctx = fx.setup_fulfilled_medicare_sale(price=32000, allowable=30000, hcpcs="A5500")
        claim = fx.create_draft_claim(ctx, hcpcs="A5500", billed=32000)
        submitted = validate_success(api.submit_claim(claim["id"], BS))
        assert submitted["allowed_amount_cents"] == 30000, "allowed = min(32000, 30000)"
        assert submitted["provisional_reimbursement_cents"] == 24000, "provisional = round(30000*0.80)"

    def test_final_reimbursement_subtracts_full_deductible(self, api):
        """PRD §3.6: "The `deductible_applied_cents` for this claim is the lesser of
        `allowed_amount_cents` and that remaining deductible. The amount after the
        deductible is `allowed_amount_cents` minus `deductible_applied_cents`; the
        coinsurance is that after-deductible amount times the 20% coinsurance rate,
        rounded half up; `medicare_paid_cents` is the after-deductible amount minus the
        coinsurance; and `patient_responsibility_cents` is `deductible_applied_cents`
        plus the coinsurance."

        Design: Difficulty/dual_variant_calc/medicare_provisional_vs_final_reimbursement
        """
        ctx = fx.setup_fulfilled_medicare_sale(price=32000, allowable=30000, hcpcs="A5500")
        claim = fx.create_draft_claim(ctx, hcpcs="A5500", billed=32000)
        fx.submit_claim(claim["id"])
        paid = validate_success(api.adjudicate_claim(claim["id"], {"payer_decision": "PAID"}, BS))
        # deductible_remaining = 25700 (no prior PAID); applied = min(30000, 25700) = 25700
        # after = 4300; coinsurance = round(4300*0.20) = 860; medicare_paid = 3440
        assert paid["medicare_paid_cents"] == 3440
        assert paid["patient_responsibility_cents"] == 26560
        assert_claim_reimbursement_invariant(paid)


class TestNestedMinDeductibleAbsorption:
    """billed 20000 below allowable 30000: allowed=20000 (billed wins), then the 25700
    deductible fully absorbs it, so medicare_paid=0 and patient_responsibility=20000."""

    def test_allowed_amount_and_deductible_absorb_billed(self, api):
        """PRD §3.6: "sets `allowed_amount_cents` to the lesser of `billed_amount_cents`
        and the product's `medicare_allowable_cents`."
        PRD §3.6: "The `deductible_applied_cents` for this claim is the lesser of
        `allowed_amount_cents` and that remaining deductible."

        Design: Difficulty/combinatorial_formula/medicare_final_nested_min_deductible_absorption
        """
        ctx = fx.setup_fulfilled_medicare_sale(price=24000, allowable=30000, hcpcs="A5500")
        claim = fx.create_draft_claim(ctx, hcpcs="A5500", billed=20000)
        fx.submit_claim(claim["id"])
        paid = validate_success(api.adjudicate_claim(claim["id"], {"payer_decision": "PAID"}, BS))
        assert paid["allowed_amount_cents"] == 20000, "allowed = min(20000, 30000)"
        assert paid["deductible_applied_cents"] == 20000, "deductible_applied = min(20000, 25700)"

    def test_medicare_pays_zero_when_deductible_absorbs_all(self, api):
        """PRD §3.6: "`medicare_paid_cents` is the after-deductible amount minus the
        coinsurance; and `patient_responsibility_cents` is `deductible_applied_cents`
        plus the coinsurance. By construction `medicare_paid_cents` plus
        `patient_responsibility_cents` equals `allowed_amount_cents`."

        Design: Difficulty/combinatorial_formula/medicare_final_nested_min_deductible_absorption
        """
        ctx = fx.setup_fulfilled_medicare_sale(price=24000, allowable=30000, hcpcs="A5500")
        claim = fx.create_draft_claim(ctx, hcpcs="A5500", billed=20000)
        fx.submit_claim(claim["id"])
        paid = validate_success(api.adjudicate_claim(claim["id"], {"payer_decision": "PAID"}, BS))
        # after_deductible = 20000 - 20000 = 0; coinsurance = 0; medicare_paid = 0
        assert paid["medicare_paid_cents"] == 0
        assert paid["patient_responsibility_cents"] == 20000
        assert_claim_reimbursement_invariant(paid)


def test_deductible_remaining_reconciles_to_zero_after_paid_claim(api):
    """PRD §3.6: "`medicare_deductible_remaining_cents` is 25,700 cents minus the sum of
    `deductible_applied_cents` over those same-year `PAID` claims."
    PRD §3.6: "Reaching `PAID` consumes the customer's annual allowance and deductible,
    so `medicare_pairs_claimed_ytd`, `medicare_inserts_claimed_ytd`, and
    `medicare_deductible_remaining_cents` all recompute to include this claim."

    Design: Corner/cross_cutting_complexity_layers/derived_deductible_reconciled_after_paid_claim
    """
    ctx = fx.setup_fulfilled_medicare_sale(price=32000, allowable=30000, hcpcs="A5500")
    claim = fx.create_draft_claim(ctx, hcpcs="A5500", billed=32000)
    fx.submit_claim(claim["id"])
    fx.adjudicate_claim(claim["id"], "PAID")
    customer = get_success_data(api.get_customer(ctx["customer"]["id"], BS))
    assert customer["medicare_deductible_remaining_cents"] == 0
    assert customer["medicare_pairs_claimed_ytd"] == 1
