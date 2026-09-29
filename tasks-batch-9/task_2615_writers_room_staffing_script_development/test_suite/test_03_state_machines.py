"""Lifecycles that are not ladders: a revision cycle and a two-branch fork.

The assignment loop re-enters states it has already left, and the credit
determination sends one endpoint to two different terminals that then rejoin.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import GUILD_ADMINISTRATOR_HEADERS


def _statuses(api, assignment_id):
    """The milestone statuses of one assignment, in sequence order."""
    return [m["status"] for m in X.milestones_of(api, assignment_id)]


def _second_pass_world(api):
    """A delivered assignment that has already been through one notes round."""
    world = X.build_delivered_assignment_world(api)
    last_id = world["a1_milestone_ids"][-1]
    validate_success(
        api.issue_notes(
            world["a1_id"],
            {"notes": "Tighten the cold open and cut the second flashback."},
            world["sr_headers"],
        )
    )
    X.deliver_milestone(api, last_id, world["w1_id"])
    world["last_milestone_id"] = last_id
    return world


def test_the_revision_cycle_is_traversed_twice_on_one_assignment(api):
    """Notes and redelivery walk DELIVERED to IN_NOTES to DRAFTING to DELIVERED twice.

    PRD: "Notes move the assignment `DELIVERED → IN_NOTES` and increment `revision_round` by one, and every milestone of the assignment currently in `DELIVERED` becomes `NOTES_ISSUED`."

    PRD: "A single delivery can therefore execute both transitions in that order, which is exactly how the loop `DRAFTING → DELIVERED → IN_NOTES → DRAFTING → DELIVERED` is traversed."

    Design: Difficulty/non_linear_state_machine/script_assignment_revision_loop_traversed_twice_then_capped
    """
    world = X.build_delivered_assignment_world(api)
    last_id = world["a1_milestone_ids"][-1]
    A.assert_field_values(world["a1"], status="DELIVERED", revision_round=0)

    first_notes = validate_success(
        api.issue_notes(
            world["a1_id"],
            {"notes": "Tighten the cold open and cut the second flashback."},
            world["sr_headers"],
        )
    )
    A.assert_field_values(first_notes, status="IN_NOTES", revision_round=1)
    assert _statuses(api, world["a1_id"]) == ["NOTES_ISSUED"] * 3

    redelivered = X.deliver_milestone(api, last_id, world["w1_id"])
    A.assert_field_values(redelivered, status="DELIVERED", days_late=0)
    A.assert_field_values(
        X.read_assignment(api, world["a1_id"]), status="DELIVERED", revision_round=1
    )

    second_notes = validate_success(
        api.issue_notes(
            world["a1_id"], {"notes": "Act three still needs a button."}, world["sr_headers"]
        )
    )
    A.assert_field_values(second_notes, status="IN_NOTES", revision_round=2)
    A.assert_field_values(X.read_milestone(api, last_id), status="NOTES_ISSUED")

    X.deliver_milestone(api, last_id, world["w1_id"])
    A.assert_field_values(
        X.read_assignment(api, world["a1_id"]), status="DELIVERED", revision_round=2
    )


def test_a_third_notes_round_is_refused_and_changes_nothing(api):
    """The free-revision allowance of two stops the loop at its second pass.

    PRD: "With the default allowance of two, notes may be issued twice on one assignment and a third attempt fails."

    Design: Difficulty/non_linear_state_machine/script_assignment_revision_loop_traversed_twice_then_capped
    """
    world = _second_pass_world(api)
    validate_success(
        api.issue_notes(
            world["a1_id"], {"notes": "Act three still needs a button."}, world["sr_headers"]
        )
    )
    X.deliver_milestone(api, world["last_milestone_id"], world["w1_id"])

    validate_error(
        api.issue_notes(
            world["a1_id"], {"notes": "One more pass on the tag."}, world["sr_headers"]
        ),
        ApiErrorId.REVISION_CAP_EXCEEDED,
    )

    assignment = X.read_assignment(api, world["a1_id"])
    A.assert_field_values(
        assignment, status="DELIVERED", revision_round=2, late_milestone_count=0
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="IN_PROGRESS"
    )


def test_a_scattered_panel_deadlocks_and_writes_no_arbitrated_share(api):
    """One ballot of three inside the band gives a concurrence of 0.333.

    PRD: "When `concurrence_pct` falls below the threshold, the panel has failed: the arbitration moves to `DEADLOCKED`, `outcome` stays `NONE`, no `arbitrated_share_pct` is written anywhere, `final_credit_shares` stays empty and the episode remains in `IN_ARBITRATION`."

    PRD: "The `leading_writer_id` is the participant with the highest panel mean, with ties broken by submission `created_at` ascending."

    Design: Difficulty/non_linear_state_machine/credit_arbitration_fork_to_deadlock_then_join_through_policy_review
    """
    world = X.build_arbitration_world(api)
    X.cast_full_panel(api, world, X.deadlocking_ballots(world))

    arbitration = validate_success(
        api.determine_arbitration(
            world["arbitration_id"],
            GUILD_ADMINISTRATOR_HEADERS,
            {"policy_override": False},
        )
    )
    A.assert_field_values(
        arbitration,
        status="DEADLOCKED",
        outcome="NONE",
        votes_cast_count=3,
        leading_writer_id=world["w1_id"],
        concurrence_pct=0.333,
    )

    episode = X.read_episode(api, world["ep1_id"])
    A.assert_field_values(episode, credit_status="IN_ARBITRATION", final_credit_shares={})
    A.assert_field_values(
        X.read_submission(api, world["sb1_id"]), arbitrated_share_pct=None
    )
    A.assert_field_values(
        X.read_submission(api, world["sb2_id"]), arbitrated_share_pct=None
    )


def test_the_policy_override_rejoins_the_deadlock_at_the_provisional_split(api):
    """The override carries the claims-based split forward untouched.

    PRD: "The override moves the arbitration `DEADLOCKED → POLICY_REVIEW`, sets `outcome` to `DEADLOCK_RESOLVED_BY_POLICY`, and applies the guild's policy fallback: each eligible submission's `arbitrated_share_pct` is set equal to its own `provisional_share_pct` and the episode's `final_credit_shares` receives the provisional map unchanged."

    PRD: "The episode's `credit_status` moves to `DETERMINED`, and the `determined_credit_string` is assembled and stored on both the arbitration and the episode: it is the `legal_name` of every writer whose `receives_credit` is true, joined by the three-character separator " & ", in descending order of final share with ties broken by submission `created_at` ascending."

    Design: Difficulty/non_linear_state_machine/credit_arbitration_fork_to_deadlock_then_join_through_policy_review
    """
    world = X.build_deadlocked_world(api)
    A.assert_field_values(world["arbitration"], status="DEADLOCKED")

    resolved = validate_success(
        api.determine_arbitration(
            world["arbitration_id"],
            GUILD_ADMINISTRATOR_HEADERS,
            {"policy_override": True},
        )
    )
    A.assert_field_values(
        resolved,
        status="POLICY_REVIEW",
        outcome="DEADLOCK_RESOLVED_BY_POLICY",
        determined_credit_string="Wanda Cole & Bram Ochoa",
    )

    episode = X.read_episode(api, world["ep1_id"])
    assert episode["final_credit_shares"] == {
        world["w1_id"]: 67,
        world["w2_id"]: 33,
    }, f"The provisional map must carry forward: {episode['final_credit_shares']}"
    A.assert_field_values(
        episode,
        credit_status="DETERMINED",
        determined_credit_string="Wanda Cole & Bram Ochoa",
    )

    A.assert_field_values(
        X.read_submission(api, world["sb1_id"]),
        arbitrated_share_pct=67,
        receives_credit=True,
    )
    A.assert_field_values(
        X.read_submission(api, world["sb2_id"]),
        arbitrated_share_pct=33,
        receives_credit=True,
    )
