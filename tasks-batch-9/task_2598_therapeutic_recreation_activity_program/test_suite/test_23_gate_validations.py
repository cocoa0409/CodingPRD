"""Gate validations: the refusals that guard enrollment, outings, calendars and packets.

Every test drives the live API over real HTTP. The server is restarted before
each test, so the database starts empty and the logical clock reads exactly
2026-08-01T00:00:00Z; all state below is built through declared endpoints.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ABSENT_UUID


def test_unassessed_resident_enrollment_rejected(api, director, aide):
    """An admitted resident who has never been assessed carries no supervision weight, so
    enrolling them is refused for the missing clinical record rather than for any tier or
    staffing reason, and the session's counters stay at zero.

    PRD §3.5: "The resident must have at least one assessment on file, so that a supervision weight exists at all."

    Design: Corner/validations/unassessed_resident_enrollment_rejected
    """
    resident = fx.create_resident(
        api, full_name="Unassessed Ulla", room_number="501A", admission_date="2026-07-26"
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Unassessed Program",
            "domain": "SOCIAL",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Unassessed Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-30T10:00:00Z",
        ends_at="2026-08-30T11:00:00Z",
        assigned_staff_count=4,
    )

    response = api.create_enrollment(
        session["id"], f.enrollment_payload(resident["id"]), aide
    )
    validate_error(response, ApiErrorId.NO_ACTIVE_ASSESSMENT.value, 409)

    resident_row = fx.read_resident(api, resident["id"], headers=director)
    assert resident_row["supervision_tier"] is None
    assert resident_row["status"] == "ADMITTED"

    session_row = fx.read_session(api, session["id"], headers=director)
    assert session_row["enrolled_count"] == 0
    assert session_row["weighted_supervision_load"] == 0.0


def test_discharged_resident_outing_consent_rejected(api, director, therapist):
    """Adding a rider to an outing manifest depends on the census row of the other entity:
    the identical consent request succeeds while the resident is admitted and is refused
    once that resident has been discharged, leaving the earlier consent untouched.

    PRD §3.8: "the resident must be `ADMITTED`, with `ON_LEAVE` and `DISCHARGED` both refused as `ERR_RESIDENT_NOT_ADMITTED`"

    Design: Corner/validations/discharged_resident_outing_consent_rejected
    """
    staying = fx.create_resident(
        api, full_name="Still Admitted", room_number="502A", admission_date="2026-07-26"
    )
    fx.file_assessment(
        api,
        staying["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-26",
    )
    leaving = fx.create_resident(
        api, full_name="Going Home", room_number="502B", admission_date="2026-07-26"
    )
    fx.file_assessment(
        api,
        leaving["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-26",
    )
    program = fx.create_program(
        api,
        name="Discharge Outing Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 13",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="County Fair",
        departure_at="2026-08-31T09:00:00Z",
        return_at="2026-08-31T13:00:00Z",
        escort_count=2,
    )
    admitted_consent = fx.add_rider(
        api,
        outing["id"],
        staying["id"],
        headers=director,
        responsible_party_name="A Family",
        responsible_party_relation="SPOUSE",
    )
    validate_success(
        api.update_resident(leaving["id"], {"status": "DISCHARGED"}, director), 200
    )

    response = api.create_outing_consent(
        outing["id"],
        f.consent_payload(
            leaving["id"],
            responsible_party_name="B Family",
            responsible_party_relation="GUARDIAN",
        ),
        director,
    )
    validate_error(response, ApiErrorId.RESIDENT_NOT_ADMITTED.value, 409)

    assert fx.read_consent(api, admitted_consent["id"], headers=director)["status"] == (
        "REQUESTED"
    )
    outing_row = fx.read_outing(api, outing["id"], headers=director)
    assert outing_row["roster_count"] == 1
    assert outing_row["manifest_count"] == 1

    rows, meta = validate_paginated(
        api.list_outing_consents(director, {"resident_id": leaving["id"]})
    )
    assert meta["total_count"] == 0, "The refused consent was never created"
    assert rows == []


def test_unauthorized_role_on_unknown_id_returns_403_unauthorized(api, director, aide):
    """A census edit belongs to the activity director alone, so an aide probing a
    fabricated resident identifier is told only that they are unauthorized, while the
    director aiming at the same absent identifier learns it does not exist.

    PRD §2.1: "This authorization check deliberately outranks every existence check in the system"

    Design: Corner/validations/unauthorized_role_on_unknown_id_returns_403_unauthorized
    """
    aide_response = api.update_resident(ABSENT_UUID, {"status": "ON_LEAVE"}, aide)
    validate_error(aide_response, ApiErrorId.UNAUTHORIZED.value, 403)

    director_response = api.update_resident(ABSENT_UUID, {"status": "ON_LEAVE"}, director)
    validate_error(director_response, ApiErrorId.RESIDENT_NOT_FOUND.value, 404)


def test_adaptive_equipment_union_not_stocked_rejected(api, director, therapist, aide):
    """The equipment gate looks at both sides at once: a room stocking only the program's
    required item still fails the resident's own documented need, while a room stocking
    both items admits the identical enrollment.

    PRD §3.5: "must be wholly contained in the room's `equipment_available`, and any shortfall reports `ERR_ADAPTIVE_EQUIPMENT_UNAVAILABLE`"

    Design: Corner/validations/adaptive_equipment_union_not_stocked_rejected
    """
    resident = fx.create_resident(
        api, full_name="Union Ursula", room_number="503A", admission_date="2026-07-26"
    )
    fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["COGNITIVE"],
        preferred_group_size="SMALL",
        adaptive_equipment_needs=["HEARING_AMPLIFIER"],
        effective_date="2026-07-26",
    )
    program = fx.create_program(
        api,
        name="Large Print Reading",
        domain="COGNITIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
        required_adaptive_equipment=["LARGE_PRINT"],
    )
    partial_room = fx.create_room(
        api,
        name="Partly Stocked Room",
        capacity=10,
        buffer_minutes=0,
        equipment_available=["LARGE_PRINT"],
    )
    stocked_room = fx.create_room(
        api,
        name="Fully Stocked Room",
        capacity=10,
        buffer_minutes=0,
        equipment_available=["LARGE_PRINT", "HEARING_AMPLIFIER"],
    )
    partial_session = fx.create_session(
        api,
        program["id"],
        partial_room["id"],
        starts_at="2026-09-01T10:00:00Z",
        ends_at="2026-09-01T11:00:00Z",
        assigned_staff_count=2,
    )
    stocked_session = fx.create_session(
        api,
        program["id"],
        stocked_room["id"],
        starts_at="2026-09-01T13:00:00Z",
        ends_at="2026-09-01T14:00:00Z",
        assigned_staff_count=2,
    )

    refused = api.create_enrollment(
        partial_session["id"], f.enrollment_payload(resident["id"]), aide
    )
    validate_error(refused, ApiErrorId.ADAPTIVE_EQUIPMENT_UNAVAILABLE.value, 422)
    assert fx.read_session(api, partial_session["id"], headers=director)["enrolled_count"] == 0

    admitted = validate_success(
        api.create_enrollment(
            stocked_session["id"], f.enrollment_payload(resident["id"]), aide
        ),
        201,
    )
    assert admitted["status"] == "PLANNED"
    assert fx.read_session(api, stocked_session["id"], headers=director)["enrolled_count"] == 1


def test_room_zero_buffer_allows_touching_sessions(api, director):
    """With no turnover time configured, a session that begins at the exact instant the
    previous one ends is booked, while a session that starts one minute before that end
    genuinely intersects and is refused.

    PRD §3.4: "in a room with `buffer_minutes` at 0, a session starting at the exact instant another ends is legal"

    Design: Corner/validations/room_zero_buffer_allows_touching_sessions
    """
    program = fx.create_program(
        api,
        name="Back To Back Program",
        domain="PHYSICAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    room = fx.create_room(api, name="No Buffer Room", capacity=10, buffer_minutes=0)
    first = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-02T10:00:00Z",
        ends_at="2026-09-02T11:00:00Z",
    )

    touching = validate_success(
        api.create_session(
            f.session_payload(
                program["id"],
                room["id"],
                starts_at="2026-09-02T11:00:00Z",
                ends_at="2026-09-02T12:00:00Z",
            ),
            director,
        ),
        201,
    )
    assert touching["status"] == "SCHEDULED"

    overlapping = api.create_session(
        f.session_payload(
            program["id"],
            room["id"],
            starts_at="2026-09-02T11:59:00Z",
            ends_at="2026-09-02T12:30:00Z",
        ),
        director,
    )
    validate_error(overlapping, ApiErrorId.ROOM_TIME_CONFLICT.value, 409)

    rows, meta = validate_paginated(api.list_sessions(director, {"room_id": room["id"]}))
    assert meta["total_count"] == 2, "Only the two non-intersecting slots were booked"
    assert {row["id"] for row in rows} == {first["id"], touching["id"]}


def test_packet_windows_may_touch_but_overlap_rejected(api, compliance):
    """Two survey windows that share no calendar date coexist even when the second begins
    the day after the first ends, but a third window covering days already claimed by both
    is refused and leaves the earlier packet untouched.

    PRD §3.9: "a packet ending on one date and another starting on the next date coexist happily while any shared date reports `ERR_PACKET_WINDOW_OVERLAP`"

    Design: Corner/validations/packet_windows_may_touch_but_overlap_rejected
    """
    august = fx.open_packet(
        api, headers=compliance, window_start="2026-08-01", window_end="2026-08-31"
    )

    september = validate_success(
        api.create_survey_packet(
            f.packet_payload(window_start="2026-09-01", window_end="2026-09-30"),
            compliance,
        ),
        201,
    )
    assert september["status"] == "OPEN"

    overlapping = api.create_survey_packet(
        f.packet_payload(window_start="2026-08-15", window_end="2026-09-15"), compliance
    )
    validate_error(overlapping, ApiErrorId.PACKET_WINDOW_OVERLAP.value, 409)

    august_row = fx.read_packet(api, august["id"], headers=compliance)
    assert august_row["status"] == "OPEN"
    assert august_row["provision_score"] is None


def test_clock_rewind_rejected(api, director):
    """The logical clock only moves forward: after being advanced almost a week, an attempt
    to return it to the startup instant is refused, while re-setting it to the instant it
    already reads is accepted.

    PRD §2.5: "a value earlier than the clock's present reading is refused with `ERR_CLOCK_REWIND_FORBIDDEN`"
    PRD §2.5: "a value equal to the present reading is accepted"

    Design: Corner/validations/clock_rewind_rejected
    """
    validate_success(api.set_clock("2026-08-06T09:00:00Z", director), 200)

    rewound = api.set_clock("2026-08-01T00:00:00Z", director)
    validate_error(rewound, ApiErrorId.CLOCK_REWIND_FORBIDDEN.value, 409)

    validate_success(api.set_clock("2026-08-06T09:00:00Z", director), 200)


def test_zero_length_session_interval_rejected(api, director, compliance):
    """Interval sanity differs by resource kind: a session whose end equals its start is
    refused as an empty half-open interval, while a survey packet covering the single
    inclusive calendar date 2026-10-05 is perfectly legal.

    PRD §2.5: "A zero-length session interval is therefore rejected while a single-day packet window is perfectly legal"

    Design: Corner/validations/zero_length_session_interval_rejected
    """
    program = fx.create_program(
        api,
        name="Zero Length Program",
        domain="CREATIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    room = fx.create_room(api, name="Zero Length Room", capacity=10, buffer_minutes=0)

    empty_interval = api.create_session(
        f.session_payload(
            program["id"],
            room["id"],
            starts_at="2026-10-05T09:00:00Z",
            ends_at="2026-10-05T09:00:00Z",
        ),
        director,
    )
    validate_error(empty_interval, ApiErrorId.TIME_WINDOW_INVALID.value, 422)

    single_day = validate_success(
        api.create_survey_packet(
            f.packet_payload(window_start="2026-10-05", window_end="2026-10-05"),
            compliance,
        ),
        201,
    )
    assert single_day["status"] == "OPEN"

    _, meta = validate_paginated(api.list_sessions(director, {"room_id": room["id"]}))
    assert meta["total_count"] == 0, "The empty-interval session was never created"


def test_session_pinned_to_clock_accepted_past_start_rejected(api, director):
    """A calendar slot may be booked for the exact instant the logical clock currently
    reads, but a slot whose start lies before that reading is in the past and is refused.

    PRD §2.5: "a slot pinned exactly to the current clock reading is accepted while one a second earlier is rejected"

    Design: Corner/validations/session_pinned_to_clock_accepted_past_start_rejected
    """
    program = fx.create_program(
        api,
        name="Clock Pinned Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    room = fx.create_room(api, name="Clock Pinned Room", capacity=10, buffer_minutes=0)

    pinned = validate_success(
        api.create_session(
            f.session_payload(
                program["id"],
                room["id"],
                starts_at="2026-08-01T00:00:00Z",
                ends_at="2026-08-01T01:00:00Z",
            ),
            director,
        ),
        201,
    )
    assert pinned["status"] == "SCHEDULED"
    stored = fx.read_session(api, pinned["id"], headers=director)
    assert stored["status"] == "SCHEDULED"
    assert stored["starts_at"].startswith("2026-08-01T00:00:00")

    in_the_past = api.create_session(
        f.session_payload(
            program["id"],
            room["id"],
            starts_at="2026-07-31T22:00:00Z",
            ends_at="2026-07-31T23:00:00Z",
        ),
        director,
    )
    validate_error(in_the_past, ApiErrorId.SESSION_IN_PAST.value, 409)


def test_intergenerational_student_program_lead_rejected(api, coordinator):
    """A student volunteer may never be the senior volunteer in the room and may never work a
    thinly staffed slot: both the lead role on a well-staffed session and the assistant role
    on a single-staff session are refused, while an adult community volunteer leads that
    same single-staff session without complaint.

    PRD §3.7: "may only be assigned to a session whose `assigned_staff_count` is at least 2, and may never hold `role_type` `PROGRAM_LEAD`"

    Design: Corner/validations/intergenerational_student_program_lead_rejected
    """
    program = fx.create_program(
        api,
        name="Intergenerational Reading",
        domain="COGNITIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    two_staff_room = fx.create_room(
        api, name="Two Staff Room", capacity=10, buffer_minutes=0
    )
    one_staff_room = fx.create_room(
        api, name="One Staff Room", capacity=10, buffer_minutes=0
    )
    two_staff_session = fx.create_session(
        api,
        program["id"],
        two_staff_room["id"],
        starts_at="2026-09-04T10:00:00Z",
        ends_at="2026-09-04T11:00:00Z",
        assigned_staff_count=2,
    )
    one_staff_session = fx.create_session(
        api,
        program["id"],
        one_staff_room["id"],
        starts_at="2026-09-05T10:00:00Z",
        ends_at="2026-09-05T11:00:00Z",
        assigned_staff_count=1,
    )
    student = fx.cleared_volunteer(
        api,
        cleared_on="2026-07-02",
        completed_on="2026-07-06",
        full_name="Student Sam",
        volunteer_type="STUDENT_INTERGENERATIONAL",
    )
    adult = fx.cleared_volunteer(
        api,
        cleared_on="2026-07-02",
        completed_on="2026-07-06",
        full_name="Adult Alma",
        volunteer_type="ADULT_COMMUNITY",
    )

    as_lead = api.create_volunteer_assignment(
        f.assignment_payload(student["id"], two_staff_session["id"], role_type="PROGRAM_LEAD"),
        coordinator,
    )
    validate_error(as_lead, ApiErrorId.INTERGENERATIONAL_SUPERVISION_MISSING.value, 422)

    thinly_staffed = api.create_volunteer_assignment(
        f.assignment_payload(
            student["id"], one_staff_session["id"], role_type="GROUP_ASSISTANT"
        ),
        coordinator,
    )
    validate_error(thinly_staffed, ApiErrorId.INTERGENERATIONAL_SUPERVISION_MISSING.value, 422)

    adult_lead = validate_success(
        api.create_volunteer_assignment(
            f.assignment_payload(
                adult["id"], one_staff_session["id"], role_type="PROGRAM_LEAD"
            ),
            coordinator,
        ),
        201,
    )
    assert adult_lead["status"] == "PROPOSED"

    assert fx.read_volunteer(api, student["id"], headers=coordinator)[
        "scheduled_hours_week"
    ] == 0.0


def test_volunteer_weekly_hour_cap_aggregate_exceeded_rejected(api, coordinator):
    """The weekly cap is an aggregate over the ISO week holding the clock: two four-hour
    commitments reach exactly the cap and are both admitted, and a third one-hour
    commitment in the same week is refused without disturbing the stored total.

    PRD §3.7: "so a volunteer may be scheduled to exactly 8.00 hours but not to 8.01"

    Design: Corner/validations/volunteer_weekly_hour_cap_aggregate_exceeded_rejected
    """
    fx.advance_clock(api, "2026-08-03T00:00:00Z")
    program = fx.create_program(
        api,
        name="Hour Cap Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    room = fx.create_room(api, name="Hour Cap Room", capacity=10, buffer_minutes=0)
    monday = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T09:00:00Z",
        ends_at="2026-08-03T13:00:00Z",
    )
    tuesday = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-04T09:00:00Z",
        ends_at="2026-08-04T13:00:00Z",
    )
    wednesday = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
    )
    volunteer = fx.cleared_volunteer(
        api, cleared_on="2026-07-02", completed_on="2026-07-06", full_name="Busy Bea"
    )

    first = fx.assign_volunteer(api, volunteer["id"], monday["id"])
    second = fx.assign_volunteer(api, volunteer["id"], tuesday["id"])
    assert first["hours"] == 4.0
    assert second["hours"] == 4.0
    assert fx.read_volunteer(api, volunteer["id"], headers=coordinator)[
        "scheduled_hours_week"
    ] == 8.0

    over_cap = api.create_volunteer_assignment(
        f.assignment_payload(volunteer["id"], wednesday["id"]), coordinator
    )
    validate_error(over_cap, ApiErrorId.VOLUNTEER_HOUR_CAP_EXCEEDED.value, 409)

    assert fx.read_volunteer(api, volunteer["id"], headers=coordinator)[
        "scheduled_hours_week"
    ] == 8.0

    rows, meta = validate_paginated(
        api.list_volunteer_assignments(coordinator, {"volunteer_id": volunteer["id"]})
    )
    assert meta["total_count"] == 2, "The over-cap assignment was never created"
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_council_adoption_below_quorum_rejected(api, director):
    """A council request carrying four votes cannot be adopted, because adoption alone needs a
    quorum; deferring the very same request succeeds, stores the director's note, and leaves
    the named program's preference counter untouched since no adoption cascade ran.

    PRD §3.9: "`vote_count` must be at least 5, and a short vote reports `ERR_COUNCIL_QUORUM_NOT_MET`"

    Design: Corner/validations/council_adoption_below_quorum_rejected
    """
    resident = fx.create_resident(
        api, full_name="Council Cora", room_number="504A", admission_date="2026-07-26"
    )
    program = fx.create_program(
        api,
        name="Hymn Sing",
        domain="SPIRITUAL",
        staffing_ratio_denominator=4,
        max_group_size=20,
        max_supervision_tier="TIER_3",
    )
    request = fx.council_request(
        api,
        resident["id"],
        requested_domain="SPIRITUAL",
        requested_program_id=program["id"],
        vote_count=4,
        note="Four members voted for a weekly hymn sing",
    )

    short_vote = api.review_council_request(
        request["id"],
        {"decision": "ADOPTED", "decision_note": "The council asked for this"},
        director,
    )
    validate_error(short_vote, ApiErrorId.COUNCIL_QUORUM_NOT_MET.value, 422)

    validate_success(
        api.review_council_request(
            request["id"],
            {
                "decision": "DEFERRED",
                "decision_note": "Revisit after the next council meeting",
            },
            director,
        ),
        200,
    )

    stored = fx.read_council_request(api, request["id"], headers=director)
    assert stored["status"] == "DEFERRED"
    assert stored["decision_note"] == "Revisit after the next council meeting"
    assert fx.read_program(api, program["id"], headers=director)[
        "council_preference_weight"
    ] == 0, "Only an adoption ever moves the preference counter"


def test_duplicate_outing_consent_rejected(api, director, therapist):
    """A denied consent still occupies the resident's place on the outing roster, so a second
    consent request for the same resident on the same outing is refused as a duplicate and
    the denial stands exactly as decided.

    PRD §3.8: "must not already hold a consent row on this outing **in any status whatsoever**"

    Design: Corner/validations/duplicate_outing_consent_rejected
    """
    resident = fx.create_resident(
        api, full_name="Denied Dora", room_number="505A", admission_date="2026-07-26"
    )
    fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-26",
    )
    program = fx.create_program(
        api,
        name="Duplicate Consent Outing Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 21",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Garden Centre",
        departure_at="2026-08-25T09:00:00Z",
        return_at="2026-08-25T12:00:00Z",
        escort_count=1,
    )
    consent = fx.add_rider(
        api,
        outing["id"],
        resident["id"],
        headers=director,
        responsible_party_name="Daughter Dee",
        responsible_party_relation="ADULT_CHILD",
    )
    fx.decide_consent(api, outing["id"], consent["id"], "DENIED", headers=director)

    duplicate = api.create_outing_consent(
        outing["id"],
        f.consent_payload(
            resident["id"],
            responsible_party_name="Daughter Dee",
            responsible_party_relation="ADULT_CHILD",
        ),
        director,
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_CONSENT.value, 409)

    stored = fx.read_consent(api, consent["id"], headers=director)
    assert stored["status"] == "DENIED"
    assert stored["responsible_party_relation"] == "ADULT_CHILD"

    outing_row = fx.read_outing(api, outing["id"], headers=director)
    assert outing_row["roster_count"] == 1, "The denied row still holds the resident's place"
    assert outing_row["manifest_count"] == 0, "A denied consent has left the manifest"


def test_consent_from_another_outing_not_found(api, director, therapist):
    """Deciding a consent through the wrong outing's path is a lookup failure, not an
    authorization failure and not a missing outing: the consent belongs to a real outing,
    just not the one named in the path, and it stays undecided.

    PRD §2.9: "if it names a real consent belonging to a different outing, the answer is `ERR_CONSENT_NOT_FOUND`"

    Design: Corner/validations/consent_from_another_outing_not_found
    """
    first_resident = fx.create_resident(
        api, full_name="Trip One Rider", room_number="506A", admission_date="2026-07-26"
    )
    second_resident = fx.create_resident(
        api, full_name="Trip Two Rider", room_number="506B", admission_date="2026-07-26"
    )
    for resident_id in (first_resident["id"], second_resident["id"]):
        fx.file_assessment(
            api,
            resident_id,
            headers=therapist,
            cognitive_level="INTACT",
            functional_mobility="INDEPENDENT",
            interest_domains=["SOCIAL"],
            preferred_group_size="SMALL",
            effective_date="2026-07-26",
        )
    program = fx.create_program(
        api,
        name="Two Trips Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 22",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    first_outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Museum Morning",
        departure_at="2026-08-26T09:00:00Z",
        return_at="2026-08-26T12:00:00Z",
        escort_count=1,
    )
    second_outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Museum Afternoon",
        departure_at="2026-08-27T09:00:00Z",
        return_at="2026-08-27T12:00:00Z",
        escort_count=1,
    )
    fx.add_rider(api, first_outing["id"], first_resident["id"], headers=director)
    foreign_consent = fx.add_rider(
        api, second_outing["id"], second_resident["id"], headers=director
    )

    response = api.decide_outing_consent(
        first_outing["id"], foreign_consent["id"], {"decision": "GRANTED"}, director
    )
    validate_error(response, ApiErrorId.CONSENT_NOT_FOUND.value, 404)

    stored = fx.read_consent(api, foreign_consent["id"], headers=director)
    assert stored["status"] == "REQUESTED"
    assert stored["decided_at"] is None

    assert fx.read_outing(api, first_outing["id"], headers=director)["consent_status"] == (
        "COLLECTING"
    )
    assert fx.read_outing(api, second_outing["id"], headers=director)["consent_status"] == (
        "COLLECTING"
    )
