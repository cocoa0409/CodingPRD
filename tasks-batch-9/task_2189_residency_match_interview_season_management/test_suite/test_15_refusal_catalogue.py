"""The refusal catalogue: one test per declared error condition.

Every test here drives a single refusal to the exact boundary the PRD fixes for it,
asserts the specific error id the ordered refusal table assigns — never a generic
one — and then proves the refused write left the world untouched. The closing group
covers the role and ownership gates, including one endpoint two roles genuinely
share and one actor barred by their own prior act.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLOCK_AFTER_CERTIFICATION_DEADLINE,
    CLOCK_AFTER_INTERVIEW,
    CLOCK_RANKING_DAY,
    CLOCK_SOAP_EXPIRY,
    CLOCK_WAVE_RELEASE,
    DIRECTOR_NAME,
    LEAD_INTERVIEWER_NAME,
    MEMBER_INTERVIEWER_NAME,
    NRMP_ADMIN_HEADERS,
    PROGRAM_CODE,
    PROGRAM_COORDINATOR_HEADERS,
    PROGRAM_NAME,
    SCORES_FOURTH,
    SCORES_THIRD,
    ApiErrorId,
    Ballot,
    ComplianceStatus,
    InterviewStatus,
    InvitationStatus,
    MatchOutcome,
    PanelRole,
    RankListStatus,
    ScoreCardStatus,
    ScreeningDecision,
    ScreeningStatus,
    SeasonBuilder,
    SeasonPhase,
    SlotStatus,
    SoapOfferStatus,
    assert_position_conservation,
    assert_slot_booking,
    build_accept_invitation_payload,
    build_certify_payload,
    build_communication_log_payload,
    build_invitation_payload,
    build_pathology_program_payload,
    build_program_payload,
    build_rank_list_entry_payload,
    build_rank_list_payload,
    build_resolve_payload,
    build_screen_payload,
    build_soap_offer_payload,
    find_by,
    setup_accepted_invitation,
    setup_approved_rank_list,
    setup_certified_rank_list,
    setup_issued_invitations,
    setup_program,
    setup_released_wave,
    setup_reviewed_application,
    setup_screened_application,
)

#: issued_at 2026-10-01T12:00:00Z plus the 120-hour response window.
INVITATION_EXPIRY_INSTANT = "2026-10-06T12:00:00Z"

#: The prohibited-phrase message the compliance scan must flag.
RANKING_INTENT_BODY = "Off the record - where will we be on your list?"
RESOLUTION_NOTE = "Reviewed with the director; no ranking commitment was solicited"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 instant so two spellings of the same moment compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _soap_active_season() -> SeasonBuilder:
    """A one-position program in SOAP_ACTIVE with two unmatched ranked applications.

    Both applicants interview and are ranked, then both withdraw, so match day
    publishes two UNMATCHED results and leaves the single position unfilled.
    """
    builder = setup_issued_invitations(
        applicant_count=2, seat_capacity=2, slot_capacity=2, quota_positions=1
    )
    builder.accept_invitation("inv1", "slot1", "cand1")
    builder.accept_invitation("inv2", "slot1", "cand2")
    builder.clock(CLOCK_AFTER_INTERVIEW)
    builder.complete_slot()
    builder.add_standard_score_cards("app1", "1")
    builder.add_score_card("sc3", "asg1", "app2", "f1", SCORES_THIRD)
    builder.add_score_card("sc4", "asg1b", "app2", "f2", SCORES_FOURTH)
    builder.clock(CLOCK_RANKING_DAY)
    builder.close_wave()
    builder.open_ranking()
    builder.create_rank_list()
    builder.add_entry("entry1", "app1", 1)
    builder.add_entry("entry2", "app2", 2)
    builder.withdraw_application("app1")
    builder.withdraw_application("app2")
    builder.submit_to_committee()
    builder.cast_vote("f1")
    builder.certify("pd")
    builder.run_match()
    builder.open_soap()
    return builder


# ----------------------------------------------------------------------
# Identity and role gates
# ----------------------------------------------------------------------
def test_program_create_with_no_identity_headers_is_unauthenticated(api):
    """A well-formed program create with no identity headers is refused at 401.

    Authentication is evaluated before anything else, so the perfectly valid body
    must not be examined and no program may be created.

    PRD 2.1: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is examined."
    PRD 2.12: "Both `X-User-ID` and `X-User-Role` are present and non-empty. Otherwise `ERR_UNAUTHENTICATED`, HTTP 401. Applies to every endpoint."

    Design: Corner/errors/a_program_create_with_no_identity_headers_returns_unauthenticated
    """
    response = api.create_program(build_program_payload(), {})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

    message = response.json()["data"]["message"]
    assert isinstance(message, str) and message, (
        f"the error envelope must carry a non-empty human message, got {message!r}"
    )

    _, meta = validate_paginated(api.list_programs(NRMP_ADMIN_HEADERS))
    assert meta["total_count"] == 0, (
        "an unauthenticated create must not register a program, but the registry "
        f"reports {meta['total_count']}"
    )


def test_a_coordinator_cannot_create_a_program(api):
    """Program registration is the national operator's alone, so a coordinator is 403.

    The coordinator is a recognised role with wide operational authority, so this
    tests the per-endpoint role list rather than the role vocabulary.

    PRD 2.1: "If `X-User-Role` is not one of the eight recognised role names, or is a recognised role that is not authorised for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.12: "`X-User-Role` names one of the eight declared roles *and* that role is listed for the endpoint being called. Otherwise `ERR_FORBIDDEN_ROLE`, HTTP 403. Applies to every endpoint."
    PRD 3.1: "A season begins with registration by the national operator."

    Design: Corner/errors/a_coordinator_cannot_create_a_program
    """
    response = api.create_program(build_program_payload(), PROGRAM_COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    _, meta = validate_paginated(api.list_programs(NRMP_ADMIN_HEADERS))
    assert meta["total_count"] == 0, (
        "the refused create must leave the registry empty, but it reports "
        f"{meta['total_count']}"
    )


def test_an_applicant_cannot_accept_another_applicants_invitation(api):
    """Answering someone else's invitation is an ownership breach, not a role breach.

    The acting user holds the Applicant role and the invitation is genuinely
    acceptable, so only the identity behind the header can reject the request.

    PRD 2.1: "When an entity-backed actor addresses a resource that does not belong to the entity whose `id` the header carries — an applicant answering another applicant's invitation, an interviewer scoring a panel seat that is not theirs, a faculty member acting on a target belonging to a different program than their own `program_id` — the request is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD 3.4: "Six conditions gate it: the acting applicant's `id` equals the `applicant_id` of the invitation's application; the logical clock is strictly before the invitation's `expires_at`, otherwise `ERR_INVITATION_EXPIRED`; the wave's `status` is `RELEASED`; the requested slot's `wave_id` equals the invitation's own `wave_id`, otherwise `ERR_CROSS_REFERENCE_MISMATCH`; the requested slot's `status` is neither `COMPLETED` nor `CANCELLED`; and no other invitation for the same `application_id` is already `ACCEPTED`."

    Design: Corner/errors/an_applicant_cannot_accept_another_applicants_invitation
    """
    builder = setup_issued_invitations(
        applicant_count=2, seat_capacity=2, slot_capacity=2
    )

    response = api.accept_interview_invitation(
        builder.id("inv1"),
        build_accept_invitation_payload(builder.id("slot1")),
        builder.applicant("cand2"),
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    invitation = get_success_data(
        api.get_interview_invitation(builder.id("inv1"), builder.coordinator)
    )
    assert invitation["status"] == InvitationStatus.ISSUED, (
        "the first applicant's invitation must remain ISSUED, got "
        f"{invitation['status']}"
    )
    assert invitation["slot_id"] is None, (
        f"no slot may have been booked, got slot_id {invitation['slot_id']}"
    )

    slot = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(slot, 0, SlotStatus.OPEN)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.INVITED, (
        "the first application must still be merely INVITED, got "
        f"{application['interview_status']}"
    )


# ----------------------------------------------------------------------
# Certification gates
# ----------------------------------------------------------------------
def test_certification_by_the_author_of_a_ranked_score_card_is_rejected(api):
    """The director who scored a ranked application may not certify the list.

    This exercises the authorship limb of segregation of duties alone — the acting
    director cast no ballot — and a second, uninvolved director then certifies the
    very same list, which proves the refusal was about the actor, not the list.

    PRD 2.11: "The `FacultyMember` certifying a list must have authored no `ScoreCard` for any `Application` ranked on that list, and must have cast no `CommitteeVote` for that list in its current `review_round`."
    PRD 2.11: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."
    PRD 3.7: "Five conditions gate it: the acting faculty member's `is_program_director` is true; that member's `program_id` equals the list's `program_id`; that member authored **no** `ScoreCard` for **any** application ranked on this list; that member cast **no** `CommitteeVote` for this list in its current `review_round`; and the logical clock is at or before the national certification deadline of `2027-02-25T21:00:00Z`."

    Design: Corner/errors/certification_by_the_director_who_authored_a_ranked_score_card_is_rejected
    """
    builder = setup_program()
    builder.add_standard_faculty()
    builder.add_second_director("pd2")
    builder.add_applicant("cand1")
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1")
    builder.screen("app1")
    builder.open_interviews()
    builder.create_wave(seat_capacity=1)
    builder.create_slot(applicant_capacity=1)
    # The first director takes a panel seat himself and writes the rubric card.
    builder.assign("asg1", "slot1", faculty_key="pd", panel_role=PanelRole.LEAD)
    builder.assign("asg1b", "slot1", faculty_key="f2", panel_role=PanelRole.MEMBER)
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    builder.issue_invitation("inv1", "app1")
    builder.accept_invitation("inv1", "slot1", "cand1")
    builder.clock(CLOCK_AFTER_INTERVIEW)
    builder.complete_slot()
    builder.add_score_card("sc1", "asg1", "app1", faculty_key="pd")
    builder.add_score_card("sc2", "asg1b", "app1", faculty_key="f2")
    builder.clock(CLOCK_RANKING_DAY)
    builder.close_wave()
    builder.open_ranking()
    builder.create_rank_list()
    builder.add_entry("entry1", "app1", 1)
    builder.submit_to_committee()
    builder.cast_vote("f1")

    refused = api.certify_rank_list(
        builder.id("rank_list"),
        build_certify_payload(builder.id("pd")),
        builder.director("pd"),
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert rank_list["status"] == RankListStatus.APPROVED, (
        f"the list must stay APPROVED after the refusal, got {rank_list['status']}"
    )
    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert program["season_phase"] == SeasonPhase.RANKING, (
        "the refused certification must not advance the season, got "
        f"{program['season_phase']}"
    )

    certified = validate_success(
        api.certify_rank_list(
            builder.id("rank_list"),
            build_certify_payload(builder.id("pd2")),
            builder.director("pd2"),
        ),
        200,
    )
    assert certified["status"] == RankListStatus.CERTIFIED, (
        "an uninvolved director must be able to certify the same list, got status "
        f"{certified['status']}"
    )
    assert certified["certified_by_faculty_id"] == builder.id("pd2"), (
        "certified_by_faculty_id must name the second director, got "
        f"{certified['certified_by_faculty_id']}"
    )


def test_certifying_after_the_deadline_instant_is_rejected(api):
    """Once the clock has passed the national deadline, certification is refused.

    The list is APPROVED and the acting director is untainted, so only the calendar
    can reject the request, and none of certification's four side effects may land.

    PRD 2.7: "The rank list certification deadline is `2027-02-25T21:00:00Z`; certification is permitted while the logical clock is at or before that instant and refused once the clock has passed it."
    PRD 2.12: "On `POST /rank-lists/{id}/certify`, the logical clock is at or before `2027-02-25T21:00:00Z`. Otherwise `ERR_CERTIFICATION_DEADLINE_PASSED`, HTTP 409."
    PRD 3.7: "Certification carries four side effects: `RankList.certified_by_faculty_id` is set to the acting faculty member's `id`; every `ScoreCard` whose scored application is ranked on this list is driven `SUBMITTED → LOCKED`; the owning program advances `RANKING → LIST_CERTIFIED` and `Program.rank_list_certified_at` is stamped with the current logical clock instant, which also increments the program's `version` by one; and `RankList.version` increments by one."

    Design: Corner/errors/certifying_after_the_deadline_instant_is_rejected
    """
    builder = setup_approved_rank_list()
    builder.clock(CLOCK_AFTER_CERTIFICATION_DEADLINE)

    response = api.certify_rank_list(
        builder.id("rank_list"),
        build_certify_payload(builder.id("pd")),
        builder.director("pd"),
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_DEADLINE_PASSED)

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert rank_list["status"] == RankListStatus.APPROVED, (
        f"the list must stay APPROVED, got {rank_list['status']}"
    )
    assert rank_list["certified_by_faculty_id"] is None, (
        "no certifier may be recorded, got "
        f"{rank_list['certified_by_faculty_id']}"
    )

    score_card = get_success_data(
        api.get_score_card(builder.id("sc1"), builder.interviewer("f1"))
    )
    assert score_card["status"] == ScoreCardStatus.SUBMITTED, (
        "the card-locking side effect must not have run, got status "
        f"{score_card['status']}"
    )

    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert program["season_phase"] == SeasonPhase.RANKING, (
        f"the program must stay in RANKING, got {program['season_phase']}"
    )
    assert program["rank_list_certified_at"] is None, (
        "rank_list_certified_at must stay null, got "
        f"{program['rank_list_certified_at']}"
    )


# ----------------------------------------------------------------------
# Compliance gate on match day
# ----------------------------------------------------------------------
def test_an_unresolved_communication_flag_blocks_match_day_until_cleared(api):
    """A FLAGGED contact on a ranked application blocks match day until resolved.

    The gate is the FLAGGED verdict, not the mere existence of a log, and the
    officer's adjudication moves the row to CLEARED rather than deleting it, so the
    identical run-match call must then succeed.

    PRD 3.10: "A flag is not merely decorative: while any `CommunicationLog` row for a subject application carries `compliance_status` `FLAGGED`, that application blocks two operations with `ERR_UNRESOLVED_COMMUNICATION_FLAG` — extending a SOAP offer to it, and running the program's match."
    PRD 3.10: "Only a `ComplianceOfficer` can clear it, by adjudicating the flagged contact with a `resolution_note`, which advances `compliance_status` `FLAGGED → CLEARED` and lifts the block."
    PRD 3.10: "When the body contains ranking intent **and** the contact is pre-match, `compliance_status` is set to `FLAGGED`; in every other combination it is set to `CLEAN`."

    Design: Corner/errors/an_unresolved_communication_flag_blocks_match_day_until_the_officer_clears_it
    """
    builder = setup_certified_rank_list()

    log = validate_success(
        api.create_communication_log(
            build_communication_log_payload(
                builder.id("app1"),
                RANKING_INTENT_BODY,
                author_faculty_id=builder.id("pd"),
            ),
            builder.director("pd"),
        ),
        201,
    )
    assert log["compliance_status"] == ComplianceStatus.FLAGGED, (
        "a prohibited phrase logged before match day must be FLAGGED, got "
        f"{log['compliance_status']}"
    )

    blocked = api.run_match(builder.id("program"), builder.admin)
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_COMMUNICATION_FLAG)

    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert program["season_phase"] == SeasonPhase.LIST_CERTIFIED, (
        "the blocked match must leave the program in LIST_CERTIFIED, got "
        f"{program['season_phase']}"
    )
    _, meta = validate_paginated(
        api.list_match_results(
            builder.coordinator, params={"program_id": builder.id("program")}
        )
    )
    assert meta["total_count"] == 0, (
        f"no result may have been published, got {meta['total_count']}"
    )

    resolved = validate_success(
        api.resolve_communication_log(
            log["id"], build_resolve_payload(RESOLUTION_NOTE), builder.officer
        ),
        200,
    )
    assert resolved["compliance_status"] == ComplianceStatus.CLEARED, (
        "the officer's adjudication must advance the row to CLEARED, got "
        f"{resolved['compliance_status']}"
    )

    ran = validate_success(api.run_match(builder.id("program"), builder.admin), 200)
    assert ran["season_phase"] == SeasonPhase.MATCH_COMPLETE, (
        "the identical call must now succeed and complete the match, got "
        f"{ran['season_phase']}"
    )
    assert ran["matched_count"] == 1, (
        f"the single ranked application must match, got matched_count {ran['matched_count']}"
    )


# ----------------------------------------------------------------------
# Expiry instants are strict
# ----------------------------------------------------------------------
def test_accepting_at_exactly_the_invitation_expiry_instant_is_rejected(api):
    """Acceptance at exactly expires_at is refused, because the comparison is strict.

    expires_at is the earlier of the wave deadline and issued_at plus 120 hours, so
    the response window binds here rather than the deadline, and the specific expiry
    code is reported rather than a generic invalid-state code.

    PRD 3.4: "While `issued_count` is strictly below `seat_capacity`, the invitation is created with `status` `ISSUED`, its `issued_at` stamped with the current logical clock instant, and its `expires_at` set to **the earlier of** the wave's `response_deadline_at` and `issued_at` plus 120 hours — a five-day response window."
    PRD 2.12: "On `POST /interview-invitations/{id}/accept`, the logical clock is strictly before the invitation's `expires_at`. Otherwise `ERR_INVITATION_EXPIRED`, HTTP 409."

    Design: Corner/errors/accepting_at_exactly_the_invitation_expiry_instant_is_rejected
    """
    builder = setup_issued_invitations(applicant_count=1, seat_capacity=1, slot_capacity=1)

    invitation = get_success_data(
        api.get_interview_invitation(builder.id("inv1"), builder.coordinator)
    )
    assert _instant(invitation["expires_at"]) == _instant(INVITATION_EXPIRY_INSTANT), (
        "the 120-hour window must bind before the wave deadline, so expires_at should "
        f"be {INVITATION_EXPIRY_INSTANT}, got {invitation['expires_at']}"
    )

    builder.clock(INVITATION_EXPIRY_INSTANT)
    response = api.accept_interview_invitation(
        builder.id("inv1"),
        build_accept_invitation_payload(builder.id("slot1")),
        builder.applicant("cand1"),
    )
    validate_error(response, ApiErrorId.ERR_INVITATION_EXPIRED)

    slot = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(slot, 0, SlotStatus.OPEN)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] != InterviewStatus.SCHEDULED, (
        "a lapsed acceptance must not schedule the applicant, got interview_status "
        f"{application['interview_status']}"
    )


def test_accepting_at_exactly_the_soap_offer_expiry_instant_is_rejected(api):
    """A SOAP acceptance at exactly expires_at is refused and the position stays open.

    The SOAP window is four hours with no competing deadline, so an offer extended at
    09:00 expires at 13:00 exactly; the same strict comparison the invitation rule
    uses applies, and the vacancy must not be consumed by a lapsed offer.

    PRD 3.8: "The offer is created with `status` `OFFERED`, `offered_at` stamped with the current logical clock instant, and `expires_at` set to `offered_at` plus 4 hours — SOAP moves fast."
    PRD 2.12: "On `POST /soap-offers/{id}/accept` and on `POST /soap-offers/{id}/decline`, the logical clock is strictly before the offer's `expires_at`. Otherwise `ERR_SOAP_OFFER_EXPIRED`, HTTP 409. Both endpoints are in scope."

    Design: Corner/errors/accepting_at_exactly_the_soap_offer_expiry_instant_is_rejected
    """
    builder = _soap_active_season()
    builder.make_soap_offer("so1", "app1", 1)

    offer = get_success_data(
        api.get_soap_offer(builder.id("so1"), builder.director("pd"))
    )
    assert _instant(offer["offered_at"]) == _instant(CLOCK_RANKING_DAY), (
        f"offered_at must be stamped at {CLOCK_RANKING_DAY}, got {offer['offered_at']}"
    )
    assert _instant(offer["expires_at"]) == _instant(CLOCK_SOAP_EXPIRY), (
        f"expires_at must be offered_at plus four hours ({CLOCK_SOAP_EXPIRY}), got "
        f"{offer['expires_at']}"
    )

    builder.clock(CLOCK_SOAP_EXPIRY)
    response = api.accept_soap_offer(builder.id("so1"), builder.applicant("cand1"))
    validate_error(response, ApiErrorId.ERR_SOAP_OFFER_EXPIRED)

    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert_position_conservation(program, 0, 1)

    results, _ = validate_paginated(
        api.list_match_results(
            builder.coordinator, params={"application_id": builder.id("app1")}
        )
    )
    result = find_by(results, application_id=builder.id("app1"))
    assert result["outcome"] == MatchOutcome.UNMATCHED, (
        "the lapsed acceptance must not promote the result, got outcome "
        f"{result['outcome']}"
    )


# ----------------------------------------------------------------------
# Conserved seats, codes and positions
# ----------------------------------------------------------------------
def test_accepting_into_a_slot_whose_only_seat_is_taken_is_rejected(api):
    """A full block refuses the second booking under the seat rule, not a state rule.

    The wave holds two issued seats but the block holds one, and the block's own
    status field already reads BOOKED, so the PRD is explicit that the seat-
    availability rule at the last priority tier owns this refusal.

    PRD 2.12: "On `POST /interview-invitations/{id}/accept`, the chosen slot's `booked_count` is strictly less than its `applicant_capacity`. Otherwise `ERR_SLOT_FULL`, HTTP 409. This rule, not the slot's state field, owns the full-seat case."
    PRD 3.4: "Note carefully that the full-seat case is **not** owned by the slot's state check — a slot whose seats are gone is refused by the seat-availability rule as `ERR_SLOT_FULL`, at the last priority tier, not as an invalid state."

    Design: Corner/errors/accepting_into_a_slot_whose_only_seat_is_already_taken_is_rejected
    """
    builder = setup_accepted_invitation(
        applicant_count=2, seat_capacity=2, slot_capacity=1
    )

    before = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(before, 1, SlotStatus.BOOKED)

    response = api.accept_interview_invitation(
        builder.id("inv2"),
        build_accept_invitation_payload(builder.id("slot1")),
        builder.applicant("cand2"),
    )
    validate_error(response, ApiErrorId.ERR_SLOT_FULL)

    after = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(after, 1, SlotStatus.BOOKED)

    invitation = get_success_data(
        api.get_interview_invitation(builder.id("inv2"), builder.coordinator)
    )
    assert invitation["status"] == InvitationStatus.ISSUED, (
        f"the refused invitation must stay ISSUED, got {invitation['status']}"
    )

    application = get_success_data(
        api.get_application(builder.id("app2"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.INVITED, (
        "the second application must stay INVITED, got "
        f"{application['interview_status']}"
    )


def test_a_second_program_reusing_an_nrmp_program_code_is_rejected(api):
    """The NRMP program code is unique platform-wide, so the reuse is a duplicate.

    Every other field of the second registration differs, so only the code collision
    can refuse it, and the first program must be left exactly as it was.

    PRD 3.1: "An `NrmpAdmin` registers a participating program by supplying its display `name` (non-empty, at most 200 characters), its NRMP-assigned `nrmp_program_code` (non-empty and unique across every program on the platform), its ACGME `specialty_code` abbreviation such as IM, EM or PEDS (non-empty), and `quota_positions` — the number of PGY-1 positions the program is certified to fill, which must be at least 1."
    PRD 2.12: "Any breach is `ERR_DUPLICATE_RESOURCE`, HTTP 409. Applies to every create endpoint."

    Design: Corner/errors/a_second_program_reusing_an_nrmp_program_code_is_rejected
    """
    builder = setup_program()

    response = api.create_program(
        build_pathology_program_payload(nrmp_program_code=PROGRAM_CODE),
        NRMP_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    _, meta = validate_paginated(api.list_programs(NRMP_ADMIN_HEADERS))
    assert meta["total_count"] == 1, (
        "the duplicate must not be registered, so exactly one program should remain, "
        f"got {meta['total_count']}"
    )

    first = get_success_data(
        api.get_program(builder.id("program"), NRMP_ADMIN_HEADERS)
    )
    assert first["name"] == PROGRAM_NAME, (
        f"the incumbent program must be untouched, got name {first['name']!r}"
    )
    assert first["nrmp_program_code"] == PROGRAM_CODE, (
        f"the incumbent program must keep its code, got {first['nrmp_program_code']!r}"
    )


def test_the_first_entry_of_a_list_may_not_be_created_at_rank_position_two(api):
    """An empty list accepts position 1 only, because appends are strictly contiguous.

    Position 2 on an empty list is a plausible reservation of the runner-up seat, so
    an implementation that merely checks uniqueness would let the gap through.

    PRD 3.7: "`rank_position` is a 1-based preference position of at least 1, unique within the list, and — crucially — it must equal the list's current `entry_count` plus one **exactly**, which makes the list strictly append-only; any other value is `ERR_RANK_POSITION_SEQUENCE`."
    PRD 2.12: "On `POST /rank-lists/{id}/entries`, the supplied `rank_position` equals the list's current `entry_count` plus one exactly, so the list is built append-only."

    Design: Corner/errors/the_first_entry_of_a_list_may_not_be_created_at_rank_position_two
    """
    builder = setup_screened_application(1, quota_positions=1)
    builder.open_interviews()
    builder.open_ranking()
    builder.create_rank_list()

    response = api.create_rank_list_entry(
        builder.id("rank_list"),
        build_rank_list_entry_payload(
            builder.id("app1"), 2, builder.current_rank_list_version()
        ),
        builder.director("pd"),
    )
    validate_error(response, ApiErrorId.ERR_RANK_POSITION_SEQUENCE)

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert rank_list["entry_count"] == 0, (
        f"the refused append must leave the list empty, got {rank_list['entry_count']}"
    )
    _, meta = validate_paginated(
        api.list_entries_of_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert meta["total_count"] == 0, (
        f"no entry may have been created, got {meta['total_count']}"
    )


def test_a_third_invitation_with_seats_and_waitlist_both_full_is_rejected(api):
    """Only when the waitlist is also exhausted does a wave refuse an invitation.

    One seat capacity means the first invitation is issued and the second is routed
    to the waitlist rather than refused; the third has nowhere left to land.

    PRD 3.4: "The waitlist is not unbounded: it may itself grow only until the number of `WAITLISTED` invitations in the wave reaches `seat_capacity`."
    PRD 3.4: "When both the issued seats and the waitlist are exhausted, or the wave is already `CLOSED`, or the program has moved past `INTERVIEWS_OPEN` so no waitlist can absorb the request, the create is refused with `ERR_WAVE_CAPACITY_REACHED`."
    PRD 3.4: "Reaching `seat_capacity` alone is never a refusal — it is a routing decision."

    Design: Corner/errors/a_third_invitation_with_seats_and_waitlist_both_full_is_rejected
    """
    builder = setup_released_wave(applicant_count=3, seat_capacity=1, slot_capacity=3)
    builder.issue_invitation("inv1", "app1")
    builder.issue_invitation("inv2", "app2")

    first = get_success_data(
        api.get_interview_invitation(builder.id("inv1"), builder.coordinator)
    )
    assert first["status"] == InvitationStatus.ISSUED, (
        f"the first invitation must consume the only seat, got {first['status']}"
    )
    second = get_success_data(
        api.get_interview_invitation(builder.id("inv2"), builder.coordinator)
    )
    assert second["status"] == InvitationStatus.WAITLISTED, (
        "reaching seat_capacity routes rather than refuses, so the second invitation "
        f"must be WAITLISTED, got {second['status']}"
    )
    wave = get_success_data(
        api.get_interview_wave(builder.id("wave1"), builder.coordinator)
    )
    assert wave["issued_count"] == 1, (
        f"only one seat may have been consumed, got issued_count {wave['issued_count']}"
    )

    response = api.create_interview_invitation(
        builder.id("wave1"),
        build_invitation_payload(
            builder.id("app3"), builder.current_wave_version("wave1")
        ),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_WAVE_CAPACITY_REACHED)

    _, meta = validate_paginated(
        api.list_interview_invitations(
            builder.coordinator, params={"wave_id": builder.id("wave1")}
        )
    )
    assert meta["total_count"] == 2, (
        f"the wave must still hold exactly two invitations, got {meta['total_count']}"
    )
    application = get_success_data(
        api.get_application(builder.id("app3"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.NOT_INVITED, (
        "the third application must stay NOT_INVITED, got "
        f"{application['interview_status']}"
    )


def test_a_third_soap_offer_against_a_budget_of_two_is_rejected(api):
    """The live-offer count spans every round, so a third offer breaches a budget of two.

    One unfilled position yields a base vacancy of 1 plus a reserve credit of 1, a
    ceiling deliberately larger than the vacancy it protects; the third offer targets
    a different round and is still refused.

    PRD 3.8: "The number of live offers compared against this budget is the count of `SoapOffer` rows for the program whose `status` is `OFFERED` or `ACCEPTED`, across all rounds; a create that would push that count above the budget is refused with `ERR_SOAP_BUDGET_EXCEEDED`."
    PRD 3.8: "**Step two:** a reserve credit is selected from that base vacancy in a strict cascade — a base vacancy of at least 6 earns a credit of 3; otherwise a base vacancy of at least 3 earns 2; otherwise a base vacancy of at least 1 earns 1; a base vacancy of 0 earns 0."
    PRD 2.12: "On `POST /soap-offers`, the count of `SoapOffer` rows for the program whose `status` is `OFFERED` or `ACCEPTED` must remain at or below the program's `soap_offer_budget` after the create."

    Design: Corner/errors/a_third_soap_offer_against_a_budget_of_two_is_rejected
    """
    builder = _soap_active_season()
    builder.make_soap_offer("so1", "app1", 1)
    builder.make_soap_offer("so2", "app2", 1)

    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert program["soap_offer_budget"] == 2, (
        "one unfilled position must yield a budget of two, got "
        f"{program['soap_offer_budget']}"
    )
    assert program["unfilled_positions"] == 1, (
        f"the single position must still be unfilled, got {program['unfilled_positions']}"
    )

    response = api.create_soap_offer(
        build_soap_offer_payload(builder.id("program"), builder.id("app1"), 2),
        builder.director("pd"),
    )
    validate_error(response, ApiErrorId.ERR_SOAP_BUDGET_EXCEEDED)

    _, meta = validate_paginated(
        api.list_soap_offers(
            builder.director("pd"), params={"program_id": builder.id("program")}
        )
    )
    assert meta["total_count"] == 2, (
        f"the refused offer must not be created, got {meta['total_count']} offers"
    )
    for key in ("so1", "so2"):
        offer = get_success_data(
            api.get_soap_offer(builder.id(key), builder.director("pd"))
        )
        assert offer["status"] == SoapOfferStatus.OFFERED, (
            f"the live offer {key} must stay OFFERED, got {offer['status']}"
        )


def test_a_second_soap_acceptance_with_no_position_left_is_rejected(api):
    """Two live offers may outnumber the vacancy, but only one may be accepted.

    The budget deliberately allows more offers than positions, so the conservation
    identity has to be defended at acceptance time rather than at offer time.

    PRD 3.8: "Acceptance also requires the program to have room — `Program.unfilled_positions` at least 1, otherwise `ERR_NO_POSITIONS_AVAILABLE`."
    PRD 2.12: "On `POST /soap-offers/{id}/accept`, the program's `unfilled_positions` is at least 1, so no program fills more than `quota_positions` positions."

    Design: Corner/errors/a_second_soap_acceptance_with_no_position_left_is_rejected
    """
    builder = _soap_active_season()
    builder.make_soap_offer("so1", "app1", 1)
    builder.make_soap_offer("so2", "app2", 1)
    validate_success(
        api.accept_soap_offer(builder.id("so1"), builder.applicant("cand1")), 200
    )

    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert_position_conservation(program, 1, 0)

    response = api.accept_soap_offer(builder.id("so2"), builder.applicant("cand2"))
    validate_error(response, ApiErrorId.ERR_NO_POSITIONS_AVAILABLE)

    offer = get_success_data(
        api.get_soap_offer(builder.id("so2"), builder.director("pd"))
    )
    assert offer["status"] == SoapOfferStatus.OFFERED, (
        f"the refused offer must stay OFFERED, got {offer['status']}"
    )

    results, _ = validate_paginated(
        api.list_match_results(
            builder.coordinator, params={"application_id": builder.id("app2")}
        )
    )
    result = find_by(results, application_id=builder.id("app2"))
    assert result["outcome"] == MatchOutcome.UNMATCHED, (
        f"the second applicant must stay UNMATCHED, got {result['outcome']}"
    )

    after = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert after["matched_count"] == 1, (
        f"matched_count must stay at one, got {after['matched_count']}"
    )


def _program_in_ranking(**overrides) -> SeasonBuilder:
    """A screened program walked forward to RANKING with no rank list yet."""
    builder = setup_screened_application(1, **overrides)
    builder.open_interviews()
    builder.open_ranking()
    return builder


# ----------------------------------------------------------------------
# The per-endpoint role list
# ----------------------------------------------------------------------
def test_a_coordinator_cannot_create_a_rank_list(api):
    """Opening the preference list belongs to the director, not to the coordinator.

    The coordinator runs almost every other logistical step of the season, so this
    isolates one endpoint deliberately withheld from that role.

    PRD 2.1: "A `ProgramDirector` owns the program's preference order and its irreversible commitments — opening the rank list, appending entries to it, sending it to committee, reviving a returned list, certifying it, withdrawing it, extending SOAP offers, rescinding a contract, and sending a submitted score card back for amendment."
    PRD 2.1: "A `ProgramCoordinator` is the operational staff role that runs the season's logistics: application intake, faculty registration, screening decisions, applicant withdrawal, wave planning, release and closure, invitation issuance, slot creation, completion and cancellation, panel staffing and release, phase advancement, running the match, and contract issuance and activation."
    PRD 2.12: "`X-User-Role` names one of the eight declared roles *and* that role is listed for the endpoint being called. Otherwise `ERR_FORBIDDEN_ROLE`, HTTP 403. Applies to every endpoint."

    Design: Corner/rbac/a_coordinator_cannot_create_a_rank_list
    """
    builder = _program_in_ranking(quota_positions=1)

    response = api.create_rank_list(
        build_rank_list_payload(builder.id("program")), builder.coordinator
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    _, meta = validate_paginated(
        api.list_rank_lists(
            builder.director("pd"), params={"program_id": builder.id("program")}
        )
    )
    assert meta["total_count"] == 0, (
        "the refused open must not create a list, but the program reports "
        f"{meta['total_count']}"
    )


def test_the_committee_member_and_the_director_share_the_rank_list_read(api):
    """One list read is shared by the director and the committee member alike.

    A role gate implemented as a single owning role per resource would lock the
    committee out of the very list it has to deliberate on, so both actors must see
    the same list and the same version.

    PRD 2.1: "A `CommitteeMember` casts one ballot per deliberation round on a rank list under review."
    PRD 2.1: "The authoritative per-endpoint role list is the table in §4; where this paragraph and that table could be read differently, the table governs."
    PRD 3.7: "Lists are listed with optional `program_id`, `status` and `certified_by_faculty_id` filters, and a single list read exposes `entry_count`, `review_round` and the `version` that the concurrency guard of §2.9 compares against."

    Design: Corner/rbac/the_committee_member_and_the_director_share_the_rank_list_read
    """
    builder = _program_in_ranking(quota_positions=1)
    builder.create_rank_list()

    as_committee = validate_success(
        api.get_rank_list(builder.id("rank_list"), builder.committee("f1")), 200
    )
    as_director = validate_success(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd")), 200
    )

    for label, data in (("committee member", as_committee), ("director", as_director)):
        assert data["id"] == builder.id("rank_list"), (
            f"the {label} must read back the same list, got id {data['id']}"
        )
        assert data["status"] == RankListStatus.DRAFT, (
            f"the {label} must see the list as DRAFT, got {data['status']}"
        )
        assert data["entry_count"] == 0, (
            f"the {label} must see an empty list, got entry_count {data['entry_count']}"
        )

    assert as_committee["version"] == as_director["version"], (
        "both readers must observe the same version of the list, got "
        f"{as_committee['version']} and {as_director['version']}"
    )


def test_a_reviewer_cannot_screen_the_application_it_reviewed(api):
    """The reviewer who wrote a review may not also record the screening decision.

    The reviewer is the actor with the most context on this application and its two
    reviews already clear the evaluation minimum, so nothing but the role list can
    refuse the call — as the identical call from the coordinator then shows.

    PRD 2.1: "A `Reviewer` writes paper-screening reviews of applications and does nothing else that mutates state."
    PRD 3.2: "A `ProgramCoordinator` records the screening decision by supplying a `decision` field."
    PRD 2.12: "`X-User-Role` names one of the eight declared roles *and* that role is listed for the endpoint being called. Otherwise `ERR_FORBIDDEN_ROLE`, HTTP 403. Applies to every endpoint."

    Design: Corner/rbac/a_reviewer_cannot_screen_the_application_it_reviewed
    """
    builder = setup_reviewed_application(1, review_count=2)

    response = api.screen_application(
        builder.id("app1"),
        build_screen_payload(ScreeningDecision.ADVANCE),
        builder.reviewer("f1"),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["screening_status"] == ScreeningStatus.UNDER_REVIEW, (
        "the refused screen must leave the application UNDER_REVIEW, got "
        f"{application['screening_status']}"
    )
    assert application["final_screen_score"] is None, (
        "no decision ran, so final_screen_score must stay null, got "
        f"{application['final_screen_score']}"
    )

    advanced = validate_success(
        api.screen_application(
            builder.id("app1"),
            build_screen_payload(ScreeningDecision.ADVANCE),
            builder.coordinator,
        ),
        200,
    )
    assert advanced["screening_status"] == ScreeningStatus.ADVANCED, (
        "only the acting role differed, so the coordinator's identical call must "
        f"advance the application, got {advanced['screening_status']}"
    )


# ----------------------------------------------------------------------
# Segregation of duties: the ballot limb
# ----------------------------------------------------------------------
def test_a_director_who_cast_a_ballot_may_not_certify_the_list_it_approved(api):
    """A director who balloted in the current round is barred from certifying.

    This isolates the ballot limb: the acting director authored no score card, holds
    the correct role and the list is APPROVED, and a second director then certifies
    the same list, which proves the refusal tracked the actor's own history.

    PRD 2.11: "The `FacultyMember` certifying a list must have authored no `ScoreCard` for any `Application` ranked on that list, and must have cast no `CommitteeVote` for that list in its current `review_round`."
    PRD 2.11: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."
    PRD 3.6: "The quorum threshold is that electorate size multiplied by 0.60 — sixty percent — and then **rounded up to the next whole number** by the ceiling function; an electorate of four therefore needs three, and an electorate of five also needs three."

    Design: Corner/rbac/a_director_who_cast_a_ballot_may_not_certify_the_list_it_approved
    """
    builder = SeasonBuilder()
    builder.create_program()
    # The first director also sits on the committee, so the electorate is two.
    builder.add_faculty(
        "pd", DIRECTOR_NAME, is_program_director=True, is_committee_member=True
    )
    builder.add_faculty(
        "f1", LEAD_INTERVIEWER_NAME, is_program_director=False, is_committee_member=True
    )
    builder.add_faculty(
        "f2",
        MEMBER_INTERVIEWER_NAME,
        is_program_director=False,
        is_committee_member=False,
    )
    builder.add_second_director("pd2")
    builder.add_applicant("cand1")
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1")
    builder.screen("app1")
    builder.open_interviews()
    builder.create_wave(seat_capacity=1)
    builder.create_slot(applicant_capacity=1)
    builder.staff_standard_panel()
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    builder.issue_invitation("inv1", "app1")
    builder.accept_invitation("inv1", "slot1", "cand1")
    builder.clock(CLOCK_AFTER_INTERVIEW)
    builder.complete_slot()
    builder.add_standard_score_cards("app1", "1")
    builder.clock(CLOCK_RANKING_DAY)
    builder.close_wave()
    builder.open_ranking()
    builder.create_rank_list()
    builder.add_entry("entry1", "app1", 1)
    builder.submit_to_committee()
    builder.cast_vote("pd", Ballot.APPROVE)
    builder.cast_vote("f1", Ballot.APPROVE)

    ballots, meta = validate_paginated(
        api.list_votes_of_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert meta["total_count"] == 2, (
        "an electorate of two needs both ballots to approve, so the list must carry "
        f"two recorded ballots, got {meta['total_count']}"
    )
    directors_ballot = find_by(
        ballots, faculty_member_id=builder.id("pd"), ballot=Ballot.APPROVE
    )
    assert directors_ballot["rank_list_id"] == builder.id("rank_list"), (
        "the certifying director's own approve ballot must sit on this list, got "
        f"rank_list_id {directors_ballot['rank_list_id']}"
    )

    approved = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert approved["status"] == RankListStatus.APPROVED, (
        f"two approve ballots must carry the list to APPROVED, got {approved['status']}"
    )

    refused = api.certify_rank_list(
        builder.id("rank_list"),
        build_certify_payload(builder.id("pd")),
        builder.director("pd"),
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    still_approved = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert still_approved["status"] == RankListStatus.APPROVED, (
        "the refused certification must leave the list APPROVED, got "
        f"{still_approved['status']}"
    )

    certified = validate_success(
        api.certify_rank_list(
            builder.id("rank_list"),
            build_certify_payload(builder.id("pd2")),
            builder.director("pd2"),
        ),
        200,
    )
    assert certified["status"] == RankListStatus.CERTIFIED, (
        "the second director must be able to certify the same list, got "
        f"{certified['status']}"
    )
    assert certified["certified_by_faculty_id"] == builder.id("pd2"), (
        "certified_by_faculty_id must name the uninvolved director, got "
        f"{certified['certified_by_faculty_id']}"
    )

    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert program["season_phase"] == SeasonPhase.LIST_CERTIFIED, (
        "certification must carry the program to LIST_CERTIFIED, got "
        f"{program['season_phase']}"
    )
