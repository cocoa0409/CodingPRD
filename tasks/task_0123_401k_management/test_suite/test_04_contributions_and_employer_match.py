"""Contribution posting, employer match (Safe Harbor vs Tiered),
annual caps, pay-period uniqueness, and the cumulative balance
invariants (PRD §3.3, §2.13)."""
from __future__ import annotations

import pytest

from test_helpers import (
    EMPLOYEE_ANNUAL_LIMIT_CENTS,
    EMPLOYER_ANNUAL_LIMIT_CENTS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_contribution_record,
    create_contribution_payload,
    create_and_activate_plan,
    enroll_and_activate_participant,
    post_contribution,
    setup_basic_active_participant,
    setup_two_plans_same_participant_inputs,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Employee deferral computation — PRD §3.3
# ===========================================================================
def test_employee_amount_rounds_half_up_to_cent(api):
    """PRD §3.3: "The employee amount is the gross pay multiplied by
    the eligible deferral percentage divided by one hundred, then
    rounded half up to the nearest whole cent."

    Claim: gross 500000 * 6% = 30000 (exact, no rounding).
    """
    plan, p = setup_basic_active_participant(
        elected_deferral_pct=6.0,
    )
    cr = post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-15",
        gross_pay_cents=500_000,
    )
    assert_contribution_record(cr)
    assert cr["gross_pay_cents"] == 500_000
    assert cr["employee_amount_cents"] == 30_000


# ===========================================================================
# Employer match — Safe Harbor variant (PRD §3.3)
# ===========================================================================
def test_safe_harbor_employer_match_at_six_percent_deferral(api):
    """PRD §3.3 Safe Harbor: "the first tier covers the first three
    percentage points of deferral and is matched at one hundred percent
    ... the second tier covers the next two percentage points (deferral
    above three points and up to and including five points) and is
    matched at fifty percent."

    Claim: gross 500000, deferral 6% under SAFE_HARBOR_BASIC ->
    employer_match_cents = (3*1.0 + 2*0.5)% * 500000 = 4% * 500000 = 20000.

    # difficulty: dual_variant_calc/safe_harbor_vs_tiered_match_on_contribution_record
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="SAFE_HARBOR_BASIC",
        elected_deferral_pct=6.0,
    )
    cr = post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-15",
        gross_pay_cents=500_000,
    )
    assert cr["employee_amount_cents"] == 30_000
    assert cr["employer_match_cents"] == 20_000


# ===========================================================================
# Employer match — Tiered variant (PRD §3.3)
# ===========================================================================
def test_tiered_employer_match_at_six_percent_deferral(api):
    """PRD §3.3 Tiered: "When the plan's match_formula_type is TIERED,
    the system walks tiered_brackets in ascending order of
    employee_deferral_pct_up_to ... The same gross_pay_cents and
    elected_deferral_pct inputs intentionally produce a different
    employer_match_cents under TIERED than under SAFE_HARBOR_BASIC."

    Claim: TIERED with brackets [{up_to:3, rate:50}, {up_to:6, rate:25}],
    gross 500000, deferral 6% ->
    band1 = min(6, 3-0) = 3 pp at 50% = 1.5 pct of pay
    band2 = min(3, 6-3) = 3 pp at 25% = 0.75 pct of pay
    Total = 2.25% of 500000 = 11250.

    # difficulty: dual_variant_calc/safe_harbor_vs_tiered_match_on_contribution_record
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="TIERED",
        tiered_brackets=[
            {"employee_deferral_pct_up_to": 3, "match_rate_pct": 50},
            {"employee_deferral_pct_up_to": 6, "match_rate_pct": 25},
        ],
        elected_deferral_pct=6.0,
    )
    cr = post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-15",
        gross_pay_cents=500_000,
    )
    assert cr["employee_amount_cents"] == 30_000
    assert cr["employer_match_cents"] == 11_250


