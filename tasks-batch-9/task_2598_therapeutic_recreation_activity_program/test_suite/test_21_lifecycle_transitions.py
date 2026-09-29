"""Lifecycle-transition corner cases across the department's state machines.

Every test drives the live API over real HTTP against an empty database whose
logical clock reads 2026-08-01T00:00:00Z, and moves the clock only forward.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_values
from test_helpers.test_users import COMPLIANCE_USER_ID, DIRECTOR_USER_ID


def test_session_starts_in_scheduled_initial_state(api, director):
    """A calendar slot is born SCHEDULED with nothing documented and no
    cancellation reason, whatever the client sends.

    PRD §3.4: "Sessions are created in `SCHEDULED` status with `enrolled_count`
    at 0, `weighted_supervision_load` at 0.0, `required_staff_count` at 0, and
    `documented_at` null."

    Design: Corner/state_machines/session_starts_in_scheduled_initial_state
    """
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Initial State Program",
            "domain": "PHYSICAL",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Initial State Room", "capacity": 10, "buffer_minutes": 0},
    )

    created = validate_success(
        api.create_session(
            f.session_payload(
                program["id"],
                room["id"],
                starts_at="2026-08-23T10:00:00Z",
                ends_at="2026-08-23T11:00:00Z",
                assigned_staff_count=2,
            ),
            director,
        ),
        201,
    )

    session = validate_success(api.get_session(created["id"], director), 200)
    assert_values(
        session,
        status="SCHEDULED",
        documented_at=None,
        cancel_reason=None,
        version=1,
    )


def test_session_close_documentation_from_scheduled_returns_4XX(api, director, aide):
    """Closing documentation on a slot that has not started is refused and the
    enrolled resident's row is not finalized.

    PRD §3.4: "any action not admitted by the present status is refused with
    `ERR_SESSION_INVALID_STATE`."

    Design: Corner/state_machines/session_close_documentation_from_scheduled_returns_4XX
    """
    resident, _assessment = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Invalid Trigger Ida",
            "room_number": "112B",
            "admission_date": "2026-07-12",
        },
        interest_domains=["SOCIAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-12",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Invalid Trigger Program",
            "domain": "SOCIAL",
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={
            "name": "Invalid Trigger Room",
            "capacity": 10,
            "buffer_minutes": 0,
        },
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-24T10:00:00Z",
        ends_at="2026-08-24T11:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])

    validate_error(
        api.session_status(session["id"], {"action": "CLOSE_DOCUMENTATION"}, aide),
        ApiErrorId.SESSION_INVALID_STATE.value,
        409,
    )

    stored_session = fx.read_session(api, session["id"])
    assert_values(stored_session, status="SCHEDULED", documented_at=None)
    stored_record = fx.read_record(api, record["id"])
    assert_values(stored_record, status="PLANNED", outcome="PLANNED")


def test_session_start_after_cancel_returns_4XX(api, director, aide):
    """CANCELLED is the end of a slot's road: neither a start nor a second
    cancellation leaves it, and the first cancellation reason stands.

    PRD §3.4: "A session's lifecycle runs `SCHEDULED`, `IN_PROGRESS`,
    `DOCUMENTED`, and `CANCELLED`, with the last two terminal."

    Design: Corner/state_machines/session_start_after_cancel_returns_4XX
    """
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Lockdown Program",
            "domain": "PHYSICAL",
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Lockdown Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-25T10:00:00Z",
        ends_at="2026-08-25T11:00:00Z",
    )
    fx.cancel_session(api, session["id"], cancel_reason="Room flooded")

    validate_error(
        api.session_status(session["id"], {"action": "START"}, aide),
        ApiErrorId.SESSION_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.session_status(
            session["id"], {"action": "CANCEL", "cancel_reason": "Second try"}, director
        ),
        ApiErrorId.SESSION_INVALID_STATE.value,
        409,
    )

    stored = fx.read_session(api, session["id"])
    assert_values(stored, status="CANCELLED", cancel_reason="Room flooded")


def test_participation_second_documentation_rejected(api, director, aide):
    """Documenting a resident's outcome is one-shot: replaying the call on an
    already-documented row is refused and the engagement window is not
    double-counted.

    PRD §3.6: "the record must still be `PLANNED`, so a record already
    `ATTENDED`, `REFUSED`, `ABSENT`, `FINALIZED`, or `VOID` rejects any further
    documentation with `ERR_PARTICIPATION_INVALID_STATE`".

    Design: Corner/state_machines/participation_second_documentation_rejected
    """
    resident, _assessment = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Idem Ike",
            "room_number": "113A",
            "admission_date": "2026-07-13",
        },
        interest_domains=["SOCIAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-13",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Idem Program",
            "domain": "SOCIAL",
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Idem Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T10:00:00Z",
        ends_at="2026-08-03T11:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    fx.advance_clock(api, "2026-08-03T10:00:00Z")
    fx.start_session(api, session["id"])
    fx.document_attendance(api, record["id"], engagement_level="ACTIVE")

    validate_error(
        api.document_participation(
            record["id"], f.attendance_payload(engagement_level="LEADING"), aide
        ),
        ApiErrorId.PARTICIPATION_INVALID_STATE.value,
        409,
    )

    stored = fx.read_record(api, record["id"])
    assert_values(stored, status="ATTENDED", outcome="ATTENDED", engagement_level="ACTIVE")
    stored_resident = fx.read_resident(api, resident["id"])
    assert stored_resident["engagement_index"] == 0.75, (
        "The one ACTIVE attendance is worth 3 of 4 points, so the index stays "
        f"0.75, got {stored_resident['engagement_index']!r}"
    )


def test_session_start_without_enrollments_rejected(api, director, aide):
    """A slot whose roster is empty cannot be started even once the clock has
    reached its start instant.

    PRD §3.4: "a session whose roster holds no participation row in a status
    other than `VOID` cannot be run and is refused with
    `ERR_SESSION_HAS_NO_ENROLLMENTS`."

    Design: Corner/state_machines/session_start_without_enrollments_rejected
    """
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Empty Session Program",
            "domain": "SPIRITUAL",
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={
            "name": "Empty Session Room",
            "capacity": 10,
            "buffer_minutes": 0,
        },
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T14:00:00Z",
        ends_at="2026-08-03T15:00:00Z",
    )
    fx.advance_clock(api, "2026-08-03T14:00:00Z")

    validate_error(
        api.session_status(session["id"], {"action": "START"}, aide),
        ApiErrorId.SESSION_HAS_NO_ENROLLMENTS.value,
        409,
    )

    stored = fx.read_session(api, session["id"])
    assert_values(stored, status="SCHEDULED", enrolled_count=0)


def test_close_documentation_finalizes_children_and_stamps_source(api, director, aide):
    """Closing documentation finalizes every documented roster row, preserving
    the branch each one came from, and leaves the outcome every calculation reads
    unchanged.

    PRD §3.6: "Every participation row on the session whose `status` is
    `ATTENDED`, `REFUSED`, or `ABSENT` then transitions to `FINALIZED`, and each
    one preserves the branch it came from in `finalized_from`."

    Design: Corner/state_machines/close_documentation_finalizes_children_and_stamps_source
    """
    resident_a, _asmt_a = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Finalize A",
            "room_number": "320A",
            "admission_date": "2026-07-14",
        },
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-14",
    )
    resident_b, _asmt_b = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Finalize B",
            "room_number": "320B",
            "admission_date": "2026-07-14",
        },
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-14",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Finalize Program",
            "domain": "SOCIAL",
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Finalize Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T14:00:00Z",
        ends_at="2026-08-03T15:00:00Z",
    )
    record_a = fx.enroll(api, session["id"], resident_a["id"])
    record_b = fx.enroll(api, session["id"], resident_b["id"])
    fx.advance_clock(api, "2026-08-03T14:00:00Z")
    fx.start_session(api, session["id"])
    fx.document_attendance(api, record_a["id"], engagement_level="PARTIAL")
    fx.document_refusal(api, record_b["id"], refusal_reason="MOOD")

    validate_success(
        api.session_status(session["id"], {"action": "CLOSE_DOCUMENTATION"}, aide), 200
    )

    stored_session = fx.read_session(api, session["id"])
    assert_values(
        stored_session, status="DOCUMENTED", documented_at="2026-08-03T14:00:00.000Z"
    )
    stored_a = fx.read_record(api, record_a["id"])
    assert_values(
        stored_a, status="FINALIZED", finalized_from="ATTENDED", outcome="ATTENDED"
    )
    stored_b = fx.read_record(api, record_b["id"])
    assert_values(
        stored_b, status="FINALIZED", finalized_from="REFUSED", outcome="REFUSED"
    )
    assert fx.read_resident(api, resident_a["id"])["engagement_index"] == 0.5, (
        "One PARTIAL attendance is worth 2 of 4 points, so the index reads 0.5"
    )
    assert fx.read_resident(api, resident_b["id"])["refusal_streak"] == 1


def test_volunteer_expire_withdraws_confirmed_assignments(api, director, coordinator):
    """Letting a volunteer's background check lapse withdraws the shift they were
    confirmed on, stamping the clearance cause, and empties their forward-looking
    weekly commitment without touching the session or its roster.

    PRD §3.7: "every assignment they hold whose `status` is `PROPOSED` or
    `CONFIRMED` is withdrawn with `withdrawn_reason` stamped to
    `CLEARANCE_EXPIRED`; each withdrawal recomputes the volunteer's
    `scheduled_hours_week`."

    Design: Corner/state_machines/volunteer_expire_withdraws_confirmed_assignments
    """
    resident, _assessment = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Cascade Resident",
            "room_number": "114A",
            "admission_date": "2026-07-15",
        },
        interest_domains=["CREATIVE"],
        preferred_group_size="SMALL",
        effective_date="2026-07-15",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Expiry Craft",
            "domain": "CREATIVE",
            "max_group_size": 10,
            "max_supervision_tier": "TIER_2",
            "volunteer_eligible": True,
            "required_screening_level": "BASIC",
        },
        room_kwargs={"name": "Expiry Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2027-06-30T10:00:00Z",
        ends_at="2027-06-30T12:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    volunteer = fx.cleared_volunteer(
        api,
        cleared_on="2026-07-01",
        completed_on="2026-07-05",
        full_name="Expiring Erin",
        volunteer_type="ADULT_COMMUNITY",
    )
    assert volunteer["background_check_expires_on"] == "2027-07-01", (
        "A clearance dated 2026-07-01 expires 365 days later, got "
        f"{volunteer['background_check_expires_on']!r}"
    )

    fx.advance_clock(api, "2027-07-02T00:00:00Z")
    assignment = fx.assign_volunteer(
        api, volunteer["id"], session["id"], role_type="GROUP_ASSISTANT"
    )
    hours_before = fx.read_volunteer(api, volunteer["id"])["scheduled_hours_week"]
    assert hours_before == 2.0, (
        "The two-hour shift sits inside the ISO week containing the clock, so the "
        f"commitment reads 2.0, got {hours_before!r}"
    )
    fx.confirm_assignment(api, assignment["id"])

    validate_success(
        api.volunteer_screening(volunteer["id"], {"event_type": "EXPIRE"}, coordinator),
        200,
    )

    stored_volunteer = fx.read_volunteer(api, volunteer["id"])
    assert_values(
        stored_volunteer,
        status="EXPIRED",
        background_check_expires_on="2027-07-01",
        scheduled_hours_week=0.0,
    )
    stored_assignment = fx.read_assignment(api, assignment["id"])
    assert_values(
        stored_assignment, status="WITHDRAWN", withdrawn_reason="CLEARANCE_EXPIRED"
    )
    assert_values(fx.read_session(api, session["id"]), status="SCHEDULED")
    assert_values(fx.read_record(api, record["id"]), status="PLANNED")


def test_council_adoption_bubbles_into_plan_revision(api, director, therapist):
    """Adopting a council request bumps the named program's preference weight and
    pushes only those live plans whose resident wants the requested domain and
    whose target for it is zero into revision, gating those residents.

    PRD §3.9: "every activity plan in status `ACTIVE` whose resident's
    `interest_domains` contains the `requested_domain` **and** whose
    `domain_frequency_targets` records a target of 0 for that same domain is
    pushed from `ACTIVE` to `UNDER_REVISION` with `review_reason` set to
    `COUNCIL_INPUT`."

    Design: Corner/state_machines/council_adoption_bubbles_into_plan_revision
    """
    program = fx.create_program(
        api,
        name="Walking Club",
        domain="PHYSICAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    resident_a, _asmt_a, plan_a = fx.resident_with_active_plan(
        api,
        targets=f.domain_targets(social=2),
        resident_kwargs={
            "full_name": "Cascade Applies A",
            "room_number": "330A",
            "admission_date": "2026-07-16",
        },
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL", "PHYSICAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-16",
    )
    resident_b, _asmt_b, plan_b = fx.resident_with_active_plan(
        api,
        targets=f.domain_targets(physical=2),
        resident_kwargs={
            "full_name": "Cascade Skips B",
            "room_number": "330B",
            "admission_date": "2026-07-16",
        },
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["PHYSICAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-16",
    )
    request = fx.council_request(
        api,
        resident_a["id"],
        requested_domain="PHYSICAL",
        requested_program_id=program["id"],
        vote_count=6,
        note="Council asks for a walking club",
    )

    validate_success(
        api.review_council_request(
            request["id"],
            {"decision": "ADOPTED", "decision_note": "Added to the calendar"},
            director,
        ),
        200,
    )

    stored_request = fx.read_council_request(api, request["id"])
    assert_values(
        stored_request, status="ADOPTED", reviewed_by_user_id=DIRECTOR_USER_ID
    )
    assert fx.read_program(api, program["id"])["council_preference_weight"] == 1

    assert_values(
        fx.read_plan(api, plan_a["id"]),
        status="UNDER_REVISION",
        review_reason="COUNCIL_INPUT",
    )
    assert_values(
        fx.read_resident(api, resident_a["id"]),
        care_plan_review_due=True,
        enrollment_gate="THERAPIST_REVIEW",
    )
    assert_values(
        fx.read_plan(api, plan_b["id"]), status="ACTIVE", review_reason="NONE"
    )
    assert_values(
        fx.read_resident(api, resident_b["id"]),
        care_plan_review_due=False,
        enrollment_gate="NONE",
    )


def test_survey_packet_amend_cycle_reopens_attested_packet(api, compliance, compliance_b):
    """An attested packet can be amended and recompiled, so the packet has no
    terminal state: the amendment counts itself and clears the attester, and the
    fresh compilation rewrites every score field from scratch.

    PRD §3.9: "`AMENDED` returns to `COMPILED` through a fresh compilation, which
    closes the `COMPILED → ATTESTED → AMENDED → COMPILED` cycle; a packet
    therefore has no terminal state, and `amendment_count` records how many times
    the loop has been travelled."

    Design: Corner/state_machines/survey_packet_amend_cycle_reopens_attested_packet
    """
    packet = fx.open_packet(
        api, headers=compliance, window_start="2026-08-01", window_end="2026-08-01"
    )
    validate_success(api.compile_survey_packet(packet["id"], {}, compliance), 200)
    fx.attest_packet(
        api,
        packet["id"],
        compliance_b,
        remediation_note="No admitted residents in window; calendar restart planned",
    )

    validate_success(
        api.attest_survey_packet(
            packet["id"],
            {"action": "AMEND", "amendment_reason": "Late plan documentation received"},
            compliance_b,
        ),
        200,
    )

    amended = fx.read_packet(api, packet["id"], compliance)
    assert_values(
        amended, status="AMENDED", amendment_count=1, attested_by_user_id=None
    )

    validate_success(api.compile_survey_packet(packet["id"], {}, compliance), 200)

    recompiled = fx.read_packet(api, packet["id"], compliance)
    assert_values(
        recompiled,
        status="COMPILED",
        compiled_by_user_id=COMPLIANCE_USER_ID,
        amendment_count=1,
        deficiency_flags=["F248_INSUFFICIENT_FREQUENCY"],
    )
    assert recompiled["base_score"] == 0.0, (
        f"An empty cohort scores 0.0, got {recompiled['base_score']!r}"
    )
    assert recompiled["domain_coverage_penalty"] == 0.0
    assert recompiled["refusal_penalty"] == 0.0
    assert recompiled["preliminary_score"] == 0.0
    assert recompiled["provision_score"] == 0.0, (
        "The single flag deducts 3.0 from 0.0 and clamps at 0.0, got "
        f"{recompiled['provision_score']!r}"
    )


def test_consent_denial_blocks_outing_consent_dimension(api, director):
    """One denied responsible-party consent blocks the whole outing's consent
    dimension even though a sibling rider is granted, drops the denied resident
    off the manifest, and leaves the logistics dimension where it was.

    PRD §3.8: "It becomes `CONSENT_BLOCKED` the moment any row on the outing is
    `DENIED`, from either `COLLECTING` or `CONSENT_COMPLETE`."

    Design: Corner/state_machines/consent_denial_blocks_outing_consent_dimension
    """
    resident_yes, _asmt_yes = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Consent Yes",
            "room_number": "340A",
            "admission_date": "2026-07-17",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-17",
    )
    resident_no, _asmt_no = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Consent No",
            "room_number": "340B",
            "admission_date": "2026-07-17",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-17",
    )
    program = fx.create_program(
        api,
        name="Consent Outing Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=12,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 9",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Farmers Market",
        departure_at="2026-08-26T09:00:00Z",
        return_at="2026-08-26T12:00:00Z",
        escort_count=1,
    )
    consent_yes = fx.add_rider(
        api,
        outing["id"],
        resident_yes["id"],
        responsible_party_name="Yes Family",
        responsible_party_relation="ADULT_CHILD",
    )
    consent_no = fx.add_rider(
        api,
        outing["id"],
        resident_no["id"],
        responsible_party_name="No Family",
        responsible_party_relation="GUARDIAN",
    )
    fx.decide_consent(api, outing["id"], consent_yes["id"], "GRANTED")
    # The sibling row is still REQUESTED, so not every manifest row is granted and
    # effective: collection is still open right up to the denial.
    assert_values(fx.read_outing(api, outing["id"]), consent_status="COLLECTING")

    validate_success(
        api.decide_outing_consent(
            outing["id"], consent_no["id"], {"decision": "DENIED"}, director
        ),
        200,
    )

    assert_values(
        fx.read_consent(api, consent_no["id"]), status="DENIED", effective=False
    )
    assert_values(
        fx.read_consent(api, consent_yes["id"]), status="GRANTED", effective=True
    )
    stored_outing = fx.read_outing(api, outing["id"])
    assert_values(
        stored_outing,
        consent_status="CONSENT_BLOCKED",
        logistics_status="PLANNING",
        manifest_count=1,
    )
