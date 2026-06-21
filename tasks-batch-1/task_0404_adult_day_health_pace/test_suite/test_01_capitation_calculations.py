"""Capitation amount calculation (PRD 3.7, 2.7): proration modes, dual/non-dual
splits, round-per-component, and the divergence between FULL_MONTH and DAILY.

Difficulty queue A: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    assert_capitation_components_sum,
    create_program, set_clock, setup_enrolled_participant, create_participant,
    create_certified_loc, create_active_care_plan,
    create_draft_capitation, finalize_capitation, get_participant_version,
    submit_disenrollment, approve_disenrollment, finalize_disenrollment,
    TEST_USERS,
)

IC = TEST_USERS["intake_coordinator_headers"]
BS = TEST_USERS["billing_specialist_headers"]


def _enroll_dual_full_month(program, dual_eligible, effective="2026-06-01"):
    _, participant, _ = setup_enrolled_participant(
        program=program, dual_eligible=dual_eligible, effective_date=effective)
    return participant


# ===========================================================================
# dual_variant_calc / capitation_full_month_vs_daily_diverge
# ===========================================================================
def test_full_month_dual_bills_whole_member_month():
    """PRD 3.7: "Under FULL_MONTH the factor is exactly 1 - the whole member-month
    is billed regardless of how many days were covered (though at least one covered
    day is still required to finalize)."
    PRD 3.7: "For a dual-eligible participant, the Medicaid base is the program's
    medicaid_monthly_rate_cents and the supplement base is 0."

    Design: Difficulty/dual_variant_calc/capitation_full_month_vs_daily_diverge
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000)
    set_clock("2026-06-15T12:00:00Z")
    participant = _enroll_dual_full_month(program, dual_eligible=True)
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    finalized = finalize_capitation(payment["id"], participant["id"])

    assert finalized["total_billed_cents"] == 630000
    assert finalized["medicare_share_cents"] == 280000
    assert finalized["medicaid_share_cents"] == 350000
    assert finalized["supplement_cents"] == 0
    assert_capitation_components_sum(finalized)


def test_daily_proration_dual_scales_by_covered_days():
    """PRD 3.7: "Under DAILY the factor is covered_days divided by the number of
    calendar days in the month, applied to each base before its independent rounding."
    PRD 3.7: "The covered_days is the count of calendar days d within the service_month
    for which the participant's enrollment window covers d - that is, the enrollment's
    effective date is on or before d, and either no disenrollment effective date is set
    or d is strictly before it."

    A dual participant enrolled 2026-06-01 and disenrolled effective 2026-06-21 covers
    Jun 1..20 => covered_days 20 of 30; medicare 280000*20/30=186666.67->186667,
    medicaid 350000*20/30=233333.33->233333, total 420000.

    Design: Difficulty/dual_variant_calc/capitation_full_month_vs_daily_diverge
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000, lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    participant = _enroll_dual_full_month(program, dual_eligible=True)
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-06-21")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    payment = create_draft_capitation(participant["id"], "2026-06-01", "DAILY")
    finalized = finalize_capitation(payment["id"], participant["id"])

    assert finalized["covered_days"] == 20
    assert finalized["total_billed_cents"] == 420000
    assert_capitation_components_sum(finalized)


def test_full_month_and_daily_diverge_on_same_inputs():
    """PRD 3.7: "Under FULL_MONTH the factor is exactly 1 - the whole member-month
    is billed regardless of how many days were covered (though at least one covered
    day is still required to finalize)."
    PRD 3.7: "Under DAILY the factor is covered_days divided by the number of calendar
    days in the month, applied to each base before its independent rounding."

    Same rates + same dual participant + June service month: FULL_MONTH bills 630000
    while DAILY with covered_days 20/30 bills 420000 — the two algorithms diverge.

    Design: Difficulty/dual_variant_calc/capitation_full_month_vs_daily_diverge
    """
    prog_a = create_program(medicaid_monthly_rate_cents=350000,
                            medicare_monthly_rate_cents=280000, lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    p_full = _enroll_dual_full_month(prog_a, dual_eligible=True)
    pay_full = create_draft_capitation(p_full["id"], "2026-06-01", "FULL_MONTH")
    full = finalize_capitation(pay_full["id"], p_full["id"])

    p_daily = _enroll_dual_full_month(prog_a, dual_eligible=True)
    req = submit_disenrollment(p_daily["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-06-21")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], p_daily["id"])
    pay_daily = create_draft_capitation(p_daily["id"], "2026-06-01", "DAILY")
    daily = finalize_capitation(pay_daily["id"], p_daily["id"])

    assert full["total_billed_cents"] == 630000
    assert daily["total_billed_cents"] == 420000
    assert full["total_billed_cents"] != daily["total_billed_cents"]


# ===========================================================================
# dual_variant_calc / dual_vs_nondual_billing_split
# ===========================================================================
def test_nondual_participant_self_pays_medicaid_as_supplement():
    """PRD 3.7: "For a non-dual (Medicare-only) participant, the Medicaid base is 0
    and the supplement base is the sum of the program's medicaid_monthly_rate_cents
    and its medicare_only_supplement_cents - the Medicare-only member self-pays the
    Medicaid share, plus the configured supplement, as the supplement_cents line."

    Non-dual FULL_MONTH June: medicaid 0, supplement 350000+50000=400000,
    medicare 280000, total 680000.

    Design: Difficulty/dual_variant_calc/dual_vs_nondual_billing_split
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000,
                             medicare_only_supplement_cents=50000)
    set_clock("2026-06-15T12:00:00Z")
    participant = _enroll_dual_full_month(program, dual_eligible=False)
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    finalized = finalize_capitation(payment["id"], participant["id"])

    assert finalized["medicaid_share_cents"] == 0
    assert finalized["supplement_cents"] == 400000
    assert finalized["medicare_share_cents"] == 280000
    assert finalized["total_billed_cents"] == 680000
    assert_capitation_components_sum(finalized)


