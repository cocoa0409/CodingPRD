"""Cascades whose consequences travel several resources away from the request.

Declining a booked interview seat frees the seat, promotes a waitlisted rival,
advances that rival's application and rewrites the program's counter. Rescinding
a signed contract vacates a match result, restores a position and re-opens a
season that had already closed.
"""

from __future__ import annotations

from test_helpers import (
    CLOCK_WAVE_RELEASE,
    ContractStatus,
    CredentialItemStatus,
    CredentialType,
    InterviewStatus,
    InvitationStatus,
    MatchOutcome,
    SeasonPhase,
    SlotStatus,
    assert_credential_counters,
    assert_position_conservation,
    assert_slot_booking,
    assert_wave_seat_conservation,
    build_reason_payload,
    get_success_data,
    setup_signed_contract,
    setup_staffed_program,
    validate_success,
)

#: Paper reviews chosen so the four applications carry four distinct final scores.
REVIEW_POINTS = {
    "app1": ((30, 20, 20), (34, 24, 18)),
    "app2": ((20, 20, 20), (20, 20, 20)),
    "app3": ((30, 20, 20), (30, 20, 20)),
    "app4": ((26, 20, 20), (26, 20, 20)),
}

RESCISSION_REASON = "Applicant accepted a position elsewhere"
STATE_LICENSE_REFERENCE = "LIC-778812"


def _wave_with_two_seats_and_two_waitlisted():
    """Two issued invitations, two waitlisted, and the first seat booked.

    The waitlist holds a 22.00-scoring application and a 28.50-scoring one, so
    the promotion selector has a strict preference between them.
    """
    builder = setup_staffed_program()
    builder.add_applicant(
        "cand2", full_name="Omar Diaz", step2_score=230, self_identified_group="GROUP_B"
    )
    builder.add_applicant(
        "cand3",
        full_name="Priya Rao",
        medical_school_type="US_MD",
        step2_score=240,
        self_identified_group="GROUP_B",
    )
    builder.add_applicant(
        "cand4",
        eras_id="E-9004",
        full_name="Devi Shah",
        step2_score=228,
        pipeline_program_alum=False,
        self_identified_group="GROUP_A",
    )
    builder.open_review()
    for index in range(1, 5):
        app_key = f"app{index}"
        builder.add_application(app_key, f"cand{index}")
        builder.add_reviews(app_key, ("f1", "f2"), REVIEW_POINTS[app_key])
        builder.screen(app_key)
    builder.open_interviews()
    builder.create_wave(seat_capacity=2)
    builder.create_slot(applicant_capacity=1)
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    builder.issue_invitation("inv1", "app1")
    builder.issue_invitation("inv2", "app4")
    builder.issue_invitation("inv3", "app2")
    builder.issue_invitation("inv4", "app3")
    builder.accept_invitation("inv1", "slot1", "cand1")
    return builder


def _closed_season_with_one_verified_credential():
    """A signed one-position contract in a closed season, one item verified."""
    builder = setup_signed_contract(quota_positions=1)
    builder.submit_credential(CredentialType.STATE_LICENSE, STATE_LICENSE_REFERENCE)
    builder.verify_credential(CredentialType.STATE_LICENSE)
    builder.close_season()
    return builder


def test_declining_a_booked_seat_returns_the_seat_and_ends_the_invitation(api):
    """Hop one of the decline cascade: the slot's only seat comes back.

    The invitation is answered and terminal, the block is open again, and the
    declining application holds no invitation at all.

    PRD 3.4: "Declining an invitation that is already `ACCEPTED` drives `ACCEPTED → DECLINED`, adds the requirement that the logical clock be strictly before the booked slot's `start_at`, and fires the system's flagship four-hop cascade: **hop 1** decrements the booked slot's `booked_count` by one and returns that slot `BOOKED → OPEN` when `booked_count` falls below `applicant_capacity`; **hop 2** treats that freed seat as an opening and promotes the waitlist winner `WAITLISTED → ISSUED`; **hop 3** advances the promoted invitation's own application `NOT_INVITED → INVITED`; **hop 4** recomputes `Program.invited_count` from the changed set of invited applications."
    PRD 3.4: "The declining application itself reverts `SCHEDULED → NOT_INVITED` when it retains no invitation in `ISSUED`, `WAITLISTED` or `ACCEPTED`."

    Design: Difficulty/transitive_cascade/invitation_decline_frees_seat_and_promotes_waitlist_four_hop
    """
    builder = _wave_with_two_seats_and_two_waitlisted()

    declined = validate_success(
        api.decline_interview_invitation(builder.id("inv1"), builder.applicant("cand1"))
    )

    assert declined["status"] == InvitationStatus.DECLINED, (
        f"the declined invitation should be DECLINED, got {declined['status']}"
    )
    assert declined["responded_at"] is not None, "responded_at must be stamped"

    slot = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(slot, expected_booked=0, expected_status=SlotStatus.OPEN)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.NOT_INVITED, (
        "the declining application should revert to NOT_INVITED, got "
        f"{application['interview_status']}"
    )


