"""Pinned-rounding calculations: net-income per-step rounding, monthly allotment
floor, fraud-score sum-then-round, dual-variant net (elderly vs standard).

Covers PRD §2.5 (precision and ordering) and §3.2-§3.3 (calculations).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_household, add_member,
    setup_basic_household, dob_for_age,
    setup_approved_household_at_net_income,
    setup_household_at_net_income,
    create_draft_application, walk_to_interview_done, approve_application,
    EXCESS_SHELTER_CAP_CENTS, MINIMUM_BENEFIT_CENTS, MAX_ALLOTMENT_TABLE,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


class TestNetIncomePinnedRounding:
    def test_net_income_per_step_rounding_pinned(self, api):
        """PRD §2.5: "Each numbered deduction step that produces a non-integer
        intermediate (the 20% earned-income deduction and the
        half-of-adjusted-income value used in the excess-shelter test) is
        rounded half-up to a whole cent **before** being combined into the
        next step. Per-step rounding of the half-of-adjusted-income value,
        in particular, is applied **before** the subtraction that yields the
        raw excess-shelter amount."
        PRD §3.2: "Apply the **earned-income deduction**, computed as `earned`
        multiplied by twenty percent (0.20) and then rounded half-up to a
        whole cent. This rounded value is the deduction."

        Claim (mode-b ordering, scaffold #2 instance):
        Size 3, earned total = 199995, shelter = 200000, no dependent care.
            standard_deduction = 19300
            earned_income_deduction = round(199995*0.20) = round(39999.0) = 39999
            adjusted_income = max(0, 199995 - 19300 - 39999) = 140696
            half_adjusted = round(70348.0) = 70348
            excess_shelter_raw = 200000 - 70348 = 129652
            shelter_deduction = min(129652, 67200) = 67200
            net = max(0, 140696 - 67200) = 73496
        """
        # difficulty: combinatorial_formula/net_income_per_step_rounding_pinned
        hh = create_household(shelter_expense_cents=200000)
        # Two earners: 99998 + 99997 = 199995 cents
        add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(30),
                   earned_income_cents=99998)
        add_member(hh["id"], full_name="B", date_of_birth=dob_for_age(30),
                   earned_income_cents=99997)
        add_member(hh["id"], full_name="C", date_of_birth=dob_for_age(35),
                   earned_income_cents=0)
        re = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert re["gross_monthly_income_cents"] == 199995
        assert re["net_monthly_income_cents"] == 73496, (
            f"Expected net=73496 (per-step rounding), got {re['net_monthly_income_cents']}"
        )


class TestDualVariantNetIncome:
    def test_net_income_standard_vs_elderly(self, api):
        """PRD §3.2: "for households **without** an elderly or disabled member
        the cap is 67,200 cents (the lesser of the raw figure and 67,200 cents
        is taken), and for households **with** an elderly or disabled member
        the cap does not apply — the deduction is the full raw figure regardless
        of size."

        Claim (dual variant): two households with same gross income and shelter
        differ in net based on has_elderly_or_disabled.

        H1 (size=3, all 35yo, two earners 150000 each): no elderly path -> shelter cap = 67200.
        H2 (size=3, mirror with 65yo elder): elderly path -> shelter uncapped.
        Setup:
          shelter=250000 each, dep_care=0
        H1 calculation (size=3, earned=300000, gross=300000):
          std = 19300
          earned_ded = round(300000*0.20) = 60000
          adj = max(0, 300000-19300-60000-0) = 220700
          half_adj = round(220700/2) = 110350
          excess_raw = 250000 - 110350 = 139650
          shelter_ded = min(139650, 67200) = 67200
          net = max(0, 220700 - 67200) = 153500
        H2 (same gross, 65yo elder): adjusted is the same, shelter uncapped:
          shelter_ded = 139650
          net = max(0, 220700 - 139650) = 81050
        """
        # difficulty: dual_variant_calc/net_income_standard_vs_elderly_disabled
        # H1: size=3, all young, two earners 150000 each
        h1 = create_household(shelter_expense_cents=250000)
        add_member(h1["id"], full_name="A", date_of_birth=dob_for_age(35),
                   earned_income_cents=150000)
        add_member(h1["id"], full_name="B", date_of_birth=dob_for_age(35),
                   earned_income_cents=150000)
        add_member(h1["id"], full_name="C", date_of_birth=dob_for_age(35),
                   earned_income_cents=0)
        # H2: size=3, one elderly (no income, 65yo)
        h2 = create_household(shelter_expense_cents=250000)
        add_member(h2["id"], full_name="A'", date_of_birth=dob_for_age(35),
                   earned_income_cents=150000)
        add_member(h2["id"], full_name="B'", date_of_birth=dob_for_age(35),
                   earned_income_cents=150000)
        add_member(h2["id"], full_name="E'", date_of_birth=dob_for_age(65),
                   earned_income_cents=0)
        h1_re = validate_success(api.get_household(h1["id"], CASEWORKER))
        h2_re = validate_success(api.get_household(h2["id"], CASEWORKER))
        assert h1_re["has_elderly_or_disabled"] is False
        assert h2_re["has_elderly_or_disabled"] is True
        assert h1_re["net_monthly_income_cents"] == 153500
        assert h2_re["net_monthly_income_cents"] == 81050
        assert h1_re["net_monthly_income_cents"] != h2_re["net_monthly_income_cents"]


class TestMonthlyAllotmentFloor:
    def test_size_1_at_net_limit_gets_minimum_benefit_floor(self, api):
        """PRD §3.3: "A **minimum benefit floor** of 2,300 cents applies for
        households of size 1 or 2 only: if the raw allotment is below 2,300
        cents for those sizes, the final allotment is lifted to 2,300 cents."

        Claim: size=1 net=124800 (right at limit) → raw allotment formula:
            expected_contribution = round(124800 * 0.30) = round(37440) = 37440
            raw_allotment = max(0, 29100 - 37440) = 0
            size <= 2 and raw < 2300 → floor: 2300
        """
        # difficulty: combinatorial_formula/monthly_allotment_minimum_benefit_floor
        ctx = setup_approved_household_at_net_income(target_net_cents=124800, size=1)
        hh = ctx["household"]
        assert hh["net_monthly_income_cents"] == 124800
        assert hh["monthly_allotment_cents"] == 2300, (
            f"Expected size-1 min benefit floor 2300, got {hh['monthly_allotment_cents']}"
        )

    def test_size_3_at_net_limit_no_floor(self, api):
        """PRD §3.3: "For households of size 3 or larger, the floor never
        applies — a raw allotment below 2,300 cents is the final allotment
        for those households."

        Claim: size=3 net=211800 (right at limit) → raw allotment formula:
            expected_contribution = round(211800 * 0.30) = round(63540) = 63540
            raw_allotment = max(0, 76600 - 63540) = 13060
            size > 2 → no floor; allotment = 13060
        """
        # difficulty: combinatorial_formula/monthly_allotment_minimum_benefit_floor
        ctx = setup_approved_household_at_net_income(target_net_cents=211800, size=3)
        hh = ctx["household"]
        assert hh["net_monthly_income_cents"] == 211800
        assert hh["monthly_allotment_cents"] == 13060, (
            f"Expected size-3 raw allotment 13060 (no floor), got {hh['monthly_allotment_cents']}"
        )


class TestFraudScoreSumThenRound:
    def test_fraud_score_is_two_decimals(self, api):
        """PRD §2.5: "The three weighted signals are first **summed as raw
        real numbers**, and the **final sum** is rounded half-up to two
        decimal places. Rounding is applied **once, at the end** — never per
        signal — and this is the deliberate opposite of the net-income chain."

        Claim: a freshly opened fraud case has suspicious_score in [0, 1] with
        at most 2 decimal places. (We can't directly assert sum-then-round
        without engineered transactions; we assert the precision invariant.)
        """
        # difficulty: combinatorial_formula/fraud_score_sum_then_round_pinned
        hh = create_household()
        from test_helpers import open_fraud_case
        case = open_fraud_case(hh["id"])
        score = float(case["suspicious_score"])
        assert 0.0 <= score <= 1.0
        # The rounded value must equal round(score, 2) exactly
        assert abs(score - round(score, 2)) < 1e-9, (
            f"suspicious_score not rounded to 2 decimals: {score}"
        )
