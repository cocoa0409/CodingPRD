"""Role-based access control: role denial, ownership denial, the section-leader
gate, and the director's superset reach over shared operations."""
from test_helpers import (
    ApiErrorId,
    challenge_payload,
    create_audition,
    create_audition_entry,
    create_enrolled_student,
    create_event_payload,
    create_instrument,
    create_open_program,
    enroll_in_trip,
    finalize_scores,
    make_section_leader_headers,
    make_student_headers,
    publish_placements,
    setup_trip_with_open_roster,
    submit_score,
    validate_error,
    validate_success,
)


def test_student_role_cannot_retire_instrument(api, reader_headers):
    """PRD §2.1: "A request whose role is authenticated but not listed among the roles permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: "POST | `/band/instruments/{id}/retire` | Retire an instrument (terminal) | EquipmentManager".

    Design: Corner/rbac/student_cannot_retire_instrument
    """
    program = create_open_program(season_name="RB1")
    student = create_enrolled_student(program["id"], full_name="RB1")
    instrument = create_instrument(program["id"], serial_number="SN-RB-1",
                                   instrument_type="HORN",
                                   replacement_value_cents=50000)

    resp = api.retire_instrument(instrument["id"],
                                 make_student_headers(student["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    instrument = validate_success(api.get_instrument(instrument["id"],
                                                     reader_headers))
    assert instrument["status"] == "AVAILABLE"


def test_booster_treasurer_cannot_manage_events(api, treasurer_headers):
    """PRD §2.1: "A request whose role is authenticated but not listed among the roles permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: "POST | `/band/events` | Schedule an event | BandDirector, AssistantDirector".

    Design: Corner/rbac/treasurer_cannot_manage_events
    """
    program = create_open_program(season_name="RB2")
    resp = api.create_event(
        create_event_payload(program["id"], event_type="REHEARSAL",
                             facility="GYM",
                             starts_at="2026-08-10T10:00:00Z",
                             ends_at="2026-08-10T12:00:00Z", is_outdoor=False),
        treasurer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_student_may_enroll_self_but_not_others(api):
    """PRD §3.6: "A `BandDirector` or `AssistantDirector` may enroll any student; a `Student` actor may enroll only themselves — a payload whose `student_id` differs from the caller's identity is rejected with `ERR_FORBIDDEN_OWNERSHIP`." PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` record; ownership checks on any resource that references a student compare the resource's `student_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/student_enrolling_other_student_forbidden
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=5000,
        departure_at="2026-09-15T06:00:00Z")
    student_a = create_enrolled_student(program["id"], full_name="OA")
    student_b = create_enrolled_student(program["id"], full_name="OB")

    forbidden = api.create_trip_enrollment(
        {"trip_id": trip["id"], "student_id": student_b["id"]},
        make_student_headers(student_a["id"]))
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    own = validate_success(api.create_trip_enrollment(
        {"trip_id": trip["id"], "student_id": student_a["id"]},
        make_student_headers(student_a["id"])), 201)
    assert own["student_id"] == student_a["id"]
    assert own["attendance_status"] == "REGISTERED"


def test_challenge_requires_section_leader_of_that_section(
        api, director_headers, reader_headers):
    """PRD §3.8: "The acting student must hold `is_section_leader` and belong to the same `section` as the audition, else `ERR_SECTION_LEADER_REQUIRED`, and the challenge must arrive no later than seven days after `published_at` — later challenges are rejected with `ERR_CHALLENGE_WINDOW_EXPIRED` (HTTP 422). A successful challenge moves the audition to `UNDER_CHALLENGE` and increments its `version`."

    Design: Corner/rbac/challenge_requires_section_leader_of_that_section
    """
    program = create_open_program(season_name="RB4")
    leader = create_enrolled_student(program["id"], full_name="Lead", grade=12,
                                     section="BRASS")
    validate_success(api.designate_leader(leader["id"], director_headers))
    member = create_enrolled_student(program["id"], full_name="Mem", grade=10,
                                     section="BRASS")

    audition = create_audition(program["id"], section="BRASS", chair_capacity=1)
    entry = create_audition_entry(audition["id"], member["id"])
    submit_score(entry["id"], "J1", 80, 80, 80)
    audition = finalize_scores(audition["id"])
    publish_placements(audition["id"], audition["version"])

    not_leader = api.challenge_audition(
        audition["id"], challenge_payload(entry["id"]),
        make_section_leader_headers(member["id"]))
    validate_error(not_leader, ApiErrorId.ERR_SECTION_LEADER_REQUIRED)

    challenged = validate_success(api.challenge_audition(
        audition["id"], challenge_payload(entry["id"]),
        make_section_leader_headers(leader["id"])))
    assert challenged["status"] == "UNDER_CHALLENGE"
    audition = validate_success(api.get_audition(audition["id"], reader_headers))
    assert audition["status"] == "UNDER_CHALLENGE"


def test_director_superset_reaches_shared_operations(api, director_headers):
    """PRD §2.1: "Role responsibilities in brief: the `BandDirector` is the program head and holds a superset of operations, subject to the segregation-of-duties rule on arrangement approval. The `AssistantDirector` is the second staff conductor and shares day-to-day scheduling, student, trip, audition, and enrollment work." PRD §4: "POST | `/band/events` | Schedule an event | BandDirector, AssistantDirector".

    Design: Corner/rbac/director_superset_can_do_shared_operations
    """
    program = create_open_program(season_name="RB5")
    created = validate_success(api.create_event(
        create_event_payload(program["id"], event_type="REHEARSAL",
                             facility="GYM",
                             starts_at="2026-08-10T10:00:00Z",
                             ends_at="2026-08-10T12:00:00Z", is_outdoor=False),
        director_headers), 201)
    assert created["status"] == "SCHEDULED"
    assert created["program_id"] == program["id"]