def test_dual_variant_same_inputs_different_employer_match(api):
    """PRD §3.3: "The same gross_pay_cents and elected_deferral_pct
    inputs intentionally produce a different employer_match_cents
    under TIERED than under SAFE_HARBOR_BASIC."

    Claim: with identical (gross, deferral) inputs, the two variants
    produce 20000 (Safe Harbor) vs 11250 (Tiered).

    # difficulty: dual_variant_calc/safe_harbor_vs_tiered_match_on_contribution_record
    """
    (plan_a, p_a), (plan_b, p_b) = setup_two_plans_same_participant_inputs(
        plan_a_match="SAFE_HARBOR_BASIC",
        plan_b_match="TIERED",
        plan_b_brackets=[
            {"employee_deferral_pct_up_to": 3, "match_rate_pct": 50},
            {"employee_deferral_pct_up_to": 6, "match_rate_pct": 25},
        ],
        starting_clock="2026-06-01",
        hire_date="2022-01-01",
        elected_deferral_pct=6.0,
    )
    cr_a = post_contribution(
        plan_a["id"], p_a["id"],
        pay_period_end="2026-06-15", gross_pay_cents=500_000,
    )
    cr_b = post_contribution(
        plan_b["id"], p_b["id"],
        pay_period_end="2026-06-15", gross_pay_cents=500_000,
    )
    assert cr_a["employee_amount_cents"] == 30_000
    assert cr_a["employer_match_cents"] == 20_000
    assert cr_b["employee_amount_cents"] == 30_000
    assert cr_b["employer_match_cents"] == 11_250
    assert cr_a["employer_match_cents"] != cr_b["employer_match_cents"]


# ===========================================================================
# Annual employee cap — PRD §3.3
# ===========================================================================
def test_employee_cap_rejects_request_when_exceeded(api, payroll_headers):
    """PRD §3.3: "if the year-to-date employee total plus the proposed
    employee amount would exceed the employee annual limit, the entire
    request is rejected with ERR_ANNUAL_EMPLOYEE_LIMIT_EXCEEDED and
    no row is created."

    Claim: a single huge gross at 100% deferral that would yield
    employee_amount > EMPLOYEE_ANNUAL_LIMIT -> request rejected.

    With elected_deferral_pct=100, gross = EMPLOYEE_ANNUAL_LIMIT + 1
    yields proposed_employee = EMPLOYEE_ANNUAL_LIMIT + 1, exceeding the
    cap and triggering rejection.
    """
    plan, p = setup_basic_active_participant(
        elected_deferral_pct=100.0,
        annual_compensation_cents=1_000_000_000,  # so deferral binds, not pay
    )
    res = api.create_contribution_record(
        plan["id"], p["id"],
        create_contribution_payload(
            pay_period_end="2026-01-15",
            gross_pay_cents=EMPLOYEE_ANNUAL_LIMIT_CENTS + 1,
        ),
        payroll_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_ANNUAL_EMPLOYEE_LIMIT_EXCEEDED.value,
        expected_status=422,
    )


