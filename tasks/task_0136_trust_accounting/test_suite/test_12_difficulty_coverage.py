"""Difficulty-design coverage — at least two tests per declared
instance per the test-targeting index.

Each test docstring carries a ``# difficulty: <rule_id>/<instance>``
tag so coverage can be audited. Each test pins to a verbatim PRD
sentence stating the underlying rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_asset,
    add_beneficiary,
    add_tax_year,
    add_trustee,
    advance_clock_to,
    amend_tax_year,
    api_client,
    approve_distribution,
    begin_close_tax_year,
    book_transaction,
    create_distribution_payload,
    create_transaction_payload,
    execute_distribution,
    finalize_tax_year,
    iso_instant_utc,
    list_k1s_for_year,
    propose_distribution,
    re_get_trust,
    setup_activatable_trust,
    setup_active_trust,
    setup_active_trust_with_principal,
    setup_active_trust_with_proposed_income_distribution,
    setup_closed_tax_year,
    setup_draft_trust,
    setup_exemption_almost_consumed_trust,
    setup_grantor_vs_non_grantor_pair,
    setup_skip_person_distribution_pair,
    setup_tax_year_in_amend_state,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_grantor_vs_non_grantor_taxable_income_non_grantor_path(
        self, api,
    ):
        """# difficulty: dual_variant_calc/grantor_vs_non_grantor_trust_taxable_income

        PRD §3.8: "The Trust's trust_taxable_income is then the
        TaxYear's dni minus that sum, floored at zero, rounded
        half-up to two decimal places."

        Claim: under the NON_GRANTOR variant, DNI=10,000 with
        3,000 executed income distribution yields
        trust_taxable_income = 7,000.00.
        """
        non_grantor, _ = setup_grantor_vs_non_grantor_pair()
        assert non_grantor.tax_year["status"] == "CLOSED"
        assert non_grantor.tax_year["trust_taxable_income"] == (
            pytest.approx(7_000.00, abs=0.01)
        )

    def test_grantor_vs_non_grantor_taxable_income_grantor_path(
        self, api,
    ):
        """# difficulty: dual_variant_calc/grantor_vs_non_grantor_trust_taxable_income

        PRD §3.8: "Under the grantor variant ... the Trust's
        trust_taxable_income is forced to 0.00 regardless of dni,
        and the Trust's trust_income_tax is also 0.00."

        Claim: under the GRANTOR variant the same inputs produce
        trust_taxable_income=0.00 and trust_income_tax=0.00.
        """
        _, grantor = setup_grantor_vs_non_grantor_pair()
        assert grantor.tax_year["trust_taxable_income"] == (
            pytest.approx(0.00, abs=0.01)
        )
        assert grantor.tax_year["trust_income_tax"] == (
            pytest.approx(0.00, abs=0.01)
        )

    def test_skip_distribution_gst_tax_skip_path(self, api):
        """# difficulty: dual_variant_calc/skip_vs_non_skip_distribution_gst_tax

        PRD §3.6: "If the beneficiary is a skip person, the taxable
        portion is the total amount minus the remaining exemption,
        floored at zero. The distribution is gst_taxable exactly
        when the beneficiary is a skip person and the taxable
        portion is strictly greater than zero."

        Claim: GRANDCHILD distribution of $1,000,000 with $110,000
        of exemption remaining is gst_taxable=true with
        gst_tax_amount = (1,000,000 - 110,000) * 0.40 = 356,000.00.
        """
        scenario, skip, _ = setup_skip_person_distribution_pair()
        # Ensure another $1M of principal is available for the
        # taxable distribution.
        add_asset(
            scenario.trust, book_value=1_000_000.00,
            classification="PRINCIPAL", asset_class="CASH",
            headers=scenario.grantor_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        dist = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=1_000_000.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        assert dist["gst_taxable"] is True
        assert dist["gst_tax_amount"] == pytest.approx(
            356_000.00, abs=0.01,
        )

    def test_skip_distribution_gst_tax_non_skip_path(self, api):
        """# difficulty: dual_variant_calc/skip_vs_non_skip_distribution_gst_tax

        PRD §3.6: "If the beneficiary is not a skip person, the
        taxable portion is zero."

        Claim: identical $1,000,000 distribution to a CHILD
        beneficiary produces gst_taxable=false, gst_tax_amount=0.00.
        """
        scenario, _, non_skip = setup_skip_person_distribution_pair()
        # The pair fixture already consumed exemption with prior
        # distribution. Add another $1M principal to fund the new
        # one.
        add_asset(
            scenario.trust, book_value=1_000_000.00,
            classification="PRINCIPAL", asset_class="CASH",
            headers=scenario.grantor_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        dist = propose_distribution(
            scenario.trust, non_skip,
            scenario.primary_trustee_headers,
            amount_principal=1_000_000.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        assert dist["gst_taxable"] is False
        assert dist["gst_tax_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_tiered_brackets_band_3_arithmetic(self, api):
        """# difficulty: combinatorial_formula/tiered_trust_income_tax_brackets

        PRD §3.8: "Processing proceeds in ascending order: the
        portion of trust_taxable_income that falls within each band
        is multiplied by that band's rate, and the products are
        summed into a running total. Rounding is pinned and is
        applied exactly once, at the very end of the cumulative tax
        sum — never per band."

        Claim: NON_GRANTOR DNI=$20,000, no distributions ->
        trust_income_tax = 3100*0.10 + (11150-3100)*0.24 +
        (15200-11150)*0.35 + (20000-15200)*0.37 = 5,435.50.
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=20_000.00,
            distribution_income=0.0,
        )
        assert scenario.tax_year["trust_taxable_income"] == (
            pytest.approx(20_000.00, abs=0.01)
        )
        assert scenario.tax_year["trust_income_tax"] == (
            pytest.approx(5_435.50, abs=0.01)
        )

    def test_tiered_brackets_first_band_only(self, api):
        """# difficulty: combinatorial_formula/tiered_trust_income_tax_brackets

        PRD §3.8: "The first band covers taxable income from 0.00 up
        to 3,100.00 at a marginal rate of 10%."

        Claim: NON_GRANTOR DNI=$2,000 -> trust_income_tax = 200.00
        (rounded once at end).
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=2_000.00,
        )
        assert scenario.tax_year["trust_income_tax"] == (
            pytest.approx(200.00, abs=0.01)
        )

    def test_gst_exemption_then_tax_order_residual_taxed(self, api):
        """# difficulty: combinatorial_formula/gst_exemption_then_tax_evaluation_order

        PRD §3.6: "The pinned order is: first, classify gst_taxable
        using the current gst_exemption_used; second, compute the
        exemption applied as the lesser of the total amount and the
        remaining exemption; third, compute the taxable portion as
        the total amount minus the exemption applied; fourth,
        compute gst_tax_amount as the taxable portion multiplied by
        40%, rounded half-up to two decimal places."

        Claim: gst_exemption_used=13,609,999 (1.00 remaining); a
        10.00 skip-person distribution executes -> exemption_used
        advances to 13,610,000.00, gst_tax_amount = 9.00 * 0.40 =
        3.60.
        """
        scenario, skip = setup_exemption_almost_consumed_trust(
            pre_consumed=13_609_999.00,
        )
        add_asset(
            scenario.trust, book_value=100.00,
            classification="PRINCIPAL", asset_class="CASH",
            headers=scenario.grantor_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        dist = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=10.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        dist = execute_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        trust_after = re_get_trust(scenario.trust["id"])
        assert trust_after["gst_exemption_used"] == pytest.approx(
            13_610_000.00, abs=0.01,
        )
        assert dist["gst_tax_amount"] == pytest.approx(3.60, abs=0.01)
        assert dist["gst_taxable"] is True

    def test_gst_exemption_evaluation_order_classify_first(self, api):
        """# difficulty: combinatorial_formula/gst_exemption_then_tax_evaluation_order

        PRD §3.6: "The boundary condition is exact: if the total
        amount equals the remaining exemption, the taxable portion
        is zero and gst_taxable is false; if the total amount
        exceeds the remaining exemption by even 0.01, the taxable
        portion is 0.01 and gst_taxable is true."

        Claim: with exactly 1.00 of exemption remaining, a 1.00
        skip-person distribution is gst_taxable=false (boundary
        check evaluates BEFORE the exemption is written back).
        """
        scenario, skip = setup_exemption_almost_consumed_trust(
            pre_consumed=13_609_999.00,
        )
        dist = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=1.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        assert dist["gst_taxable"] is False
        assert dist["gst_tax_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_tax_year_closed_amended_closed_cycle(self, api):
        """# difficulty: non_linear_state_machine/tax_year_amendment_cycle

        PRD §3.5: "The amendment cycle reopens a CLOSED TaxYear for
        K-1 corrections. Only the TaxPreparer may invoke it. ... A
        subsequent finalize transitions the TaxYear back AMENDED →
        CLOSED and re-issues the K-1s".

        Claim: the same TaxYear can traverse CLOSED → AMENDED →
        CLOSED → AMENDED.
        """
        scenario = setup_closed_tax_year(income_amount=5_000.00)
        assert scenario.tax_year["status"] == "CLOSED"
        # First amend.
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        assert scenario.tax_year["status"] == "AMENDED"
        # Re-finalize.
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        assert scenario.tax_year["status"] == "CLOSED"
        # Second amend.
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        assert scenario.tax_year["status"] == "AMENDED"

    def test_tax_year_status_after_first_amend(self, api):
        """# difficulty: non_linear_state_machine/tax_year_amendment_cycle

        PRD §3.5: "On success the TaxYear transitions CLOSED →
        AMENDED".

        Claim: TaxYear status is exactly 'AMENDED' after the first
        amend on a CLOSED year.
        """
        scenario = setup_tax_year_in_amend_state(
            income_amount=5_000.00,
        )
        assert scenario.tax_year["status"] == "AMENDED"

    def test_k1_supersession_cycle_after_amend(self, api):
        """# difficulty: non_linear_state_machine/k1_supersession_cycle

        PRD §3.7: "ISSUED → SUPERSEDED is a system transition driven
        by TaxYear CLOSED → AMENDED."

        Claim: previously-ISSUED K-1 transitions to SUPERSEDED on
        amend.
        """
        scenario = setup_closed_tax_year(income_amount=5_000.00)
        before = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        assert any(k["status"] == "ISSUED" for k in before)
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        after = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        own_after = [
            k for k in after
            if k["beneficiary_id"] == scenario.beneficiary["id"]
        ]
        assert any(k["status"] == "SUPERSEDED" for k in own_after)

    def test_k1_supersession_then_new_issued_after_refinalize(
        self, api,
    ):
        """# difficulty: non_linear_state_machine/k1_supersession_cycle

        PRD §3.7: "DRAFT → ISSUED is a system transition driven by
        TaxYear CLOSING → CLOSED or AMENDED → CLOSED, at which
        point the K-1 totals are pinned".

        Claim: after CLOSED→AMENDED→CLOSED, exactly one ISSUED K-1
        and exactly one SUPERSEDED K-1 exist for the beneficiary.
        """
        scenario = setup_tax_year_in_amend_state(
            income_amount=5_000.00,
        )
        # Re-finalize.
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        k1s = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        own = [
            k for k in k1s
            if k["beneficiary_id"] == scenario.beneficiary["id"]
        ]
        issued = [k for k in own if k["status"] == "ISSUED"]
        superseded = [k for k in own if k["status"] == "SUPERSEDED"]
        assert len(issued) == 1, (
            f"Expected exactly one ISSUED K-1 per beneficiary; got "
            f"{issued}"
        )
        assert len(superseded) >= 1, (
            f"Expected at least one SUPERSEDED K-1 from the prior "
            f"cycle; got {superseded}"
        )


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_distribution_execute_chain_depth_3_link2_balance(
        self, api,
    ):
        """# difficulty: transitive_cascade/distribution_execute_chain_depth_3

        PRD §3.4: "On success the Distribution transitions APPROVED
        → EXECUTED and four cascade effects fire: the Trust's
        principal_balance is reduced by amount_principal; its
        income_balance is reduced by amount_income".

        Claim (link 1 + link 2): after execute of a 20,000 income
        distribution against $50,000 income, trust.income_balance =
        30,000.00 and distribution.status = 'EXECUTED'.
        """
        from test_helpers import (
            setup_active_trust_with_approved_income_distribution,
        )
        scenario, dist = (
            setup_active_trust_with_approved_income_distribution(
                income_amount=50_000.00,
                distribution_income=20_000.00,
            )
        )
        dist = execute_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        assert dist["status"] == "EXECUTED"
        trust_after = re_get_trust(scenario.trust["id"])
        assert trust_after["income_balance"] == pytest.approx(
            30_000.00, abs=0.01,
        )

    def test_distribution_execute_chain_depth_3_link3_k1_recompute(
        self, api,
    ):
        """# difficulty: transitive_cascade/distribution_execute_chain_depth_3

        PRD §3.4: "The DRAFT K-1 for this beneficiary in the
        affected TaxYear is recomputed (refreshing
        ordinary_income_share, interest_income_share,
        dividend_income_share, capital_gain_share, and
        total_distributed)".

        Claim (link 3): after execute, the beneficiary's DRAFT K-1
        in the affected TaxYear has total_distributed = 20,000.00.
        """
        from test_helpers import (
            setup_active_trust_with_approved_income_distribution,
        )
        scenario, dist = (
            setup_active_trust_with_approved_income_distribution(
                income_amount=50_000.00,
                distribution_income=20_000.00,
            )
        )
        execute_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        k1s = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        own_draft = [
            k for k in k1s
            if k["beneficiary_id"] == scenario.beneficiary["id"]
            and k["status"] == "DRAFT"
        ]
        assert own_draft, (
            f"Expected a DRAFT K-1 for this beneficiary in the "
            f"open TaxYear; got {k1s}"
        )
        assert own_draft[0]["total_distributed"] == pytest.approx(
            20_000.00, abs=0.01,
        )

    def test_trust_revoke_chain_terminates_beneficiary_and_assets(
        self, api,
    ):
        """# difficulty: transitive_cascade/trust_revoke_chain_depth_3

        PRD §3.1: "every Beneficiary with status of ACTIVE
        transitions to TERMINATED; every Asset with status of FUNDED
        transitions to DISTRIBUTED".

        Claim (links 1 + 2): revoke flips Trust.status to REVOKED
        and the ACTIVE beneficiary transitions to TERMINATED.
        """
        scenario = setup_active_trust_with_principal(
            trust_type="REVOCABLE",
            grantor_tax_status="GRANTOR",
            principal_amount=100_000.00,
        )
        from test_helpers import revoke_trust
        scenario.trust = revoke_trust(
            scenario.trust, scenario.grantor_headers,
        )
        assert scenario.trust["status"] == "REVOKED"
        resp = api.get_beneficiary(
            scenario.trust["id"], scenario.beneficiary["id"],
            scenario.grantor_headers,
        )
        b = validate_success(resp, 200)
        assert b["status"] == "TERMINATED"

    def test_trust_revoke_chain_zeros_balances(self, api):
        """# difficulty: transitive_cascade/trust_revoke_chain_depth_3

        PRD §3.1: "the principal_balance and income_balance are
        returned to the grantor by being zeroed".

        Claim (link 3): after revoke, both balances on the Trust
        equal 0.00.
        """
        scenario = setup_active_trust_with_principal(
            trust_type="REVOCABLE",
            grantor_tax_status="GRANTOR",
            principal_amount=100_000.00,
        )
        from test_helpers import revoke_trust
        scenario.trust = revoke_trust(
            scenario.trust, scenario.grantor_headers,
        )
        assert scenario.trust["principal_balance"] == pytest.approx(
            0.00, abs=0.01,
        )
        assert scenario.trust["income_balance"] == pytest.approx(
            0.00, abs=0.01,
        )


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_check_wins_over_beneficiary_terminated(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_approve

        PRD §2.8: "State-machine acceptability comes sixth, producing
        ERR_INVALID_STATE when the target resource is not in a state
        from which the requested action is allowed. Beneficiary-
        active checks come seventh, producing
        ERR_BENEFICIARY_TERMINATED."

        Claim: approve on an already-EXECUTED Distribution whose
        beneficiary has been terminated since approval ->
        ERR_INVALID_STATE (priority 6) wins over
        ERR_BENEFICIARY_TERMINATED (priority 7).
        """
        from test_helpers import (
            setup_active_trust_with_approved_income_distribution,
        )
        scenario, dist = (
            setup_active_trust_with_approved_income_distribution(
                income_amount=5_000.00,
                distribution_income=500.00,
            )
        )
        # Execute the distribution.
        dist = execute_distribution(
            scenario.trust, dist,
            scenario.second_trustee_headers,
        )
        assert dist["status"] == "EXECUTED"
        # Terminate the beneficiary.
        api.terminate_beneficiary(
            scenario.trust["id"], scenario.beneficiary["id"],
            scenario.primary_trustee_headers,
        )
        # Approve on EXECUTED + terminated beneficiary -> state
        # check wins.
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_segregation_wins_over_insufficient_income_on_approve(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_approve

        PRD §2.8: "Segregation-of-duties checks come eighth,
        producing ERR_SEGREGATION_OF_DUTIES. ... Fiscal sufficiency
        checks are fifteenth, sixteenth, and seventeenth, producing
        ERR_INSUFFICIENT_PRINCIPAL, ERR_INSUFFICIENT_INCOME, and
        ERR_INSUFFICIENT_INCOME_FOR_TAX respectively."

        Claim: a self-approval where amount_income also exceeds
        income_balance produces ERR_SEGREGATION_OF_DUTIES (priority
        8), not ERR_INSUFFICIENT_INCOME (priority 16).
        """
        from test_helpers import (
            setup_active_trust_with_proposed_income_distribution,
        )
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=100.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        # Same trustee attempts to approve their own proposal AND
        # the income is insufficient.
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.primary_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

    def test_state_check_wins_over_beneficiary_terminated_alt(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_approve

        PRD §2.8: "State-machine acceptability comes sixth, producing
        ERR_INVALID_STATE when the target resource is not in a state
        from which the requested action is allowed. Beneficiary-
        active checks come seventh, producing
        ERR_BENEFICIARY_TERMINATED."

        Claim (alt scenario): approve on a REJECTED distribution
        whose beneficiary is also TERMINATED -> ERR_INVALID_STATE
        (priority 6 wins over priority 7). Different state to the
        first variant (EXECUTED vs REJECTED) but same priority pair.
        """
        from test_helpers import (
            setup_active_trust_with_proposed_income_distribution,
        )
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        # Reject the proposal first.
        rejected = api.reject_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_success(rejected, 200)
        # Terminate the beneficiary.
        api.terminate_beneficiary(
            scenario.trust["id"], scenario.beneficiary["id"],
            scenario.primary_trustee_headers,
        )
        # Now approve — both state (REJECTED, not PROPOSED) and
        # beneficiary_terminated would fire; state must win.
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_segregation_wins_alt_self_approval_only(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_approve

        PRD §2.8: "Segregation-of-duties checks come eighth ...
        Fiscal sufficiency checks are fifteenth, sixteenth, and
        seventeenth".

        Claim (alt scenario): same self-approver, this time the
        clash is on amount_principal exceeding principal_balance.
        Same priority pair (business_safety vs business_fiscal);
        priority 8 still wins.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=10.00,
        )
        # Propose a 100-principal distribution.
        from test_helpers import propose_distribution
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_principal=100.00,
            distribution_type="DISCRETIONARY",
        )
        # Self-approve (same primary trustee).
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.primary_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_gst_skip_person_age_boundary_at_37_5(self, api):
        """# difficulty: boundary_precision_check/gst_skip_person_age_boundary

        PRD §3.2: "The threshold uses an at-least comparison, so an
        age difference of exactly 37.5 years qualifies as a skip
        person; 37.49 does not."

        Claim: NON_LINEAL born exactly 37.5 years after inception
        (inception 2026-01-01, birth 2063-07-02) is is_skip_person =
        true.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Exact NL", relation_class="NON_LINEAL",
            distribution_tier="TIER_2",
            birth_date="2063-07-02",
        )
        assert b["is_skip_person"] is True

    def test_gst_skip_person_age_boundary_just_below_37_5(self, api):
        """# difficulty: boundary_precision_check/gst_skip_person_age_boundary

        PRD §3.2: "The threshold uses an at-least comparison, so an
        age difference of exactly 37.5 years qualifies as a skip
        person; 37.49 does not."

        Claim: NON_LINEAL born one day short of 37.5 years
        (inception 2026-01-01, birth 2063-07-01) is is_skip_person
        = false.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Just-under NL", relation_class="NON_LINEAL",
            distribution_tier="TIER_2",
            birth_date="2063-07-01",
        )
        assert b["is_skip_person"] is False

    def test_activation_with_zero_active_beneficiaries(self, api):
        """# difficulty: boundary_precision_check/empty_active_beneficiary_set_at_activation

        PRD §3.1: "There must be at least one Beneficiary record
        under the trust with status equal to ACTIVE; otherwise
        activation fails with ERR_NO_BENEFICIARY."

        Claim: activation with a primary trustee and an open
        TaxYear but ZERO beneficiaries -> ERR_NO_BENEFICIARY.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        add_trustee(
            scenario.trust, scenario.grantor_headers,
            is_primary=True,
        )
        add_tax_year(scenario.trust, calendar_year=2026)
        resp = api.activate_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_BENEFICIARY.value)

    def test_activation_with_one_active_beneficiary_succeeds(
        self, api,
    ):
        """# difficulty: boundary_precision_check/empty_active_beneficiary_set_at_activation

        PRD §3.1: "There must be at least one Beneficiary record
        under the trust with status equal to ACTIVE".

        Claim: at the boundary (count == 1), activation succeeds —
        confirming the ZERO case is the exact lower edge.
        """
        scenario = setup_activatable_trust(
            inception_date="2026-01-01", calendar_year=2026,
        )
        from test_helpers import activate_trust
        trust = activate_trust(
            scenario.trust, scenario.grantor_headers,
        )
        assert trust["status"] == "ACTIVE"


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_distribution_approve_blocked_after_year_closing(self, api):
        """# difficulty: cross_entity_state_dependency/distribution_approve_requires_tax_year_open

        PRD §3.4: "Approval requires that ... the referenced TaxYear
        is in OPEN status (otherwise ERR_TAX_YEAR_NOT_OPEN)."
        PRD §3.5: "every Distribution in PROPOSED status for this
        tax_year_id is automatically transitioned to REJECTED."

        Two PRD-faithful implementations diverge here: one reports
        ERR_TAX_YEAR_NOT_OPEN by checking the year first; another
        reports ERR_INVALID_STATE because begin-close's auto-reject
        side effect has already flipped the distribution to REJECTED.
        Both readings are PRD-consistent, so we accept either error
        for the cross-entity dependency Distribution → TaxYear.

        Claim: approve after begin-close fails with either
        ERR_TAX_YEAR_NOT_OPEN or ERR_INVALID_STATE (any 4xx). The
        dependency on TaxYear status is what's under test.
        """
        from test_helpers import (
            setup_active_trust_with_proposed_income_distribution,
            validate_error_is_one_of,
        )
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        begin_close_tax_year(scenario.trust, scenario.tax_year)
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        # Either error proves the cross-entity dependency.
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_TAX_YEAR_NOT_OPEN.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )

    def test_distribution_propose_requires_tax_year_open(self, api):
        """# difficulty: cross_entity_state_dependency/distribution_approve_requires_tax_year_open

        PRD §3.4: "The scheduled_date must fall inside an OPEN
        TaxYear for this trust; otherwise the proposal is rejected
        with ERR_TAX_YEAR_CLOSED."

        Claim: alternate cross-entity dependency exercise on the
        same entity pair (Distribution → TaxYear): propose with a
        scheduled_date in a non-OPEN year -> ERR_TAX_YEAR_CLOSED.
        """
        scenario = setup_active_trust(calendar_year=2026)
        resp = api.create_distribution(
            scenario.trust["id"],
            create_distribution_payload(
                beneficiary_id=scenario.beneficiary["id"],
                scheduled_date=iso_instant_utc(2030, 6, 1),
                amount_income=10.00,
                distribution_type="DISCRETIONARY",
            ),
            scenario.primary_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TAX_YEAR_CLOSED.value)

    def test_terminate_blocked_by_funded_asset(self, api):
        """# difficulty: cross_entity_state_dependency/trust_terminate_requires_no_funded_assets

        PRD §3.1: "Termination requires that every Asset is in
        either DISTRIBUTED or SOLD status (otherwise
        ERR_HAS_UNDISTRIBUTED_ASSETS)".

        Claim: terminate on a Trust that still has a FUNDED asset
        -> ERR_HAS_UNDISTRIBUTED_ASSETS.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=100_000.00,
        )
        # Drive the TaxYear to CLOSED so the year-state precondition
        # passes.
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        scenario.tax_year = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        resp = api.terminate_trust(
            scenario.trust["id"],
            scenario.primary_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_HAS_UNDISTRIBUTED_ASSETS.value,
        )

    def test_terminate_blocked_by_funded_asset_alternate_setup(
        self, api,
    ):
        """# difficulty: cross_entity_state_dependency/trust_terminate_requires_no_funded_assets

        PRD §3.1: "Termination requires that every Asset is in
        either DISTRIBUTED or SOLD status (otherwise
        ERR_HAS_UNDISTRIBUTED_ASSETS)".

        Claim: same trigger reached via a smaller asset and a
        REVOCABLE+GRANTOR tax variant (grantor variant => no tax
        debit, so the year-state precondition is easier to clear).
        """
        scenario = setup_active_trust_with_principal(
            trust_type="REVOCABLE",
            grantor_tax_status="GRANTOR",
            principal_amount=10.00,
        )
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        scenario.tax_year = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        resp = api.terminate_trust(
            scenario.trust["id"],
            scenario.primary_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_HAS_UNDISTRIBUTED_ASSETS.value,
        )


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_transaction_date_in_closed_year_rejected(self, api):
        """# difficulty: resource_temporal_overlap/transaction_date_must_lie_inside_open_tax_year_inclusive

        PRD §3.3: "A Transaction's transaction_date must fall
        inside a TaxYear that is in either OPEN or CLOSING status
        for this trust; otherwise the request is rejected with
        ERR_TAX_YEAR_CLOSED."

        Claim: a transaction whose date is inside the CLOSED 2026
        year (after begin-close+finalize for 2026 and after a 2027
        TaxYear was opened) is rejected with ERR_TAX_YEAR_CLOSED.
        """
        # Build CLOSED 2026 + OPEN 2027 trust.
        scenario = setup_closed_tax_year(income_amount=500.00)
        ty_2027 = add_tax_year(scenario.trust, calendar_year=2027)
        assert ty_2027["status"] == "OPEN"
        # Now try to book a 2026 transaction.
        resp = api.create_transaction(
            scenario.trust["id"],
            create_transaction_payload(
                txn_type="INCOME_ORDINARY", amount=1.00,
                transaction_date=iso_instant_utc(2026, 12, 31),
                principal_or_income="INCOME",
            ),
            scenario.primary_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TAX_YEAR_CLOSED.value)

    def test_transaction_date_in_open_year_accepted(self, api):
        """# difficulty: resource_temporal_overlap/transaction_date_must_lie_inside_open_tax_year_inclusive

        PRD §3.3: "A Transaction's transaction_date must fall
        inside a TaxYear that is in either OPEN or CLOSING status
        for this trust".

        Claim: a transaction whose date falls inside the 2027 OPEN
        year (after 2026 is CLOSED) is accepted.
        """
        scenario = setup_closed_tax_year(income_amount=500.00)
        ty_2027 = add_tax_year(scenario.trust, calendar_year=2027)
        # We need the trust's clock state to permit the trustee's
        # operation; the 2027 year is OPEN so a date inside it is
        # valid.
        resp = api.create_transaction(
            scenario.trust["id"],
            create_transaction_payload(
                txn_type="INCOME_ORDINARY", amount=1.00,
                transaction_date=iso_instant_utc(2027, 6, 1),
                principal_or_income="INCOME",
            ),
            scenario.primary_trustee_headers,
        )
        txn = validate_success(resp, 201)
        assert txn["tax_year_id"] == ty_2027["id"]

    def test_amend_blocked_when_later_closed_year_exists(self, api):
        """# difficulty: resource_temporal_overlap/amend_chain_no_later_closed_year

        PRD §3.5: "Amendment is forbidden when a later TaxYear for
        the same trust has already reached CLOSED status — the rule
        is 'amend in chronological order' and the rejection code is
        ERR_NEWER_YEAR_CLOSED."

        Claim: amend(2025) when 2026 is already CLOSED ->
        ERR_NEWER_YEAR_CLOSED.
        """
        # Construct sequentially CLOSED 2025 and 2026.
        scenario = setup_activatable_trust(
            inception_date="2025-01-01", calendar_year=2025,
        )
        from test_helpers import activate_trust
        scenario.trust = activate_trust(
            scenario.trust, scenario.grantor_headers,
        )
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_ORDINARY", amount=100.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2025, 6, 1),
        )
        advance_clock_to(iso_instant_utc(2026, 1, 2))
        ty_2025 = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        ty_2025 = finalize_tax_year(scenario.trust, ty_2025)
        ty_2026 = add_tax_year(scenario.trust, calendar_year=2026)
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_ORDINARY", amount=50.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2026, 6, 1),
        )
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        ty_2026 = begin_close_tax_year(scenario.trust, ty_2026)
        ty_2026 = finalize_tax_year(scenario.trust, ty_2026)
        assert ty_2026["status"] == "CLOSED"
        resp = api.amend_tax_year(
            scenario.trust["id"], ty_2025["id"],
            TEST_USERS["tax_preparer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NEWER_YEAR_CLOSED.value)

    def test_amend_chronologically_latest_allowed(self, api):
        """# difficulty: resource_temporal_overlap/amend_chain_no_later_closed_year

        PRD §3.5: "the rule is 'amend in chronological order'".

        Claim: amend on the LATEST closed year (no later year is
        CLOSED) is permitted; status transitions CLOSED -> AMENDED.
        """
        scenario = setup_closed_tax_year(income_amount=1_000.00)
        # No later year is CLOSED for this trust.
        resp = api.amend_tax_year(
            scenario.trust["id"], scenario.tax_year["id"],
            TEST_USERS["tax_preparer_headers"],
        )
        ty = validate_success(resp, 200)
        assert ty["status"] == "AMENDED"


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_propose_then_reject_preserves_balances(self, api):
        """# difficulty: compensating_invariant/propose_then_reject_preserves_trust_balances

        PRD §3.4: "Rejection ends a Distribution's life early. A
        Trustee may reject a Distribution that is in PROPOSED status,
        which transitions it PROPOSED → REJECTED".

        Claim: balances after propose+reject equal balances before
        propose.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=10_000.00,
        )
        # Add some income.
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_INTEREST", amount=2_000.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2026, 5, 1),
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        before_p = scenario.trust["principal_balance"]
        before_i = scenario.trust["income_balance"]
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_principal=500.00, amount_income=300.00,
            distribution_type="DISCRETIONARY",
        )
        api.reject_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        assert scenario.trust["principal_balance"] == pytest.approx(
            before_p, abs=0.01,
        )
        assert scenario.trust["income_balance"] == pytest.approx(
            before_i, abs=0.01,
        )

    def test_propose_then_reject_preserves_balances_zero_amounts(
        self, api,
    ):
        """# difficulty: compensating_invariant/propose_then_reject_preserves_trust_balances

        PRD §3.4: "Rejection ends a Distribution's life early."

        Claim: even with zero-amount propose, reject leaves
        balances exactly equal to the pre-propose snapshot.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=5_000.00,
        )
        before_p = scenario.trust["principal_balance"]
        before_i = scenario.trust["income_balance"]
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_principal=0.0, amount_income=0.0,
            distribution_type="DISCRETIONARY",
        )
        api.reject_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        assert scenario.trust["principal_balance"] == pytest.approx(
            before_p, abs=0.01,
        )
        assert scenario.trust["income_balance"] == pytest.approx(
            before_i, abs=0.01,
        )

    def test_amend_refinalize_preserves_total_distributed(self, api):
        """# difficulty: compensating_invariant/amend_then_refinalize_preserves_total_distributions_to_beneficiary

        PRD §3.7: "a total_distributed field (the sum of amount_income
        plus amount_principal over EXECUTED distributions to this
        beneficiary in this TaxYear)".

        Claim: K1.total_distributed for the beneficiary in the
        re-closed TaxYear equals the value from the original close
        (no distributions added or modified across the cycle).
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=10_000.00,
            distribution_income=4_000.00,
        )
        # First-close K-1.
        k1s_before = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        own_before = [
            k for k in k1s_before
            if k["beneficiary_id"] == scenario.beneficiary["id"]
            and k["status"] == "ISSUED"
        ]
        assert own_before, "expected ISSUED K-1 after first close"
        before_total = own_before[0]["total_distributed"]
        # Amend and re-finalize without any new distributions.
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        k1s_after = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        own_after = [
            k for k in k1s_after
            if k["beneficiary_id"] == scenario.beneficiary["id"]
            and k["status"] == "ISSUED"
        ]
        # Exactly one ISSUED K-1 per pair after re-close.
        assert len(own_after) == 1
        assert own_after[0]["total_distributed"] == pytest.approx(
            before_total, abs=0.01,
        )

    def test_amend_refinalize_preserves_total_distributed_zero_dist(
        self, api,
    ):
        """# difficulty: compensating_invariant/amend_then_refinalize_preserves_total_distributions_to_beneficiary

        PRD §3.7: "a total_distributed field (the sum of amount_income
        plus amount_principal over EXECUTED distributions to this
        beneficiary in this TaxYear)".

        Claim: with zero distributions, total_distributed is
        preserved at 0.00 across CLOSED→AMENDED→CLOSED.
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=5_000.00,
            distribution_income=0.0,
        )
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        k1s = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        own = [
            k for k in k1s
            if k["beneficiary_id"] == scenario.beneficiary["id"]
            and k["status"] == "ISSUED"
        ]
        assert len(own) == 1
        assert own[0]["total_distributed"] == pytest.approx(
            0.00, abs=0.01,
        )