def test_the_freed_seat_promotes_the_higher_scoring_waitlisted_rival(api):
    """Hop two: the 28.50 waitlisted candidate wins the seat over the 22.00 one.

    The selector orders by final screen score descending, so the lower-scoring
    invitation stays on the waitlist even though it was waitlisted first.

    PRD 3.4: "Candidates are ordered by their application's `final_screen_score` in **descending** order, and ties are broken by the invitation's own `created_at` in **ascending** order — earliest waitlisted first."
    PRD 3.4: "A promotion stamps the promoted invitation's `issued_at` with the current logical clock instant, sets its `expires_at` to the earlier of the wave's `response_deadline_at` and that `issued_at` plus 120 hours, increments the wave's `issued_count` by one, and advances the promoted application `NOT_INVITED → INVITED`."

    Design: Difficulty/transitive_cascade/invitation_decline_frees_seat_and_promotes_waitlist_four_hop
    """
    builder = _wave_with_two_seats_and_two_waitlisted()

    api.decline_interview_invitation(builder.id("inv1"), builder.applicant("cand1"))

    promoted = get_success_data(
        api.get_interview_invitation(builder.id("inv4"), builder.coordinator)
    )
    assert promoted["status"] == InvitationStatus.ISSUED, (
        "the highest-scoring waitlisted invitation should be promoted, got "
        f"{promoted['status']}"
    )
    assert promoted["issued_at"] is not None, "a promotion stamps issued_at"
    assert promoted["expires_at"] is not None, "a promotion computes expires_at"

    passed_over = get_success_data(
        api.get_interview_invitation(builder.id("inv3"), builder.coordinator)
    )
    assert passed_over["status"] == InvitationStatus.WAITLISTED, (
        "exactly one invitation is promoted per freed seat, got "
        f"{passed_over['status']}"
    )


def test_the_promotion_advances_the_promoted_application_and_the_counters(api):
    """Hops three and four: the promoted application and the program counter move.

    The wave is back to two issued seats and the program counts two applications
    off NOT_INVITED — the promoted one and the one that never declined.

    PRD 3.4: "`Program.invited_count` is by definition the number of applications under the program whose `interview_status` is anything other than `NOT_INVITED`."
    PRD 3.3: "The wave materialises with `status` `PLANNED` and `issued_count` at 0, where `issued_count` is by definition the number of invitations in the wave whose `status` is `ISSUED` or `ACCEPTED`."

    Design: Difficulty/transitive_cascade/invitation_decline_frees_seat_and_promotes_waitlist_four_hop
    """
    builder = _wave_with_two_seats_and_two_waitlisted()

    api.decline_interview_invitation(builder.id("inv1"), builder.applicant("cand1"))

    promoted_application = get_success_data(
        api.get_application(builder.id("app3"), builder.coordinator)
    )
    assert promoted_application["interview_status"] == InterviewStatus.INVITED, (
        "the promoted application should advance to INVITED, got "
        f"{promoted_application['interview_status']}"
    )

    still_waiting = get_success_data(
        api.get_application(builder.id("app2"), builder.coordinator)
    )
    assert still_waiting["interview_status"] == InterviewStatus.NOT_INVITED, (
        "a waitlisted place leaves the interview dimension untouched, got "
        f"{still_waiting['interview_status']}"
    )

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["invited_count"] == 2, (
        f"two applications should be off NOT_INVITED, got {program['invited_count']}"
    )

    wave = get_success_data(
        api.get_interview_wave(builder.id("wave1"), builder.coordinator)
    )
    assert_wave_seat_conservation(wave, expected_issued=2)


