"""State machines that are neither linear nor single-dimensional.

An application tracks paper review and interview progress on two independent
dimensions of the same row, and a rank list can leave committee review by a fork
that loops back through drafting for a second round of ballots.
"""

from __future__ import annotations

from test_helpers import (
    Ballot,
    CLOCK_AFTER_INTERVIEW,
    CLOCK_RANKING_DAY,
    CLOCK_WAVE_RELEASE,
    DIRECTOR_NAME,
    InterviewStatus,
    LEAD_INTERVIEWER_NAME,
    MEMBER_INTERVIEWER_NAME,
    RankListStatus,
    ScreeningStatus,
    SeasonBuilder,
    assert_score_equals,
    build_committee_vote_payload,
    get_success_data,
    setup_staffed_program,
    validate_paginated,
    validate_success,
)

#: The unequal paper reviews that put the final screen score at 34.75.
FIRST_REVIEW = (30, 20, 20)
SECOND_REVIEW = (34, 24, 18)
EXPECTED_FINAL_SCORE = 34.75


def _advanced_application_in_released_wave():
    """An advanced application and a released wave, with no panel staffed."""
    builder = setup_staffed_program()
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1", ("f1", "f2"), (FIRST_REVIEW, SECOND_REVIEW))
    builder.screen("app1")
    builder.open_interviews()
    builder.create_wave(seat_capacity=4)
    builder.create_slot(applicant_capacity=4)
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    return builder


def _list_in_committee_with_two_member_electorate():
    """A list under committee review whose electorate is two faculty members."""
    builder = SeasonBuilder()
    builder.create_program()
    builder.add_faculty(
        "pd", DIRECTOR_NAME, is_program_director=True, is_committee_member=False
    )
    builder.add_faculty("f1", LEAD_INTERVIEWER_NAME, is_committee_member=True)
    builder.add_faculty("f2", MEMBER_INTERVIEWER_NAME, is_committee_member=True)
    builder.add_applicant("cand1")
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1", ("f1", "f2"))
    builder.screen("app1")
    builder.open_interviews()
    builder.create_wave(seat_capacity=4)
    builder.create_slot(applicant_capacity=4)
    builder.staff_standard_panel()
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    builder.issue_invitation("inv1", "app1")
    builder.accept_invitation("inv1", "slot1", "cand1")
    builder.clock(CLOCK_AFTER_INTERVIEW)
    builder.complete_slot("slot1")
    builder.add_standard_score_cards("app1", "1")
    builder.clock(CLOCK_RANKING_DAY)
    builder.close_wave()
    builder.open_ranking()
    builder.create_rank_list()
    builder.add_entry("entry1", "app1", 1)
    builder.submit_to_committee()
    return builder


def test_an_invitation_moves_the_interview_dimension_and_leaves_the_paper_one(api):
    """Issuing an invitation writes one dimension of the row and not the other.

    The paper dimension stays where screening left it, and the score screening
    wrote stays put too.

    PRD 3.1: "Those two enumerations are **independent state dimensions on the same row**: they share no state names, and no movement on one dimension writes the other except where a side effect explicitly says so."
    PRD 3.4: "Creating an issued invitation carries four further effects: `InterviewWave.issued_count` increments by one, the invited application advances `NOT_INVITED → INVITED` on its interview dimension (which requires the application's `screening_status` to be `ADVANCED` — an unadvanced application cannot be invited at all), `Program.invited_count` is recomputed, and the wave's `version` increments by one."

    Design: Difficulty/non_linear_state_machine/application_parallel_screening_and_interview_dimensions
    """
    builder = _advanced_application_in_released_wave()

    builder.issue_invitation("inv1", "app1")

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.INVITED, (
        "the interview dimension should have advanced to INVITED, got "
        f"{application['interview_status']}"
    )
    assert application["screening_status"] == ScreeningStatus.ADVANCED, (
        "the paper dimension must stay ADVANCED, got "
        f"{application['screening_status']}"
    )
    assert_score_equals(
        application["final_screen_score"],
        EXPECTED_FINAL_SCORE,
        "Application.final_screen_score",
    )


def test_booking_a_seat_advances_only_the_interview_dimension(api):
    """The accept walks the interview dimension a second step on its own.

    Both dimensions are read from the same row after the accept, and only the
    interview one has moved.

    PRD 3.1: "`interview_status` tracks interview progress and takes one of `NOT_INVITED`, `INVITED`, `SCHEDULED`, `COMPLETED`, `NO_SHOW` or `CANCELLED`, of which `COMPLETED`, `NO_SHOW` and `CANCELLED` are terminal; it evolves freely once `screening_status` has reached `ADVANCED`."
    PRD 3.4: "Acceptance stores the chosen `slot_id` and stamps `responded_at` with the current logical clock instant, increments the slot's `booked_count` by one, moves the slot `OPEN → BOOKED` when `booked_count` reaches `applicant_capacity`, and advances the application `INVITED → SCHEDULED` on its interview dimension — which itself requires that the accepted invitation's `slot_id` is no longer null."

    Design: Difficulty/non_linear_state_machine/application_parallel_screening_and_interview_dimensions
    """
    builder = _advanced_application_in_released_wave()
    builder.issue_invitation("inv1", "app1")

    builder.accept_invitation("inv1", "slot1", "cand1")

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.SCHEDULED, (
        "booking a seat should advance the interview dimension to SCHEDULED, got "
        f"{application['interview_status']}"
    )
    assert application["screening_status"] == ScreeningStatus.ADVANCED
    assert_score_equals(
        application["final_screen_score"],
        EXPECTED_FINAL_SCORE,
        "Application.final_screen_score",
    )

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["invited_count"] == 1, (
        "one application is off NOT_INVITED, so invited_count should be 1, got "
        f"{program['invited_count']}"
    )


