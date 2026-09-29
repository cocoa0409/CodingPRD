"""Disposition analyses: the two cost-recovery variants and the exchange lock on a policy."""
import pytest
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.factories import death_claim_payload
from test_helpers.fixtures import (
    ANALYST,
    CLAIMS,
    TREASURY,
    approved_purchase_request,
    authorized_carrier_with_product,
    committed_analysis,
    create_analysis,
    in_force_policy,
    insured_employee,
    issue_policy,
    post_valuation,
    register_product_type,
)


HARBORVIEW = {"legal_name": "Harborview Life", "naic_code": "62151", "domicile_state": "VA"}
TANAGER = {"legal_name": "Tanager Life", "naic_code": "62161", "domicile_state": "SC"}

BAPTISTE = {
    "full_name": "Yves Baptiste",
    "employee_number": "E-7401",
    "annual_salary_usd": 900_000.00,
    "officer_flag": False,
}


def _two_policies_one_mec(api):
    """One carrier, a NON_MEC and a MEC product, and a valued policy under each."""
    context = authorized_carrier_with_product(
        api,
        carrier_overrides=HARBORVIEW,
        product_overrides={
            "product_name": "Harborview GA NON_MEC",
            "disclosed_me_charge_bps": 50,
        },
    )
    mec_product = register_product_type(
        api,
        context["carrier_id"],
        product_name="Harborview GA MEC",
        mec_status="MEC",
        disclosed_me_charge_bps=50,
    )

    policies = {}
    for label, product_id, number, employee in (
        (
            "NON_MEC",
            context["product_type_id"],
            "HV-0001",
            {
                "full_name": "Nora Vale",
                "employee_number": "E-7501",
                "annual_salary_usd": 900_000.00,
                "officer_flag": False,
            },
        ),
        (
            "MEC",
            mec_product["id"],
            "HV-0002",
            {
                "full_name": "Piet Vos",
                "employee_number": "E-7502",
                "annual_salary_usd": 900_000.00,
                "officer_flag": False,
            },
        ),
    ):
        insured = insured_employee(
            api,
            employee_overrides=employee,
            consent_overrides={"consent_form_reference": f"CF-{employee['employee_number']}"},
        )
        request = approved_purchase_request(
            api,
            context["carrier_id"],
            product_id,
            insured["employee_id"],
            single_premium_usd=1_200_000.00,
            face_amount_usd=3_600_000.00,
        )
        policy = issue_policy(api, request["id"], policy_number=number)
        valuation = post_valuation(
            api,
            policy["id"],
            credited_interest_usd=306_000.00,
            mortality_expense_charge_usd=6_000.00,
            gross_crediting_rate_bps=2550,
        )
        policies[label] = {"policy": policy, "valuation": valuation}

    context["policies"] = policies
    context["mec_product_id"] = mec_product["id"]
    return context


