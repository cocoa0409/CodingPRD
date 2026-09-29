"""Deferred compensation funding: the two liability bases and the distribution cascade."""
import pytest
from test_helpers import validate_success
from test_helpers.assertions import assert_funding_summary_shape
from test_helpers.fixtures import (
    CLAIMS,
    TREASURY,
    add_allocation,
    add_liability,
    approved_claim,
    create_plan,
    funding_summary,
    in_force_policy,
    move_clock,
    register_employee,
    seal_allocations,
)


LARKSPUR = {"legal_name": "Larkspur Life", "naic_code": "62141", "domicile_state": "MD"}

REYES = {
    "full_name": "Dana Reyes",
    "employee_number": "E-7201",
    "annual_salary_usd": 2_000_000.00,
    "officer_flag": True,
}
ALVAREZ = {
    "full_name": "Sol Alvarez",
    "employee_number": "E-7202",
    "annual_salary_usd": 900_000.00,
    "officer_flag": False,
}
DUVAL = {
    "full_name": "Marc Duval",
    "employee_number": "E-7301",
    "annual_salary_usd": 2_000_000.00,
    "officer_flag": True,
}


def _plan_with_two_participants(api):
    """A plan carrying one matched liability and one unmatched liability."""
    context = in_force_policy(
        api,
        product_overrides={"product_name": "Northbridge GA BOLI"},
        employee_overrides=REYES,
        policy_overrides={"policy_number": "NB-0001"},
    )
    alvarez = register_employee(api, **ALVAREZ)
    plan = create_plan(api, plan_name="Executive SERP 2026")
    matched = add_liability(
        api,
        plan["id"],
        context["employee_id"],
        accrued_to_date_usd=600_000.00,
        projected_benefit_usd=2_000_000.00,
        years_to_payout=10,
        matched_policy_id=context["policy_id"],
    )
    unmatched = add_liability(
        api,
        plan["id"],
        alvarez["id"],
        accrued_to_date_usd=500_000.00,
        projected_benefit_usd=700_000.00,
        years_to_payout=5,
    )
    context.update(
        {
            "plan_id": plan["id"],
            "matched_liability": matched,
            "unmatched_liability": unmatched,
        }
    )
    return context


