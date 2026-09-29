"""Which liabilities count towards a plan, and which ceiling caps a survivor's share."""
import pytest
from test_helpers import validate_success
from test_helpers.assertions import assert_death_benefit_conservation
from test_helpers.fixtures import (
    TREASURY,
    add_allocation,
    add_liability,
    approved_claim,
    claim_allocations,
    create_plan,
    funding_summary,
    in_force_policy,
    register_employee,
    seal_allocations,
)


PEARL = {
    "legal_name": "Pearl Life",
    "naic_code": "71016",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "KY",
}

ITO = {
    "full_name": "Hana Ito",
    "employee_number": "E-8101",
    "annual_salary_usd": 1_000_000.00,
    "officer_flag": False,
}


class TestSettledLiabilitiesLeaveTheFundingBases:
    def test_settling_one_of_two_participants_drops_it_from_both_bases(self, api):
        """A settled promise is no longer a liability on either view.

        "`accrual_liability_usd` is the sum of `accrued_to_date_usd` over the
        plan's `ACTIVE` liabilities and `pbo_liability_usd` is the sum of the
        rounded per-participant `discounted_benefit_usd` values over the same
        set." Settling removes the participant from that set, since "Settling a
        liability sets its `status` to `SETTLED`, increments that liability's
        `version` by 1, recomputes the plan's totals and accrual-basis posture,
        and increments the plan's `version` by 1", and the summary reports "the
        `participant_count` of `ACTIVE` liabilities".

        Design: Corner/calculations/nqdc_funding_summary_excludes_settled_liabilities
        """
        plan = create_plan(api, plan_name="Filter SERP", plan_type="SERP", discount_rate_bps=500)
        reyes = register_employee(
            api,
            full_name="Ada Reyes",
            employee_number="E-7901",
            annual_salary_usd=700_000.00,
            officer_flag=False,
        )
        diaz = register_employee(
            api,
            full_name="Owen Diaz",
            employee_number="E-7902",
            annual_salary_usd=600_000.00,
            officer_flag=False,
        )
        kept = add_liability(
            api,
            plan["id"],
            reyes["id"],
            accrued_to_date_usd=600_000.00,
            projected_benefit_usd=800_000.00,
            years_to_payout=5,
        )
        settled_liability = add_liability(
            api,
            plan["id"],
            diaz["id"],
            accrued_to_date_usd=400_000.00,
            projected_benefit_usd=500_000.00,
            years_to_payout=10,
        )
        assert kept["discounted_benefit_usd"] == pytest.approx(626_820.93, abs=0.01)
        assert settled_liability["discounted_benefit_usd"] == pytest.approx(306_956.63, abs=0.01)

        before = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert before["accrual_liability_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert before["pbo_liability_usd"] == pytest.approx(933_777.56, abs=0.01)

        closed = validate_success(
            api.settle_nqdc_liability(settled_liability["id"], TREASURY)
        )
        assert closed["status"] == "SETTLED"

        accrual = funding_summary(api, plan["id"])
        assert accrual["basis"] == "ACCRUAL"
        assert accrual["accrual_liability_usd"] == pytest.approx(600_000.00, abs=0.01)
        assert accrual["pbo_liability_usd"] == pytest.approx(626_820.93, abs=0.01)
        assert accrual["basis_liability_usd"] == pytest.approx(600_000.00, abs=0.01)
        assert accrual["participant_count"] == 1
        assert accrual["matched_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert accrual["funded_ratio_bps"] == 0
        assert accrual["funding_posture"] == "CRITICAL"

        projected = funding_summary(api, plan["id"], basis="PBO")
        assert projected["basis"] == "PBO"
        assert projected["basis_liability_usd"] == pytest.approx(626_820.93, abs=0.01)
        assert projected["participant_count"] == 1
        assert projected["funded_ratio_bps"] == 0
        assert projected["funding_posture"] == "CRITICAL"

        after = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert after["accrual_liability_usd"] == pytest.approx(600_000.00, abs=0.01)
        assert after["pbo_liability_usd"] == pytest.approx(626_820.93, abs=0.01)
        assert after["status"] == "ACTIVE"

    def test_settling_the_last_participant_restores_the_full_funding_convention(self, api):
        """An empty plan is fully funded by convention, not by division.

        "when the basis liability is exactly 0.00 the ratio is reported as 10000
        rather than being left undefined", and "`funding_posture` is `FUNDED` when
        `funded_ratio_bps` is 10000 or more". Settling only "recomputes the plan's
        totals and accrual-basis posture", so nothing freezes the plan on the way
        back to that convention.

        Design: Corner/calculations/settling_the_last_liability_restores_the_zero_liability_full_funding_guard
        """
        plan = create_plan(api, plan_name="Solo SERP", plan_type="SERP", discount_rate_bps=500)
        berg = register_employee(
            api,
            full_name="Nils Berg",
            employee_number="E-8001",
            annual_salary_usd=700_000.00,
            officer_flag=False,
        )
        liability = add_liability(
            api,
            plan["id"],
            berg["id"],
            accrued_to_date_usd=600_000.00,
            projected_benefit_usd=800_000.00,
            years_to_payout=5,
        )

        loaded = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert loaded["accrual_liability_usd"] == pytest.approx(600_000.00, abs=0.01)
        assert loaded["pbo_liability_usd"] == pytest.approx(626_820.93, abs=0.01)
        assert loaded["funded_ratio_bps"] == 0
        assert loaded["funding_posture"] == "CRITICAL"

        closed = validate_success(api.settle_nqdc_liability(liability["id"], TREASURY))
        assert closed["status"] == "SETTLED"

        emptied = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert emptied["accrual_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert emptied["pbo_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert emptied["matched_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert emptied["funded_ratio_bps"] == 10000
        assert emptied["funding_posture"] == "FUNDED"
        assert emptied["status"] == "ACTIVE", "settling never freezes the plan"

        summary = funding_summary(api, plan["id"], basis="PBO")
        assert summary["basis"] == "PBO"
        assert summary["basis_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert summary["funded_ratio_bps"] == 10000
        assert summary["funding_posture"] == "FUNDED"
        assert summary["participant_count"] == 0


class TestSurvivorEntitlementTakesTheLowerCeiling:
    def test_a_modest_salary_makes_the_multiple_the_binding_ceiling(self, api):
        """When the salary multiple is the smaller figure, it wins.

        "Against that total two ceilings are computed and the lower one wins. The
        first is a proportional cap: sixty hundredths of the total death benefit,
        rounded half up to 2 decimal places. The second is a salary multiple: the
        insured employee's `annual_salary_usd` multiplied by two, rounded half up
        to 2 decimal places. `survivor_entitlement_usd` is the lesser of those two
        figures, and `bank_portion_usd` is the total death benefit minus the
        survivor entitlement". A 1,000,000.00 salary yields 2,000,000.00 against a
        3,000,000.00 proportional cap.

        Design: Corner/calculations/survivor_entitlement_uses_the_salary_multiple_when_it_is_below_the_family_cap
        """
        context = in_force_policy(
            api,
            carrier_overrides=PEARL,
            product_overrides={"product_name": "Pearl GA BOLI"},
            employee_overrides=ITO,
            consent_overrides={"consent_form_reference": "CF-8101"},
            request_overrides={
                "single_premium_usd": 1_200_000.00,
                "face_amount_usd": 5_000_000.00,
            },
            policy_overrides={"policy_number": "PL-0001"},
        )
        claim = approved_claim(
            api,
            context["policy_id"],
            date_of_death="2026-08-20T00:00:00Z",
            terminal_dividend_usd=0.00,
            proof_reference="DC-8101",
        )
        assert claim["total_death_benefit_usd"] == pytest.approx(5_000_000.00, abs=0.01)
        assert claim["survivor_entitlement_usd"] == pytest.approx(2_000_000.00, abs=0.01)
        assert claim["bank_portion_usd"] == pytest.approx(3_000_000.00, abs=0.01)

        spouse = add_allocation(
            api,
            claim["id"],
            beneficiary_name="Kenji Ito",
            relationship="SPOUSE",
            allocation_pct_bps=6000,
        )
        child = add_allocation(
            api,
            claim["id"],
            beneficiary_name="Sora Ito",
            relationship="CHILD",
            allocation_pct_bps=4000,
        )

        sealed = seal_allocations(api, claim["id"])
        assert sealed["distribution_status"] == "ALLOCATED"
        assert sealed["allocated_bps_total"] == 10000

        allocations = claim_allocations(api, claim["id"])
        by_id = {a["id"]: a for a in allocations}
        assert by_id[spouse["id"]]["gross_amount_usd"] == pytest.approx(1_200_000.00, abs=0.01)
        assert by_id[child["id"]]["gross_amount_usd"] == pytest.approx(800_000.00, abs=0.01)
        assert_death_benefit_conservation(sealed, allocations)
