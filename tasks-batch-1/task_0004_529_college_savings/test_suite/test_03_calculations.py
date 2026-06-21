"""Calculation tests: earnings_ratio (pre/post-disbursal), k12_excess_calc,
excess_withdrawal_penalty, state_tax_incentive_match (CA cap-then-rate vs NY tiered)."""
from test_helpers import (
    validate_success,
    setup_donor_beneficiary_account,
    setup_account_with_earnings,
    set_clock,
    create_and_post_contribution,
    credit_market_earnings,
    create_draft_withdrawal,
    submit_withdrawal,
    approve_withdrawal,
    disburse_withdrawal,
    create_state_tax_incentive,
    calculate_state_tax_incentive,
    get_account,
    make_compliance_headers,
    make_account_owner_headers,
    make_custodian_headers,
)


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc
# ---------------------------------------------------------------------------

class TestEarningsRatioDualVariant:
    def test_earnings_ratio_pre_vs_post_disbursal_divergence(self, api):
        """PRD §3.6: "Step one computes the earnings_portion_cents as the withdrawal's amount_cents
        multiplied by the account's total_earnings_cents, divided by the account's
        account_balance_cents, rounded half-up to the nearest whole cent — the rounding is
        applied to this single withdrawal, not deferred to a sum across multiple withdrawals.
        Step two computes the basis_portion_cents as the withdrawal's amount_cents minus the
        just-rounded earnings_portion_cents, so that the two parts add exactly to amount_cents."
        PRD §3.6: "The post-disbursal audit capability — a read-only operation exposed only to a
        ComplianceOfficer — recomputes the basis/earnings split for an already-finalised
        withdrawal against current account totals (that is, after this withdrawal and any
        subsequent posted contributions or disbursed withdrawals have already updated the
        ledger). The pinned fields on the withdrawal row are not mutated by this audit; the
        response simply returns what the split would be if recomputed today."

        Design: Difficulty/dual_variant_calc/earnings_ratio_pre_vs_post_disbursal_divergence
        """
        # Stage the account: balance=500000 basis=300000 earnings=200000.
        donor, _ben, _account, a_v_after_market = setup_account_with_earnings(
            contribution_cents=300_000,
            market_credit_cents=200_000,
            donor_email="d1@x.com",
        )
        account_id = _account["id"]
        # W1 NON_QUALIFIED 100000 — earnings_portion = round_half_up(100000*200000/500000) = 40000.
        w1 = create_draft_withdrawal(account_id, donor["id"], 100_000, "NON_QUALIFIED")
        submit_withdrawal(w1["id"], donor["id"])
        approved = approve_withdrawal(w1["id"], a_v_after_market)
        assert approved["basis_portion_cents"] == 60_000
        assert approved["earnings_portion_cents"] == 40_000
        assert approved["penalty_cents"] == 4_000  # 0.10 * 40000
        disburse_withdrawal(w1["id"])
        # After W1 disburse: balance=400000 basis=240000 earnings=160000.
        # Post a new 200000 contribution: balance=600000 basis=440000 earnings=160000.
        create_and_post_contribution(account_id, 200_000)
        # Audit: basis=round_half_up(100000*440000/600000)=73333, earnings=26667.
        audit_resp = api.audit_withdrawal(w1["id"], make_compliance_headers())
        audit_data = validate_success(audit_resp, expected_status=200)
        assert audit_data["basis_portion_cents"] == 73_333
        assert audit_data["earnings_portion_cents"] == 26_667
        # Pinned fields on the withdrawal row are not mutated.
        get_resp = api.get_withdrawal(w1["id"], make_compliance_headers())
        stored = validate_success(get_resp, expected_status=200)
        assert stored["basis_portion_cents"] == 60_000
        assert stored["earnings_portion_cents"] == 40_000

    def test_state_tax_incentive_ca_cap_vs_ny_tiered_divergence(self, api):
        """PRD §3.8: "For donors in California, the match is the lesser of the eligible
        contributions or 600,000 cents ($6,000 — the CA annual cap), multiplied by the
        California rate of 0.10 (10%), rounded half-up to whole cents. For donors in New York,
        the match is computed in two tiers and summed: the first tier applies a 5% rate to the
        eligible contributions up to the NY first-tier ceiling of 500,000 cents ($5,000); the
        second tier applies a 2% rate to eligible contributions that sit between the NY
        first-tier ceiling of 500,000 cents and the NY absolute upper bound of 1,000,000 cents
        ($10,000); each tier is rounded half-up to whole cents independently before the two are
        summed (this is per-tier rounding, not sum-then-round)."

        Design: Difficulty/dual_variant_calc/state_tax_incentive_ca_cap_vs_ny_tiered_divergence
        """
        set_clock("2026-03-01T00:00:00.000Z")
        # CA donor with 800000 cents posted.
        ca_donor, _b_ca, a_ca = setup_donor_beneficiary_account(
            clock_iso=None, donor_email="dca@x.com", donor_state="CA", donor_tax_id="1111",
            beneficiary_tax_id="3333",
        )
        create_and_post_contribution(a_ca["id"], 800_000)
        # NY donor with 800000 cents posted.
        ny_donor, _b_ny, a_ny = setup_donor_beneficiary_account(
            clock_iso=None,
            donor_email="dny@x.com",
            donor_state="NY",
            donor_tax_id="2222",
            beneficiary_tax_id="4444",
        )
        create_and_post_contribution(a_ny["id"], 800_000)
        sti_ca = create_state_tax_incentive(ca_donor["id"], 2026)
        sti_ny = create_state_tax_incentive(ny_donor["id"], 2026)
        ca_result = calculate_state_tax_incentive(sti_ca["id"])
        ny_result = calculate_state_tax_incentive(sti_ny["id"])
        # CA: min(800000, 600000) * 0.10 = 60000.
        assert ca_result["match_cents"] == 60_000
        # NY: tier1=500000*0.05=25000; tier2=300000*0.02=6000; total=31000.
        assert ny_result["match_cents"] == 31_000
        assert ca_result["status"] == "CALCULATED"
        assert ny_result["status"] == "CALCULATED"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula
