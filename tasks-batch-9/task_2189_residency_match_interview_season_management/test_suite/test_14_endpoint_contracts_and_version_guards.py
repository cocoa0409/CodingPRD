"""Endpoint contracts: coherence, load recomputation, phase gating, stale versions.

Each test drives one declared operation to its stated outcome and then checks
every row the operation was supposed to touch — and, on a refusal, every row it
was supposed to leave alone. The last two replay a version token an earlier write
already superseded, then resend the identical body with a freshly read one.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_faculty_member,
    assert_score_equals,
    assert_slot_booking,
)
from test_helpers.constants import (
    CLOCK_AFTER_INTERVIEW,
    CLOCK_RANKING_DAY,
    CLOCK_WAVE_RELEASE,
    LEAD_INTERVIEWER_NAME,
)
from test_helpers.factories import (
    build_accept_invitation_payload,
    build_faculty_member_payload,
    build_invitation_payload,
    build_rank_list_entry_payload,
    build_soap_offer_payload,
)
from test_helpers.fixtures import (
    SCORES_FOURTH,
    SCORES_LEAD,
    SCORES_MEMBER,
    SCORES_THIRD,
    setup_issued_invitations,
    setup_planned_wave,
    setup_program,
    setup_released_wave,
    setup_reviewed_application,
    setup_screened_application,
)
from test_helpers.types import (
    AssignmentStatus,
    Ballot,
    InterviewStatus,
    InvitationStatus,
    SeasonPhase,
    SlotStatus,
)

# ======================================================================
# POST /interview-invitations/{id}/accept — cross-aggregate coherence
# ======================================================================


def test_accepting_into_a_slot_from_another_wave_is_a_cross_reference_mismatch(api):
    """Booking a slot that belongs to a different wave is a cross-reference mismatch.

    Both rows exist and the applicant owns the invitation, so neither the
    existence check nor the ownership check fires: the only defect is that the
    slot hangs off wave 2 while the invitation was issued by wave 1. That must
    read as a coherence breach rather than a 404, and the untouched wave 2 slot
    must keep an empty seat pool.

    PRD 3.4: "Six conditions gate it: the acting applicant's `id` equals the `applicant_id` of the invitation's application; the logical clock is strictly before the invitation's `expires_at`, otherwise `ERR_INVITATION_EXPIRED`; the wave's `status` is `RELEASED`; the requested slot's `wave_id` equals the invitation's own `wave_id`, otherwise `ERR_CROSS_REFERENCE_MISMATCH`; the requested slot's `status` is neither `COMPLETED` nor `CANCELLED`; and no other invitation for the same `application_id` is already `ACCEPTED`."
    PRD 3.4: "An invitation's `slot_id` is null whenever its `status` is `ISSUED`, `WAITLISTED`, `DECLINED`, `EXPIRED` or `WITHDRAWN`; it holds a value only while the invitation is `ACCEPTED`."
    PRD 2.10: "For every `InterviewSlot`, `applicant_capacity` minus `booked_count` is the free seat pool, where `booked_count` is the number of `InterviewInvitation` rows whose `slot_id` is this slot and whose `status` is `ACCEPTED`."

    Design: Corner/endpoints/accepting_into_a_slot_from_another_wave_is_a_cross_reference_mismatch
    """
    builder = setup_issued_invitations(
        applicant_count=1, seat_capacity=1, slot_capacity=1
    )
    builder.create_wave(
        "wave2",
        wave_index=2,
        invite_release_at="2026-10-10T12:00:00Z",
        response_deadline_at="2026-10-15T12:00:00Z",
        seat_capacity=1,
    )
    builder.create_slot(
        "slot2",
        "wave2",
        start_at="2026-10-12T13:00:00Z",
        end_at="2026-10-12T16:00:00Z",
        room_label="B-2",
        applicant_capacity=1,
    )

    response = api.accept_interview_invitation(
        builder.id("inv1"),
        build_accept_invitation_payload(builder.id("slot2")),
        builder.applicant("cand1"),
    )

    validate_error(response, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)

    invitation = validate_success(
        api.get_interview_invitation(builder.id("inv1"), builder.coordinator), 200
    )
    assert (
        invitation["status"] == InvitationStatus.ISSUED
    ), f"the refused invitation must still be ISSUED, got {invitation['status']}"
    assert (
        invitation["slot_id"] is None
    ), "an ISSUED invitation must carry a null slot_id after a refused accept"

    foreign_slot = validate_success(
        api.get_interview_slot(builder.id("slot2"), builder.coordinator), 200
    )
    assert_slot_booking(foreign_slot, 0, SlotStatus.OPEN)

    application = validate_success(
        api.get_application(builder.id("app1"), builder.coordinator), 200
    )
    assert (
        application["interview_status"] == InterviewStatus.INVITED
    ), f"the application must stay INVITED, got {application['interview_status']}"


# ======================================================================
# POST /interview-assignments/{id}/release — load recomputation
# ======================================================================


def test_releasing_a_panel_seat_drops_that_faculty_members_scheduled_load_to_zero(api):
    """Releasing a LEAD seat recomputes that member's scheduled load to zero.

    The declared side effect is a recomputation over the remaining ASSIGNED
    seats, not a subtraction: the three-hour block weighted 1.5 for LEAD gives
    4.50 before the release and 0.00 after, while the MEMBER seat on the very
    same block keeps its 3.00 untouched and the released row itself remains
    listable.

    PRD 3.5: "Releasing an interviewer drives the assignment `ASSIGNED → RELEASED` and recomputes that member's `scheduled_load`."
    PRD 3.5: "`scheduled_load` is the **forward-looking** variant: over every `ASSIGNED` assignment of this faculty member whose slot's `status` is `OPEN` or `BOOKED`, take the block's duration in hours multiplied by that seat's role weight, add those products together, and round the total half up to two decimal places once at the end."
    PRD 3.5: "`RELEASED` assignments are excluded from both variants entirely."

    Design: Corner/endpoints/releasing_a_panel_seat_drops_that_faculty_members_scheduled_load_to_zero
    """
    builder = setup_planned_wave(applicant_count=1, seat_capacity=1, slot_capacity=1)
    lead_id = builder.id("f1")
    member_id = builder.id("f2")

    lead_before = validate_success(
        api.get_faculty_member(lead_id, builder.coordinator), 200
    )
    assert_faculty_member(lead_before)
    assert_score_equals(
        lead_before["scheduled_load"], 4.50, "FacultyMember.scheduled_load before release"
    )
    member_before = validate_success(
        api.get_faculty_member(member_id, builder.coordinator), 200
    )
    assert_score_equals(
        member_before["scheduled_load"],
        3.00,
        "the MEMBER seat's scheduled_load before release",
    )

    response = api.release_interview_assignment(
        builder.id("asg1"), builder.coordinator
    )

    released = validate_success(response, 200)
    assert (
        released["status"] == AssignmentStatus.RELEASED
    ), f"the released seat must read RELEASED, got {released['status']}"

    lead_after = validate_success(
        api.get_faculty_member(lead_id, builder.coordinator), 200
    )
    assert_score_equals(
        lead_after["scheduled_load"],
        0.00,
        "FacultyMember.scheduled_load after the only seat was released",
    )
    assert_score_equals(
        lead_after["realized_load"],
        0.00,
        "FacultyMember.realized_load while the block has not run",
    )

    member_after = validate_success(
        api.get_faculty_member(member_id, builder.coordinator), 200
    )
    assert_score_equals(
        member_after["scheduled_load"],
        3.00,
        "the MEMBER seat's scheduled_load must be unchanged by the other release",
    )

    _, meta = validate_paginated(
        api.list_interview_assignments(
            builder.coordinator, params={"slot_id": builder.id("slot1")}
        )
    )
    assert (
        meta["total_count"] == 2
    ), f"releasing a seat must not delete the row, got {meta['total_count']} of 2"


# ======================================================================
# POST /soap-offers — the season phase gate
# ======================================================================


def test_a_soap_offer_before_the_program_enters_soap_active_is_rejected(api):
    """A SOAP offer extended while the program is still MATCH_COMPLETE is refused.

    Every other condition the offer names already holds — soap_participating is
    true, one position is unfilled, and the target application owns an UNMATCHED
    result — so the phase gate alone must reject the call, and no offer row may
    be created one advance short of SOAP_ACTIVE.

    PRD 3.8: "Three contextual conditions apply: the program must be in `SOAP_ACTIVE`, `Program.soap_participating` must be true, and a `MatchResult` must already exist for this application under this program with `outcome` `UNMATCHED`."
    PRD 2.4: "When the governing `Program` is in a phase that does not permit the operation being requested, the refusal is `ERR_INVALID_STATE` (HTTP 409) — the same code used when a resource's own state field does not admit the requested transition."
    PRD 3.8: "After the walk, `Program.matched_count` is set to the number of `MatchResult` rows whose `outcome` is `MATCHED`, `Program.unfilled_positions` is set to `quota_positions` minus `matched_count`, and the program's `version` increments by one."

    Design: Corner/endpoints/a_soap_offer_before_the_program_enters_soap_active_is_rejected
    """
    builder = setup_screened_application(applicant_count=2, quota_positions=1)
    builder.open_interviews()
    builder.create_wave(seat_capacity=2)
    builder.create_slot(applicant_capacity=2)
    builder.staff_standard_panel()
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    builder.issue_invitation("inv1", "app1")
    builder.issue_invitation("inv2", "app2")
    builder.accept_invitation("inv1", "slot1", "cand1")
    builder.accept_invitation("inv2", "slot1", "cand2")
    builder.clock(CLOCK_AFTER_INTERVIEW)
    builder.complete_slot()
    builder.add_score_card("sc1", "asg1", "app1", "f1", SCORES_LEAD)
    builder.add_score_card("sc2", "asg1b", "app1", "f2", SCORES_MEMBER)
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
    builder.cast_vote("f1", Ballot.APPROVE)
    builder.certify("pd")
    builder.run_match()
    program_id = builder.id("program")

    response = api.create_soap_offer(
        build_soap_offer_payload(program_id, builder.id("app1"), 1),
        builder.director("pd"),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    program = validate_success(api.get_program(program_id, builder.admin), 200)
    assert (
        program["season_phase"] == SeasonPhase.MATCH_COMPLETE
    ), f"the refused offer must leave the program in MATCH_COMPLETE, got {program['season_phase']}"
    assert (
        program["unfilled_positions"] == 1
    ), f"the program's single position must remain unfilled, got {program['unfilled_positions']}"

    _, meta = validate_paginated(
        api.list_soap_offers(builder.coordinator, params={"program_id": program_id})
    )
    assert (
        meta["total_count"] == 0
    ), f"no SoapOffer row may be created before SOAP_ACTIVE, found {meta['total_count']}"


# ======================================================================
# POST /faculty-members — create, read and filtered list
# ======================================================================


def test_faculty_member_create_and_read_back_round_trip(api):
    """A registered faculty member reads back unchanged and answers the committee filter.

    The committee flag must survive the round trip, both load figures must start
    at 0.00 rather than null, the conflict array must come back as the empty
    array the default declares, and the boolean list filter must actually
    select the row.

    PRD 3.1: "Faculty are registered per program, by a coordinator or by the national operator, against the program's `program_id` and with a non-empty `full_name`."
    PRD 3.5: "`scheduled_load` is the **forward-looking** variant: over every `ASSIGNED` assignment of this faculty member whose slot's `status` is `OPEN` or `BOOKED`, take the block's duration in hours multiplied by that seat's role weight, add those products together, and round the total half up to two decimal places once at the end."
    PRD 3.5: "`realized_load` is the **retrospective** variant: over every `ASSIGNED` assignment of this faculty member whose slot's `status` is `COMPLETED`, take the block's duration in hours multiplied by that seat's role weight multiplied by that block's **attendance factor**, add those products together, and round the total half up to two decimal places once at the end."
    PRD 3.1: "Faculty listings accept `program_id`, `is_program_director` and `is_committee_member` filters."

    Design: Corner/endpoints/faculty_member_create_and_read_back_round_trip
    """
    builder = setup_program()
    program_id = builder.id("program")

    created = validate_success(
        api.create_faculty_member(
            build_faculty_member_payload(
                program_id,
                full_name=LEAD_INTERVIEWER_NAME,
                is_program_director=False,
                is_committee_member=True,
                conflict_applicant_ids=[],
            ),
            builder.coordinator,
        ),
        201,
    )
    faculty_id = created["id"]

    read_back = validate_success(
        api.get_faculty_member(faculty_id, builder.coordinator), 200
    )
    assert_faculty_member(read_back)
    assert (
        read_back["id"] == faculty_id
    ), "the read-back must carry the created faculty member's id"
    assert (
        read_back["program_id"] == program_id
    ), "the stored program_id must survive the round trip"
    assert (
        read_back["full_name"] == LEAD_INTERVIEWER_NAME
    ), f"full_name must survive the round trip, got {read_back['full_name']!r}"
    assert (
        read_back["is_committee_member"] is True
    ), "is_committee_member must survive the round trip as true"
    assert (
        read_back["is_program_director"] is False
    ), "is_program_director must survive the round trip as false"
    assert (
        read_back["conflict_applicant_ids"] == []
    ), f"conflict_applicant_ids must read as the empty array, got {read_back['conflict_applicant_ids']!r}"
    assert_score_equals(
        read_back["scheduled_load"], 0.00, "a fresh FacultyMember.scheduled_load"
    )
    assert_score_equals(
        read_back["realized_load"], 0.00, "a fresh FacultyMember.realized_load"
    )

    rows, meta = validate_paginated(
        api.list_faculty_members(
            builder.coordinator, params={"is_committee_member": "true"}
        )
    )
    assert (
        meta["total_count"] == 1
    ), f"the committee filter must select exactly the one member, got {meta['total_count']}"
    assert (
        rows[0]["id"] == faculty_id
    ), "the filtered row must be the committee member just registered"


# ======================================================================
# Optimistic concurrency guards on the two versioned parents
# ======================================================================


def test_a_stale_rank_list_version_is_refused_then_the_refreshed_one_succeeds(api):
    """Replaying the version the first append consumed is refused at 412.

    The first append consumed version 1 and bumped the list to version 2, so the
    second append carrying version 1 must be refused under the distinct 412 status
    and must write nothing; the identical body with a freshly read version succeeds.

    PRD 2.9: "A `POST /rank-lists/{id}/entries` request must carry `expected_rank_list_version` as a required, non-optional field, holding the `version` of the target `RankList` as the client last observed it."
    PRD 2.9: "If that value does not equal the list's current `version`, the append is rejected with `ERR_STALE_RANK_LIST_VERSION` (HTTP 412)."
    PRD 3.7: "Appending an entry creates the row, increments `RankList.entry_count` by one, and increments `RankList.version` by one."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_rank_list_version_is_refused_and_the_refreshed_one_succeeds
    """
    builder = setup_reviewed_application(1, quota_positions=1)
    builder.screen("app1")
    builder.add_applicant("cand2")
    builder.add_application("app2", "cand2")
    builder.open_interviews()
    builder.open_ranking()
    builder.create_rank_list()
    stale_version = builder.rows["rank_list"]["version"]
    builder.add_entry("entry1", "app1", 1)

    payload = build_rank_list_entry_payload(builder.id("app2"), 2, stale_version)
    refused = api.create_rank_list_entry(
        builder.id("rank_list"), payload, builder.director("pd")
    )
    validate_error(refused, ApiErrorId.ERR_STALE_RANK_LIST_VERSION)

    after_refusal = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert after_refusal["entry_count"] == 1, (
        "the stale append must write nothing, so entry_count should still be 1, got "
        f"{after_refusal['entry_count']}"
    )
    assert after_refusal["version"] > stale_version, (
        "the first append already advanced the list, so the re-read version must be "
        f"strictly greater than {stale_version}, got {after_refusal['version']}"
    )

    accepted = validate_success(
        api.create_rank_list_entry(
            builder.id("rank_list"),
            build_rank_list_entry_payload(
                builder.id("app2"), 2, after_refusal["version"]
            ),
            builder.director("pd"),
        ),
        201,
    )
    assert accepted["rank_position"] == 2, (
        "the identical body with a current version must append at position 2, got "
        f"{accepted['rank_position']}"
    )

    final = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert final["entry_count"] == 2, (
        f"the list must now hold two entries, got {final['entry_count']}"
    )


def test_a_stale_wave_version_is_refused_under_its_own_error_id(api):
    """The same priority-6 guard on the wave reports the wave's own error id.

    The wave's version advances on the invitation write as well as on the release, so
    the token the release call returned is already one behind; the refusal must be
    distinguishable from the rank list guard and must consume no seat.

    PRD 2.9: "A `POST /interview-waves/{id}/invitations` request must carry `expected_wave_version` as a required, non-optional field, holding the `version` of the target `InterviewWave` as the client last observed it."
    PRD 2.9: "If that value does not equal the wave's current `version`, the issue is rejected with `ERR_STALE_WAVE_VERSION` (HTTP 412)."
    PRD 2.12: "This is the same check as the row above, instantiated on the other parent; the two share priority 6."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_wave_version_is_refused_under_its_own_error_id
    """
    builder = setup_released_wave(applicant_count=2, seat_capacity=2, slot_capacity=2)
    stale_version = builder.wave_version
    builder.issue_invitation("inv1", "app1")

    refused = api.create_interview_invitation(
        builder.id("wave1"),
        build_invitation_payload(builder.id("app2"), stale_version),
        builder.coordinator,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_WAVE_VERSION)

    after_refusal = get_success_data(
        api.get_interview_wave(builder.id("wave1"), builder.coordinator)
    )
    assert after_refusal["issued_count"] == 1, (
        "the stale issue must consume no seat, so issued_count should still be 1, got "
        f"{after_refusal['issued_count']}"
    )
    assert after_refusal["version"] > stale_version, (
        "the first issue already advanced the wave, so the re-read version must be "
        f"strictly greater than {stale_version}, got {after_refusal['version']}"
    )

    application = get_success_data(
        api.get_application(builder.id("app2"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.NOT_INVITED, (
        "the refused issue must leave the second application NOT_INVITED, got "
        f"{application['interview_status']}"
    )

    accepted = validate_success(
        api.create_interview_invitation(
            builder.id("wave1"),
            build_invitation_payload(builder.id("app2"), after_refusal["version"]),
            builder.coordinator,
        ),
        201,
    )
    assert accepted["status"] == InvitationStatus.ISSUED, (
        "the second seat is still free, so the resent issue must land as ISSUED, got "
        f"{accepted['status']}"
    )

    wave = get_success_data(
        api.get_interview_wave(builder.id("wave1"), builder.coordinator)
    )
    assert wave["issued_count"] == 2, (
        f"both seats must now be consumed, got issued_count {wave['issued_count']}"
    )
    program = get_success_data(
        api.get_program(builder.id("program"), builder.coordinator)
    )
    assert program["invited_count"] == 2, (
        f"the program must count two invited applications, got {program['invited_count']}"
    )
