"""The rating engine: five loaded components, a tiered credit and a floor."""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import api_client
from test_helpers import fixtures as fx

# The schedule the premium is rated from: only SOFT_COST and
# DELAY_IN_COMPLETION feed the soft-cost component, and every rateable policy
# needs a MATERIALS_ON_SITE part.
RATED_PART_PLAN = (
    ("SOFT_COST", 300000000),
    ("DELAY_IN_COMPLETION", 250000000),
    ("MATERIALS_ON_SITE", 1000000000),
)


def test_quoted_premium_stacks_every_component_over_the_frozen_insured_value():
    """The five rounded components are added to give the subtotal, the
    deductible credit is subtracted, and the result is the greater of that
    figure and the minimum premium: base 2200000 on 20000 units at the
    non-combustible rate, plus an 18 percent wind load of 396000, plus no
    duration load on an 11-month term, plus 330000 of soft-cost load on 5500
    units, less the 6 percent elevated-tier credit of 175560. A submission
    score of 28 is below the referral threshold, so the branch is QUOTED.

    Design: Difficulty/combinatorial_formula/quote_premium_component_stack_mode_a
    """
    account = fx.draft_account(parts=RATED_PART_PLAN)

    assert account.policy["insured_tiv_cents"] == 2000000000, account.policy
    assert account.policy["original_term_days"] == 302, account.policy

    fx.quote_account(account)

    assert account.policy["status"] == "QUOTED", (
        "submission_risk_score 28 is below 75, so rating must not refer, "
        f"got {account.policy['status']}")
    assert account.policy["quoted_premium_cents"] == 2750440, (
        "2200000 + 396000 + 0 + 330000 + 0 less the 175560 credit, "
        f"got {account.policy['quoted_premium_cents']}")


def test_editing_one_child_sublimit_reprices_the_parent_policy():
    """The soft-cost load is read off the coverage schedule, so a reopened
    policy whose SOFT_COST sublimit is patched down to 100000000 re-rates on a
    soft-cost component of 210000 instead of 330000: subtotal 2806000, credit
    168360, quoted premium 2637640 - 112800 cents below the first quote.

    Design: Difficulty/combinatorial_formula/quote_premium_component_stack_mode_a
    """
    account = fx.draft_account(parts=RATED_PART_PLAN)
    fx.quote_account(account)
    first_premium = account.policy["quoted_premium_cents"]

    account.policy = get_success_data(
        api_client.reopen_policy(account.policy_id, fx.UW))
    assert account.policy["status"] == "DRAFT", account.policy
    assert account.policy["quoted_premium_cents"] is None, account.policy

    get_success_data(api_client.patch_coverage_part(
        account.part("SOFT_COST")["id"], {"sublimit_cents": 100000000}, fx.UW))

    fx.quote_account(account)
    second_premium = account.policy["quoted_premium_cents"]

    assert second_premium == 2637640, (
        "soft component 210000, subtotal 2806000, credit 168360, "
        f"got {second_premium}")
    assert first_premium - second_premium == 112800