def test_dual_and_nondual_split_diverge_same_rates():
    """PRD 3.7: "For a dual-eligible participant, the Medicaid base is the program's
    medicaid_monthly_rate_cents and the supplement base is 0."
    PRD 3.7: "For a non-dual (Medicare-only) participant, the Medicaid base is 0 and
    the supplement base is the sum of the program's medicaid_monthly_rate_cents and
    its medicare_only_supplement_cents - the Medicare-only member self-pays the
    Medicaid share, plus the configured supplement, as the supplement_cents line."

    Same base rates route to different component splits by dual_eligible: dual bills
    medicaid 350000 + supplement 0; non-dual bills medicaid 0 + supplement 400000.

    Design: Difficulty/dual_variant_calc/dual_vs_nondual_billing_split
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000,
                             medicare_only_supplement_cents=50000)
    set_clock("2026-06-15T12:00:00Z")
    p_dual = _enroll_dual_full_month(program, dual_eligible=True)
    dual = finalize_capitation(
        create_draft_capitation(p_dual["id"], "2026-06-01", "FULL_MONTH")["id"], p_dual["id"])

    p_nondual = _enroll_dual_full_month(program, dual_eligible=False)
    nondual = finalize_capitation(
        create_draft_capitation(p_nondual["id"], "2026-06-01", "FULL_MONTH")["id"], p_nondual["id"])

    assert dual["medicaid_share_cents"] == 350000 and dual["supplement_cents"] == 0
    assert nondual["medicaid_share_cents"] == 0 and nondual["supplement_cents"] == 400000


# ===========================================================================
# combinatorial_formula / capitation_tiered_mode_dual_factor_combination
# ===========================================================================
def test_nondual_daily_combines_mode_dual_and_factor():
    """PRD 3.7: "the supplement base is the sum of the program's
    medicaid_monthly_rate_cents and its medicare_only_supplement_cents".
    PRD 3.7: "Under DAILY the factor is covered_days divided by the number of calendar
    days in the month, applied to each base before its independent rounding."
    PRD 3.7: "Each share is the product of its base and the factor, rounded half-up to
    whole cents".

    Non-dual June, disenrolled effective 2026-06-11 => covered_days 10/30:
    medicare round(280000*10/30)=93333; supplement round(400000*10/30)=133333;
    medicaid 0; total 226666.

    Design: Difficulty/combinatorial_formula/capitation_tiered_mode_dual_factor_combination
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000,
                             medicare_only_supplement_cents=50000, lock_in_days=30)
    set_clock("2026-07-05T12:00:00Z")
    participant = _enroll_dual_full_month(program, dual_eligible=False)
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-06-11")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    payment = create_draft_capitation(participant["id"], "2026-06-01", "DAILY")
    finalized = finalize_capitation(payment["id"], participant["id"])

    assert finalized["covered_days"] == 10
    assert finalized["medicare_share_cents"] == 93333
    assert finalized["medicaid_share_cents"] == 0
    assert finalized["supplement_cents"] == 133333
    assert finalized["total_billed_cents"] == 226666
    assert_capitation_components_sum(finalized)


