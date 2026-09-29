"""Final rating at issuance: per-line rounding and the plan expense charge tier."""
from test_helpers import (
    BEACON,
    SIX_POINT_VIOLATIONS,
    T02_ADULT_CLEAN,
    T02_YOUTHFUL_SIX_POINTS,
    T03_ADULT_CLEAN,
    YOUTHFUL_APPLICANT,
    ATLAS,
    assert_premium_lines_sum_to_final_premium,
    assert_total_annual_charge,
    read_application,
    setup_policy_in_force,
)


def test_final_premium_sums_three_independently_rounded_coverage_lines():
    """Each coverage line is rounded to whole cents before the three are added.

    A youthful operator in T02 with one major speeding conviction rates at six
    surcharge points, so the T02 territory base of 148337 cents is multiplied by
    the PLEASURE class factor of 1.00 and by the 1.60 surcharge factor. Splitting
    that product 0.55 / 0.30 / 0.15 and rounding each share on its own gives
    130537, 71202 and 35601, whose sum of 237340 is one cent above the figure a
    single rounding of the unrounded sum would produce.

    PRD: "The policy's `final_premium_cents` is the sum of those three
    already-rounded lines. Summing the unrounded lines and rounding once at the
    end is wrong and diverges: for territory `T02`, class `PLEASURE` and 6
    applied points the three rounded lines are 130537, 71202 and 35601, giving
    237340, whereas rounding the unrounded sum yields 237339"
    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_pins_annual_premium
    """
    env = setup_policy_in_force(
        applicant_overrides=YOUTHFUL_APPLICANT,
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
    )
    policy = env["policy"]

    assert policy["surcharge_points_applied"] == T02_YOUTHFUL_SIX_POINTS["surcharge_points"]
    assert policy["surcharge_factor_applied"] == T02_YOUTHFUL_SIX_POINTS["surcharge_factor"]
    assert policy["premium_lines"] == T02_YOUTHFUL_SIX_POINTS["premium_lines"]
    assert policy["final_premium_cents"] == 237340
    assert policy["final_premium_cents"] != 237339, (
        "237339 is the sum-then-round figure the plan forbids"
    )
    assert_premium_lines_sum_to_final_premium(policy)


def test_the_per_line_rounding_cent_propagates_into_the_term_charge_and_the_deposit():
    """The extra cent from per-line rounding is carried through the whole ledger.

    Because the six-point youthful risk in T02 rates to 237340 rather than
    237339, the 0.04 expense charge of 9494 cents lands on a term charge of
    246834, and one quarter of that term charge rounds half up to a required
    deposit of 61709 cents rather than 61708.

    PRD: "and that single cent propagates into the expense tier and the deposit
    requirement."
    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_pins_annual_premium
    """
    env = setup_policy_in_force(
        applicant_overrides=YOUTHFUL_APPLICANT,
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
    )
    policy = env["policy"]
    application = read_application(env["application"]["id"])

    assert policy["plan_expense_charge_cents"] == 9494
    assert policy["total_annual_charge_cents"] == 246834
    assert_total_annual_charge(policy)
    assert application["required_deposit_cents"] == 61709
    assert policy["premium_credited_cents"] == 61709
    assert policy["additional_premium_due_cents"] == 185125
    assert policy["premium_settlement_status"] == "PREMIUM_OUTSTANDING"


def test_expense_charge_rate_is_chosen_from_the_premium_before_the_charge_is_added():
    """The expense rate is read from final_premium_cents, never from the total.

    A clean adult risk in T02 rates to a final premium of 148337 cents, which is
    below the 150000-cent ceiling, so the plan charges 0.05 and yields 7417
    cents. Reading the tier from the charge-inclusive total instead would put the
    risk in the 0.04 band and yield 5933 cents.

    PRD: "Its rate is chosen from `final_premium_cents` *before* the charge is
    added, never from the charge-inclusive total: 0.06 when `final_premium_cents`
    is below 75000 cents, 0.05 when it is at least 75000 but below 150000 cents,
    and 0.04 when it is 150000 cents or more."
    Design: Difficulty/combinatorial_formula/expense_charge_tier_read_from_pre_charge_premium
    """
    env = setup_policy_in_force()
    policy = env["policy"]

    assert policy["surcharge_points_applied"] == 0
    assert policy["surcharge_factor_applied"] == 1.00
    assert policy["final_premium_cents"] == 148337
    assert policy["plan_expense_charge_cents"] == 7417
    assert policy["plan_expense_charge_cents"] != 5933, (
        "5933 is the 0.04 charge the plan would levy if it read the tier from the total"
    )
    assert policy["total_annual_charge_cents"] == 155754
    assert policy["total_annual_charge_cents"] != 154270
    assert policy["premium_credited_cents"] == T02_ADULT_CLEAN["required_deposit_cents"]
    assert policy["additional_premium_due_cents"] == 116815


def test_a_premium_at_or_above_the_upper_ceiling_takes_the_lowest_expense_rate():
    """A pre-charge premium of 150000 cents or more attracts the 0.04 rate.

    A clean adult risk in T03 rates to a final premium of 231909 cents, which is
    at or above the 150000-cent ceiling, so the plan charges 0.04 and yields 9276
    cents for a term charge of 241185.

    PRD: "The rate is applied to `final_premium_cents` and rounded half up to
    whole cents to give `plan_expense_charge_cents`, and `total_annual_charge_cents`
    is `final_premium_cents` plus `plan_expense_charge_cents`."
    Design: Difficulty/combinatorial_formula/expense_charge_tier_read_from_pre_charge_premium
    """
    env = setup_policy_in_force(
        carriers=[dict(ATLAS, licensed_territories=["T03"]),
                  dict(BEACON, licensed_territories=["T03"])],
        applicant_overrides={"territory_code": "T03"},
    )
    policy = env["policy"]

    assert policy["final_premium_cents"] == T03_ADULT_CLEAN["final_premium_cents"]
    assert policy["plan_expense_charge_cents"] == 9276
    assert policy["total_annual_charge_cents"] == 241185
    assert_total_annual_charge(policy)
    assert read_application(env["application"]["id"])["required_deposit_cents"] == 60296
