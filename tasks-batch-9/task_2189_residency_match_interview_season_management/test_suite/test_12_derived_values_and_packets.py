"""Derived values the season computes: match fills, packets, flags and scores.

Each test pins one computation the PRD specifies exactly — the rank-order match
walk, the deterministic credential packet, the compliance scan, the freed-seat
cascade, and the screening composite the response body must already carry.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_credential_counters,
    assert_match_result,
    assert_position_conservation,
    assert_score_equals,
    assert_slot_booking,
    assert_wave_seat_conservation,
    expected_final_score,
    expected_provisional_score,
    find_by,
)
from test_helpers.constants import (
    CLOCK_AFTER_INTERVIEW,
    CLOCK_RANKING_DAY,
    CLOCK_SEASON_START,
    CLOCK_WAVE_RELEASE,
    DEFAULT_SALARY_CENTS,
    PATHOLOGY_PROGRAM_CODE,
    PATHOLOGY_PROGRAM_NAME,
    PATHOLOGY_SPECIALTY,
)
from test_helpers.factories import (
    build_communication_log_payload,
    build_contract_payload,
    build_screen_payload,
)
from test_helpers.fixtures import (
    SCORES_FOURTH,
    SCORES_THIRD,
    SeasonBuilder,
    setup_accepted_invitation,
    setup_issued_invitations,
    setup_reviewed_application,
    setup_staffed_program,
)
from test_helpers.types import (
    CommunicationChannel,
    ComplianceStatus,
    ContractStatus,
    CredentialItemStatus,
    CredentialType,
    InterviewStatus,
    InvitationStatus,
    MatchOutcome,
    ScreeningDecision,
    ScreeningStatus,
    SeasonPhase,
    SlotStatus,
    VisaStatus,
)

#: The two review triples every screened application in these walks carries.
STANDARD_REVIEWS = ((30, 20, 20), (30, 20, 20))

#: The applicant profile the standard first candidate is created with.
CAND1_STEP2_SCORE = 251
CAND1_PIPELINE_ALUM = True

FLAGGED_BODY = "Great to meet you today - How Will You Rank our program?"
CLEAN_BODY = "Thank you for interviewing with us today; our coordinator will follow up."


def _normalise_instant(value: str) -> str:
    """Strip the optional fractional part from an ISO 8601 UTC instant."""
    assert value is not None, "expected an ISO 8601 UTC instant, got null"
    return value.replace("Z", "").split(".")[0]


# ======================================================================
# Match day
# ======================================================================
def test_match_day_fills_the_quota_in_rank_order_and_skips_the_ineligible_entry(api):
    """A two-position quota matches the eligible entry and publishes the other unmatched.

    The withdrawn application is still ranked, so it must receive its own
    published result rather than be dropped from the walk, and the position it
    could not fill must surface as an unfilled position.

    PRD 3.8: "An entry is **eligible** when its application's `screening_status` is `ADVANCED` **and** its application's `interview_status` is `COMPLETED`; an application that withdrew, was rejected, or no-showed its interview is therefore ineligible."
    PRD 3.8: "Walking the entries in that order: when the entry is eligible **and** the fill counter is strictly less than the program's `quota_positions`, a `MatchResult` is created with `outcome` `MATCHED` and `matched_rank_position` set to that entry's `rank_position`, and the fill counter increases by one; in every other case a `MatchResult` is created with `outcome` `UNMATCHED` and `matched_rank_position` left null."
    PRD 3.8: "Exactly one `MatchResult` is created per `RankListEntry`, so every ranked application receives a published result; applications that were never ranked receive no `MatchResult` at all."
    PRD 3.8: "Match day is run by the national operator against a certified program, and it drives the program `LIST_CERTIFIED → MATCH_COMPLETE`."

    Design: Corner/calculations/match_day_fills_the_quota_in_rank_order_and_leaves_the_ineligible_entry_unmatched
    """
    builder = setup_issued_invitations(
        applicant_count=2, seat_capacity=2, slot_capacity=2
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
    builder.withdraw_application("app2")
    builder.submit_to_committee()
    builder.cast_vote("f1")
    builder.certify("pd")
    program_id = builder.id("program")

    response = api.run_match(program_id, builder.admin)

    validate_success(response, 200)
    program = get_success_data(api.get_program(program_id, builder.admin))
    assert program["season_phase"] == SeasonPhase.MATCH_COMPLETE, (
        "match day must drive the program to MATCH_COMPLETE, got "
        f"{program['season_phase']}"
    )

    rows, meta = validate_paginated(
        api.list_match_results(builder.admin, params={"program_id": program_id})
    )
    assert meta["total_count"] == 2, (
        "one published result per ranked entry, got total_count "
        f"{meta['total_count']}"
    )

    matched = find_by(rows, application_id=builder.id("app1"))
    assert_match_result(matched)
    assert (
        matched["outcome"] == MatchOutcome.MATCHED
    ), f"the eligible top-ranked entry must be MATCHED, got {matched['outcome']}"
    assert matched["matched_rank_position"] == 1, (
        "matched_rank_position must be the entry's own rank_position, got "
        f"{matched['matched_rank_position']}"
    )
    assert (
        matched["published_at"] is not None
    ), "every created match result carries a published_at stamp"

    unmatched = find_by(rows, application_id=builder.id("app2"))
    assert unmatched["outcome"] == MatchOutcome.UNMATCHED, (
        "the withdrawn application is ineligible and must be UNMATCHED, got "
        f"{unmatched['outcome']}"
    )
    assert unmatched["matched_rank_position"] is None, (
        "an unmatched result leaves matched_rank_position null, got "
        f"{unmatched['matched_rank_position']}"
    )

    assert_position_conservation(program, 1, 1)


# ======================================================================
# Onboarding credential packet
# ======================================================================
def test_pathology_packet_makes_the_dea_optional_and_adds_a_visa_item(api):
    """A J-1 pathology hire gets four items, with DEA optional and VISA mandatory.

    Two independent composition rules meet on one packet: the pathology
    speciality demotes the DEA item without deleting it, and the J-1 visa status
    adds a mandatory fourth item, so exactly three of the four are mandatory.

    PRD 3.9: "A `DEA` item is **always created**, but its `is_mandatory` is true only when the program's `specialty_code` is anything other than `PATH`, and false for pathology programs — the item still exists, it simply does not gate activation."
    PRD 3.9: "A `VISA` item is created **only** when the applicant's `visa_status` is `NEEDS_J1` or `NEEDS_H1B`, and when created it is mandatory."
    PRD 3.9: "`Contract.mandatory_credential_count` is set to the number of created items whose `is_mandatory` is true, and `Contract.verified_credential_count` is set to 0."
    PRD 3.9: "Every created `CredentialItem` names its `contract_id`, holds a `credential_type` that is one of `STATE_LICENSE`, `DEA`, `VISA` or `BLS`, starts in `status` `PENDING` with `reference_number` null and `verified_at` null."

    Design: Corner/calculations/pathology_packet_drops_the_mandatory_dea_and_a_j1_applicant_adds_a_visa_item
    """
    builder = SeasonBuilder()
    builder.create_program(
        name=PATHOLOGY_PROGRAM_NAME,
        nrmp_program_code=PATHOLOGY_PROGRAM_CODE,
        specialty_code=PATHOLOGY_SPECIALTY,
        quota_positions=2,
        visa_sponsorship_allowed=True,
    )
    builder.add_standard_faculty()
    builder.add_applicant(
        "cand1", visa_status=VisaStatus.NEEDS_J1, step2_score=CAND1_STEP2_SCORE
    )
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
    builder.cast_vote("f1")
    builder.certify("pd")
    builder.run_match()
    builder.load_match_result("match1", "app1")

    response = api.create_contract(
        build_contract_payload(builder.id("match1"), DEFAULT_SALARY_CENTS),
        builder.coordinator,
    )

    contract = validate_success(response, 201)
    assert (
        contract["status"] == ContractStatus.ISSUED
    ), f"issuance is atomic, so the row is observable as ISSUED, got {contract['status']}"
    assert_credential_counters(contract, 3, 0)

    rows, meta = validate_paginated(
        api.list_credential_items_of_contract(contract["id"], builder.coordinator)
    )
    assert (
        meta["total_count"] == 4
    ), f"a J-1 candidate's packet holds four items, got total_count {meta['total_count']}"
    assert {row["credential_type"] for row in rows} == {
        CredentialType.STATE_LICENSE,
        CredentialType.BLS,
        CredentialType.DEA,
        CredentialType.VISA,
    }, f"unexpected packet composition: {[row['credential_type'] for row in rows]}"

    expected_mandatory = {
        CredentialType.STATE_LICENSE: True,
        CredentialType.BLS: True,
        CredentialType.VISA: True,
        CredentialType.DEA: False,
    }
    for credential_type, is_mandatory in expected_mandatory.items():
        item = find_by(rows, credential_type=credential_type)
        assert item["is_mandatory"] is is_mandatory, (
            f"{credential_type}.is_mandatory should be {is_mandatory} for a J-1 "
            f"pathology hire, got {item['is_mandatory']}"
        )
        assert item["status"] == CredentialItemStatus.PENDING, (
            f"{credential_type} must start PENDING, got {item['status']}"
        )
        assert item["reference_number"] is None, (
            f"{credential_type} must start with a null reference_number, got "
            f"{item['reference_number']!r}"
        )
        assert (
            item["verified_at"] is None
        ), f"{credential_type} must start with a null verified_at, got {item['verified_at']!r}"


# ======================================================================
# Pre-match communication compliance scan
# ======================================================================
def test_a_prohibited_phrase_is_flagged_while_a_neutral_body_stays_clean(api):
    """A ranking-intent phrase in mixed case is flagged; a neutral body is clean.

    The scan is a case-insensitive substring test, so mixed-case wording must not
    escape it, and both rows are created regardless of the verdict.

    PRD 3.10: "The `body` is lowercased, and `contains_ranking_intent` is set true when the lowercased text contains any of five fixed prohibited phrases as a plain substring: "how will you rank", "rank us", "commit to us", "where will we be on your list", or "ranking intent"."
    PRD 3.10: "When the body contains ranking intent **and** the contact is pre-match, `compliance_status` is set to `FLAGGED`; in every other combination it is set to `CLEAN`."
    PRD 3.10: "`sent_at` is stamped with the current logical clock instant."
    PRD 3.10: "The row is **always** created and the response is 201 Created even when the verdict is `FLAGGED` — the flag is an audit record, not a rejection."

    Design: Corner/calculations/a_prohibited_ranking_phrase_lands_flagged_while_a_neutral_body_lands_clean
    """
    builder = setup_staffed_program(1)
    builder.open_review()
    builder.add_application("app1", "cand1")
    application_id = builder.id("app1")
    author_id = builder.id("pd")

    flagged_response = api.create_communication_log(
        build_communication_log_payload(
            application_id,
            FLAGGED_BODY,
            channel=CommunicationChannel.EMAIL,
            author_faculty_id=author_id,
        ),
        builder.director("pd"),
    )
    clean_response = api.create_communication_log(
        build_communication_log_payload(
            application_id,
            CLEAN_BODY,
            channel=CommunicationChannel.EMAIL,
            author_faculty_id=author_id,
        ),
        builder.director("pd"),
    )

    flagged = validate_success(flagged_response, 201)
    clean = validate_success(clean_response, 201)

    assert flagged["contains_ranking_intent"] is True, (
        "'How Will You Rank' must match the prohibited phrase case-insensitively, got "
        f"contains_ranking_intent {flagged['contains_ranking_intent']}"
    )
    assert flagged["compliance_status"] == ComplianceStatus.FLAGGED, (
        "ranking intent logged in REVIEW_OPEN is pre-match and must be FLAGGED, got "
        f"{flagged['compliance_status']}"
    )
    assert _normalise_instant(flagged["sent_at"]) == _normalise_instant(
        CLOCK_SEASON_START
    ), f"sent_at must come from the logical clock, got {flagged['sent_at']!r}"

    assert clean["contains_ranking_intent"] is False, (
        "the neutral body contains no prohibited phrase, got contains_ranking_intent "
        f"{clean['contains_ranking_intent']}"
    )
    assert (
        clean["compliance_status"] == ComplianceStatus.CLEAN
    ), f"a body without ranking intent is CLEAN, got {clean['compliance_status']}"

    rows, meta = validate_paginated(
        api.list_communication_logs(
            builder.officer, params={"compliance_status": ComplianceStatus.FLAGGED}
        )
    )
    assert meta["total_count"] == 1, (
        "exactly one of the two contacts is flagged, got total_count "
        f"{meta['total_count']}"
    )
    assert rows[0]["id"] == flagged["id"], (
        "the flagged filter must return the ranking-intent contact, got "
        f"{rows[0]['id']!r}"
    )


# ======================================================================
# Freed-seat cascade with nobody to promote
# ======================================================================
def test_declining_with_an_empty_waitlist_frees_the_seat_without_promoting(api):
    """A post-acceptance decline frees the seat and promotes nobody when none waits.

    The four-hop cascade must still run its seat and counter arithmetic when the
    candidate set is empty, and the empty waitlist is not an error.

    PRD 3.4: "Declining an invitation that is already `ACCEPTED` drives `ACCEPTED → DECLINED`, adds the requirement that the logical clock be strictly before the booked slot's `start_at`, and fires the system's flagship four-hop cascade: **hop 1** decrements the booked slot's `booked_count` by one and returns that slot `BOOKED → OPEN` when `booked_count` falls below `applicant_capacity`; **hop 2** treats that freed seat as an opening and promotes the waitlist winner `WAITLISTED → ISSUED`; **hop 3** advances the promoted invitation's own application `NOT_INVITED → INVITED`; **hop 4** recomputes `Program.invited_count` from the changed set of invited applications."
    PRD 3.4: "When the candidate set is empty, no promotion occurs, the freed seat simply stays available, and this is **not** an error."
    PRD 3.4: "The declining application itself reverts `SCHEDULED → NOT_INVITED` when it retains no invitation in `ISSUED`, `WAITLISTED` or `ACCEPTED`."

    Design: Corner/calculations/declining_with_an_empty_waitlist_frees_the_seat_without_promoting_anyone
    """
    builder = setup_accepted_invitation(
        applicant_count=1, seat_capacity=1, slot_capacity=1
    )
    wave_id = builder.id("wave1")
    slot_id = builder.id("slot1")

    booked = get_success_data(api.get_interview_slot(slot_id, builder.coordinator))
    assert_slot_booking(booked, 1, SlotStatus.BOOKED)
    wave = get_success_data(api.get_interview_wave(wave_id, builder.coordinator))
    assert_wave_seat_conservation(wave, 1)

    response = api.decline_interview_invitation(
        builder.id("inv1"), builder.applicant("cand1")
    )

    data = validate_success(response, 200)
    assert (
        data["status"] == InvitationStatus.DECLINED
    ), f"the accepted invitation must become DECLINED, got {data['status']}"

    wave = get_success_data(api.get_interview_wave(wave_id, builder.coordinator))
    assert_wave_seat_conservation(wave, 0)

    slot = get_success_data(api.get_interview_slot(slot_id, builder.coordinator))
    assert_slot_booking(slot, 0, SlotStatus.OPEN)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.NOT_INVITED, (
        "the declining application retains no live invitation and reverts to "
        f"NOT_INVITED, got {application['interview_status']}"
    )
    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert (
        program["invited_count"] == 0
    ), f"Program.invited_count must be recomputed to 0, got {program['invited_count']}"

    rows, meta = validate_paginated(
        api.list_interview_invitations(
            builder.coordinator, params={"wave_id": wave_id}
        )
    )
    assert meta["total_count"] == 1, (
        "no promotion means no further invitation exists in the wave, got "
        f"total_count {meta['total_count']}"
    )
    assert rows[0]["status"] == InvitationStatus.DECLINED, (
        "the wave's only invitation is the declined one, got " f"{rows[0]['status']}"
    )


# ======================================================================
# Read-your-write on the screening composite
# ======================================================================
def test_the_screening_response_already_carries_the_score_it_computed(api):
    """The screening response body carries the final score, and the read-back agrees.

    The composite is written by this very transition, so returning a body whose
    final_screen_score is still null and only materialising it on the next read
    would break read-your-write consistency.

    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD 3.2: "Both branches carry the identical single side effect: `Application.final_screen_score` is written using Variant B."
    PRD 3.2: "`final_screen_score` is **Variant B**: the base plus the Step 2 band bonus plus the pipeline bonus, then capped at a ceiling of 40.0, then rounded half up to two decimal places once at the end."
    PRD 3.2: "`provisional_screen_score` is **Variant A**: the base alone, rounded half up to two decimal places, with the rounding applied once at the very end."

    Design: Corner/consistency_model/the_screening_response_body_already_carries_the_final_score_it_computed
    """
    builder = setup_reviewed_application(applicant_count=1, review_count=2)
    application_id = builder.id("app1")

    response = api.screen_application(
        application_id,
        build_screen_payload(ScreeningDecision.ADVANCE),
        builder.coordinator,
    )

    data = validate_success(response, 200)
    assert data["screening_status"] == ScreeningStatus.ADVANCED, (
        "an advance decision drives the paper dimension to ADVANCED, got "
        f"{data['screening_status']}"
    )
    assert (
        data["review_count"] == 2
    ), f"the composite was computed over two reviews, got review_count {data['review_count']}"
    assert_score_equals(
        data["final_screen_score"],
        expected_final_score(STANDARD_REVIEWS, CAND1_STEP2_SCORE, CAND1_PIPELINE_ALUM),
        "Application.final_screen_score in the screening response body",
    )
    assert_score_equals(
        data["provisional_screen_score"],
        expected_provisional_score(STANDARD_REVIEWS),
        "Application.provisional_screen_score in the screening response body",
    )

    read_back = get_success_data(
        api.get_application(application_id, builder.coordinator)
    )
    assert read_back["screening_status"] == data["screening_status"], (
        "the read-back must report the same screening_status the transition "
        f"returned: {read_back['screening_status']} != {data['screening_status']}"
    )
    assert_score_equals(
        read_back["final_screen_score"],
        data["final_screen_score"],
        "Application.final_screen_score read back after screening",
    )
