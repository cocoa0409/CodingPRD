"""Loan-maximum calculations: nested min/max, exact boundary, and the trailing
12-month high-water mark (PRD §3.4)."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_loan_fully,
    create_loan_payload,
    create_plan_payload,
    create_remittance_payload,
    enroll_participant,
    make_participant_headers,
    request_loan,
    set_clock,
    setup_plan_and_participant,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


# ---------------------------------------------------------------------------
# Difficulty: loan_maximum_nested_min_max
# ---------------------------------------------------------------------------


def test_loan_maximum_nested_min_max_plan_cap_binds(api):
    """PRD §3.4: "That maximum is the smallest of three quantities: one half of
    the participant's `vested_balance_cents`, rounded down to a whole cent; the
    statutory ceiling of 5,000,000 cents (fifty thousand dollars), reduced by
    the amount — never below zero — by which the participant's trailing
    twelve-month high-water mark of outstanding principal exceeds their current
    outstanding total; and the plan's own `max_loan_amount_cents`."

    Design: Difficulty/combinatorial_formula/loan_maximum_nested_min_max
    """
    plan = validate_success(
        api.create_plan(
            create_plan_payload(name="Plan MinMax", max_loan_amount_cents=4_000_000),
            ADMIN,
        ),
        201,
    )
    participant = enroll_participant(plan["id"], vested_balance_cents=12_000_000)
    elig = validate_success(api.get_loan_eligibility(participant["id"], ADMIN), 200)
    # vested/2 = 6,000,000; IRC cap = 5,000,000; plan cap = 4,000,000 -> 4,000,000
    assert elig["max_loan_amount_cents"] == 4_000_000


def test_loan_maximum_nested_min_max_over_cap_rejected(api):
    """PRD §2.8 priority 12: "The requested principal — or, for a refinance, the
    new principal — must not exceed the computed maximum loan amount (otherwise
    `ERR_LOAN_LIMIT_EXCEEDED`)"."

    Design: Difficulty/combinatorial_formula/loan_maximum_nested_min_max
    """
    plan = validate_success(
        api.create_plan(
            create_plan_payload(name="Plan MinMax2", max_loan_amount_cents=4_000_000),
            ADMIN,
        ),
        201,
    )
    p1 = enroll_participant(plan["id"], vested_balance_cents=12_000_000)
    p2 = enroll_participant(plan["id"], vested_balance_cents=12_000_000)
    # At the cap: accepted
    loan_ok = validate_success(
        api.create_loan(
            p1["id"],
            create_loan_payload(principal_amount_cents=4_000_000, term_months=12),
            make_participant_headers(p1["id"]),
        ),
        201,
    )
    assert loan_ok["lifecycle_status"] == "REQUESTED"
    # One cent over the cap: rejected
    res = api.create_loan(
        p2["id"],
        create_loan_payload(principal_amount_cents=4_000_001, term_months=12),
        make_participant_headers(p2["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAN_LIMIT_EXCEEDED, expected_status=422)


# ---------------------------------------------------------------------------
# Difficulty: loan_request_at_exact_vested_ratio_boundary
# ---------------------------------------------------------------------------


def test_loan_request_at_exact_vested_ratio_boundary_accepted(api):
    """PRD §3.4: "That maximum is the smallest of three quantities: one half of
    the participant's `vested_balance_cents`, rounded down to a whole cent; the
    statutory ceiling of 5,000,000 cents ... and the plan's own
    `max_loan_amount_cents`." With vested 10,000,000 the vested component is
    5,000,000 (equal to the IRC cap and the default plan cap), so principal
    exactly 5,000,000 is accepted.

    Design: Difficulty/boundary_precision_check/loan_request_at_exact_vested_ratio_boundary
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = validate_success(
        api.create_loan(
            participant["id"],
            create_loan_payload(principal_amount_cents=5_000_000, term_months=60),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    assert loan["lifecycle_status"] == "REQUESTED"
    assert loan["principal_amount_cents"] == 5_000_000


def test_loan_request_at_exact_vested_ratio_boundary_over_rejected(api):
    """PRD §2.8 priority 12: "The requested principal ... must not exceed the
    computed maximum loan amount (otherwise `ERR_LOAN_LIMIT_EXCEEDED`)"."

    Design: Difficulty/boundary_precision_check/loan_request_at_exact_vested_ratio_boundary
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    res = api.create_loan(
        participant["id"],
        create_loan_payload(principal_amount_cents=5_000_001, term_months=60),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAN_LIMIT_EXCEEDED, expected_status=422)


# ---------------------------------------------------------------------------
# Corner: trailing_12m_high_water_mark_reduces_irc_cap
# ---------------------------------------------------------------------------


def test_trailing_12m_high_water_mark_reduces_irc_cap(api):
    """PRD §3.4: "the statutory ceiling of 5,000,000 cents (fifty thousand
    dollars), reduced by the amount — never below zero — by which the
    participant's trailing twelve-month high-water mark of outstanding principal
    exceeds their current outstanding total". A participant who repaid a
    2,000,000c loan sees the IRC cap shrink to 3,000,000c.

    PRD §3.4: "The high-water mark is computed over the closed lookback window
    running from the day twelve calendar months before today through
    yesterday." The peak must therefore sit on a day strictly before the
    eligibility read: disburse at the startup clock, hold the 2,000,000c
    balance across several end-of-day totals, repay, and read the next day.

    Design: Corner/calculations/trailing_12m_high_water_mark_reduces_irc_cap
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    # Disburse a 2,000,000c loan at the startup clock (2026-05-01), then let the
    # balance stand so the window reconstruction observes 2,000,000c end-of-day
    # totals on 2026-05-01 through 2026-05-09.
    loan = request_loan(participant, principal_amount_cents=2_000_000, term_months=12)
    approve_loan_fully(loan["id"])
    validate_success(api.disburse_loan(loan["id"], ADMIN), 200)
    set_clock("2026-05-10T00:00:00Z")
    # 2,000,000c / 500bps / 12mo 30/360 amortizes to 171,215c/mo for months 1..11
    # and 171,215c final rounding remainder; full payoff total is 2,054,580c.
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=2_054_580, pay_date="2026-05-10T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    # Read the next day: the window [2025-05-11 .. 2026-05-10] now contains the
    # 2,000,000c end-of-day totals, so the IRC cap shrinks by 2,000,000c - 0c.
    set_clock("2026-05-11T00:00:00Z")
    elig = validate_success(api.get_loan_eligibility(participant["id"], ADMIN), 200)
    assert elig["max_loan_amount_cents"] == 3_000_000
    assert elig["eligible"] is True
