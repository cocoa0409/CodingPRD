"""Damage fee dual-variant and multi-branch calculation tests (PRD §3.6)."""

from test_helpers import (
    add_active_insurance,
    confirm_damage_report,
    file_damage_report,
    setup_student_with_assignment,
    submit_damage_report,
)

# Fleet economics used throughout: replacement 100000, salvage 10000,
# useful_life 36, in_service 2025-09-01. Unit pre-damage grade B.
# Provisional (SCREEN on a grade-B unit) = 100000 * 0.55 * (1 - 0.10) = 49500.
PROVISIONAL_SCREEN_GRADE_B = 49500


def _setup_with_insurance(deductible_cents=2500, coverage_cap_cents=50000,
                          free_lunch=True):
    ctx = setup_student_with_assignment(free_lunch=free_lunch, asset_grade="B")
    policy = add_active_insurance(
        ctx["program"]["id"], ctx["student"]["id"],
        deductible_cents=deductible_cents, coverage_cap_cents=coverage_cap_cents,
    )
    ctx["policy"] = policy
    return ctx


class TestProvisionalVsFinalDamageFee:
    def test_provisional_fee_excludes_insurance_and_waiver(self, api):
        """PRD §3.6: "No insurance and no waiver enter the provisional figure; it is a gross quote."
        PRD §3.6: "the result is then discounted for the unit's pre-damage `condition_grade`, reduced by 0% for grade `A`, 10% for `B`, 25% for `C`, 50% for `D`, and 75% for `F`."

        SCREEN on a grade-B unit with an ACTIVE policy and free-lunch eligibility:
        provisional = 100000 * 0.55 * (1 - 0.10) = 49500 regardless of insurance/waiver.

        Design: Difficulty/dual_variant_calc/damage_fee_provisional_vs_final
        """
        ctx = _setup_with_insurance()
        report = file_damage_report(
            ctx, damage_category="SCREEN", observed_condition_grade="D"
        )
        assert report["status"] == "DRAFT"
        assert report["provisional_fee_cents"] == PROVISIONAL_SCREEN_GRADE_B, (
            f"Expected gross provisional 49500, got {report['provisional_fee_cents']}"
        )
        submitted = submit_damage_report(ctx, report["id"])
        assert submitted["provisional_fee_cents"] == PROVISIONAL_SCREEN_GRADE_B, (
            "PRD §3.6: submitting 'freezes the `provisional_fee_cents` at the submitted figure'"
        )

    def test_final_fee_applies_insurance_then_waiver_below_provisional(self, api):
        """PRD §3.6: "when the remaining coverage is at least that amount, the insurer pays the gross minus the deductible and the family owes exactly the deductible".
        PRD §3.6: "Third, the fee waiver: for a `free_lunch_eligible` student, 80 percent of the family's responsibility is waived — rounded half up to a whole cent — and subtracted."

        gross 49500 -> insurer pays 47000, family owes deductible 2500 -> waiver
        removes 80% (2000) -> final 500, strictly below the frozen provisional 49500.

        Design: Difficulty/dual_variant_calc/damage_fee_provisional_vs_final
        """
        ctx = _setup_with_insurance()
        report = file_damage_report(
            ctx, damage_category="SCREEN", observed_condition_grade="D"
        )
        submit_damage_report(ctx, report["id"])
        confirmed = confirm_damage_report(ctx, report["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["final_fee_cents"] == 500, (
            f"Expected final 500 (deductible 2500 less 80% waiver), "
            f"got {confirmed['final_fee_cents']}"
        )
        assert confirmed["final_fee_cents"] < confirmed["provisional_fee_cents"]


class TestFinalDamageFeeBranchInteraction:
    def test_final_fee_free_lunch_waiver_branch_without_insurance(self, api):
        """PRD §3.6: "Third, the fee waiver: for a `free_lunch_eligible` student, 80 percent of the family's responsibility is waived — rounded half up to a whole cent — and subtracted."
        PRD §3.6: "Without an active policy the family owes the gross."

        No insurance: responsibility 49500 -> waiver removes round(49500*0.80)=39600
        -> final 9900 (cap at depreciated value 82500 does not bind).

        Design: Difficulty/combinatorial_formula/final_damage_fee_mode_a_multi_input_conditional
        """
        ctx = setup_student_with_assignment(free_lunch=True, asset_grade="B")
        report = file_damage_report(
            ctx, damage_category="SCREEN", observed_condition_grade="C"
        )
        assert report["provisional_fee_cents"] == PROVISIONAL_SCREEN_GRADE_B
        submit_damage_report(ctx, report["id"])
        confirmed = confirm_damage_report(ctx, report["id"])
        assert confirmed["final_fee_cents"] == 9900, (
            f"Expected 9900 (49500 less 80% waiver), got {confirmed['final_fee_cents']}"
        )

    def test_final_fee_insurance_deductible_branch_without_waiver(self, api):
        """PRD §3.6: "Second, insurance: if the student's `insurance_enrolled` is true and the policy is `ACTIVE`, the coverage remaining under the policy's `coverage_cap_cents` (after payouts already made this school year) is compared against the gross minus the policy's `deductible_cents`; when the remaining coverage is at least that amount, the insurer pays the gross minus the deductible and the family owes exactly the deductible".

        Same gross 49500 as the waiver-branch twin, but with insurance and no
        free-lunch eligibility: insurer pays 47000, family owes exactly the
        2500 deductible -> final 2500. Identical inputs branch to different
        finals depending on insurance/waiver state.

        Design: Difficulty/combinatorial_formula/final_damage_fee_mode_a_multi_input_conditional
        """
        ctx = _setup_with_insurance(free_lunch=False)
        report = file_damage_report(
            ctx, damage_category="SCREEN", observed_condition_grade="C"
        )
        assert report["provisional_fee_cents"] == PROVISIONAL_SCREEN_GRADE_B
        submit_damage_report(ctx, report["id"])
        confirmed = confirm_damage_report(ctx, report["id"])
        assert confirmed["final_fee_cents"] == 2500, (
            f"Expected 2500 (exactly the deductible), got {confirmed['final_fee_cents']}"
        )
