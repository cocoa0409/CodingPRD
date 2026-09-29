"""The pricing engine's two variants: the provisional basis over agency quotes at
submission, and the final basis over attested premiums at activation.
"""

from test_helpers import (
    add_on_finance_charge_cents,
    assert_installments_sum,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN


def _two_policy_note(api):
    """A DRAFT note carrying a 1200000 policy and a 300000 policy."""
    ctx = fixtures.origination_context(api)
    return fixtures.draft_agreement(
        api,
        ctx,
        policies=[
            factories.financed_policy(
                ctx["insurer_id"],
                policy_number="MC-TX-1001",
                gross_premium_cents=1200000,
                min_earned_days=30,
            ),
            factories.financed_policy(
                ctx["insurer_id"],
                policy_number="MC-TX-1002",
                gross_premium_cents=300000,
            ),
        ],
        down_payment_cents=300000,
        service_fee_cents=2000,
        installment_count=9,
        first_installment_due_date="2026-10-01",
    )


def _attest(api, bundle):
    """The carrier and the agency both correct the big policy to 1250000 and both
    confirm the small one."""
    for headers in (bundle["insurer_headers"], bundle["agent_headers"]):
        validate_success(
            api.create_verification(
                bundle["policy_ids"][0],
                factories.corrected_verification(1250000),
                headers,
            ),
            201,
        )
    for headers in (bundle["insurer_headers"], bundle["agent_headers"]):
        validate_success(
            api.create_verification(
                bundle["policy_ids"][1],
                factories.confirmed_verification(),
                headers,
            ),
            201,
        )


class TestProvisionalVersusFinalPremiumBasis:
    """The same note carries two different finance charges without the borrower
    changing anything."""

    def test_the_provisional_variant_sums_the_agency_quotes(self, api):
        """Submission prices over the agency-quoted gross premiums of the pending
        policies.

        The PRD states: "First it establishes the premium basis: the provisional
        variant sums `gross_premium_cents` over the note's policies whose `status`
        is `PENDING_VERIFICATION` and whose `carried_over` flag is false, and
        writes the result to `total_premium_cents`".

        Design: Difficulty/dual_variant_calc/provisional_vs_final_premium_basis_divergence
        """
        bundle = _two_policy_note(api)

        priced = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert priced["quote_basis"] == "PROVISIONAL"
        assert priced["total_premium_cents"] == 1500000, (
            "1200000 + 300000 of agency-quoted gross premium"
        )
        assert priced["amount_financed_cents"] == 1202000, (
            "1500000 - 300000 down payment + 2000 service fee"
        )
        assert priced["effective_annual_rate_bps"] == 1500, (
            "1202000 is above 5,000 dollars but not above 20,000 dollars, and "
            "1500 is below the TX ceiling of 1800"
        )
        assert priced["finance_charge_cents"] == add_on_finance_charge_cents(
            1202000, 1500, 9
        ) == 135225
        assert priced["total_of_payments_cents"] == 1337225

    def test_the_final_variant_sums_the_attested_premiums(self, api):
        """Activation reprices over the attested premiums, moving the finance
        charge on its own.

        The PRD states: "the final variant sums `financed_premium_cents` (the
        attested premium plus any financed endorsements) over the note's policies
        whose `status` is `VERIFIED` and whose `carried_over` flag is false,
        rather than the agency-quoted gross premiums over pending policies."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_premium_basis_divergence
        """
        bundle = _two_policy_note(api)
        provisional = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        _attest(api, bundle)
        fixtures.set_clock(api, "2026-09-01T00:00:00Z")

        final = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert final["quote_basis"] == "FINAL"
        assert final["total_premium_cents"] == 1550000, (
            "the attested 1250000 plus the confirmed 300000"
        )
        assert final["amount_financed_cents"] == 1252000
        assert final["effective_annual_rate_bps"] == 1500
        assert final["finance_charge_cents"] == add_on_finance_charge_cents(
            1252000, 1500, 9
        ) == 140850
        assert final["total_of_payments_cents"] == 1392850
        assert (
            final["finance_charge_cents"] - provisional["finance_charge_cents"] == 5625
        ), (
            "the variant switch alone moved the finance charge; no borrower input "
            "changed between the two quotes"
        )

    def test_activation_writes_the_balances_and_the_schedule(self, api):
        """The receivable and the schedule are cut from the final quote.

        The PRD states: "The note's `principal_balance_cents` is set to
        `amount_financed_cents`, its `unpaid_finance_charge_cents` to
        `finance_charge_cents`, its `activated_at` to the current logical-clock
        instant, its financing status to `ACTIVE`, and its `version` advances."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_premium_basis_divergence
        """
        bundle = _two_policy_note(api)
        validate_success(api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200)
        _attest(api, bundle)
        fixtures.set_clock(api, "2026-09-01T00:00:00Z")
        activated = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert activated["status"] == "ACTIVE"
        assert activated["principal_balance_cents"] == 1252000
        assert activated["unpaid_finance_charge_cents"] == 140850

        rows, meta = validate_paginated(
            api.list_installments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 100})
        )
        assert meta["total_count"] == 9
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["amount_cents"] == 154761
        assert rows[0]["finance_charge_component_cents"] == 15650
        assert rows[0]["principal_component_cents"] == 139111
        assert rows[0]["due_date"] == "2026-10-01", (
            "installment number 1 falls on first_installment_due_date"
        )
        assert rows[8]["amount_cents"] == 154762, (
            "the arithmetic remainder lands on the final installment only"
        )
        assert rows[8]["due_date"] == "2027-06-01", (
            "installment k falls one whole calendar month later than installment "
            "k minus one"
        )
        assert_installments_sum(rows, 1392850, 140850)
