"""The reviewer-invitation lifecycle: birth at `INVITED`, selector choice, and death by sweep."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_EPOCH_MS

DEFAULT_DUE_AT = "2026-08-22T00:00:00.000Z"
SHORT_DUE_AT = "2026-08-06T00:00:00.000Z"
SHORT_DUE_DAYS = 5


def _setup_overdue_invitation():
    """One `INVITED` invitation whose deadline the clock has just reached.

    The journal's reminder cadence is short enough that a reminder is also due at
    that instant, so the sweep has to choose between the two actions.
    """
    world = fx.setup_under_review_manuscript(
        journal_overrides={
            "reminder_cadence_days": 3,
            "max_reminders_per_invitation": 2,
        }
    )
    reviewer, reviewer_headers = fx.create_reviewer()
    world["reviewer"] = reviewer
    world["reviewer_headers"] = reviewer_headers
    world["invitation"] = fx.invite_reviewer(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=reviewer["id"],
        due_days=SHORT_DUE_DAYS,
    )
    assert world["invitation"]["invited_at"] == CLOCK_EPOCH_MS
    assert world["invitation"]["due_at"] == SHORT_DUE_AT
    fx.set_clock("2026-08-06T00:00:00Z")
    return world


def _setup_two_tied_reviewers():
    """An `UNDER_REVIEW` manuscript and two freshly seeded reviewers, created in order."""
    world = fx.setup_under_review_manuscript()
    first, _first_headers = fx.create_reviewer()
    second, _second_headers = fx.create_reviewer()
    a.assert_score_equals(
        first["reliability_score_rolling"], 50.00, "reliability_score_rolling"
    )
    a.assert_score_equals(
        second["reliability_score_rolling"], 50.00, "reliability_score_rolling"
    )
    world["first_reviewer"] = first
    world["second_reviewer"] = second
    return world


def test_invitation_is_born_invited_with_the_journal_default_deadline():
    """No `due_days` override, so the deadline is the clock plus the journal's target days.

    PRD: "The created invitation is stamped with `round` equal to the manuscript's `revision_round`, `invited_at` equal to the current logical clock, and `due_at` equal to `invited_at` plus a number of days taken from `due_days` when supplied and from the journal's `review_target_days` otherwise."

    Design: Corner/state_machines/review_invitation_created_in_invited_state_with_target_due_date
    """
    world = fx.setup_under_review_manuscript()
    reviewer, _headers = fx.create_reviewer()

    invitation = fx.invite_reviewer(
        world["manuscript"]["id"], world["handling_headers"], reviewer_id=reviewer["id"]
    )

    a.assert_fields(
        invitation,
        state="INVITED",
        round=0,
        selected_by="EXPLICIT",
        reminder_count=0,
        invited_at=CLOCK_EPOCH_MS,
        due_at=DEFAULT_DUE_AT,
    )
    assert invitation.get("last_reminder_at") is None
    assert invitation.get("responded_at") is None
    assert invitation.get("closed_reason") is None


def test_invitation_creation_raises_the_open_load_at_the_neutral_seed():
    """The invitation counts twice on the reviewer, and closes nothing, so the score holds.

    PRD: "Creating the invitation raises that reviewer's `invited_count` by 1 and their `open_invitation_count` by 1, and re-runs both reliability variants for that reviewer."

    Design: Corner/state_machines/review_invitation_created_in_invited_state_with_target_due_date
    """
    world = fx.setup_under_review_manuscript()
    reviewer, _headers = fx.create_reviewer()

    fx.invite_reviewer(
        world["manuscript"]["id"], world["handling_headers"], reviewer_id=reviewer["id"]
    )

    invited = fx.get_reviewer(reviewer["id"])
    a.assert_fields(
        invited, invited_count=1, open_invitation_count=1, status="ACTIVE"
    )
    a.assert_score_equals(
        invited["reliability_score_rolling"], 50.00, "reliability_score_rolling"
    )
    a.assert_score_equals(
        invited["reliability_score_lifetime"], 50.00, "reliability_score_lifetime"
    )


def test_sweep_expires_the_overdue_invitation_and_reports_the_shortfall():
    """The deadline instant itself expires, and the round loses its last prospect.

    PRD: "That flag is true exactly when the manuscript's current round holds fewer submitted reviews than the journal's `min_completed_reviews_for_decision` **and** no invitation on the manuscript remains in `INVITED` or `ACCEPTED` — in other words, when there is no longer any prospect of the round completing itself."

    Design: Corner/state_machines/reminder_sweep_expires_overdue_invitation_and_syncs_reviewer_counters
    """
    world = _setup_overdue_invitation()

    report = fx.run_reminder_sweep(world["journal"]["id"])

    a.assert_fields(report, expired_invitation_count=1, probation_reviewer_count=0)
    assert report["shortfall_manuscript_ids"] == [world["manuscript"]["id"]]
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="UNDER_REVIEW",
        review_shortfall_flag=True,
        submitted_review_count=0,
    )


def test_sweep_expiry_takes_precedence_over_the_due_reminder():
    """Both actions are due at this instant; the invitation receives exactly one of them.

    PRD: "Each such invitation receives **exactly one** action, with expiry taking precedence over reminding."

    Design: Corner/state_machines/reminder_sweep_expires_overdue_invitation_and_syncs_reviewer_counters
    """
    world = _setup_overdue_invitation()

    report = fx.run_reminder_sweep(world["journal"]["id"])

    a.assert_fields(report, reminded_invitation_count=0, expired_invitation_count=1)
    invitation = fx.get_invitation(world["invitation"]["id"])
    a.assert_fields(
        invitation, state="EXPIRED", closed_reason="SWEEP_EXPIRY", reminder_count=0
    )
    assert invitation.get("last_reminder_at") is None


def test_expiry_zeroes_both_reliability_variants_without_probation():
    """One lapsed invitation is a delivery rate of 0 and a responsiveness rate of 0.

    PRD: "The raw score is 100 multiplied by the sum of three weighted rates — the delivery rate weighted 0.45, the on-time rate weighted 0.35 and the responsiveness rate weighted 0.20 — with the lateness penalty subtracted."

    Design: Corner/state_machines/reminder_sweep_expires_overdue_invitation_and_syncs_reviewer_counters
    """
    world = _setup_overdue_invitation()

    fx.run_reminder_sweep(world["journal"]["id"])

    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_fields(
        reviewer,
        expired_count=1,
        open_invitation_count=0,
        invited_count=1,
        status="ACTIVE",
    )
    a.assert_score_equals(
        reviewer["reliability_score_rolling"], 0.00, "reliability_score_rolling"
    )
    a.assert_score_equals(
        reviewer["reliability_score_lifetime"], 0.00, "reliability_score_lifetime"
    )


def test_selector_breaks_the_reliability_tie_on_the_earlier_created_reviewer():
    """Two reviewers on the same seed and the same open load, so `created_at` decides.

    PRD: "Candidates are ranked by `reliability_score_rolling` descending, compared at its stored two-decimal precision, then by `open_invitation_count` ascending, then by `created_at` ascending; the first row after sorting wins."

    Design: Corner/cross_cutting_complexity_layers/reviewer_selector_tie_break_then_exclusion_on_the_second_invitation
    """
    world = _setup_two_tied_reviewers()

    invitation = fx.invite_reviewer(
        world["manuscript"]["id"], world["handling_headers"]
    )

    a.assert_fields(
        invitation,
        reviewer_id=world["first_reviewer"]["id"],
        selected_by="SELECTOR",
        state="INVITED",
        round=0,
    )
    assert fx.get_reviewer(world["first_reviewer"]["id"])["open_invitation_count"] == 1
    assert fx.get_reviewer(world["second_reviewer"]["id"])["invited_count"] == 0


def test_second_selector_invitation_excludes_the_reviewer_it_just_invited():
    """The winner of the first draw is out of the pool for the second, so the runner-up wins.

    PRD: "The eligible pool is every reviewer whose `status` is `ACTIVE`; whose `subject_areas` contain the manuscript's `subject_area`; whose `email` differs from the corresponding author's `email`; whose `email` does not appear among the manuscript's `coauthor_emails`; whose `affiliation` differs from the corresponding author's `affiliation`; whose `email` differs from the `email` of the editor holding the manuscript's `ACTIVE` assignment; who holds no existing invitation on this manuscript in state `INVITED`, `ACCEPTED` or `SUBMITTED`; and whose overlapping open windows number fewer than the journal's `reviewer_concurrent_window_limit`."

    Design: Corner/cross_cutting_complexity_layers/reviewer_selector_tie_break_then_exclusion_on_the_second_invitation
    """
    world = _setup_two_tied_reviewers()
    manuscript_id = world["manuscript"]["id"]
    fx.invite_reviewer(manuscript_id, world["handling_headers"])

    second_invitation = fx.invite_reviewer(manuscript_id, world["handling_headers"])

    a.assert_fields(
        second_invitation,
        reviewer_id=world["second_reviewer"]["id"],
        selected_by="SELECTOR",
        round=0,
    )
    for reviewer in (world["first_reviewer"], world["second_reviewer"]):
        a.assert_fields(
            fx.get_reviewer(reviewer["id"]),
            invited_count=1,
            open_invitation_count=1,
        )
    assert fx.get_manuscript(manuscript_id)["submitted_review_count"] == 0
