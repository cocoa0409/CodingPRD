"""Reviewer reliability under its two window variants and the conserved open load.

Both concerns are read off the same `Reviewer` record: the ROLLING and LIFETIME
variants of the reliability computation, and the `open_invitation_count` that an
editor withdrawal must restore.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def test_rolling_window_excludes_the_stale_decline_that_lifetime_keeps():
    """One reviewer carries two different scores at once, split only by the 180-day boundary.

    PRD: "The `ROLLING` variant's set is the reviewer's closed invitations whose `created_at` is at or after the current clock instant minus 180 days, the lower bound being inclusive; it is written to `reliability_score_rolling`."

    Design: Difficulty/dual_variant_calc/reviewer_reliability_rolling_vs_lifetime_window_divergence
    """
    world = fx.setup_rolling_vs_lifetime_reviewer()
    reviewer = world["reviewer"]

    a.assert_score_equals(
        reviewer["reliability_score_rolling"], 100.00, "reliability_score_rolling"
    )
    a.assert_score_equals(
        reviewer["reliability_score_lifetime"], 77.50, "reliability_score_lifetime"
    )
    delta = round(
        float(reviewer["reliability_score_rolling"])
        - float(reviewer["reliability_score_lifetime"]),
        2,
    )
    assert delta == 22.50, f"Expected a 22.50 window delta, got {delta}"


def test_lifetime_variant_keeps_conduct_older_than_the_rolling_window():
    """The decline dropped by the rolling set is still full weight in the lifetime set.

    PRD: "The `LIFETIME` variant's set is every closed invitation the reviewer has ever had, so conduct older than 180 days keeps its full weight and the two variants disagree whenever behaviour changed across that boundary; it is written to `reliability_score_lifetime`."

    Design: Difficulty/dual_variant_calc/reviewer_reliability_rolling_vs_lifetime_window_divergence
    """
    world = fx.setup_rolling_vs_lifetime_reviewer()
    reviewer = world["reviewer"]

    assert world["declined_invitation"]["state"] == "DECLINED"
    assert world["submitted_invitation"]["state"] == "SUBMITTED"
    a.assert_fields(
        reviewer,
        declined_count=1,
        submitted_count=1,
        late_days_total=0,
        status="ACTIVE",
    )
    assert float(reviewer["reliability_score_lifetime"]) < float(
        reviewer["reliability_score_rolling"]
    ), "the lifetime set holds the extra non-delivery, so it must score lower"


def test_review_weight_freezes_from_the_recomputed_rolling_score():
    """The delivered review carries the rolling score written in that same request.

    PRD: "The weight is the reviewer's new rolling score divided by 100, rounded half up to 4 decimal places, and then floored at 0.2500 — that is, the larger of 0.2500 and the rounded quotient — so even a reviewer with a rolling score of zero still carries a quarter of a vote."

    Design: Difficulty/dual_variant_calc/reviewer_reliability_rolling_vs_lifetime_window_divergence
    """
    world = fx.setup_rolling_vs_lifetime_reviewer()
    review = world["review"]

    assert review["days_late"] == 0, "the review landed on its deadline instant"
    a.assert_weight_equals(review["reliability_weight"], 1.0000)


def test_open_invitation_count_returns_to_its_pre_invitation_value():
    """Withdrawal restores the conserved open load 0 -> 1 -> 0.

    PRD: "The reviewer's `open_invitation_count` falls by 1, restoring the conserved open-load quantity to its pre-invitation value, while `invited_count` is deliberately **not** decremented — the invitation happened, and the audit trail says so."

    Design: Difficulty/compensating_invariant/reviewer_open_invitation_count_conserved_by_withdraw
    """
    world = fx.setup_open_invitation_for_withdrawal()

    assert world["reviewer_before"]["open_invitation_count"] == 0
    assert world["reviewer_while_open"]["open_invitation_count"] == 1

    fx.withdraw_invitation(
        world["invitation"]["id"],
        world["handling_headers"],
        reason="Reviewer pool rebalanced",
    )

    after = fx.get_reviewer(world["reviewer"]["id"])
    assert after["open_invitation_count"] == 0, (
        "the withdraw must restore the pre-invitation open load"
    )
    assert after["invited_count"] == 1, "the audit counter is never decremented"


def test_withdrawn_invitation_records_the_editor_withdrawal():
    """The pulled invitation closes as `WITHDRAWN` / `EDITOR_WITHDRAWN`.

    PRD: "Withdrawal carries an optional `reason` and applies to an invitation at either `INVITED` or `ACCEPTED`, so the declared moves are `INVITED → WITHDRAWN` and `ACCEPTED → WITHDRAWN`, each carrying `closed_reason` `EDITOR_WITHDRAWN`."

    Design: Difficulty/compensating_invariant/reviewer_open_invitation_count_conserved_by_withdraw
    """
    world = fx.setup_open_invitation_for_withdrawal()

    fx.withdraw_invitation(
        world["invitation"]["id"],
        world["handling_headers"],
        reason="Reviewer pool rebalanced",
    )

    invitation = fx.get_invitation(world["invitation"]["id"])
    a.assert_fields(invitation, state="WITHDRAWN", closed_reason="EDITOR_WITHDRAWN")
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "UNDER_REVIEW"


def test_withdraw_scores_as_a_closed_non_delivery_without_demoting_the_reviewer():
    """The withdrawal enters the scoring set, but one closed invitation is not enough for probation.

    PRD: "A reviewer at `ACTIVE` moves to `PROBATION` when the new `reliability_score_rolling` is strictly below 40.00 **and** the rolling set holds at least 3 closed invitations — the minimum-evidence requirement stops a single unlucky expiry from demoting a reviewer."

    Design: Difficulty/compensating_invariant/reviewer_open_invitation_count_conserved_by_withdraw
    """
    world = fx.setup_open_invitation_for_withdrawal()

    fx.withdraw_invitation(
        world["invitation"]["id"],
        world["handling_headers"],
        reason="Reviewer pool rebalanced",
    )

    after = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_score_equals(
        after["reliability_score_rolling"], 20.00, "reliability_score_rolling"
    )
    a.assert_fields(after, status="ACTIVE", declined_count=0, submitted_count=0)