def test_nondual_daily_total_equals_component_sum_not_single_rate():
    """PRD 3.7: "The total_billed_cents is the sum of those three rounded components."
    PRD 3.7: "first compute covered_days; second select three bases; third apply a
    single proration factor to each base; fourth round each of the three results
    independently to whole cents using round-half-up; fifth sum the three rounded
    components."

    The non-dual DAILY 10/30 case totals 226666 = 93333 (medicare) + 0 (medicaid) +
    133333 (supplement); no single linear rate reproduces this combination.

    Design: Difficulty/combinatorial_formula/capitation_tiered_mode_dual_factor_combination
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000,
                             medicare_only_supplement_cents=50000, lock_in_days=30)
    set_clock("2026-07-05T12:00:00Z")
    participant = _enroll_dual_full_month(program, dual_eligible=False)
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-06-11")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    payment = create_draft_capitation(participant["id"], "2026-06-01", "DAILY")
    finalized = finalize_capitation(payment["id"], participant["id"])

    assert finalized["total_billed_cents"] == (
        finalized["medicare_share_cents"]
        + finalized["medicaid_share_cents"]
        + finalized["supplement_cents"]
    )
    assert finalized["total_billed_cents"] == 226666


# ===========================================================================
# combinatorial_formula / capitation_round_per_component_not_sum_then_round
# ===========================================================================
def test_round_per_component_then_sum_dual_daily():
    """PRD 2.7: "Where a calculation specifies that several components are rounded
    independently and then summed, the rounding is applied to each component first and
    the rounded components are added afterward; the sum is not re-rounded."
    PRD 3.7: "fourth round each of the three results independently to whole cents using
    round-half-up; fifth sum the three rounded components."

    Dual DAILY covered_days 7/30 (disenroll effective 2026-06-08): medicare
    round(280000*7/30)=65333 (.33) and medicaid round(350000*7/30)=81667 (.66) sum to
    147000 — round-per-component, not sum-then-round.

    Design: Difficulty/combinatorial_formula/capitation_round_per_component_not_sum_then_round
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000, lock_in_days=30)
    set_clock("2026-07-05T12:00:00Z")
    participant = _enroll_dual_full_month(program, dual_eligible=True)
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-06-08")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    payment = create_draft_capitation(participant["id"], "2026-06-01", "DAILY")
    finalized = finalize_capitation(payment["id"], participant["id"])

    assert finalized["covered_days"] == 7
    assert finalized["medicare_share_cents"] == 65333
    assert finalized["medicaid_share_cents"] == 81667
    assert finalized["total_billed_cents"] == 147000
    assert_capitation_components_sum(finalized)


def test_each_component_rounded_half_up_independently():
    """PRD 2.7: "Wherever a calculation produces a fractional cent - chiefly when a
    proration factor or a lock-in fraction multiplies a monthly rate - the result is
    rounded to a whole number of cents using the round-half-up convention (a value
    exactly at the halfway point rounds up, away from zero)."
    PRD 3.7: "Each share is the product of its base and the factor, rounded half-up to
    whole cents: medicare_share_cents from the Medicare base, medicaid_share_cents from
    the Medicaid base, and supplement_cents from the supplement base."

    Dual DAILY 7/30: 280000*7/30 = 65333.33 rounds DOWN to 65333; 350000*7/30 = 81666.66
    rounds UP to 81667 — each component rounded independently.

    Design: Difficulty/combinatorial_formula/capitation_round_per_component_not_sum_then_round
    """
    program = create_program(medicaid_monthly_rate_cents=350000,
                             medicare_monthly_rate_cents=280000, lock_in_days=30)
    set_clock("2026-07-05T12:00:00Z")
    participant = _enroll_dual_full_month(program, dual_eligible=True)
    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-06-08")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    payment = create_draft_capitation(participant["id"], "2026-06-01", "DAILY")
    finalized = finalize_capitation(payment["id"], participant["id"])

    assert finalized["medicare_share_cents"] == 65333, "280000*7/30=65333.33 rounds down"
    assert finalized["medicaid_share_cents"] == 81667, "350000*7/30=81666.66 rounds up"