def test_rescinding_a_signed_contract_vacates_its_match_result(api):
    """Hop one of the rescission cascade reaches the match result.

    The contract is terminal and the result it documented is vacated with its
    rank position cleared.

    PRD 3.9: "**Hop 1:** the referenced `MatchResult` advances `MATCHED → VACATED`, and its `matched_rank_position` is cleared to null."
    PRD 3.9: "It drives `SIGNED → RESCINDED` or `ACTIVE → RESCINDED`, carries a `reason`, and has no preconditions beyond the state."

    Design: Difficulty/transitive_cascade/contract_rescission_vacates_position_and_reopens_soap_four_hop
    """
    builder = _closed_season_with_one_verified_credential()

    rescinded = validate_success(
        api.rescind_contract(
            builder.id("contract"),
            build_reason_payload(RESCISSION_REASON),
            builder.director("pd"),
        )
    )
    assert rescinded["status"] == ContractStatus.RESCINDED, (
        f"the contract should be RESCINDED, got {rescinded['status']}"
    )

    match_result = get_success_data(
        api.get_match_result(builder.id("match1"), builder.coordinator)
    )
    assert match_result["outcome"] == MatchOutcome.VACATED, (
        f"the match result should be VACATED, got {match_result['outcome']}"
    )
    assert match_result["matched_rank_position"] is None, (
        "the vacating cascade clears matched_rank_position, got "
        f"{match_result['matched_rank_position']}"
    )


def test_the_vacated_position_returns_to_the_pool_and_reopens_the_closed_season(api):
    """Hops two and three: the position comes back and the season re-opens.

    The program had filled its only position and closed; after the rescission it
    is vacant again and sitting back in the SOAP phase.

    PRD 3.9: "**Hop 2:** because that result is no longer `MATCHED`, `Program.matched_count` decrements by one and `Program.unfilled_positions` increments by one, preserving `quota_positions` equal to `matched_count` plus `unfilled_positions` exactly."
    PRD 3.9: "**Hop 3:** because the program's `unfilled_positions` has risen above 0, a program sitting in `SEASON_CLOSED` re-opens `SEASON_CLOSED → SOAP_ACTIVE`, gated on `Program.soap_participating` being true and on `unfilled_positions` being at least 1 after the vacating cascade, and that hop increments the program's `version` by one."

    Design: Difficulty/transitive_cascade/contract_rescission_vacates_position_and_reopens_soap_four_hop
    """
    builder = _closed_season_with_one_verified_credential()

    before = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert_position_conservation(before, expected_matched=1, expected_unfilled=0)
    assert before["season_phase"] == SeasonPhase.SEASON_CLOSED

    api.rescind_contract(
        builder.id("contract"),
        build_reason_payload(RESCISSION_REASON),
        builder.director("pd"),
    )

    after = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert_position_conservation(after, expected_matched=0, expected_unfilled=1)
    assert after["season_phase"] == SeasonPhase.SOAP_ACTIVE, (
        "a closed season with a restored vacancy re-opens to SOAP_ACTIVE, got "
        f"{after['season_phase']}"
    )


def test_the_packet_is_voided_except_for_the_item_already_verified(api):
    """The same rescission voids the unanswered packet items and spares the verified one.

    Two mandatory items were still pending; the third had been verified and is
    left exactly as it was.

    PRD 3.9: "Alongside the cascade, the same three packet-voiding edges fire as on a void — `PENDING` → `VOIDED`, `SUBMITTED` → `VOIDED` and `REJECTED` → `VOIDED` — leaving `VERIFIED` items untouched."
    PRD 3.9: "`Contract.verified_credential_count` is by definition the count of items on the contract that are both mandatory and `VERIFIED`, and `Contract.mandatory_credential_count` the count of items on the contract that are mandatory."

    Design: Difficulty/transitive_cascade/contract_rescission_vacates_position_and_reopens_soap_four_hop
    """
    builder = _closed_season_with_one_verified_credential()

    before = get_success_data(
        api.get_contract(builder.id("contract"), builder.coordinator)
    )
    assert_credential_counters(before, expected_mandatory=3, expected_verified=1)

    api.rescind_contract(
        builder.id("contract"),
        build_reason_payload(RESCISSION_REASON),
        builder.director("pd"),
    )

    for credential_type in (CredentialType.DEA, CredentialType.BLS):
        item = get_success_data(
            api.get_credential_item(
                builder.id(f"cred_{credential_type}"), builder.coordinator
            )
        )
        assert item["status"] == CredentialItemStatus.VOIDED, (
            f"the pending {credential_type} item should be VOIDED, got {item['status']}"
        )

    license_item = get_success_data(
        api.get_credential_item(
            builder.id(f"cred_{CredentialType.STATE_LICENSE}"), builder.coordinator
        )
    )
    assert license_item["status"] == CredentialItemStatus.VERIFIED, (
        "an already-verified item is left alone, got " f"{license_item['status']}"
    )
