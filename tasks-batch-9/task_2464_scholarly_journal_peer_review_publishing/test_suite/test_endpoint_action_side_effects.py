"""One action call, and every consequence the PRD attaches to it, visible immediately."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client

SWEEP_INSTANT = "2026-08-08T00:00:00Z"
SWEEP_INSTANT_MS = "2026-08-08T00:00:00.000Z"


def _recuse(assignment_id, headers, reason):
    return validate_success(
        api_client.recuse_assignment(
            assignment_id, f.recusal_payload(reason=reason), headers
        )
    )


def _setup_two_editor_world():
    world = fx.setup_active_assignment(handling_editor_count=2)
    world["first_editor"] = world["handlings"][0]["editor"]
    world["second_editor"] = world["handlings"][1]["editor"]
    return world


def _setup_two_open_invitations():
    world = fx.setup_under_review_manuscript()
    invitations = []
    reviewers = []
    for _ in range(2):
        reviewer, _headers = fx.create_reviewer()
        reviewers.append(reviewer)
        invitations.append(
            fx.invite_reviewer(
                world["manuscript"]["id"],
                world["handling_headers"],
                reviewer_id=reviewer["id"],
            )
        )
    world["reviewers"] = reviewers
    world["invitations"] = invitations
    return world


def _setup_accepted_invitation_ready_to_submit():
    world = fx.setup_under_review_manuscript(
        journal_overrides={"min_completed_reviews_for_decision": 1}
    )
    reviewer, reviewer_headers = fx.create_reviewer()
    invitation = fx.invite_reviewer(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=reviewer["id"],
    )
    fx.accept_invitation(invitation["id"], reviewer_headers)
    world["reviewer"] = reviewer
    world["reviewer_headers"] = reviewer_headers
    world["invitation"] = invitation
    return world


def _submit_one_review(world):
    return fx.submit_review(
        world["invitation"]["id"],
        world["reviewer_headers"],
        "ACCEPT",
        novelty_score=4,
        rigor_score=4,
        clarity_score=4,
    )


def test_recusal_releases_the_active_editor():
    """The chief's recusal call closes the assignment and frees the editor's workload.

    PRD: "The assignment moves `ACTIVE → RECUSED` with `released_reason` `RECUSAL`, that editor's `active_assignment_count` falls by 1, and the identical replacement-selection cascade runs — same exclusions, same ranking, same `replaced_assignment_id` link, same `handling_gap_flag` fallback on an empty pool."

    Design: Corner/endpoints/recusal_action_endpoint_releases_editor_and_proposes_replacement
    """
    world = _setup_two_editor_world()
    a.assert_fields(world["assignment"], state="ACTIVE")

    recused = _recuse(
        world["assignment"]["id"],
        world["chief_headers"],
        "Undisclosed collaboration with the corresponding author",
    )

    a.assert_fields(recused, id=world["assignment"]["id"], state="RECUSED", released_reason="RECUSAL")
    assert fx.get_editor(world["first_editor"]["id"])["active_assignment_count"] == 0


def test_recusal_proposes_the_remaining_eligible_editor_as_replacement():
    """The same call creates the successor assignment and links it to the one it supersedes.

    PRD: "The assignment moves `ACTIVE → RECUSED` with `released_reason` `RECUSAL`, that editor's `active_assignment_count` falls by 1, and the identical replacement-selection cascade runs — same exclusions, same ranking, same `replaced_assignment_id` link, same `handling_gap_flag` fallback on an empty pool."

    Design: Corner/endpoints/recusal_action_endpoint_releases_editor_and_proposes_replacement
    """
    world = _setup_two_editor_world()

    _recuse(
        world["assignment"]["id"],
        world["chief_headers"],
        "Undisclosed collaboration with the corresponding author",
    )

    proposed = fx.list_assignments(world["manuscript"]["id"], state="PROPOSED")
    assert len(proposed) == 1, f"Expected one replacement assignment, got {len(proposed)}"
    a.assert_fields(
        proposed[0],
        editor_id=world["second_editor"]["id"],
        state="PROPOSED",
        selected_by="SELECTOR",
        replaced_assignment_id=world["assignment"]["id"],
    )
    assert fx.get_editor(world["second_editor"]["id"])["active_assignment_count"] == 1
    assert fx.get_manuscript(world["manuscript"]["id"])["handling_gap_flag"] is False


def test_licence_change_switches_the_licence_on_a_manuscript_under_review():
    """The author's licensing call rewrites only the licence, mid-review.

    PRD: "The corresponding author may change the manuscript's `oa_license` at any point before the article becomes immutable — that is, while the manuscript's `status` is not `PUBLISHED`, `CORRECTED`, `RETRACTED` or `DESK_REJECTED`."

    Design: Corner/endpoints/licensing_action_endpoint_switches_license_without_touching_status
    """
    world = fx.setup_under_review_manuscript(
        manuscript_overrides={"page_count": 16, "figure_count": 2}
    )
    before = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(before, oa_license="CC_BY", status="UNDER_REVIEW")

    validate_success(
        api_client.change_licensing(
            world["manuscript"]["id"],
            f.licensing_payload("CC_BY_NC_ND"),
            world["author_headers"],
        )
    )

    after = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        after,
        oa_license="CC_BY_NC_ND",
        status="UNDER_REVIEW",
        revision_round=0,
        page_count=16,
        figure_count=2,
        formatting_status="COMPLIANT",
        version=before["version"] + 1,
    )
    assert after.get("embargo_end_date") is None


def test_one_sweep_call_reminds_both_open_invitations():
    """A single sweep of the journal reports two reminders and no expiries.

    PRD: "The sweep reports what it did: `reminded_invitation_count`, `expired_invitation_count`, `probation_reviewer_count` — the number of reviewers this sweep moved from `ACTIVE` to `PROBATION` — and `shortfall_manuscript_ids`, the identifiers of manuscripts whose `review_shortfall_flag` became true during the run."

    Design: Corner/endpoints/reminder_sweep_bulk_action_reminds_two_invitations_in_one_call
    """
    world = _setup_two_open_invitations()
    fx.set_clock(SWEEP_INSTANT)

    report = fx.run_reminder_sweep(world["journal"]["id"])

    a.assert_fields(
        report,
        reminded_invitation_count=2,
        expired_invitation_count=0,
        probation_reviewer_count=0,
        shortfall_manuscript_ids=[],
    )


def test_sweep_stamps_each_reminded_invitation_with_the_current_instant():
    """Both invitations carry one reminder stamped at the swept instant and stay open.

    PRD: "Emitting a reminder raises `reminder_count` by 1 and sets `last_reminder_at` to the current clock instant."

    Design: Corner/endpoints/reminder_sweep_bulk_action_reminds_two_invitations_in_one_call
    """
    world = _setup_two_open_invitations()
    for invitation in world["invitations"]:
        a.assert_fields(invitation, reminder_count=0, state="INVITED")
    fx.set_clock(SWEEP_INSTANT)

    fx.run_reminder_sweep(world["journal"]["id"])

    for invitation in world["invitations"]:
        refreshed = fx.get_invitation(invitation["id"])
        a.assert_fields(
            refreshed,
            reminder_count=1,
            last_reminder_at=SWEEP_INSTANT_MS,
            state="INVITED",
        )
    for reviewer in world["reviewers"]:
        assert fx.get_reviewer(reviewer["id"])["open_invitation_count"] == 1


def test_review_submission_advances_the_manuscript_in_the_same_request():
    """The threshold is reached by this submission, so the manuscript has already moved.

    PRD: "If that count reaches the journal's `min_completed_reviews_for_decision`, the manuscript automatically advances `UNDER_REVIEW → DECISION_PENDING` inside the same request, and its `version` advances by 1."

    Design: Corner/consistency_model/review_submission_shows_decision_pending_in_the_same_response
    """
    world = _setup_accepted_invitation_ready_to_submit()
    before = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(before, status="UNDER_REVIEW", submitted_review_count=0)

    _submit_one_review(world)

    after = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        after,
        status="DECISION_PENDING",
        submitted_review_count=1,
        version=before["version"] + 1,
    )


def test_review_submission_closes_the_invitation_and_updates_the_reviewer():
    """The invitation and the reviewer's counters are settled by the same call.

    PRD: "Submission then closes the invitation and updates the reviewer: the invitation moves `ACCEPTED → SUBMITTED` with `closed_reason` `REVIEW_SUBMITTED`, the reviewer's `submitted_count` rises by 1, their `late_days_total` rises by this review's `days_late`, and their `open_invitation_count` falls by 1."

    Design: Corner/consistency_model/review_submission_shows_decision_pending_in_the_same_response
    """
    world = _setup_accepted_invitation_ready_to_submit()

    review = _submit_one_review(world)

    a.assert_fields(review, days_late=0)
    invitation = fx.get_invitation(world["invitation"]["id"])
    a.assert_fields(invitation, state="SUBMITTED", closed_reason="REVIEW_SUBMITTED")
    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_fields(
        reviewer, submitted_count=1, open_invitation_count=0, late_days_total=0
    )


def test_review_weight_is_frozen_from_the_score_this_submission_produced():
    """Both reliability variants are already rewritten when the weight is taken.

    PRD: "The ordering of the next two steps is contractual: **both reliability variants are recomputed first**, and only then is this review's `reliability_weight` frozen from the freshly-written `reliability_score_rolling`."

    Design: Corner/consistency_model/review_submission_shows_decision_pending_in_the_same_response
    """
    world = _setup_accepted_invitation_ready_to_submit()

    review = _submit_one_review(world)

    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_score_equals(
        reviewer["reliability_score_rolling"], 100.00, "reliability_score_rolling"
    )
    a.assert_score_equals(
        reviewer["reliability_score_lifetime"], 100.00, "reliability_score_lifetime"
    )
    a.assert_weight_equals(review["reliability_weight"], 1.0)


def test_sweep_report_is_scoped_to_the_named_journal():
    """An invitation on another journal is untouched by this journal's sweep.

    PRD: "The sweep considers only invitations in state `INVITED` whose manuscript belongs to the swept journal, and processes them in `created_at` ascending order."

    Design: Corner/endpoints/reminder_sweep_bulk_action_reminds_two_invitations_in_one_call
    """
    world = _setup_two_open_invitations()
    other = fx.setup_under_review_manuscript()
    other_reviewer, _headers = fx.create_reviewer()
    other_invitation = fx.invite_reviewer(
        other["manuscript"]["id"],
        other["handling_headers"],
        reviewer_id=other_reviewer["id"],
    )
    fx.set_clock(SWEEP_INSTANT)

    report = validate_success(
        api_client.run_reminder_sweep(
            f.reminder_sweep_payload(world["journal"]["id"]), SYSTEM_ADMIN_HEADERS
        )
    )

    a.assert_fields(report, reminded_invitation_count=2, expired_invitation_count=0)
    untouched = fx.get_invitation(other_invitation["id"])
    a.assert_fields(untouched, reminder_count=0, state="INVITED")
    assert untouched.get("last_reminder_at") is None