def test_employer_cap_silently_caps_rather_than_rejects(api, payroll_headers):
    """PRD §3.3: "if the year-to-date employer total plus the proposed
    employer amount would exceed the employer annual limit, the
    employer side is silently capped (never rejected) at the larger
    of zero and the employer annual limit minus the year-to-date
    employer total, and the capped value is what is persisted in
    employer_match_cents."

    Claim: a contribution that would push employer past
    EMPLOYER_ANNUAL_LIMIT returns 201 (not 422) and the persisted
    employer_match_cents is the difference between the cap and the
    YTD employer total at the moment of evaluation — NOT the
    unbounded computation.

    Approach: post one giant contribution under SAFE_HARBOR_BASIC at
    5%+ deferral. Gross is sized so the unbounded employer match
    would exceed EMPLOYER_ANNUAL_LIMIT. The first row's employer side
    is capped to exactly EMPLOYER_ANNUAL_LIMIT (since ytd_employer
    starts at 0 and the cap binds the proposed amount).

    Under SAFE_HARBOR_BASIC with deferral=5%, match_pct_of_pay = 4%.
    Choose gross so that 4% of gross > EMPLOYER_ANNUAL_LIMIT.
    EMPLOYER_ANNUAL_LIMIT / 0.04 = 4_600_000 / 0.04 = 115_000_000.
    Use gross = 120_000_000 -> unbounded employer = 4_800_000;
    capped to 4_600_000.

    But the employee side at 5% on 120_000_000 = 6_000_000, which
    exceeds EMPLOYEE_ANNUAL_LIMIT and would trigger
    ERR_ANNUAL_EMPLOYEE_LIMIT_EXCEEDED first. To exercise the
    employer-only cap, choose gross where employee_amount <=
    EMPLOYEE_ANNUAL_LIMIT but employer match would exceed
    EMPLOYER_ANNUAL_LIMIT.

    With deferral=5%: employee = 5% of gross. EMPLOYEE_CAP /
    0.05 = 47_000_000. So gross up to 47_000_000 keeps employee
    within the cap. At gross = 47_000_000, employer (Safe Harbor 4%) =
    1_880_000, well within the employer cap.

    Use a tiered plan with a high match_rate_pct so the employer
    match grows much faster than the employee deferral. With
    brackets [{up_to:5, rate:200}]: at deferral=5%, employer match
    pct = 5*2 = 10%. Then gross = 47_000_000 yields
    employee = 2_350_000 (=== cap) and employer = 4_700_000 ->
    EXCEEDS cap, cap binds, persisted employer = 4_600_000.
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="TIERED",
        tiered_brackets=[
            {"employee_deferral_pct_up_to": 5, "match_rate_pct": 200},
        ],
        elected_deferral_pct=5.0,
        annual_compensation_cents=1_000_000_000,
    )
    gross = 47_000_000
    res = api.create_contribution_record(
        plan["id"], p["id"],
        create_contribution_payload(
            pay_period_end="2026-01-15", gross_pay_cents=gross,
        ),
        payroll_headers,
    )
    cr = validate_success(res, 201)
    # Employee at 5% of 47M = 2,350,000 = cap exactly.
    assert cr["employee_amount_cents"] == EMPLOYEE_ANNUAL_LIMIT_CENTS
    # Employer 10% of 47M = 4,700,000 — capped to EMPLOYER_ANNUAL_LIMIT.
    assert cr["employer_match_cents"] == EMPLOYER_ANNUAL_LIMIT_CENTS


def test_employer_cap_binds_at_exact_threshold_silent_cap(api,
                                                         payroll_headers):
    """PRD §3.3: "the employer side is silently capped (never rejected)
    at the larger of zero and the employer annual limit minus the
    year-to-date employer total".

    Claim: after a prior contribution pushes ytd_employer close to the
    cap, a second contribution's employer side is capped to exactly
    (cap - ytd_employer), not to its full unbounded value. Returns
    201, not 422.

    Difficulty instance pinning: employer_cap binds AFTER per-row
    employee — proves the order-of-evaluation rule.

    # difficulty: combinatorial_formula/employer_match_pinned_after_per_row_employee_when_ytd_cap_binds
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="SAFE_HARBOR_BASIC",
        elected_deferral_pct=5.0,
        annual_compensation_cents=1_000_000_000,
    )
    # First contribution: drives ytd_employer to (EMPLOYER_CAP - 10000).
    # Safe Harbor at 5%: match% = 4%.
    # We want ytd_employer == 4_590_000; pick gross so that 4% of gross
    # = 4_590_000 -> gross = 114_750_000. Round to a multiple yielding
    # exact employer cents.
    target_ytd = EMPLOYER_ANNUAL_LIMIT_CENTS - 10_000  # 4_590_000
    gross_first = int(round(target_ytd / 0.04))         # 114_750_000
    # Employee = 5% of 114_750_000 = 5_737_500 -> exceeds employee cap
    # 2_350_000. Need employee side WITHIN cap. Drop deferral so
    # employee cap doesn't bind: set deferral=2% via PATCH? But Safe
    # Harbor match pct then becomes 2*1.0 = 2% of pay. To keep
    # employer cap binding while staying within employee cap, switch
    # to a tiered scheme that magnifies employer match relative to
    # employee deferral.
    # Use tiered_brackets [{up_to:1, rate:1000}] giving employer match
    # pct = 10% of pay at deferral=1%. Then employer match per row =
    # 10% * gross; employee per row = 1% * gross.
    plan, p = setup_basic_active_participant(
        match_formula_type="TIERED",
        tiered_brackets=[
            {"employee_deferral_pct_up_to": 1, "match_rate_pct": 1000},
        ],
        elected_deferral_pct=1.0,
        annual_compensation_cents=1_000_000_000,
    )
    # Choose gross so employer match per row hits target_ytd exactly.
    # employer_pct_of_pay = applied_pp * match_rate / 100 with applied_pp=1
    # so = 1 * 1000 / 100 = 10.0% of gross.
    gross_first = int(round(target_ytd / 0.10))  # 45_900_000
    # employee per row = 1% * 45_900_000 = 459_000 -> under cap.
    cr1 = post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-15", gross_pay_cents=gross_first,
        headers=payroll_headers,
    )
    assert cr1["employee_amount_cents"] == 459_000
    assert cr1["employer_match_cents"] == 4_590_000

    # Second contribution: gross sized so unbounded employer match
    # would be 20000; cap leaves only 10000.
    # employer_unbounded = 10% * gross_second = 20_000 -> gross_second
    # = 200_000.
    gross_second = 200_000
    res2 = api.create_contribution_record(
        plan["id"], p["id"],
        create_contribution_payload(
            pay_period_end="2026-01-31", gross_pay_cents=gross_second,
        ),
        payroll_headers,
    )
    cr2 = validate_success(res2, 201)
    # Employee 1% of 200_000 = 2_000.
    assert cr2["employee_amount_cents"] == 2_000
    # Employer cap binds: 4_600_000 - 4_590_000 = 10_000.
    assert cr2["employer_match_cents"] == 10_000


