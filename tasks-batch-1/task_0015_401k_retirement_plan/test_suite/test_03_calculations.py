"""Calculations: tiered/safe-harbor match, RMD (uniform/joint-life), loan
amortization, max-hardship, cliff/graded vesting.

Difficulty queue A — rule 1 (dual_variant_calc), rule 2 (combinatorial_formula),
rule 6 (boundary_precision_check).
Corner queue B — Section: calculations.
"""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    setup_active_plan_with_enrolled_participant,
    setup_participant_with_seeded_balances,
    setup_rmd_eligible_participant,
    create_and_activate_plan,
    create_and_enroll_participant,
    create_open_contribution_period,
    close_contribution_period,
    create_pending_participant,
    create_rmd_distribution_payload,
    create_contribution_period_payload,
    create_loan_payload,
    create_hardship_withdrawal_payload,
    update_deferral_rate,
    get_participant,
    get_contribution_period,
    get_loan,
)

_ADMIN = TEST_USERS["plan_admin_headers"]


# ─── Difficulty/dual_variant_calc/match_tiered_vs_safe_harbor_diverges ──────

def test_tiered_match_at_deferral_400_bps_yields_17500(api):
    """PRD §3.3: "Under the tiered formula the maximum effective employer cost is
    4% of compensation — reached once the participant defers at least 5% — but the
    schedule is curved: at a 4% deferral the participant earns only 3.5% of
    compensation in match (the full first tier plus half of one remaining deferral
    percentage point)."

    With gross_compensation_cents=500000 and deferral_rate_bps=400, the
    tiered formula yields employer_match_cents = floor(500000*300/10000) +
    floor(500000*100/10000)//2 = 15000 + 2500 = 17500 — exactly 3.5% of comp.

    Design: Difficulty/dual_variant_calc/match_tiered_vs_safe_harbor_diverges_for_identical_period
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "Tiered", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "Alice",
                               "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 400},
    )
    cp = create_open_contribution_period(participant["id"],
                                         period_end_date="2026-06-30T00:00:00Z",
                                         gross_compensation_cents=500_000)
    closed = validate_success(api.close_contribution_period(cp["id"], _ADMIN))
    assert closed["employee_contribution_cents"] == 20_000
    assert closed["employer_match_cents"] == 17_500


def test_safe_harbor_match_at_deferral_400_bps_yields_20000(api):
    """PRD §3.3: "When the plan's `match_formula` is `SAFE_HARBOR_ENHANCED`, the
    match is a single-tier full-rate cap: the effective matched deferral basis
    points are the smaller of the participant's `deferral_rate_bps` and 400, and
    the match equals the capped compensation multiplied by that effective
    basis-point value, divided by 10000, with a floor applied."

    With gross_compensation_cents=500000 and deferral_rate_bps=400,
    safe_harbor employer_match_cents = floor(500000*400/10000) = 20000 — 4% of
    comp, divergent from the tiered formula's 17500 on identical inputs.

    Design: Difficulty/dual_variant_calc/match_tiered_vs_safe_harbor_diverges_for_identical_period
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "Safe", "match_formula": "SAFE_HARBOR_ENHANCED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "Bob",
                               "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 400},
    )
    cp = create_open_contribution_period(participant["id"],
                                         period_end_date="2026-06-30T00:00:00Z",
                                         gross_compensation_cents=500_000)
    closed = validate_success(api.close_contribution_period(cp["id"], _ADMIN))
    assert closed["employee_contribution_cents"] == 20_000
    assert closed["employer_match_cents"] == 20_000
    # Divergence from the tiered formula's 17500 — both faithful PRD readings.
    assert closed["employer_match_cents"] != 17_500


# ─── Difficulty/dual_variant_calc/rmd_uniform_vs_joint_life_diverges ────────

