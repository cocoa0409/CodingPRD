"""Transitive cascades: the rejection chain and the appeal-overturn chain."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_EPOCH_MS


def test_reject_decision_withdraws_every_still_open_invitation():
    """The rejection closes the live invitation and leaves the already-closed ones alone.

    PRD: "Second, every invitation on the manuscript still in `INVITED` or `ACCEPTED` moves to `WITHDRAWN` with `closed_reason` `DECISION_CASCADE`."

    Design: Difficulty/transitive_cascade/reject_decision_cascade_withdraws_invitation_and_probates_reviewer
    """
    world = fx.setup_reject_cascade_world()

    decision = fx.issue_decision(
        world["manuscript"]["id"],
        world["handling_headers"],
        editorial_note="Rejected on unanimous reviewer recommendation",
    )

    a.assert_fields(decision, auto_category="REJECT", category_source="AUTO")
    a.assert_score_equals(decision["consensus_index"], 1.00, "consensus_index")
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "REJECTED"

    cascaded = fx.get_invitation(world["open_invitation"]["id"])
    a.assert_fields(cascaded, state="WITHDRAWN", closed_reason="DECISION_CASCADE")
    for review in world["rejecting_reviews"]:
        assert fx.get_invitation(review["invitation_id"])["state"] == "SUBMITTED"


def test_cascade_lowers_the_open_load_and_demotes_the_reviewer():
    """The third closed invitation is what tips the reviewer over the evidence bar.

    PRD: "Fourth, caused by that third link, any reviewer whose recomputed `reliability_score_rolling` is below 40.00 while holding at least 3 closed invitations in the rolling window moves `ACTIVE → PROBATION`."

    Design: Difficulty/transitive_cascade/reject_decision_cascade_withdraws_invitation_and_probates_reviewer
    """
    world = fx.setup_reject_cascade_world()
    assert world["cascaded_reviewer_before"]["status"] == "ACTIVE"
    assert world["cascaded_reviewer_before"]["open_invitation_count"] == 1

    fx.issue_decision(
        world["manuscript"]["id"],
        world["handling_headers"],
        editorial_note="Rejected on unanimous reviewer recommendation",
    )

    reviewer = fx.get_reviewer(world["cascaded_reviewer"]["id"])
    a.assert_fields(
        reviewer,
        open_invitation_count=0,
        invited_count=3,
        declined_count=2,
        status="PROBATION",
    )
    a.assert_score_equals(
        reviewer["reliability_score_rolling"], 20.00, "reliability_score_rolling"
    )
    a.assert_score_equals(
        reviewer["reliability_score_lifetime"], 20.00, "reliability_score_lifetime"
    )


def test_reject_decision_releases_the_handling_assignment():
    """The same request that rejects the paper frees the editor.

    PRD: "Alongside those, the `ACTIVE` assignment moves to `RELEASED` with `released_reason` `DECISION_FINAL`, lowering that editor's `active_assignment_count` by 1, and the manuscript's `version` advances by 1."

    Design: Difficulty/transitive_cascade/reject_decision_cascade_withdraws_invitation_and_probates_reviewer
    """
    world = fx.setup_reject_cascade_world()

    fx.issue_decision(
        world["manuscript"]["id"],
        world["handling_headers"],
        editorial_note="Rejected on unanimous reviewer recommendation",
    )

    assignment = fx.get_assignment(world["assignment"]["id"])
    a.assert_fields(assignment, state="RELEASED", released_reason="DECISION_FINAL")
    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 0


def test_overturned_appeal_returns_the_manuscript_to_review():
    """The first two links of the chain: the appeal closes and the manuscript reopens.

    PRD: "The second, caused by it, moves the manuscript `UNDER_APPEAL → UNDER_REVIEW` and recomputes its `review_shortfall_flag`."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_reassigns_to_untainted_editor
    """
    world = fx.setup_appeal_filed(handling_editor_count=2)

    appeal = fx.adjudicate_appeal(
        world["appeal"]["id"],
        world["chief_headers"],
        "OVERTURNED",
        rationale="Statistical critique was unfounded; returning to review",
    )

    a.assert_fields(
        appeal,
        state="OVERTURNED",
        adjudicated_by_editor_id=world["chief"]["id"],
        adjudicated_at=CLOCK_EPOCH_MS,
    )
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, status="UNDER_REVIEW", handling_gap_flag=False)


def test_overturn_cascade_selects_an_editor_other_than_the_one_who_decided():
    """The third link re-runs the selector with the deciding editor removed from the pool.

    PRD: "When the selector is invoked from the appeal-overturn cascade, one further exclusion applies: the editor who issued the appealed decision is removed from the pool."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_reassigns_to_untainted_editor
    """
    world = fx.setup_appeal_filed(handling_editor_count=2)
    decider = world["handlings"][0]["editor"]
    replacement = world["handlings"][1]["editor"]

    fx.adjudicate_appeal(
        world["appeal"]["id"],
        world["chief_headers"],
        "OVERTURNED",
        rationale="Statistical critique was unfounded; returning to review",
    )

    proposed = fx.list_assignments(world["manuscript"]["id"], state="PROPOSED")
    assert len(proposed) == 1, f"Expected exactly one fresh assignment, got {proposed}"
    a.assert_fields(
        proposed[0],
        editor_id=replacement["id"],
        state="PROPOSED",
        selected_by="SELECTOR",
    )
    assert proposed[0]["editor_id"] != decider["id"]


def test_overturn_cascade_raises_only_the_replacement_editors_open_load():
    """The fourth link touches the new editor's counter and nobody else's.

    PRD: "The fourth, caused by the third and only when an assignment was actually created, raises that editor's `active_assignment_count` by 1."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_reassigns_to_untainted_editor
    """
    world = fx.setup_appeal_filed(handling_editor_count=2)
    decider = world["handlings"][0]["editor"]
    replacement = world["handlings"][1]["editor"]

    fx.adjudicate_appeal(
        world["appeal"]["id"],
        world["chief_headers"],
        "OVERTURNED",
        rationale="Statistical critique was unfounded; returning to review",
    )

    assert fx.get_editor(replacement["id"])["active_assignment_count"] == 1
    assert fx.get_editor(decider["id"])["active_assignment_count"] == 0
    assert fx.get_assignment(world["assignment"]["id"])["state"] == "RELEASED"
