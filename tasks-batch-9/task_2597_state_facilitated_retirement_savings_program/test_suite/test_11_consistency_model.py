"""
Every derived figure on a record is current in the very response that changed it.

Nothing in this service is eventually consistent: a write that moves an
account's balance must answer with the balance, the fund-level split, the
untouched contribution basis and the advanced version counter all already
settled, and a later read of the same account must add nothing and change
nothing. A service that recomputed the split on the next read instead would pass
a read-after-write check while failing this one.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    RECORDKEEPER,
    assert_amounts,
    assert_fund_balances,
    build_active_saver_environment,
    elect_allocations,
    fund_account_by_remittance,
    read_account,
)

# The pay cycle that funds the account, and the day the earnings are recognised.
PAY_PERIOD_START = "2026-02-01"
PAY_PERIOD_END = "2026-02-14"
PAY_DATE = "2026-02-25"
POSTING_CLOCK = "2026-02-28T00:00:00Z"
EARNINGS_DATE = "2026-02-28"

# 8000000 cents of gross wages at the programme default of 500 basis points.
GROSS_WAGES_CENTS = 8000000
DEDUCTED_CENTS = 400000
EARNINGS_CENTS = 10000

# A sixty-forty split of the funded balance across the two-fund menu.
SPLIT_ALLOCATIONS = [
    {"fund_code": "TDF2045", "allocation_bp": 6000},
    {"fund_code": "MMKT01", "allocation_bp": 4000},
]


def _account_split_sixty_forty_across_two_funds(api):
    """
    An active saver whose account holds one posted pay cycle's deductions and
    whose own fund election splits that balance sixty-forty, with the clock
    standing on the day the earnings will be recognised.
    """
    env = build_active_saver_environment(api)
    fund_account_by_remittance(
        api, env, PAY_PERIOD_START, PAY_PERIOD_END, PAY_DATE,
        GROSS_WAGES_CENTS, DEDUCTED_CENTS, POSTING_CLOCK,
        posting_reference="PR-2026-0400")
    funded = read_account(api, env["account_id"])
    elect_allocations(api, env["account_id"], env["participant_id"],
                      SPLIT_ALLOCATIONS, funded["version"])
    env["account_before_earnings"] = read_account(api, env["account_id"])
    return env


def test_an_earnings_credit_answers_with_every_derived_figure_already_settled(api):
    """
    One earnings credit against a sixty-forty account must come back with the new
    balance of 410000 cents, a contribution basis still standing at the 400000
    cents that were actually contributed, a fund split re-derived from scratch
    against the new balance into 246000 and 164000 cents, and a version counter
    that has already moved — and re-reading the account afterwards must return
    exactly the same figures.

    "The account's `balance_cents` is adjusted by that amount while
    `contribution_basis_cents` is left exactly as it was — earnings create no new
    basis — the fund split is recomputed from the new balance, and the account's
    `version` increments."

    "For every entry except the last in that order, the fund's balance is the
    account balance multiplied by the entry's weight in basis points, divided by
    10000, rounded half up to a whole cent."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
    """
    env = _account_split_sixty_forty_across_two_funds(api)
    before = env["account_before_earnings"]
    assert_amounts(before, {
        "balance_cents": 400000,
        "contribution_basis_cents": 400000,
    }, label="account before the earnings credit")
    assert_fund_balances(before, [
        {"fund_code": "TDF2045", "balance_cents": 240000},
        {"fund_code": "MMKT01", "balance_cents": 160000},
    ])

    posted = validate_success(api.post_earnings(
        env["account_id"],
        {"earnings_cents": EARNINGS_CENTS, "posting_date": EARNINGS_DATE},
        RECORDKEEPER))

    assert_amounts(posted, {
        "balance_cents": 410000,
        "contribution_basis_cents": 400000,
        "ytd_contribution_cents": 400000,
    }, label="account in the earnings-credit response")
    assert_fund_balances(posted, [
        {"fund_code": "TDF2045", "balance_cents": 246000},
        {"fund_code": "MMKT01", "balance_cents": 164000},
    ])
    assert posted["version"] > before["version"], (
        "the earnings credit must advance the account's version in the same "
        f"response: was {before['version']}, answered {posted['version']}"
    )

    reread = read_account(api, env["account_id"])
    assert reread["balance_cents"] == posted["balance_cents"]
    assert reread["contribution_basis_cents"] == posted["contribution_basis_cents"]
    assert reread["fund_balances"] == posted["fund_balances"]
    assert reread["version"] == posted["version"]