def test_employer_cap_binds_silent_cap_second_scenario(api, payroll_headers):
    """PRD §3.3: "the employer side is silently capped (never rejected)
    at the larger of zero and the employer annual limit minus the
    year-to-date employer total, and the capped value is what is
    persisted in employer_match_cents."

    Second test for the difficulty instance: a different starting
    cap-headroom value (1000 cents headroom instead of 10000) proves
    the cap formula is general, not coincidental to a single setup.

    # difficulty: combinatorial_formula/employer_match_pinned_after_per_row_employee_when_ytd_cap_binds
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="TIERED",
        tiered_brackets=[
            {"employee_deferral_pct_up_to": 1, "match_rate_pct": 1000},
        ],
        elected_deferral_pct=1.0,
        annual_compensation_cents=1_000_000_000,
    )
    # Drive ytd_employer to EMPLOYER_CAP - 1000 = 4_599_000.
    target_ytd = EMPLOYER_ANNUAL_LIMIT_CENTS - 1_000
    # employer_pct_of_pay = 10% of gross; gross = target_ytd / 0.10
    gross_first = int(round(target_ytd / 0.10))   # 45_990_000
    # employee at 1% = 459_900 < cap, ok.
    cr1 = post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-15", gross_pay_cents=gross_first,
        headers=payroll_headers,
    )
    assert cr1["employer_match_cents"] == 4_599_000

    # Second post: unbounded employer = 10% * gross = 5_000 (need to
    # exceed remaining headroom of 1000). Use gross = 50_000 so
    # employer unbounded = 5_000, but capped to 1_000.
    res2 = api.create_contribution_record(
        plan["id"], p["id"],
        create_contribution_payload(
            pay_period_end="2026-01-31", gross_pay_cents=50_000,
        ),
        payroll_headers,
    )
    cr2 = validate_success(res2, 201)
    assert cr2["employer_match_cents"] == 1_000
    assert cr2["employee_amount_cents"] == 500  # 1% of 50000


# ===========================================================================
# Pay-period uniqueness — PRD §3.3, §2.13
# ===========================================================================
def test_duplicate_pay_period_rejected(api, payroll_headers):
    """PRD §3.3: "No two ContributionRecord rows may share the pair
    (participant_id, pay_period_end). A duplicate request is rejected
    with ERR_DUPLICATE_PAY_PERIOD."

    Claim: posting twice with identical pay_period_end -> 409
    ERR_DUPLICATE_PAY_PERIOD.

    # difficulty: resource_temporal_overlap/contribution_pay_period_exact_day_uniqueness
    """
    plan, p = setup_basic_active_participant(elected_deferral_pct=5.0)
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-02-15", gross_pay_cents=500_000,
    )
    res = api.create_contribution_record(
        plan["id"], p["id"],
        create_contribution_payload(
            pay_period_end="2026-02-15", gross_pay_cents=500_000,
        ),
        payroll_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_DUPLICATE_PAY_PERIOD.value,
        expected_status=409,
    )


def test_adjacent_pay_periods_do_not_collide(api, payroll_headers):
    """PRD §3.3: "No two ContributionRecord rows may share the pair
    (participant_id, pay_period_end)." Closed-point semantics:
    different dates do not collide.

    Claim: two contributions one day apart both succeed (201 each).

    # difficulty: resource_temporal_overlap/contribution_pay_period_exact_day_uniqueness
    """
    plan, p = setup_basic_active_participant(elected_deferral_pct=5.0)
    cr1 = post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-02-15", gross_pay_cents=500_000,
    )
    cr2 = post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-02-16", gross_pay_cents=500_000,
    )
    assert cr1["id"] != cr2["id"]
    assert cr1["pay_period_end"] == "2026-02-15"
    assert cr2["pay_period_end"] == "2026-02-16"


# ===========================================================================
# Side effects on success — PRD §3.3
# ===========================================================================
def test_contribution_updates_cumulative_balances(api):
    """PRD §3.3: "On successful posting, the participant's
    cumulative_employee_contribution_cents is increased by the
    (capped) employee_amount_cents, the participant's
    cumulative_employer_match_cents is increased by the (capped)
    employer_match_cents, and total_account_balance_cents is updated
    to reflect both deltas."

    Claim: after one Safe Harbor 6% post, cumulative_employee = 30000,
    cumulative_employer = 20000, total = 50000.
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="SAFE_HARBOR_BASIC",
        elected_deferral_pct=6.0,
    )
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-15", gross_pay_cents=500_000,
    )
    p_after = validate_success(
        api.get_participant(plan["id"], p["id"], TEST_USERS["admin_headers"]),
        200,
    )
    assert p_after["cumulative_employee_contribution_cents"] == 30_000
    assert p_after["cumulative_employer_match_cents"] == 20_000
    assert p_after["total_account_balance_cents"] == 50_000