def test_the_return_fork_needs_the_whole_two_member_threshold(api):
    """One return ballot of a two-member electorate leaves the list in committee.

    Sixty percent of two rounds up to two, so a single ballot cannot resolve the
    round either way.

    PRD 3.7: "The quorum threshold is that electorate size multiplied by 0.60 — sixty percent — and then **rounded up to the next whole number** by the ceiling function; an electorate of four therefore needs three, and an electorate of five also needs three."
    PRD 3.7: "**The approve branch is evaluated first, and both comparisons are inclusive:** when the approve count is at or above the threshold the list advances `COMMITTEE_REVIEW → APPROVED`; otherwise, when the return count is at or above the threshold the list advances `COMMITTEE_REVIEW → RETURNED`; otherwise the list stays in `COMMITTEE_REVIEW` and the ballot is simply recorded."

    Design: Difficulty/non_linear_state_machine/rank_list_committee_fork_with_returned_revision_cycle
    """
    builder = _list_in_committee_with_two_member_electorate()

    api.create_committee_vote(
        builder.id("rank_list"),
        build_committee_vote_payload(
            builder.id("f1"), Ballot.RETURN, comment="reorder the top three"
        ),
        builder.committee("f1"),
    )

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert rank_list["status"] == RankListStatus.COMMITTEE_REVIEW, (
        "one of two required ballots must not resolve the round, got "
        f"{rank_list['status']}"
    )
    assert rank_list["review_round"] == 1


def test_the_return_branch_returns_the_list_without_stamping_an_approval(api):
    """The second return ballot forks the list to RETURNED and writes no timestamp.

    The approve branch is checked first and finds no approvals, so the return
    branch fires — and that branch is the one with no approval timestamp.

    PRD 3.7: "The approve branch stamps `RankList.approved_at` with the current logical clock instant and increments `RankList.version` by one."
    PRD 3.7: "The return branch **leaves `RankList.approved_at` null** — that branch writes no approval timestamp at all — and increments `RankList.version` by one."

    Design: Difficulty/non_linear_state_machine/rank_list_committee_fork_with_returned_revision_cycle
    """
    builder = _list_in_committee_with_two_member_electorate()
    builder.cast_vote("f1", Ballot.RETURN)

    api.create_committee_vote(
        builder.id("rank_list"),
        build_committee_vote_payload(builder.id("f2"), Ballot.RETURN, comment="agree"),
        builder.committee("f2"),
    )

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert rank_list["status"] == RankListStatus.RETURNED, (
        "two return ballots of a two-member electorate should return the list, got "
        f"{rank_list['status']}"
    )
    assert rank_list["approved_at"] is None, (
        "the return branch writes no approval timestamp, got "
        f"{rank_list['approved_at']}"
    )


def test_resubmitting_a_revised_list_opens_a_round_that_ignores_the_old_ballots(api):
    """The returned list is revived, resubmitted, and starts round two empty.

    The two round-one ballots survive as history, but the reopened round carries
    no effective tally at all and the list is still unapproved.

    PRD 3.7: "Because `review_round` increments again on the next trip to committee, and because only current-round ballots count, the revision cycle `DRAFT → COMMITTEE_REVIEW → RETURNED → DRAFT` may repeat indefinitely."
    PRD 3.7: "The effective tally counts only `CommitteeVote` rows for this list whose `review_round` equals the list's **current** `review_round`; ballots from an earlier round survive as history but are excluded, so a list that was returned and reopened starts its next round with an empty effective tally."

    Design: Difficulty/non_linear_state_machine/rank_list_committee_fork_with_returned_revision_cycle
    """
    builder = _list_in_committee_with_two_member_electorate()
    builder.cast_vote("f1", Ballot.RETURN)
    builder.cast_vote("f2", Ballot.RETURN)

    revised = validate_success(
        api.revise_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert revised["status"] == RankListStatus.DRAFT, (
        "a returned list is revived into DRAFT, got " f"{revised['status']}"
    )

    resubmitted = validate_success(
        api.submit_rank_list_to_committee(builder.id("rank_list"), builder.director("pd"))
    )
    assert resubmitted["status"] == RankListStatus.COMMITTEE_REVIEW
    assert resubmitted["review_round"] == 2, (
        "the second trip to committee is round two, got "
        f"{resubmitted['review_round']}"
    )
    assert resubmitted["approved_at"] is None

    rows, meta = validate_paginated(
        api.list_votes_of_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert meta["total_count"] == 2, (
        f"both round-one ballots should survive as history, got {meta['total_count']}"
    )
    assert all(row["review_round"] == 1 for row in rows), (
        "the surviving ballots belong to round one, got "
        f"{[row['review_round'] for row in rows]}"
    )