def test_rmd_uniform_lifetime_at_age_73_balance_1m_yields_37735(api):
    """PRD §3.6: "Under the `UNIFORM_LIFETIME` variant, the life-expectancy factor
    is read from the IRS Uniform Lifetime Table indexed by the participant's age at
    year-end (representative entries: 26.5 at age 73...)."
    PRD §3.6: "The required amount is then `prior_year_end_balance_cents` divided
    by the chosen life-expectancy factor, with a floor applied."

    For prior_year_end_balance_cents=1000000 and factor=26.5,
    required_amount_cents = floor(1_000_000 * 1_000_000 / floor(26.5 * 1_000_000))
                          = floor(1e12 / 26_500_000) = 37735.

    Design: Difficulty/dual_variant_calc/rmd_uniform_vs_joint_life_diverges_for_same_balance
    """
    _plan, participant = setup_rmd_eligible_participant(
        plan_overrides={"name": "RMD-UL", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        date_of_birth="1954-01-01T00:00:00Z",   # age 73 at 2026-12-31
        hire_date="2010-01-01T00:00:00Z",
    )
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(
            participant["id"],
            distribution_year=2026,
            prior_year_end_balance_cents=1_000_000,
            rmd_variant="UNIFORM_LIFETIME",
        ),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert data["required_amount_cents"] == 37_735


def test_rmd_joint_life_at_age_73_spouse_60_balance_1m_yields_36496(api):
    """PRD §3.6: "When eligible, the factor is read from the Joint Life Table
    indexed by the pair (participant_age, spouse_age) (representative entries:
    27.4 at (73, 60), 30.7 at (73, 55), 22.6 at (80, 65)). The Joint Life table
    produces strictly larger factors than the Uniform Lifetime table for the same
    participant age, so for the same `prior_year_end_balance_cents` the joint-life
    variant yields a strictly smaller `required_amount_cents`..."

    For prior_year_end_balance_cents=1000000 and factor=27.4,
    required_amount_cents = floor(1e12 / 27_400_000) = 36496, strictly less than
    the 37735 yielded by the uniform variant on identical balance.

    Design: Difficulty/dual_variant_calc/rmd_uniform_vs_joint_life_diverges_for_same_balance
    """
    _plan, participant = setup_rmd_eligible_participant(
        plan_overrides={"name": "RMD-JL", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        date_of_birth="1954-01-01T00:00:00Z",   # participant 73 at 2026-12-31
        hire_date="2010-01-01T00:00:00Z",
    )
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(
            participant["id"],
            distribution_year=2026,
            prior_year_end_balance_cents=1_000_000,
            rmd_variant="JOINT_LIFE",
            # PRD §3.6: spouse age at year-end is floor((Dec 31 - DOB).days / 365).
            # For year-end 2026 to yield spouse age 60, DOB must satisfy 60 <=
            # (2026-12-31 - DOB).days / 365 < 61, i.e., DOB in
            # [1966-01-21, 1967-01-20]. Use 1966-06-30 so floor((22184)/365)=60.
            spouse_date_of_birth="1966-06-30T00:00:00Z",  # spouse 60 at 2026-12-31
        ),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert data["required_amount_cents"] == 36_496
    # Strictly smaller than uniform-lifetime for the same balance.
    assert data["required_amount_cents"] < 37_735


# ─── Difficulty/combinatorial_formula/max_hardship_three_input_min ──────────

def test_max_hardship_combines_three_caps_with_floor_and_max(api):
    """PRD §3.5: "The maximum hardship amount is the greater of zero and the
    smallest of three candidates. The first candidate, the vested-savings cap,
    equals one-half of the sum of the participant's `employee_balance_cents` and
    `vested_employer_balance_cents` (with a floor applied), reduced by the
    participant's current `outstanding_loan_principal_cents`..."

    With employee_balance=40000, vested_employer_balance=14000,
    outstanding_loan_principal=0: cap_a = floor((40000+14000)*0.5) - 0 = 27000.
    cap_b = HARDSHIP_HARD_CAP_CENTS = 5_000_000. cap_c = requested = 100000.
    approved_amount_cents = max(0, min(27000, 5_000_000, 100000)) = 27000.

    Design: Difficulty/combinatorial_formula/max_hardship_three_input_min_with_age_branch
    """
    _plan, _participant, hardship = _setup_age45_hardship(api)
    approved = validate_success(api.approve_hardship(hardship["id"], _ADMIN))
    assert approved["approved_amount_cents"] == 27_000


def test_max_hardship_ten_percent_penalty_applies_when_age_under_59(api):
    """PRD §3.5: "a 10% early-withdrawal penalty is assessed only if the
    participant is younger than the age penalty threshold of 59 full years (the
    IRS age 59.5 threshold rounded down to whole years per the integer-arithmetic
    precision rule in §2.5)... the penalty `ten_percent_penalty_cents` is set to
    ten percent of `approved_amount_cents` with a floor applied; otherwise the
    penalty is 0."

    For age 45 with approved_amount=27000, ten_percent_penalty_cents =
    floor(27000 * 0.10) = 2700.

    Design: Difficulty/combinatorial_formula/max_hardship_three_input_min_with_age_branch
    """
    _plan, _participant, hardship = _setup_age45_hardship(api)
    approved = validate_success(api.approve_hardship(hardship["id"], _ADMIN))
    assert approved["ten_percent_penalty_cents"] == 2_700


def _setup_age45_hardship(api):
    """Reusable fixture: age-45 participant with employee_balance=40000,
    employer_balance=35000, vested_employer_balance=14000; one REQUESTED
    hardship for 100000 cents."""
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="HardshipCalc", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Dan",
        date_of_birth="1981-06-15T00:00:00Z",   # age 45
        hire_date="2024-06-15T00:00:00Z",       # yos=2, GRADED_6 -> 40%
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    # Two CLOSED periods give employee_balance=40000, employer_balance=35000,
    # vested_employer_balance = floor(35000 * 4000 / 10000) = 14000.
    for end_date in ("2026-05-31T00:00:00Z", "2026-06-15T00:00:00Z"):
        cp = create_open_contribution_period(participant["id"],
                                              period_end_date=end_date,
                                              gross_compensation_cents=500_000)
        close_contribution_period(cp["id"])
    p = get_participant(participant["id"])
    assert p["employee_balance_cents"] == 40_000, p
    assert p["employer_balance_cents"] == 35_000, p
    assert p["vested_employer_balance_cents"] == 14_000, p
    hardship = get_success_data(api.create_hardship_withdrawal(
        create_hardship_withdrawal_payload(participant["id"],
                                           requested_amount_cents=100_000,
                                           hardship_category="MEDICAL_EXPENSES"),
        _ADMIN,
    ))
    return plan, p, hardship


# ─── Difficulty/combinatorial_formula/loan_amortization_per_payment_round ──

def test_loan_amortization_monthly_payment_uses_per_payment_ceil(api):
    """PRD §3.4: "The result is rounded up (`ceil`) to the next whole cent to
    produce `monthly_payment_cents`, so that the payment schedule fully repays the
    loan rather than leaving a sub-cent residual. The rounding order is pinned at
    the per-payment scalar — never on a sum of raw values; reversing the order
    would change the total interest and is forbidden."

    For P=1_000_000 cents, n=12, annual_rate=700 bps (monthly rate 7%/12),
    raw monthly payment = P * r * (1+r)^n / ((1+r)^n - 1) ~ 86526.74 cents;
    ceil -> 86527.

    Design: Difficulty/combinatorial_formula/loan_amortization_per_payment_round_then_sum_pinned
    """
    # Need balances large enough for the loan headroom check
    # (PRD §3.4: principal <= floor(min(vested_total/2, 5_000_000)).
    # One CLOSED period at gross=10M, deferral 400bps, GRADED_6 yos=8 (full vest)
    # yields employee_balance=53076, employer_balance=46441, vested_employer=46441.
    # vested_total = 53076 + 46441 = 99517; half = 49758. That's < 1_000_000.
    # Need more periods. Use seeded balances helper with enough periods to clear
    # 2_000_000 vested_total. Each period adds employee=53076, employer=46441
    # (fully vested at yos=8), so vested_total_per_period ~= 99517.
    # Need ~21 periods for vested_total/2 >= 1_000_000 (period_pairs >= ~21).
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="LoanCalc", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Eve",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2018-06-15T00:00:00Z",  # yos=8 GRADED_6 -> 100% vested
        annual_compensation_cents=50_000_000,
        deferral_rate_bps=400,
    )
    for i in range(21):
        cp = create_open_contribution_period(participant["id"],
                                              period_end_date=f"2026-{(i%12)+1:02d}-15T00:00:00Z",
                                              gross_compensation_cents=10_000_000)
        close_contribution_period(cp["id"])
    p = get_participant(participant["id"])
    vested_total = p["employee_balance_cents"] + p["vested_employer_balance_cents"]
    assert vested_total // 2 >= 1_000_000, f"insufficient vested headroom: {vested_total}"
    # Create + disburse the loan
    loan = get_success_data(api.create_loan(
        create_loan_payload(participant["id"], principal_cents=1_000_000,
                            term_months=12, annual_interest_rate_bps=700),
        _ADMIN,
    ))
    disbursed = validate_success(api.disburse_loan(loan["id"], _ADMIN))
    assert disbursed["monthly_payment_cents"] == 86_527


def test_loan_disburse_sets_outstanding_principal_equal_to_principal(api):
    """PRD §3.4: "On a successful disbursement the loan's `outstanding_principal_cents`
    is set equal to `principal_cents`..."

    Design: Difficulty/combinatorial_formula/loan_amortization_per_payment_round_then_sum_pinned
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="LoanCalc2", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Eve2",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2018-06-15T00:00:00Z",
        annual_compensation_cents=50_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=10_000_000)
    close_contribution_period(cp["id"])
    loan = get_success_data(api.create_loan(
        create_loan_payload(participant["id"], principal_cents=10_000,
                            term_months=12, annual_interest_rate_bps=700),
        _ADMIN,
    ))
    disbursed = validate_success(api.disburse_loan(loan["id"], _ADMIN))
    assert disbursed["outstanding_principal_cents"] == 10_000
    assert disbursed["status"] == "DISBURSED"


# ─── Difficulty/boundary_precision_check/rmd_age_strictly_at_73 ─────────────

def test_rmd_created_for_participant_at_age_73_year_end(api):
    """PRD §3.6: "If that age is less than the age trigger of 73, the creation is
    rejected with `ERR_RMD_NOT_REQUIRED`..."

    A participant whose age at distribution_year_end is exactly 73 MUST be
    accepted; the rejection only fires for age < 73.

    Design: Difficulty/boundary_precision_check/rmd_age_strictly_at_73_accepts_72_rejects
    """
    _plan, p_at = setup_rmd_eligible_participant(
        plan_overrides={"name": "RMD-At", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        date_of_birth="1954-01-01T00:00:00Z",   # 73 at 2026-12-31
        hire_date="2010-01-01T00:00:00Z",
    )
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(
            p_at["id"], distribution_year=2026,
            prior_year_end_balance_cents=1_000_000,
            rmd_variant="UNIFORM_LIFETIME",
        ),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert data["required_amount_cents"] == 37_735
    assert data["status"] == "PENDING"


def test_rmd_rejected_for_participant_at_age_72_year_end(api):
    """PRD §3.6: "If that age is less than the age trigger of 73, the creation
    is rejected with `ERR_RMD_NOT_REQUIRED` — the participant is not yet subject
    to RMDs and the system refuses to manufacture a distribution."

    Design: Difficulty/boundary_precision_check/rmd_age_strictly_at_73_accepts_72_rejects
    """
    _plan, p_below = setup_rmd_eligible_participant(
        plan_overrides={"name": "RMD-Below", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        date_of_birth="1955-01-01T00:00:00Z",   # 71 at 2026-12-31
        hire_date="2010-01-01T00:00:00Z",
    )
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(
            p_below["id"], distribution_year=2026,
            prior_year_end_balance_cents=1_000_000,
            rmd_variant="UNIFORM_LIFETIME",
        ),
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_RMD_NOT_REQUIRED)


# ─── Difficulty/boundary_precision_check/cliff_vesting_at_year_3 ────────────

def test_cliff_vesting_zero_below_year_3(api):
    """PRD §2.9: "Under the `CLIFF_3` schedule the participant's vested percentage
    is zero while years of service is below 3 and is 100% once years of service
    reaches 3 or more."

    yos=2 under CLIFF_3 -> vested_pct=0 -> vested_employer_balance_cents=0
    even though employer_balance_cents was updated by the close cascade.

    Design: Difficulty/boundary_precision_check/cliff_vesting_at_year_3_exact_boundary
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="CliffPre", match_formula="TIERED",
                                    vesting_schedule="CLIFF_3")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Pre",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",   # yos=2
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    p = get_participant(participant["id"])
    assert p["employer_balance_cents"] == 17_500
    assert p["vested_employer_balance_cents"] == 0