# ---------------------------------------------------------------------------

class TestCombinatorialFormulas:
    def test_excess_withdrawal_penalty_multi_input_nonlinear(self, api):
        """PRD §3.6: "The system first computes a penalty_base_cents value according to fixed
        branching: when the expense_class is NON_QUALIFIED, the penalty base is the entire
        earnings_portion_cents just pinned; otherwise, when the expense_class is K_12_TUITION
        and the k12_excess_cents is strictly greater than zero, the penalty base is the
        earnings_portion_cents multiplied by k12_excess_cents divided by amount_cents, rounded
        half-up to whole cents (this is the earnings share of the excess portion only);
        otherwise, the penalty base is zero. The penalty_cents is then that penalty_base_cents
        multiplied by the federal penalty rate of 0.10 (10%), again rounded half-up to whole
        cents."

        Design: Difficulty/combinatorial_formula/excess_withdrawal_penalty_multi_input_nonlinear
        """
        # Build balance=3000000 basis=2000000 earnings=1000000.
        donor, _ben, _acc, a_v1 = setup_account_with_earnings(
            contribution_cents=1_000_000,
            market_credit_cents=1_000_000,
            donor_email="d2@x.com",
        )
        account_id = _acc["id"]
        # Need one more 1000000 contribution to reach balance=3000000.
        # The helper already posts one 1M contribution + 1M earnings credit -> balance=2000000, basis=1000000, earnings=1000000.
        # Add second 1M contribution: balance=3000000, basis=2000000, earnings=1000000.
        create_and_post_contribution(account_id, 1_000_000)
        a_v_after = get_account(account_id)["version"]
        # W1 K_12 600000 -> earnings_portion = round_half_up(600000*1000000/3000000) = 200000; k12_excess=0; penalty=0.
        w1 = create_draft_withdrawal(account_id, donor["id"], 600_000, "K_12_TUITION")
        submit_withdrawal(w1["id"], donor["id"])
        w1_approved = approve_withdrawal(w1["id"], a_v_after)
        assert w1_approved["k12_excess_cents"] == 0
        assert w1_approved["penalty_cents"] == 0
        disburse_withdrawal(w1["id"])
        a_v3 = get_account(account_id)["version"]
        # After W1 disburse: balance=2400000, basis=1600000, earnings=800000. ytd_k12=600000.
        # W2 K_12 600000 -> projected ytd=1200000 -> k12_excess=200000.
        # earnings_portion = round_half_up(600000*800000/2400000) = 200000.
        # penalty_base = round_half_up(200000*200000/600000) = 66667.
        # penalty = round_half_up(66667*0.10) = 6667.
        w2 = create_draft_withdrawal(account_id, donor["id"], 600_000, "K_12_TUITION")
        submit_withdrawal(w2["id"], donor["id"])
        approved2 = approve_withdrawal(w2["id"], a_v3)
        assert approved2["earnings_portion_cents"] == 200_000
        assert approved2["basis_portion_cents"] == 400_000
        assert approved2["k12_excess_cents"] == 200_000
        assert approved2["penalty_cents"] == 6_667

    def test_ny_tiered_match_pinned_per_tier_rounding_order(self, api):
        """PRD §3.8: "the second tier applies a 2% rate to eligible contributions that sit between
        the NY first-tier ceiling of 500,000 cents and the NY absolute upper bound of 1,000,000
        cents ($10,000); each tier is rounded half-up to whole cents independently before the
        two are summed (this is per-tier rounding, not sum-then-round). The pinned ordering is
        tier one first, then tier two."

        Design: Difficulty/combinatorial_formula/ny_tiered_match_pinned_per_tier_rounding_order
        """
        donor, _ben, account = setup_donor_beneficiary_account(
            donor_email="dny2@x.com", donor_state="NY"
        )
        create_and_post_contribution(account["id"], 1_000_000)
        sti = create_state_tax_incentive(donor["id"], 2026)
        result = calculate_state_tax_incentive(sti["id"])
        # tier1=500000*0.05=25000; tier2=500000*0.02=10000; total=35000.
        assert result["match_cents"] == 35_000
        assert result["contributions_eligible_cents"] == 1_000_000


