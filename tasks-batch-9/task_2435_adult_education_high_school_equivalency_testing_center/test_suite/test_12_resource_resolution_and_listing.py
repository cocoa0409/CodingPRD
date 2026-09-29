"""How the flat topology answers for records that are not there, and how the collection
reads report a filtered total that is wider than the page they return.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_envelope_meta, assert_hours_value
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AttendanceStatus,
    IntakeStatus,
    ProgramTrack,
    SectionStatus,
)

UNKNOWN_STUDENT_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_SECTION_ID = "00000000-0000-4000-8000-0000000000cc"
UNKNOWN_CENTER_ID = "00000000-0000-4000-8000-0000000000aa"

PRE_TEST_AT = "2026-08-02T09:00:00Z"
LEDGER_CLOCK = "2026-08-05T00:00:00Z"
LEDGER_DATES = ("2026-08-03", "2026-08-04", "2026-08-05")
LEDGER_HOURS = 2.00


def _setup_three_learners_one_oriented():
    first = fixtures.create_student(
        full_name="Cal Otieno",
        email="cal.otieno@example.org",
        primary_track=ProgramTrack.LITERACY,
    )
    second = fixtures.create_student(
        full_name="Dara Nkemi",
        email="dara.nkemi@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    third = fixtures.create_student(
        full_name="Emil Torres",
        email="emil.torres@example.org",
        primary_track=ProgramTrack.ESL,
    )
    validate_success(
        api_client.complete_orientation(second["id"], headers=make_registrar_headers())
    )
    return {
        "ids": [first["id"], second["id"], third["id"]],
        "oriented_id": second["id"],
    }


def _setup_enrollment_with_three_entries_one_voided():
    placed = fixtures.create_placed_student(
        scale_score=205,
        full_name="Omar Saleh",
        email="omar.saleh@example.org",
        pre_test_at=PRE_TEST_AT,
    )
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        title="HSE Ledger",
        instructor_user_id="instructor-4",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    fixtures.set_clock(LEDGER_CLOCK)
    entries = [
        fixtures.post_attendance(enrollment["id"], date, LEDGER_HOURS)
        for date in LEDGER_DATES
    ]
    fixtures.void_attendance(
        entries[-1]["id"], enrollment["id"], void_reason="duplicate entry"
    )
    return {
        "enrollment_id": enrollment["id"],
        "entry_ids": [entry["id"] for entry in entries],
        "voided_id": entries[-1]["id"],
    }


def test_01_an_unknown_learner_id_in_the_path_is_a_not_found_on_read_and_on_write():
    """"**Path identifier resolution.** Every identifier embedded in the path is resolved left
    to right, and the first one that does not resolve determines the 404 reported:
    `ERR_STUDENT_NOT_FOUND`"

    Design: Corner/entities/student_path_id_unresolvable_returns_not_found
    """
    read = api_client.get_student(UNKNOWN_STUDENT_ID, headers=make_registrar_headers())
    validate_error(read, ApiErrorId.STUDENT_NOT_FOUND, expected_status=404)
    assert read.json()["response_type"] == "error"
    assert isinstance(read.json()["data"]["message"], str)
    assert read.json()["data"]["message"] != ""

    write = api_client.complete_orientation(
        UNKNOWN_STUDENT_ID, headers=make_registrar_headers()
    )
    validate_error(write, ApiErrorId.STUDENT_NOT_FOUND, expected_status=404)
    assert write.json()["response_type"] == "error"
    assert isinstance(write.json()["data"]["message"], str)
    assert write.json()["data"]["message"] != ""


def test_02_an_unresolved_body_reference_names_the_missing_section_not_the_learner():
    """"**Body foreign keys.** Every identifier supplied in a request body — `student_id`,
    `class_section_id`, `exam_session_id`, `accommodation_request_id`,
    `credential_issuance_id`, `funding_period_id`, `proctor_id`, `testing_room_id`,
    `enrollment_id` — must resolve, and an unresolved one reports the matching 404 from the
    list in band 3."

    Design: Corner/entities/enrollment_with_unknown_class_section_not_found
    """
    placed = fixtures.create_placed_student(
        scale_score=205,
        full_name="Noor Idris",
        email="noor.idris@example.org",
        pre_test_at=PRE_TEST_AT,
    )

    response = api_client.create_enrollment(
        factories.create_enrollment_payload(placed["student_id"], UNKNOWN_SECTION_ID),
        headers=make_program_coordinator_headers(),
    )
    validate_error(response, ApiErrorId.CLASS_SECTION_NOT_FOUND, expected_status=404)

    learner = fixtures.read_student(placed["student_id"])
    assert learner["intake_status"] == IntakeStatus.PLACED
    assert learner["active_enrollment_count"] == 0


def test_03_a_room_under_an_unknown_centre_resolves_the_path_before_authorisation():
    """"**Path identifier resolution.** Every identifier embedded in the path is resolved left
    to right, and the first one that does not resolve determines the 404 reported:
    `ERR_STUDENT_NOT_FOUND`, `ERR_TESTING_CENTER_NOT_FOUND`" and "This band guards four
    operations: room creation under a centre, exam-session creation, proctor assignment and
    exam-registration creation."

    Design: Corner/entities/room_creation_under_unknown_center_not_found
    """
    response = api_client.create_testing_room(
        UNKNOWN_CENTER_ID,
        factories.create_testing_room_payload(room_code="R-1", seat_capacity=10),
        headers=make_state_authority_headers(),
    )
    validate_error(response, ApiErrorId.TESTING_CENTER_NOT_FOUND, expected_status=404)

    _, meta = validate_paginated(
        api_client.list_testing_rooms(
            headers=make_state_authority_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0


def test_04_the_learner_page_reports_the_whole_filtered_total():
    """"`total_count` is the number of records matching the filters before the pagination
    window is applied, and `has_more` states whether any matching record remains beyond the
    returned window."

    Design: Corner/entities/student_listing_paginated_with_total_count_and_has_more
    """
    _setup_three_learners_one_oriented()

    page, meta = validate_paginated(
        api_client.list_students(
            headers=make_registrar_headers(), params={"limit": 2, "offset": 0}
        )
    )
    assert_envelope_meta(meta)
    assert len(page) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_05_the_intake_status_filter_narrows_the_learner_collection():
    """"The collection read is restricted to staff roles and accepts `intake_status`,
    `primary_track` and `credential_status` as filters alongside `limit` and `offset`."

    Design: Corner/entities/student_listing_paginated_with_total_count_and_has_more
    """
    context = _setup_three_learners_one_oriented()

    page, meta = validate_paginated(
        api_client.list_students(
            headers=make_registrar_headers(),
            params={"intake_status": IntakeStatus.ORIENTED},
        )
    )
    assert len(page) == 1
    assert page[0]["id"] == context["oriented_id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_06_the_attendance_collection_pages_within_one_enrollment():
    """"List attendance entries, filterable by enrollment and status." and "`total_count` is
    the number of records matching the filters before the pagination window is applied, and
    `has_more` states whether any matching record remains beyond the returned window."

    Design: Corner/entities/attendance_entries_listed_by_enrollment_with_pagination
    """
    context = _setup_enrollment_with_three_entries_one_voided()

    page, meta = validate_paginated(
        api_client.list_attendance_entries(
            headers=make_program_coordinator_headers(),
            params={"enrollment_id": context["enrollment_id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    for row in page:
        assert row["enrollment_id"] == context["enrollment_id"]


def test_07_the_status_filter_isolates_the_single_voided_entry():
    """"An enrollment's `posted_hours` is the sum of the `hours` of that enrollment's entries
    whose `status` is `POSTED` — voided entries contribute nothing."

    Design: Corner/entities/attendance_entries_listed_by_enrollment_with_pagination
    """
    context = _setup_enrollment_with_three_entries_one_voided()

    page, meta = validate_paginated(
        api_client.list_attendance_entries(
            headers=make_instructor_headers(),
            params={
                "enrollment_id": context["enrollment_id"],
                "status": AttendanceStatus.VOIDED,
            },
        )
    )
    assert len(page) == 1
    assert page[0]["id"] == context["voided_id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 4.00)
