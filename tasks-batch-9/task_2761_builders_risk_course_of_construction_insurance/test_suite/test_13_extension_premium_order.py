"""The pinned five-step evaluation order behind an extension's premium.

The tier reads cumulative days that already include the request being priced,
the daily rate is rounded before it is multiplied out, and the catastrophe
reslip reads the risk index as of the start of the request.
"""
from test_helpers import fixtures as fx
from test_helpers.factories import loss_item


def test_first_slip_prices_on_a_rounded_daily_base_and_takes_no_catastrophe_reslip():
    """A project scoring exactly 75 is referred rather than quoted, and the
    manager's 0.10 load re-prices the stored premium to 22423995. The first
    120-day slip is more than a quarter of the 364-day original term, so the
    slip factor is 1.40 on a daily base of round_half_up(22423995 / 364) =
    61604, giving 10349472. No reslip load applies, because the audit score
    does not exist yet and the submission score of 75 is below 85.

    Design: Difficulty/combinatorial_formula/extension_premium_pinned_evaluation_order_mode_c
    """
    account = fx.gulfside_referred_account()

    assert account.project["submission_risk_score"] == 75, account.project
    assert account.policy["status"] == "REFERRED", account.policy
    assert account.policy["quoted_premium_cents"] == 20385450, account.policy

    fx.approve_referral(account, referral_load_pct=0.10)
    assert account.policy["quoted_premium_cents"] == 22423995, account.policy

    fx.incept_account(fx.bind_account(account))
    endorsement = fx.file_endorsement(account, 120, slip_reason="MATERIAL_DELAY")

    assert endorsement["slip_factor"] == 1.40, endorsement["slip_factor"]
    assert endorsement["additional_premium_cents"] == 10349472, (
        "61604 * 120 * 1.40 with no catastrophe reslip, "
        f"got {endorsement['additional_premium_cents']}")
    assert endorsement["revised_completion_date"] == "2027-12-23T00:00:00Z", endorsement


def test_repeat_slip_tiers_on_unapproved_days_and_takes_the_catastrophe_reslip():
    """Once the first extension is approved and a claim is adjusted the audit
    score reaches 88, so the next request is loaded by 1.25 on top of its own
    arithmetic: cumulative-after 150 of 364 is above a quarter so the factor is
    1.40, round_half_up(61604 * 30 * 1.40) is 2587368, and the reslip lifts it
    to 3234210. The tier used days the policy has not yet approved, so
    cumulative_extension_days still reads 120 while the request is REQUESTED.

    Design: Difficulty/combinatorial_formula/extension_premium_pinned_evaluation_order_mode_c
    """
    account = fx.gulfside_in_force_account(referral_load_pct=0.10)
    fx.approved_endorsement(account, 120, slip_reason="MATERIAL_DELAY")
    fx.adjusted_claim(
        account,
        [loss_item("MATERIALS_ON_SITE", 100000000)],
        adjustment_basis="ACTUAL_LOSS",
        peril="FLOOD",
        loss_date="2027-03-05T00:00:00Z",
    )

    project = account.refresh_project()
    assert project["audit_risk_score"] == 88, (
        "30 + 30 + 15 value + 8 duration + 5 claim, "
        f"got {project['audit_risk_score']}")

    second = fx.file_endorsement(account, 30, slip_reason="WEATHER")

    assert second["slip_factor"] == 1.40, second["slip_factor"]
    assert second["additional_premium_cents"] == 3234210, (
        "2587368 loaded by the 1.25 catastrophe reslip, "
        f"got {second['additional_premium_cents']}")
    assert second["status"] == "REQUESTED", second["status"]
    assert account.policy["cumulative_extension_days"] == 120, (
        "the unapproved 30 days must not be added to the policy yet, "
        f"got {account.policy['cumulative_extension_days']}")