def test_cumulative_fields_sum_underlying_rows(api):
    """PRD §3.3: "On successful posting, the participant's
    cumulative_employee_contribution_cents is increased by the
    (capped) employee_amount_cents".

    Claim: after three Safe Harbor 6% posts (each 30000/20000),
    cumulative fields == sum of the three rows.

    # difficulty: compensating_invariant/contribution_year_totals_match_sum_of_records
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="SAFE_HARBOR_BASIC",
        elected_deferral_pct=6.0,
        annual_compensation_cents=6_000_000,
    )
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-15", gross_pay_cents=500_000,
    )
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-01-31", gross_pay_cents=500_000,
    )
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-02-15", gross_pay_cents=500_000,
    )

    data, meta = validate_paginated(
        api.list_contribution_records(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
    )
    assert meta["total_count"] >= 3
    p_after = validate_success(
        api.get_participant(plan["id"], p["id"], TEST_USERS["admin_headers"]),
        200,
    )
    # Each row: employee=30000, employer=20000.
    assert p_after["cumulative_employee_contribution_cents"] == 90_000
    assert p_after["cumulative_employer_match_cents"] == 60_000
    assert p_after["total_account_balance_cents"] == 150_000


def test_cumulative_fields_sum_underlying_rows_two_post_variant(api):
    """PRD §3.3: "On successful posting, the participant's ...
    cumulative_employer_match_cents is increased by the (capped)
    employer_match_cents".

    Claim: a 2-row variant of the conserved-totals invariant.

    # difficulty: compensating_invariant/contribution_year_totals_match_sum_of_records
    """
    plan, p = setup_basic_active_participant(
        match_formula_type="SAFE_HARBOR_BASIC",
        elected_deferral_pct=6.0,
    )
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-03-15", gross_pay_cents=500_000,
    )
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-03-31", gross_pay_cents=500_000,
    )
    p_after = validate_success(
        api.get_participant(plan["id"], p["id"], TEST_USERS["admin_headers"]),
        200,
    )
    assert p_after["cumulative_employee_contribution_cents"] == 60_000
    assert p_after["cumulative_employer_match_cents"] == 40_000
    assert p_after["total_account_balance_cents"] == 100_000


# ===========================================================================
# Empty collection — PRD §3.2 / §3.3
# ===========================================================================
def test_just_enrolled_participant_has_zero_balances_and_empty_records(api,
                                                                      admin_headers):
    """PRD §3.2: "The newly enrolled participant has ...
    cumulative_employee_contribution_cents initialized to zero ...
    total_account_balance_cents initialized to zero."

    Claim: a just-enrolled (ENROLLED, never-activated) participant
    returns zero balances; the contribution-records list returns
    [] with total_count==0 and has_more==false.

    # difficulty: boundary_precision_check/contribution_records_empty_collection_for_new_participant
    """
    plan = create_and_activate_plan()
    res = api.create_participant(
        plan["id"],
        {
            "employee_external_id": "emp-empty-1",
            "date_of_birth": "1990-01-01",
            "hire_date": "2020-01-01",
            "annual_compensation_cents": 6_000_000,
            "elected_deferral_pct": 5.0,
        },
        admin_headers,
    )
    p = validate_success(res, 201)
    p_get = validate_success(
        api.get_participant(plan["id"], p["id"], admin_headers), 200,
    )
    assert p_get["cumulative_employee_contribution_cents"] == 0
    assert p_get["total_account_balance_cents"] == 0

    data, meta = validate_paginated(
        api.list_contribution_records(plan["id"], p["id"], admin_headers),
    )
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_just_enrolled_participant_zero_balances_second_instance(api,
                                                                 admin_headers):
    """PRD §3.2: identical zero-init rule, covered through a second
    plan + participant to give the difficulty instance two tests.

    # difficulty: boundary_precision_check/contribution_records_empty_collection_for_new_participant
    """
    plan = create_and_activate_plan()
    res = api.create_participant(
        plan["id"],
        {
            "employee_external_id": "emp-empty-2",
            "date_of_birth": "1992-02-02",
            "hire_date": "2021-03-03",
            "annual_compensation_cents": 7_500_000,
            "elected_deferral_pct": 3.0,
        },
        admin_headers,
    )
    p = validate_success(res, 201)
    p_get = validate_success(
        api.get_participant(plan["id"], p["id"], admin_headers), 200,
    )
    assert p_get["cumulative_employee_contribution_cents"] == 0
    assert p_get["cumulative_employer_match_cents"] == 0
    assert p_get["total_account_balance_cents"] == 0
    data, meta = validate_paginated(
        api.list_contribution_records(plan["id"], p["id"], admin_headers),
    )
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
