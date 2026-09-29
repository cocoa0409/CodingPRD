"""Declared lifecycle transitions of the residency match season.

Each test walks exactly one declared edge — an initial state, an undeclared hop,
a terminal-state replay, a transition precondition, a cascade or a revision
cycle — and checks the outcome the PRD states for it.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_credential_counters,
    assert_one_decimal,
    assert_position_conservation,
    assert_rank_list,
    assert_score_equals,
    expected_committee_score,
    expected_domain_average,
)
from test_helpers.constants import CLOCK_RANKING_DAY
from test_helpers.factories import (
    build_advance_phase_payload,
    build_certify_payload,
    build_credential_submit_payload,
    build_rank_list_payload,
    build_reason_payload,
    build_revise_score_card_payload,
    build_withdraw_payload,
)
from test_helpers.fixtures import (
    SCORES_MEMBER,
    setup_approved_rank_list,
    setup_issued_contract,
    setup_issued_invitations,
    setup_planned_wave,
    setup_program,
    setup_ranking_phase,
    setup_scored_application,
    setup_staffed_program,
)
from test_helpers.types import (
    AssignmentStatus,
    ContractStatus,
    CredentialItemStatus,
    CredentialType,
    InterviewStatus,
    InvitationStatus,
    RankListStatus,
    ScoreCardStatus,
    ScreeningStatus,
    SeasonPhase,
    SlotStatus,
    WaveStatus,
)


def _instant(value: str) -> datetime:
    """Parse one of the ISO 8601 UTC instants every datetime field carries."""
    assert value is not None, "expected an ISO 8601 UTC instant, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ======================================================================
# Initial states and undeclared hops
# ======================================================================
def test_new_rank_list_starts_in_draft_with_no_entries_and_round_zero(api):
    """Opening a rank list yields DRAFT, entry_count 0 and review_round 0.

    The round counter is first incremented by the trip to committee, so an
    implementation that seeds review_round at 1 has silently consumed the
    program's first deliberation round before any ballot was cast.

    PRD 3.7: "A `ProgramDirector` opens it by naming the `program_id`, and it materialises with `status` `DRAFT`, `entry_count` at 0, `review_round` at 0, `approved_at` null and `certified_by_faculty_id` null."
    PRD 3.7: "`review_round` is by definition the number of times the list has entered committee review, which is why it starts at 0 and is 1 during the first deliberation."

    Design: Corner/state_machines/rank_list_create_starts_in_draft_with_no_entries_and_round_zero
    """
    builder = setup_ranking_phase()

    response = api.create_rank_list(
        build_rank_list_payload(builder.id("program")), builder.director("pd")
    )

    data = validate_success(response, 201)
    assert_rank_list(data)
    assert (
        data["status"] == RankListStatus.DRAFT
    ), f"a freshly opened rank list must be DRAFT, got {data['status']}"
    assert (
        data["entry_count"] == 0
    ), f"a freshly opened rank list holds no entries, got entry_count {data['entry_count']}"
    assert (
        data["review_round"] == 0
    ), f"review_round starts at 0, got {data['review_round']}"
    assert (
        data["approved_at"] is None
    ), f"approved_at must be null before approval, got {data['approved_at']!r}"
    assert data["certified_by_faculty_id"] is None, (
        "certified_by_faculty_id must be null before certification, got "
        f"{data['certified_by_faculty_id']!r}"
    )


def test_pre_season_cannot_advance_straight_to_ranking(api):
    """PRE_SEASON has one outgoing edge, so naming RANKING is an invalid state.

    RANKING is reachable later in the same season, so an implementation that
    validates only that the target is a member of the phase vocabulary — rather
    than that the specific hop is declared — wrongly accepts this request.

    PRD 3.1: "A coordinator moves the program `PRE_SEASON → REVIEW_OPEN` only when at least one `FacultyMember` exists for that `program_id`; the only side effect is that the program's `version` increments by one."
    PRD 3.1: "Any requested hop that is not one of the declared edges, or whose gate is unmet, is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/program_advance_phase_from_pre_season_straight_to_ranking_returns_invalid_state
    """
    builder = setup_program()

    response = api.advance_program_phase(
        builder.id("program"),
        build_advance_phase_payload(SeasonPhase.RANKING),
        builder.coordinator,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["season_phase"] == SeasonPhase.PRE_SEASON, (
        "a refused phase hop must leave the program in PRE_SEASON, got "
        f"{program['season_phase']}"
    )


# ======================================================================
# Terminal-state lockdown and replayed transitions
# ======================================================================
def test_second_withdrawal_of_a_withdrawn_application_is_refused(api):
    """A withdrawn application cannot be withdrawn again, and keeps its first reason.

    WITHDRAWN is terminal on the paper dimension, so the replay is a refusal
    rather than an idempotent second success that overwrites withdrawn_reason.

    PRD 3.1: "`screening_status` tracks paper review only, taking one of `RECEIVED`, `UNDER_REVIEW`, `ADVANCED`, `REJECTED` or `WITHDRAWN`, of which `REJECTED` and `WITHDRAWN` are terminal."
    PRD 2.12: "This covers both a wrong current state and an already-terminal resource."

    Design: Corner/state_machines/withdrawing_an_already_withdrawn_application_is_blocked_by_terminal_lockdown
    """
    builder = setup_staffed_program(1)
    builder.open_review()
    builder.add_application("app1", "cand1")
    application_id = builder.id("app1")

    validate_success(
        api.withdraw_application(
            application_id,
            build_withdraw_payload("Accepted a position elsewhere"),
            builder.applicant("cand1"),
        ),
        200,
    )

    response = api.withdraw_application(
        application_id,
        build_withdraw_payload("Changed my mind again"),
        builder.applicant("cand1"),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    application = get_success_data(
        api.get_application(application_id, builder.coordinator)
    )
    assert application["screening_status"] == ScreeningStatus.WITHDRAWN, (
        "the application must stay WITHDRAWN after the refused replay, got "
        f"{application['screening_status']}"
    )
    assert (
        application["withdrawn_reason"] == "Accepted a position elsewhere"
    ), f"the first withdrawn_reason must survive, got {application['withdrawn_reason']!r}"


def test_second_cancellation_of_a_cancelled_slot_is_refused(api):
    """Replaying a slot cancellation is an error, and re-runs none of its effects.

    CANCELLED is terminal for a block, so a server that treats the replay as
    idempotently successful would also re-run the assignment release and the
    load recomputation the first cancellation already performed.

    PRD 3.5: "Both `COMPLETED` and `CANCELLED` are terminal for a block."
    PRD 3.5: "Cancelling an `OPEN` block releases every `InterviewAssignment` on it to `RELEASED` and recomputes `scheduled_load` for every affected faculty member."

    Design: Corner/state_machines/cancelling_an_already_cancelled_slot_is_not_idempotently_successful
    """
    builder = setup_planned_wave()
    slot_id = builder.id("slot1")

    validate_success(api.cancel_interview_slot(slot_id, builder.coordinator), 200)

    response = api.cancel_interview_slot(slot_id, builder.coordinator)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    slot = get_success_data(api.get_interview_slot(slot_id, builder.coordinator))
    assert (
        slot["status"] == SlotStatus.CANCELLED
    ), f"the block must stay CANCELLED after the refused replay, got {slot['status']}"

    assignment = get_success_data(
        api.get_interview_assignment(builder.id("asg1"), builder.coordinator)
    )
    assert assignment["status"] == AssignmentStatus.RELEASED, (
        "the panel seat released by the first cancellation must stay RELEASED, got "
        f"{assignment['status']}"
    )
    faculty = get_success_data(
        api.get_faculty_member(builder.id("f1"), builder.coordinator)
    )
    assert_score_equals(
        faculty["scheduled_load"], 0.0, "FacultyMember.scheduled_load"
    )


# ======================================================================
# Transition preconditions
# ======================================================================
def test_releasing_a_wave_before_its_release_instant_is_refused(api):
    """A wave may not be released while the logical clock is short of invite_release_at.

    The program phase gate is satisfied here, so only the clock precondition can
    reject the call; an implementation that checks the phase alone releases early.

    PRD 3.3: "Releasing a wave drives `PLANNED → RELEASED` and requires two things: the owning program must be in `INTERVIEWS_OPEN`, and the logical clock must have reached the wave's `invite_release_at` or passed it."
    PRD 2.7: "No comparison in this API reads the host wall clock."

    Design: Corner/state_machines/releasing_a_wave_before_its_invite_release_at_instant_is_rejected
    """
    builder = setup_planned_wave()
    wave_id = builder.id("wave1")

    response = api.release_interview_wave(wave_id, builder.coordinator)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    wave = get_success_data(api.get_interview_wave(wave_id, builder.coordinator))
    assert (
        wave["status"] == WaveStatus.PLANNED
    ), f"the wave must stay PLANNED after the refused release, got {wave['status']}"
    assert (
        wave["issued_count"] == 0
    ), f"a refused release issues no seats, got issued_count {wave['issued_count']}"


def test_running_the_match_before_certification_is_refused(api):
    """Match day is gated on the program's phase, not on the committee's approval.

    With the list APPROVED but uncertified the program is still in RANKING, so
    run-match must refuse and publish no MatchResult row at all.

    PRD 3.8: "Match day is run by the national operator against a certified program, and it drives the program `LIST_CERTIFIED → MATCH_COMPLETE`."
    PRD 3.8: "Two conditions gate it: `Program.rank_list_certified_at` is not null, and no `MatchResult` row exists yet for that program — the match runs exactly once."
    PRD 2.4: "When the governing `Program` is in a phase that does not permit the operation being requested, the refusal is `ERR_INVALID_STATE` (HTTP 409) — the same code used when a resource's own state field does not admit the requested transition."

    Design: Corner/state_machines/running_the_match_before_the_list_is_certified_returns_invalid_state
    """
    builder = setup_approved_rank_list()
    program_id = builder.id("program")

    response = api.run_match(program_id, builder.admin)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    program = get_success_data(api.get_program(program_id, builder.admin))
    assert (
        program["season_phase"] == SeasonPhase.RANKING
    ), f"a refused match day must leave the program in RANKING, got {program['season_phase']}"
    assert_position_conservation(program, 0, program["quota_positions"])

    rows, meta = validate_paginated(
        api.list_match_results(builder.admin, params={"program_id": program_id})
    )
    assert (
        meta["total_count"] == 0
    ), f"a refused match day publishes no results, got total_count {meta['total_count']}"
    assert rows == [], f"a refused match day publishes no results, got {rows}"


# ======================================================================
# Cascades fired by one transition
# ======================================================================
def test_closing_a_wave_expires_issued_and_waitlisted_invitations_together(api):
    """Closing a wave expires the ISSUED and the WAITLISTED invitation in one hop.

    A close that swept only the issued half would leave a live waitlist place
    inside a CLOSED wave, and would leave Program.invited_count overstated.

    PRD 3.4: "Closing a wave is therefore the wholesale application of both: it drives the wave `RELEASED → CLOSED`, sets every invitation in the wave whose `status` is `ISSUED` or `WAITLISTED` to `EXPIRED`, reverts `INVITED → NOT_INVITED` for each application whose last active invitation was thereby expired, recomputes the wave's `issued_count`, recomputes `Program.invited_count`, and increments the wave's `version` by one."
    PRD 3.4: "`Program.invited_count` is by definition the number of applications under the program whose `interview_status` is anything other than `NOT_INVITED`."

    Design: Corner/state_machines/closing_a_wave_expires_the_issued_and_the_waitlisted_invitation_together
    """
    builder = setup_issued_invitations(
        applicant_count=2, seat_capacity=1, slot_capacity=2
    )
    wave_id = builder.id("wave1")

    issued = get_success_data(
        api.get_interview_invitation(builder.id("inv1"), builder.coordinator)
    )
    waitlisted = get_success_data(
        api.get_interview_invitation(builder.id("inv2"), builder.coordinator)
    )
    assert (
        issued["status"] == InvitationStatus.ISSUED
    ), f"the first invitation should be ISSUED before the close, got {issued['status']}"
    assert waitlisted["status"] == InvitationStatus.WAITLISTED, (
        "the second invitation should be WAITLISTED before the close, got "
        f"{waitlisted['status']}"
    )
    wave = get_success_data(api.get_interview_wave(wave_id, builder.coordinator))
    assert (
        wave["issued_count"] == 1
    ), f"one seat should be consumed before the close, got {wave['issued_count']}"
    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert (
        program["invited_count"] == 1
    ), f"one application should be invited before the close, got {program['invited_count']}"

    response = api.close_interview_wave(wave_id, builder.coordinator)

    data = validate_success(response, 200)
    assert (
        data["status"] == WaveStatus.CLOSED
    ), f"the close must drive the wave to CLOSED, got {data['status']}"

    for key, label in (("inv1", "the issued invitation"), ("inv2", "the waitlisted invitation")):
        invitation = get_success_data(
            api.get_interview_invitation(builder.id(key), builder.coordinator)
        )
        assert invitation["status"] == InvitationStatus.EXPIRED, (
            f"{label} must be EXPIRED once the wave closes, got {invitation['status']}"
        )

    wave = get_success_data(api.get_interview_wave(wave_id, builder.coordinator))
    assert (
        wave["issued_count"] == 0
    ), f"closing the wave releases every issued seat, got issued_count {wave['issued_count']}"

    for key in ("app1", "app2"):
        application = get_success_data(
            api.get_application(builder.id(key), builder.coordinator)
        )
        assert application["interview_status"] == InterviewStatus.NOT_INVITED, (
            f"{key} must revert to NOT_INVITED once its invitation expires, got "
            f"{application['interview_status']}"
        )

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["invited_count"] == 0, (
        "Program.invited_count must be recomputed to 0 after the close, got "
        f"{program['invited_count']}"
    )


def test_certification_locks_submitted_cards_and_advances_the_program(api):
    """One certify call records the certifier, locks the cards and moves the phase.

    Certification is a three-entity side effect; a server that only writes the
    list's own status leaves the score cards unlocked and the program in RANKING.

    PRD 3.7: "Certification carries four side effects: `RankList.certified_by_faculty_id` is set to the acting faculty member's `id`; every `ScoreCard` whose scored application is ranked on this list is driven `SUBMITTED → LOCKED`; the owning program advances `RANKING → LIST_CERTIFIED` and `Program.rank_list_certified_at` is stamped with the current logical clock instant, which also increments the program's `version` by one; and `RankList.version` increments by one."
    PRD 3.7: "**Certification** is the irreversible commitment, driving `APPROVED → CERTIFIED`, and the request carries `certified_by_faculty_id` naming the certifying director."

    Design: Corner/state_machines/certification_locks_the_submitted_cards_and_advances_the_program_to_list_certified
    """
    builder = setup_approved_rank_list()

    response = api.certify_rank_list(
        builder.id("rank_list"),
        build_certify_payload(builder.id("pd")),
        builder.director("pd"),
    )

    data = validate_success(response, 200)
    assert (
        data["status"] == RankListStatus.CERTIFIED
    ), f"certification must drive the list to CERTIFIED, got {data['status']}"
    assert data["certified_by_faculty_id"] == builder.id("pd"), (
        "certified_by_faculty_id must name the acting director, got "
        f"{data['certified_by_faculty_id']!r}"
    )

    for key in ("sc1", "sc2"):
        card = get_success_data(
            api.get_score_card(builder.id(key), builder.coordinator)
        )
        assert card["status"] == ScoreCardStatus.LOCKED, (
            f"{key} scores a ranked application and must be LOCKED, got {card['status']}"
        )

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["season_phase"] == SeasonPhase.LIST_CERTIFIED, (
        "certification must drag the program to LIST_CERTIFIED, got "
        f"{program['season_phase']}"
    )
    assert _instant(program["rank_list_certified_at"]) == _instant(CLOCK_RANKING_DAY), (
        "rank_list_certified_at must be stamped from the logical clock, got "
        f"{program['rank_list_certified_at']!r}"
    )


def test_voiding_a_contract_spares_the_already_verified_credential(api):
    """Voiding sweeps the pending and submitted items but leaves the verified one.

    The packet void is conditional on each child's own status, so a blanket
    update of every item would destroy a completed verification and its stamp.

    PRD 3.9: "**Voiding** drives `ISSUED → VOID` — an issued contract the applicant never signed — carries a `reason`, has no preconditions, and voids the packet along three system-driven edges — `PENDING` → `VOIDED`, `SUBMITTED` → `VOIDED` and `REJECTED` → `VOIDED`, none of which has any precondition or side effect of its own — while an already-`VERIFIED` item is left alone."
    PRD 3.9: "`Contract.verified_credential_count` is by definition the count of items on the contract that are both mandatory and `VERIFIED`, and `Contract.mandatory_credential_count` the count of items on the contract that are mandatory."

    Design: Corner/state_machines/voiding_a_contract_voids_its_pending_items_but_leaves_the_verified_one_alone
    """
    builder = setup_issued_contract()
    builder.submit_credential(CredentialType.STATE_LICENSE, "LIC-778812")
    builder.verify_credential(CredentialType.STATE_LICENSE)
    builder.submit_credential(CredentialType.DEA, "DEA-BP4410021")
    contract_id = builder.id("contract")

    before = get_success_data(api.get_contract(contract_id, builder.coordinator))
    assert_credential_counters(before, 3, 1)

    response = api.void_contract(
        contract_id,
        build_reason_payload("Position rescinded before onboarding"),
        builder.coordinator,
    )

    data = validate_success(response, 200)
    assert (
        data["status"] == ContractStatus.VOID
    ), f"voiding must drive the contract to VOID, got {data['status']}"

    licence = get_success_data(
        api.get_credential_item(
            builder.id(f"cred_{CredentialType.STATE_LICENSE}"), builder.officer
        )
    )
    assert licence["status"] == CredentialItemStatus.VERIFIED, (
        "an already-VERIFIED item must be left alone by the void sweep, got "
        f"{licence['status']}"
    )
    assert (
        licence["verified_at"] is not None
    ), "the verified item must keep its verified_at stamp through the void"

    for credential_type in (CredentialType.DEA, CredentialType.BLS):
        item = get_success_data(
            api.get_credential_item(
                builder.id(f"cred_{credential_type}"), builder.officer
            )
        )
        assert item["status"] == CredentialItemStatus.VOIDED, (
            f"the {credential_type} item must be VOIDED by the sweep, got {item['status']}"
        )

    after = get_success_data(api.get_contract(contract_id, builder.coordinator))
    assert_credential_counters(after, 3, 1)


# ======================================================================
# Revision cycles
# ======================================================================
def test_amendment_then_revision_returns_the_card_to_draft_and_clears_its_average(api):
    """Revising an amend-requested card returns it to DRAFT with a null average.

    The revision rewrites all four domains and drops the card out of the
    roll-up, so the committee score must be recomputed over the surviving
    submitted card alone rather than left at its two-card figure.

    PRD 3.6: "The interviewer then revises, driving `AMEND_REQUESTED → DRAFT`, permitted only when the acting faculty member's `id` equals the assignment's `faculty_member_id`."
    PRD 3.6: "Revision overwrites all four rubric domain scores from the request body — `communication_score`, `clinical_reasoning_score`, `professionalism_score` and `teamwork_score` are all supplied again — clears `ScoreCard.domain_average` back to null, and recomputes `Application.committee_score` over the remaining `SUBMITTED` and `LOCKED` cards only."

    Design: Corner/state_machines/amendment_request_then_revision_returns_the_card_to_draft_and_clears_its_average
    """
    builder = setup_scored_application()
    card_id = builder.id("sc1")

    validate_success(
        api.request_score_card_amendment(card_id, builder.director("pd")), 200
    )
    amended = get_success_data(api.get_score_card(card_id, builder.coordinator))
    assert amended["status"] == ScoreCardStatus.AMEND_REQUESTED, (
        "the director's amendment request must drive the card to AMEND_REQUESTED, got "
        f"{amended['status']}"
    )

    response = api.revise_score_card(
        card_id,
        build_revise_score_card_payload((6, 6, 6, 6)),
        builder.interviewer("f1"),
    )

    data = validate_success(response, 200)
    assert (
        data["status"] == ScoreCardStatus.DRAFT
    ), f"revision must return the card to DRAFT, got {data['status']}"
    assert (
        data["communication_score"] == 6
    ), f"revision overwrites communication_score, got {data['communication_score']}"
    assert data["domain_average"] is None, (
        "revision clears domain_average back to null, got "
        f"{data['domain_average']!r}"
    )

    survivor = get_success_data(api.get_score_card(builder.id("sc2"), builder.coordinator))
    assert survivor["status"] == ScoreCardStatus.SUBMITTED, (
        "the untouched card must stay SUBMITTED, got " f"{survivor['status']}"
    )
    assert_one_decimal(
        survivor["domain_average"],
        expected_domain_average(SCORES_MEMBER),
        "ScoreCard.domain_average of the surviving card",
    )

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert_score_equals(
        application["committee_score"],
        expected_committee_score((SCORES_MEMBER,)),
        "Application.committee_score over the single remaining submitted card",
    )


def test_a_rejected_credential_item_can_be_resubmitted(api):
    """A rejected credential item returns to SUBMITTED with the new reference number.

    REJECTED is not terminal, and the resubmission overwrites the earlier
    reference rather than appending a second row or starting the verification
    clock.

    PRD 3.9: "That drives `PENDING → SUBMITTED`, and the same operation drives `REJECTED → SUBMITTED` on a second attempt, overwriting the earlier `reference_number`; both edges require that the acting applicant is the `Applicant` behind the owning contract's `MatchResult` application and that the owning contract's `status` is `ISSUED` or `SIGNED`."
    PRD 3.9: "Rejecting drives `SUBMITTED → REJECTED`, carries a `reason` in the request body, has no preconditions and no side effects, and leaves the door open for the resubmission cycle `REJECTED → SUBMITTED`."

    Design: Corner/state_machines/a_rejected_credential_item_can_be_resubmitted_and_returns_to_submitted
    """
    builder = setup_issued_contract()
    builder.submit_credential(CredentialType.STATE_LICENSE, "LIC-000000")
    item_id = builder.id(f"cred_{CredentialType.STATE_LICENSE}")
    validate_success(
        api.reject_credential_item(
            item_id, build_reason_payload("Document is illegible"), builder.officer
        ),
        200,
    )

    rejected = get_success_data(api.get_credential_item(item_id, builder.officer))
    assert rejected["status"] == CredentialItemStatus.REJECTED, (
        "the item should be REJECTED before the resubmission, got "
        f"{rejected['status']}"
    )
    assert (
        rejected["reference_number"] == "LIC-000000"
    ), f"the rejected item keeps its first reference, got {rejected['reference_number']!r}"

    response = api.submit_credential_item(
        item_id,
        build_credential_submit_payload("LIC-778812"),
        builder.applicant("cand1"),
    )

    data = validate_success(response, 200)
    assert data["status"] == CredentialItemStatus.SUBMITTED, (
        "resubmitting a rejected item returns it to SUBMITTED, got "
        f"{data['status']}"
    )
    assert data["reference_number"] == "LIC-778812", (
        "the resubmission overwrites the earlier reference_number, got "
        f"{data['reference_number']!r}"
    )
    assert (
        data["verified_at"] is None
    ), f"a resubmitted item is not yet verified, got verified_at {data['verified_at']!r}"

    contract = get_success_data(
        api.get_contract(builder.id("contract"), builder.coordinator)
    )
    assert_credential_counters(contract, 3, 0)