class TestPartialSurrenderCostRecovery:
    def test_a_non_mec_withdrawal_recovers_basis_first_and_is_tax_free(self, api):
        """Under FIFO the withdrawal comes out of cost basis, so nothing is taxable.

        "`cost_recovery_method` is set to `LIFO_INCOME_FIRST` when the policy's
        product carries `mec_status` `MEC`, and to `FIFO_BASIS_FIRST` when it
        carries `NON_MEC`." "Under `FIFO_BASIS_FIRST` the withdrawal recovers
        cost basis first, so the `taxable_gain_usd` is the withdrawal minus the
        policy's `cost_basis_usd`, or zero if the basis is the larger — meaning a
        withdrawal that stays below basis is entirely tax free." A first-year
        contract "carries 600 basis points", so 500,000.00 loses only the 30,000.00
        surrender charge.

        Design: Difficulty/dual_variant_calc/mec_versus_non_mec_partial_surrender_cost_recovery
        """
        context = _two_policies_one_mec(api)
        policy = context["policies"]["NON_MEC"]["policy"]

        assert context["policies"]["NON_MEC"]["valuation"][
            "cash_value_usd"
        ] == pytest.approx(1_500_000.00, abs=0.01)

        analysis = create_analysis(
            api,
            policy["id"],
            disposition_type="PARTIAL_SURRENDER",
            requested_withdrawal_usd=500_000.00,
        )
        assert analysis["cost_recovery_method"] == "FIFO_BASIS_FIRST"
        assert analysis["taxable_gain_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["surrender_charge_usd"] == pytest.approx(30_000.00, abs=0.01)
        assert analysis["tax_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_proceeds_usd"] == pytest.approx(470_000.00, abs=0.01)
        assert analysis["status"] == "DRAFT"

    def test_a_mec_withdrawal_distributes_income_first_and_is_taxed(self, api):
        """Under LIFO the identical withdrawal is taxable up to the inside build-up.

        "Under `LIFO_INCOME_FIRST` the withdrawal distributes income first, so
        the `taxable_gain_usd` is the lesser of the withdrawal and the inside
        build-up, where the inside build-up is the cash value minus the cost
        basis floored at zero — meaning the very same withdrawal on identical
        figures is fully taxable up to the gain in the contract." With "the
        federal rate is 2100 basis points and the state rate is 600 basis
        points", the 300,000.00 gain carries 81,000.00 of tax, and
        "`net_proceeds_usd` is then the gross amount minus the rounded surrender
        charge minus the rounded tax liability".

        Design: Difficulty/dual_variant_calc/mec_versus_non_mec_partial_surrender_cost_recovery
        """
        context = _two_policies_one_mec(api)
        policy = context["policies"]["MEC"]["policy"]

        analysis = create_analysis(
            api,
            policy["id"],
            disposition_type="PARTIAL_SURRENDER",
            requested_withdrawal_usd=500_000.00,
        )
        assert analysis["cost_recovery_method"] == "LIFO_INCOME_FIRST"
        assert analysis["taxable_gain_usd"] == pytest.approx(300_000.00, abs=0.01), (
            "the inside build-up caps the taxable amount below the withdrawal"
        )
        assert analysis["surrender_charge_usd"] == pytest.approx(30_000.00, abs=0.01)
        assert analysis["tax_liability_usd"] == pytest.approx(81_000.00, abs=0.01)
        assert analysis["net_proceeds_usd"] == pytest.approx(389_000.00, abs=0.01)


class TestPendingExchangeBlocksAClaim:
    def _committed_surrender(self, api):
        context = in_force_policy(
            api,
            carrier_overrides=TANAGER,
            product_overrides={"product_name": "Tanager GA BOLI"},
            employee_overrides=BAPTISTE,
            policy_overrides={"policy_number": "TN-0001"},
        )
        analysis = committed_analysis(api, context["policy_id"])
        context["analysis"] = analysis
        return context

    def test_filing_a_claim_on_a_pending_exchange_policy_is_refused(self, api):
        """A policy committed to a surrender is no longer IN_FORCE, so no claim can be filed.

        Committing "requires the policy to be `IN_FORCE` and drives it `IN_FORCE
        → PENDING_EXCHANGE`", and "Filing is only possible against a policy in
        `IN_FORCE`." The analysis figures are the FULL_SURRENDER variant: "For a
        `FULL_SURRENDER` the gross amount is the policy's whole
        `cash_surrender_value_usd`, and the `taxable_gain_usd` is that cash value
        minus the policy's `cost_basis_usd`, or zero if the basis exceeds the
        cash value."

        Design: Difficulty/cross_entity_state_dependency/death_claim_refused_while_policy_is_pending_exchange
        """
        context = self._committed_surrender(api)
        analysis = context["analysis"]

        assert analysis["status"] == "COMMITTED"
        assert analysis["cost_recovery_method"] == "FIFO_BASIS_FIRST"
        assert analysis["taxable_gain_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["surrender_charge_usd"] == pytest.approx(60_000.00, abs=0.01)
        assert analysis["tax_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_proceeds_usd"] == pytest.approx(940_000.00, abs=0.01)

        locked = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert locked["status"] == "PENDING_EXCHANGE"

        validate_error(
            api.create_death_claim(
                death_claim_payload(
                    context["policy_id"],
                    date_of_death="2026-09-05T00:00:00Z",
                    proof_reference="DC-7401",
                ),
                CLAIMS,
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        items, meta = validate_paginated(
            api.list_death_claims(CLAIMS, params={"policy_id": context["policy_id"]})
        )
        assert meta["total_count"] == 0, "the refused filing writes no claim"
        assert items == []

        employee = validate_success(api.get_employee(context["employee_id"], ANALYST))
        assert employee["employment_status"] == "ACTIVE", (
            "the refused filing does not touch the employee"
        )

    def test_abandoning_the_analysis_lets_the_claim_be_filed(self, api):
        """Releasing the exchange lock restores IN_FORCE and the claim then files.

        "abandoning advances the analysis `COMMITTED → ABANDONED` and drives the
        policy `PENDING_EXCHANGE → IN_FORCE`, restoring the policy's
        `cost_basis_usd` and `cash_surrender_value_usd` to precisely their
        pre-commit values." Filing then performs its "three-resource write: the
        claim is created with `adjudication_status` `FILED`,
        `distribution_status` `NOT_STARTED`, `allocated_bps_total` at 0".

        Design: Difficulty/cross_entity_state_dependency/death_claim_refused_while_policy_is_pending_exchange
        """
        context = self._committed_surrender(api)

        abandoned = validate_success(
            api.abandon_exchange_analysis(context["analysis"]["id"], TREASURY)
        )
        assert abandoned["status"] == "ABANDONED"

        restored = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert restored["status"] == "IN_FORCE"
        assert restored["cash_surrender_value_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert restored["cost_basis_usd"] == pytest.approx(1_000_000.00, abs=0.01)

        claim = validate_success(
            api.create_death_claim(
                death_claim_payload(
                    context["policy_id"],
                    date_of_death="2026-09-05T00:00:00Z",
                    proof_reference="DC-7401",
                ),
                CLAIMS,
            ),
            201,
        )
        assert claim["adjudication_status"] == "FILED"
        assert claim["distribution_status"] == "NOT_STARTED"
        assert claim["allocated_bps_total"] == 0

        policy_after = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert policy_after["status"] == "CLAIM_PENDING"

        employee = validate_success(api.get_employee(context["employee_id"], ANALYST))
        assert employee["employment_status"] == "DECEASED"