# ---------------------------------------------------------------------------
# Corner/calculations
# ---------------------------------------------------------------------------

class TestStateTaxIncentiveOtherStates:
    def test_state_tax_incentive_match_il_donor_zero(self, api):
        """PRD §3.8: "For donors in Illinois, Texas, Florida, or Ohio, no schedule applies and
        match_cents is pinned at zero — these states pass the supported-state check at donor
        creation but have no incentive schedule in scope here."

        Design: Corner/calculations/state_tax_incentive_match_il_donor_zero
        """
        donor, _ben, account = setup_donor_beneficiary_account(
            donor_email="dil@x.com", donor_state="IL"
        )
        create_and_post_contribution(account["id"], 800_000)
        sti = create_state_tax_incentive(donor["id"], 2026)
        result = calculate_state_tax_incentive(sti["id"])
        assert result["match_cents"] == 0
        assert result["status"] == "CALCULATED"

    def test_state_tax_incentive_input_set_excludes_reversed_contributions(self, api):
        """PRD §3.4: "Reversing a posted contribution drives it from POSTED to the terminal
        REVERSED. ... On success, the same re-aggregation pass refreshes the account's
        account_balance_cents, total_basis_cents, and total_earnings_cents; Account.version is
        incremented; and the donor's StateTaxIncentive for the original tax_year is recomputed."
        PRD §3.4: "Finally, the donor's matching StateTaxIncentive for the contribution's tax_year
        — if one exists — has its contributions_eligible_cents re-aggregated from scratch
        across the donor's accounts."

        Design: Corner/calculations/state_tax_incentive_input_set_excludes_reversed_contributions
        """
        donor, _ben, account = setup_donor_beneficiary_account(
            donor_email="drx@x.com", donor_state="CA"
        )
        create_and_post_contribution(account["id"], 300_000)
        # Second contribution which will be reversed within 72h.
        post2 = create_and_post_contribution(account["id"], 300_000)
        # Advance clock by 1 day, then reverse the second one.
        set_clock("2026-03-02T00:00:00.000Z")
        reverse_resp = api.reverse_contribution(post2["id"], make_custodian_headers())
        validate_success(reverse_resp, expected_status=200)
        sti = create_state_tax_incentive(donor["id"], 2026)
        # contributions_eligible_cents must now reflect only the still-POSTED contribution.
        assert sti["contributions_eligible_cents"] == 300_000
        result = calculate_state_tax_incentive(sti["id"])
        # CA: 300000 * 0.10 = 30000.
        assert result["match_cents"] == 30_000

    def test_earnings_ratio_zero_earnings_branch(self, api):
        """PRD §3.6: "Two edge cases override the formula: when the account's total_earnings_cents
        is zero or negative, the earnings_portion_cents is set to zero and the
        basis_portion_cents is set to the full amount_cents; when the account's
        account_balance_cents is zero the withdrawal would have already been rejected by the
        insufficient-balance precondition, so the formula is not reached."

        Design: Corner/calculations/earnings_ratio_zero_earnings_branch
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="dze@x.com")
        posted = create_and_post_contribution(account["id"], 200_000)
        a_v = posted["version"]
        w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        approved = approve_withdrawal(w["id"], a_v)
        assert approved["earnings_portion_cents"] == 0
        assert approved["basis_portion_cents"] == 50_000
        assert approved["penalty_cents"] == 0