class TestAccrualVersusProjectedBasis:
    def test_the_accrual_view_is_the_one_persisted_on_the_plan(self, api):
        """The plan's own posture is the accrual posture, and it reads UNDERFUNDED.

        "`accrual_liability_usd` is the sum of `accrued_to_date_usd` over the
        plan's `ACTIVE` liabilities and `pbo_liability_usd` is the sum of the
        rounded per-participant `discounted_benefit_usd` values over the same
        set." "The `funded_ratio_bps` and `funding_posture` stored on the plan
        are" always "computed on the accrual basis." 1,000,000.00 of matched cash
        value against 1,100,000.00 of accrued liability is 9091 basis points,
        which is "`UNDERFUNDED` when it is at least 8000 but below 10000".

        Design: Difficulty/dual_variant_calc/nqdc_accrual_versus_pbo_posture_divergence
        """
        context = _plan_with_two_participants(api)

        assert context["matched_liability"]["discounted_benefit_usd"] == pytest.approx(
            1_227_826.51, abs=0.01
        ), "2,000,000.00 discounted at five percent for ten years"
        assert context["unmatched_liability"]["discounted_benefit_usd"] == pytest.approx(
            548_468.32, abs=0.01
        ), "700,000.00 discounted at five percent for five years"

        plan = validate_success(api.get_nqdc_plan(context["plan_id"], TREASURY))
        assert plan["accrual_liability_usd"] == pytest.approx(1_100_000.00, abs=0.01)
        assert plan["pbo_liability_usd"] == pytest.approx(1_776_294.83, abs=0.01), (
            "each participant's discounted amount is rounded before the two are summed"
        )
        assert plan["matched_cash_value_usd"] == pytest.approx(1_000_000.00, abs=0.01), (
            "only the liability that names a policy contributes cash value"
        )
        assert plan["funded_ratio_bps"] == 9091
        assert plan["funding_posture"] == "UNDERFUNDED"
        assert plan["status"] == "ACTIVE"

        summary = funding_summary(api, context["plan_id"])
        assert_funding_summary_shape(summary)
        assert summary["basis"] == "ACCRUAL", "the basis defaults to the accrual view"
        assert summary["basis_liability_usd"] == pytest.approx(1_100_000.00, abs=0.01)
        assert summary["funded_ratio_bps"] == 9091
        assert summary["funding_posture"] == "UNDERFUNDED"
        assert summary["participant_count"] == 2

    def test_the_projected_view_reads_critical_without_changing_the_plan(self, api):
        """The same participants read CRITICAL on the projected-benefit basis.

        "with `basis` set to `PBO` it reports the projected-benefit view", and
        "the accrual view is systematically the more favourable of the two — the
        very same participants can read `UNDERFUNDED` on the accrual basis and
        `CRITICAL` on the projected basis." The summary read changes nothing, so
        the plan still carries its accrual posture afterwards.

        Design: Difficulty/dual_variant_calc/nqdc_accrual_versus_pbo_posture_divergence
        """
        context = _plan_with_two_participants(api)

        summary = funding_summary(api, context["plan_id"], basis="PBO")
        assert summary["basis"] == "PBO"
        assert summary["accrual_liability_usd"] == pytest.approx(1_100_000.00, abs=0.01)
        assert summary["pbo_liability_usd"] == pytest.approx(1_776_294.83, abs=0.01)
        assert summary["basis_liability_usd"] == pytest.approx(1_776_294.83, abs=0.01)
        assert summary["matched_cash_value_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert summary["funded_ratio_bps"] == 5630
        assert summary["funding_posture"] == "CRITICAL", (
            "5630 basis points is below the 8000 basis point floor"
        )
        assert summary["participant_count"] == 2

        plan = validate_success(api.get_nqdc_plan(context["plan_id"], TREASURY))
        assert plan["funded_ratio_bps"] == 9091, "the persisted ratio is untouched by the read"
        assert plan["funding_posture"] == "UNDERFUNDED"


class TestDistributionCascadeReachesThePlan:
    def _funded_plan_with_claim(self, api):
        context = in_force_policy(
            api,
            carrier_overrides=LARKSPUR,
            product_overrides={"product_name": "Larkspur GA BOLI"},
            employee_overrides=DUVAL,
            policy_overrides={"policy_number": "LK-0001"},
        )
        plan = create_plan(api, plan_name="Larkspur SERP")
        liability = add_liability(
            api,
            plan["id"],
            context["employee_id"],
            accrued_to_date_usd=1_000_000.00,
            projected_benefit_usd=1_200_000.00,
            years_to_payout=5,
            matched_policy_id=context["policy_id"],
        )
        move_clock(api, "2026-11-15T00:00:00Z")
        claim = approved_claim(api, context["policy_id"])
        add_allocation(
            api,
            claim["id"],
            beneficiary_name="Elise Duval",
            relationship="SPOUSE",
            allocation_pct_bps=10000,
        )
        seal_allocations(api, claim["id"])
        context.update(
            {"plan_id": plan["id"], "liability": liability, "claim_id": claim["id"]}
        )
        return context

    def test_distribution_pays_the_policy_out_and_re_rates_the_carrier(self, api):
        """The first two hops empty the policy and the carrier's in-force totals.

        "Its first hop drives the policy `CLAIM_PENDING → PAID_OUT` and sets the
        policy's `cash_surrender_value_usd` to 0.00". "Its second hop removes
        that policy's premium and cash value from the carrier's
        `in_force_premium_usd` and `in_force_cash_value_usd`, recomputes the
        carrier's `concentration_bps` and re-applies the authorization
        hysteresis". The beneficiary carrying the whole share is paid the entire
        survivor entitlement.

        Design: Difficulty/transitive_cascade/distribute_pays_policy_then_unmatches_liability_then_freezes_plan
        """
        context = self._funded_plan_with_claim(api)
        assert context["liability"]["discounted_benefit_usd"] == pytest.approx(
            940_231.40, abs=0.01
        )

        distributed = validate_success(api.distribute_death_claim(context["claim_id"], CLAIMS))
        assert distributed["distribution_status"] == "DISTRIBUTED"
        assert distributed["adjudication_status"] == "APPROVED"

        items = api.list_beneficiary_allocations(
            CLAIMS, params={"claim_id": context["claim_id"]}
        ).json()["data"]
        assert len(items) == 1
        assert items[0]["gross_amount_usd"] == pytest.approx(3_000_000.00, abs=0.01)

        policy = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert policy["status"] == "PAID_OUT"
        assert policy["cash_surrender_value_usd"] == pytest.approx(0.00, abs=0.01)

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["in_force_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["in_force_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["concentration_bps"] == 0

    def test_the_third_hop_unmatches_the_liability_and_freezes_the_plan(self, api):
        """Losing its funding policy drives the plan critical and freezes it.

        "Its third hop reaches the deferred compensation ledger: every
        participant liability whose `matched_policy_id` was this policy has that
        field cleared, and that unmatch recomputes the owning plan's
        `accrual_liability_usd`, `pbo_liability_usd`, `matched_cash_value_usd`,
        `funded_ratio_bps` and `funding_posture`. If the recomputed
        accrual-basis posture is `CRITICAL`, the plan is driven `ACTIVE →
        FROZEN` in the same request." The liability itself is only unmatched, not
        settled, so both liability sums still include it.

        Design: Difficulty/transitive_cascade/distribute_pays_policy_then_unmatches_liability_then_freezes_plan
        """
        context = self._funded_plan_with_claim(api)
        validate_success(api.distribute_death_claim(context["claim_id"], CLAIMS))

        liability = validate_success(
            api.get_nqdc_liability(context["liability"]["id"], TREASURY)
        )
        assert liability["matched_policy_id"] is None
        assert liability["status"] == "ACTIVE", "the unmatch does not settle the liability"

        plan = validate_success(api.get_nqdc_plan(context["plan_id"], TREASURY))
        assert plan["matched_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert plan["accrual_liability_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert plan["pbo_liability_usd"] == pytest.approx(940_231.40, abs=0.01)
        assert plan["funded_ratio_bps"] == 0
        assert plan["funding_posture"] == "CRITICAL"
        assert plan["status"] == "FROZEN"