def test_cliff_vesting_full_at_year_3(api):
    """PRD §2.9: "Under the `CLIFF_3` schedule the participant's vested percentage is zero while years of service is below 3 and is 100% once years of service reaches 3 or more."

    yos=3 under CLIFF_3 -> vested_pct=10000 -> vested_employer_balance_cents
    equals employer_balance_cents.

    Design: Difficulty/boundary_precision_check/cliff_vesting_at_year_3_exact_boundary
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="CliffPost", match_formula="TIERED",
                                    vesting_schedule="CLIFF_3")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Post",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2023-06-15T00:00:00Z",   # yos=3 exactly
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    p = get_participant(participant["id"])
    assert p["employer_balance_cents"] == 17_500
    assert p["vested_employer_balance_cents"] == 17_500


# ─── Corner/calculations ────────────────────────────────────────────────────

def test_tiered_match_at_deferral_300_bps_fills_first_tier_only(api):
    """PRD §3.3: "the first tier matches 100% on the first 3% of compensation
    deferred — its tier rate is 10000 basis points (full match) and its tier cap
    is 300 basis points of deferral — and equals the capped compensation
    multiplied by the smaller of the participant's `deferral_rate_bps` and 300,
    divided by 10000, with a floor applied; the second tier matches 50% on the
    next 2% of compensation deferred..."

    At exactly deferral_rate_bps=300 the first tier is full and the second tier
    is zero: employer_match_cents = floor(500000*300/10000) + 0 = 15000.

    Design: Corner/calculations/tiered_match_at_deferral_300_bps_full_first_tier_only
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "T300", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        participant_overrides={"full_name": "T", "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 300},
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    closed = validate_success(api.close_contribution_period(cp["id"], _ADMIN))
    assert closed["employee_contribution_cents"] == 15_000
    assert closed["employer_match_cents"] == 15_000


def test_tiered_match_zero_deferral_yields_zero_employee_and_employer(api):
    """PRD §3.3: "The employee deferral amount for this period equals the capped
    compensation multiplied by the participant's `deferral_rate_bps` and divided
    by 10000, with a floor applied. That amount becomes
    `employee_contribution_cents`..."

    At deferral_rate_bps=0 (set via PATCH after enroll, since enroll requires
    deferral_rate_bps > 0 per PRD §3.2), employee_contribution_cents=0 and
    employer_match_cents=0.

    Design: Corner/calculations/tiered_match_zero_deferral_yields_zero_match
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "T0", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        participant_overrides={"full_name": "Z", "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 100},
    )
    update_deferral_rate(participant["id"], 0)
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    closed = validate_success(api.close_contribution_period(cp["id"], _ADMIN))
    assert closed["employee_contribution_cents"] == 0
    assert closed["employer_match_cents"] == 0


def test_graded_vesting_at_yos_1_is_20_percent(api):
    """PRD §2.9: "Under the `GRADED_6` schedule the participant gains vesting in
    20-percentage-point increments per year of service: 0% at less than one full
    year, 20% at one full year, 40% at two, 60% at three, 80% at four, and 100%
    at five or more..."

    Design: Corner/calculations/graded_vesting_at_yos_1_to_5_uses_table
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="G1", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="G1",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2025-06-15T00:00:00Z",   # yos=1 -> 20%
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    p = get_participant(participant["id"])
    assert p["employer_balance_cents"] == 17_500
    assert p["vested_employer_balance_cents"] == 3_500   # floor(17500 * 2000 / 10000)


def test_graded_vesting_at_yos_4_is_80_percent(api):
    """PRD §2.9: "Under the `GRADED_6` schedule the participant gains vesting in 20-percentage-point increments per year of service: 0% at less than one full year, 20% at one full year, 40% at two, 60% at three, 80% at four, and 100% at five or more (six full years confirms full vesting and any year beyond that remains fully vested)."

    Design: Corner/calculations/graded_vesting_at_yos_1_to_5_uses_table
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="G4", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="G4",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2022-06-15T00:00:00Z",   # yos=4 -> 80%
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    p = get_participant(participant["id"])
    assert p["employer_balance_cents"] == 17_500
    assert p["vested_employer_balance_cents"] == 14_000   # floor(17500 * 8000 / 10000)


def test_hardship_penalty_zero_when_participant_age_60(api):
    """PRD §3.5: "On approval the approved amount is written to `approved_amount_cents`, and a 10% early-withdrawal penalty is assessed only if the participant is younger than the age penalty threshold of 59 full years (the IRS age 59.5 threshold rounded down to whole years per the integer-arithmetic precision rule in §2.5): the participant's age in whole years is computed as the floor of the number of days between the system clock and `date_of_birth` divided by 365, and the penalty `ten_percent_penalty_cents` is set to ten percent of `approved_amount_cents` with a floor applied; otherwise the penalty is 0."

    For a participant at age 60 (at or above the 59 threshold), the penalty is 0.

    Design: Corner/calculations/hardship_penalty_zero_when_participant_age_at_or_above_59
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="Age60", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Sixty",
        date_of_birth="1966-01-01T00:00:00Z",   # age 60 at clock 2026-06-15
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    h = get_success_data(api.create_hardship_withdrawal(
        create_hardship_withdrawal_payload(participant["id"],
                                           requested_amount_cents=1_000,
                                           hardship_category="MEDICAL_EXPENSES"),
        _ADMIN,
    ))
    approved = validate_success(api.approve_hardship(h["id"], _ADMIN))
    assert approved["approved_amount_cents"] == 1_000
    assert approved["ten_percent_penalty_cents"] == 0


def test_rmd_uniform_lifetime_at_age_75_factor_24_6_yields_40650(api):
    """PRD §3.6: "the IRS Uniform Lifetime Table indexed by the participant's age
    at year-end (representative entries: 26.5 at age 73, 25.5 at age 74, 24.6 at
    age 75, 20.2 at age 80, 16.0 at age 85)."

    For prior_year_end_balance_cents=1000000 and factor=24.6,
    required_amount_cents = floor(1e12 / floor(24.6 * 1_000_000))
                          = floor(1e12 / 24_600_000) = 40650.

    Design: Corner/calculations/rmd_uniform_lifetime_table_value_at_age_75
    """
    _plan, participant = setup_rmd_eligible_participant(
        plan_overrides={"name": "R75", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        date_of_birth="1952-01-01T00:00:00Z",   # age 75 at 2026-12-31 (1952-01-01 -> 2026-12-31 ~ 74.99 -> floor = 74)
        hire_date="2010-01-01T00:00:00Z",
    )
    # Recompute the expected age. 2026-12-31 minus 1952-01-01 = 27393 days;
    # 27393 // 365 = 75 (since 27393/365 = 75.05). The seed yaml confirms 75.
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(
            participant["id"],
            distribution_year=2026,
            prior_year_end_balance_cents=1_000_000,
            rmd_variant="UNIFORM_LIFETIME",
        ),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert data["required_amount_cents"] == 40_650
