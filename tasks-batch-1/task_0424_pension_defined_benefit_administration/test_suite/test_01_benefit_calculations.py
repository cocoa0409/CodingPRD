"""Benefit-formula, lump-sum APV, J&S reduction, COLA and PBGC premium calculations.

Translates the dual_variant_calc and combinatorial_formula difficulty instances
(queue A) plus the calculation corner instances (queue B). Literal expected values
are copied from the design indices, which pre-computed them from the PRD formulas.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    create_plan_payload,
    create_premium_payload,
    create_service_adjustment_payload,
    setup_terminated_vested_participant_330k,
    create_participant,
    add_standard_comp_330k,
    draft_election,
    create_submitted_single_life_election,
    setup_in_pay_payment,
    list_payments_for_participant,
)

SPONSOR = TEST_USERS["plan_sponsor_headers"]
ACTUARY = TEST_USERS["plan_actuary_headers"]
ADMIN = TEST_USERS["benefits_admin_headers"]
ADM_A = TEST_USERS["benefits_admin_a_headers"]
ADM_B = TEST_USERS["benefits_admin_b_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / benefit_formula_fap_vs_cash_balance_diverge
# ---------------------------------------------------------------------------
def test_fap_gross_accrued_monthly_from_highest3_consecutive(api):
    """PRD §3.4: "For a `FINAL_AVERAGE_PAY` plan it is the product of
    `final_average_pay_cents`, the plan's `fap_accrual_rate`, the participant's
    `credited_service_years`, and the participant's `vested_pct`, all divided by 12,
    rounded half-up to whole cents."
    PRD §3.3: "when there are at least three rows it considers every window of three
    consecutive years, takes the window whose summed capped compensation is greatest
    (breaking ties toward the earliest starting `plan_year`), and divides that sum by
    three, rounding half-up to whole cents."

    Design: Difficulty/dual_variant_calc/benefit_formula_fap_vs_cash_balance_diverge
    """
    plan = get_success_data(api.create_plan(create_plan_payload(
        benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015,
        normal_retirement_age=65, cola_pct=0.02,
    ), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1962-01-01", hire_date="2000-01-01")
    # Highest-3-consecutive (2021/2022/2023) sum 33,000,000 -> FAP 11,000,000.
    for year, comp in ((2019, 9_000_000), (2020, 9_500_000), (2021, 10_000_000),
                       (2022, 11_000_000), (2023, 12_000_000)):
        get_success_data(api.create_compensation(
            {"participant_id": participant["id"], "plan_year": year, "gross_comp_cents": comp}, ADMIN))
    participant = get_success_data(api.terminate_participant(
        participant["id"], ADMIN, {"termination_date": "2024-01-01"}))
    assert participant["vesting_status"] == "FULLY_VESTED"
    assert participant["final_average_pay_cents"] == 11_000_000

    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "SINGLE_LIFE",
         "annuity_start_date": "2024-06-01"}, ADMIN))
    submitted = validate_success(api.submit_election(election["id"], ADM_A))
    assert submitted["gross_accrued_monthly_cents"] == 330000
    assert submitted["js_reduced_monthly_cents"] == 330000


def test_fap_final_average_pay_recomputed_to_11m(api):
    """PRD §3.3: "For a final-average-pay plan, the participant's
    `final_average_pay_cents` is the average of the highest three *consecutive* plan
    years by `capped_comp_cents`."

    Design: Difficulty/dual_variant_calc/benefit_formula_fap_vs_cash_balance_diverge
    """
    plan, participant = setup_terminated_vested_participant_330k(
        benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015)
    assert participant["final_average_pay_cents"] == 11_000_000
    assert participant["vesting_status"] == "FULLY_VESTED"


# ---------------------------------------------------------------------------
# dual_variant_calc / lump_sum_apv_sla_basis_vs_417e_basis_diverge
# ---------------------------------------------------------------------------
def _fap_lump_sum_participant(api, dob, comp_years=((2021, 10_000_000), (2022, 11_000_000), (2023, 12_000_000))):
    plan = get_success_data(api.create_plan(create_plan_payload(
        benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015, cola_pct=0.0), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth=dob, hire_date="2000-01-01")
    for year, comp in comp_years:
        get_success_data(api.create_compensation(
            {"participant_id": participant["id"], "plan_year": year, "gross_comp_cents": comp}, ADMIN))
    get_success_data(api.terminate_participant(participant["id"], ADMIN, {"termination_date": "2024-01-01"}))
    return plan, participant


def test_lump_sum_value_age_62_segment_factor_60_64(api):
    """PRD §3.4: "The lump-sum value applies a 417(e) segment factor selected by the
    participant's attained whole-year age at the `annuity_start_date`: at age 65 or
    above the factor is 12.4; at age 60 through 64 it is 11.9; at age 55 through 59 it
    is 10.8. The `lump_sum_value_cents` is the annual amount multiplied by the selected
    segment factor, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/lump_sum_apv_sla_basis_vs_417e_basis_diverge
    """
    plan, participant = _fap_lump_sum_participant(api, "1962-01-01")  # age 62 at ASD
    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "LUMP_SUM",
         "annuity_start_date": "2024-06-01"}, ADMIN))
    submitted = validate_success(api.submit_election(election["id"], ADM_A))
    assert submitted["gross_accrued_monthly_cents"] == 330000
    assert submitted["lump_sum_value_cents"] == 47124000


def test_lump_sum_relative_value_age_62_is_0952(api):
    """PRD §3.4: "The `relative_value_pct` is `lump_sum_value_cents` divided by the
    comparator present value, rounded to four decimal places."
    PRD §3.4: "The annuity comparator present value is that annual amount multiplied by
    the straight-life annuity factor of 12.5, rounded half-up to whole cents — call this
    the comparator present value."

    Design: Difficulty/dual_variant_calc/lump_sum_apv_sla_basis_vs_417e_basis_diverge
    """
    plan, participant = _fap_lump_sum_participant(api, "1962-01-01")  # age 62 at ASD
    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "LUMP_SUM",
         "annuity_start_date": "2024-06-01"}, ADMIN))
    submitted = validate_success(api.submit_election(election["id"], ADM_A))
    assert submitted["relative_value_pct"] == 0.952


# ---------------------------------------------------------------------------
# combinatorial_formula / lump_sum_age_band_tiered_factor_selection
# ---------------------------------------------------------------------------
def test_lump_sum_age_57_uses_55_59_segment_factor(api):
    """PRD §3.4: "at age 55 through 59 it is 10.8. The `lump_sum_value_cents` is the
    annual amount multiplied by the selected segment factor, rounded half-up to whole
    cents."

    Design: Difficulty/combinatorial_formula/lump_sum_age_band_tiered_factor_selection
    """
    plan, participant = _fap_lump_sum_participant(api, "1967-01-01")  # age 57 at ASD
    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "LUMP_SUM",
         "annuity_start_date": "2024-06-01"}, ADMIN))
    submitted = validate_success(api.submit_election(election["id"], ADM_A))
    assert submitted["gross_accrued_monthly_cents"] == 330000
    assert submitted["lump_sum_value_cents"] == 42768000


def test_lump_sum_relative_value_age_57_is_0864(api):
    """PRD §3.4: "The `relative_value_pct` is `lump_sum_value_cents` divided by the
    comparator present value, rounded to four decimal places. Because the 55-through-59
    segment factor is materially smaller than the comparator factor, a lump sum elected
    in that age band produces a relative value below the floor and will fail the
    relative-value test at approval."

    Design: Difficulty/combinatorial_formula/lump_sum_age_band_tiered_factor_selection
    """
    plan, participant = _fap_lump_sum_participant(api, "1967-01-01")  # age 57 at ASD
    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "LUMP_SUM",
         "annuity_start_date": "2024-06-01"}, ADMIN))
    submitted = validate_success(api.submit_election(election["id"], ADM_A))
    assert submitted["relative_value_pct"] == 0.864


# ---------------------------------------------------------------------------
# combinatorial_formula / pbgc_variable_rate_cap_applied_after_rate
# ---------------------------------------------------------------------------
def test_pbgc_variable_rate_cap_wins_over_raw_rate(api):
    """PRD §3.7: "the system first multiplies `unfunded_vested_benefits_cents` by the
    variable rate of 0.0052 and rounds half-up to whole cents, then takes the lesser of
    that figure and the cap, which is `participant_count` multiplied by 65,200 cents per
    participant. The cap is applied **after** the rate is computed, never before."

    Design: Difficulty/combinatorial_formula/pbgc_variable_rate_cap_applied_after_rate
    """
    plan = get_success_data(api.create_plan(create_plan_payload(
        benefit_formula_type="CASH_BALANCE", fap_accrual_rate=0.0,
        cb_pay_credit_rate=0.05, cb_interest_crediting_rate=0.04), SPONSOR))
    premium = get_success_data(api.create_premium(create_premium_payload(
        plan["id"], 2024, participant_count=10, unfunded_vested_benefits_cents=2_000_000_000), ACTUARY))
    fetched = validate_success(api.get_premium(premium["id"], ACTUARY))
    assert fetched["flat_rate_premium_cents"] == 101000
    assert fetched["variable_rate_premium_cents"] == 652000


def test_pbgc_total_premium_is_flat_plus_variable_capped(api):
    """PRD §3.7: "The `total_premium_cents` is the sum of `flat_rate_premium_cents` and
    `variable_rate_premium_cents`."

    Design: Difficulty/combinatorial_formula/pbgc_variable_rate_cap_applied_after_rate
    """
    plan = get_success_data(api.create_plan(create_plan_payload(
        benefit_formula_type="CASH_BALANCE", fap_accrual_rate=0.0,
        cb_pay_credit_rate=0.05, cb_interest_crediting_rate=0.04), SPONSOR))
    premium = get_success_data(api.create_premium(create_premium_payload(
        plan["id"], 2024, participant_count=10, unfunded_vested_benefits_cents=2_000_000_000), ACTUARY))
    assert premium["total_premium_cents"] == 753000


# ---------------------------------------------------------------------------
# Corner: calculations / js_reduction_factor_applied_joint_and_survivor
# ---------------------------------------------------------------------------
def test_js_reduction_factor_50pct_age_diff_3(api):
    """PRD §3.4: "It then builds a reduction factor starting from a base of 1.00,
    subtracting the product of `js_survivor_pct` and a survivor load of 0.12, and
    subtracting the product of the age difference and an age-difference load of 0.005
    per year the participant is older than the spouse. The factor is clamped to lie
    within 0.70 and 1.00 inclusive. The reduced amount is `gross_accrued_monthly_cents`
    multiplied by that clamped factor, rounded half-up to whole cents."

    Design: Corner/calculations/js_reduction_factor_applied_joint_and_survivor
    """
    plan, participant = setup_terminated_vested_participant_330k(
        benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015)
    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "JOINT_AND_SURVIVOR",
         "annuity_start_date": "2024-06-01", "js_survivor_pct": 0.50,
         "spouse_date_of_birth": "1965-01-01"}, ADMIN))
    submitted = validate_success(api.submit_election(election["id"], ADM_A))
    assert submitted["gross_accrued_monthly_cents"] == 330000
    # factor = 1.00 - 0.50*0.12 - 3*0.005 = 0.925 ; round(330000 * 0.925) = 305250
    assert submitted["js_reduced_monthly_cents"] == 305250


# ---------------------------------------------------------------------------
# Corner: calculations / cola_compounds_on_current_monthly
# ---------------------------------------------------------------------------
def test_cola_grows_current_monthly_by_2pct(api):
    """PRD §3.8: "Each application grows `current_monthly_cents` by setting it to its
    current value multiplied by the quantity (1 plus the plan's `cola_pct`), rounded
    half-up to whole cents, and increments `cola_applied_count` by one."

    Design: Corner/calculations/cola_compounds_on_current_monthly
    """
    plan, participant, election, payment = setup_in_pay_payment(plan_overrides={"cola_pct": 0.02})
    assert payment["current_monthly_cents"] == 330000
    after = validate_success(api.apply_cola(payment["id"], ADMIN))
    assert after["current_monthly_cents"] == 336600  # round(330000 * 1.02)
    assert after["cola_applied_count"] == 1


# ---------------------------------------------------------------------------
# Corner: calculations / pbgc_variable_rate_below_cap
# ---------------------------------------------------------------------------
def test_pbgc_variable_rate_below_cap_uses_raw_rate(api):
    """PRD §3.7: "the system first multiplies `unfunded_vested_benefits_cents` by the
    variable rate of 0.0052 and rounds half-up to whole cents, then takes the lesser of
    that figure and the cap, which is `participant_count` multiplied by 65,200 cents per
    participant."

    Design: Corner/calculations/pbgc_variable_rate_below_cap
    """
    plan = get_success_data(api.create_plan(create_plan_payload(
        benefit_formula_type="CASH_BALANCE", fap_accrual_rate=0.0,
        cb_pay_credit_rate=0.05, cb_interest_crediting_rate=0.04), SPONSOR))
    premium = get_success_data(api.create_premium(create_premium_payload(
        plan["id"], 2024, participant_count=100, unfunded_vested_benefits_cents=50_000_000), ACTUARY))
    # raw var = round(50,000,000 * 0.0052) = 260000 < cap 100*65200 = 6,520,000
    assert premium["variable_rate_premium_cents"] == 260000
    assert premium["total_premium_cents"] == 1270000  # flat 1,010,000 + 260,000


# ---------------------------------------------------------------------------
# Corner: calculations / service_credit_adjustment_promotes_to_fully_vested
# ---------------------------------------------------------------------------
def test_service_adjustment_promotes_to_fully_vested(api):
    """PRD §3.2: "To that rounded elapsed figure the system adds the signed sum of every
    `ServiceCreditAdjustment` recorded for the participant, and the final
    `credited_service_years` is the larger of zero and that total."
    PRD §3.2: "When credited service is 7 years or more the participant is
    `FULLY_VESTED` with a vested fraction of 1.00."

    Design: Corner/calculations/service_credit_adjustment_promotes_to_fully_vested
    """
    plan = get_success_data(api.create_plan(create_plan_payload(
        benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1965-01-01", hire_date="2010-01-01")
    participant = get_success_data(api.terminate_participant(
        participant["id"], ADMIN, {"termination_date": "2016-07-01"}))  # elapsed 6.0y -> PARTIALLY_VESTED
    assert participant["vesting_status"] == "PARTIALLY_VESTED"
    get_success_data(api.create_service_adjustment(create_service_adjustment_payload(
        participant["id"], "MILITARY_BUYBACK", 1.0), ADMIN))
    refetched = validate_success(api.get_participant(participant["id"], ADMIN))
    assert refetched["credited_service_years"] == 7.0
    assert refetched["vesting_status"] == "FULLY_VESTED"
    assert refetched["vested_pct"] == 1.0


# ---------------------------------------------------------------------------
# Corner: calculations / vesting_unvested_below_cliff
# ---------------------------------------------------------------------------
def test_vesting_unvested_below_three_year_cliff(api):
    """PRD §3.2: "When credited service is below 3 years the participant is `UNVESTED`
    with a vested fraction of 0.00."

    Design: Corner/calculations/vesting_unvested_below_cliff
    """
    plan = get_success_data(api.create_plan(create_plan_payload(
        benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1990-01-01", hire_date="2022-01-01")
    terminated = get_success_data(api.terminate_participant(
        participant["id"], ADMIN, {"termination_date": "2023-01-01"}))  # ~0.5y service
    assert terminated["vesting_status"] == "UNVESTED"
    assert terminated["vested_pct"] == 0.0
