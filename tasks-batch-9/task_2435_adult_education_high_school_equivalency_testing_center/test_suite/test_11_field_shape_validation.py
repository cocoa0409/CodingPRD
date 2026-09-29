"""Body-shape refusals: a missing required field, undeclared enum members, a value that is
in range but off the increment, inverted or empty spans, and a code in the wrong case.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_hours_value
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    ProgramTrack,
    SectionStatus,
    TestEventPurpose,
    TestEventStatus,
    TestForm,
)

PRE_TEST_SCHEDULED_FOR = "2026-08-02T09:00:00Z"
ATTENDANCE_CLOCK = "2026-08-03T00:00:00Z"
ATTENDANCE_DATE = "2026-08-03"

OFF_INCREMENT_HOURS = 1.10
OUT_OF_RANGE_SCALE_SCORE = 1000


def _total_students():
    _, meta = validate_paginated(
        api_client.list_students(
            headers=make_program_coordinator_headers(), params={"limit": 10, "offset": 0}
        )
    )
    return meta["total_count"]


def _total_class_sections():
    _, meta = validate_paginated(
        api_client.list_class_sections(
            headers=make_program_coordinator_headers(), params={"limit": 10, "offset": 0}
        )
    )
    return meta["total_count"]


def _setup_scheduled_pre_test():
    """An oriented learner holding one SCHEDULED pre-test, clock parked on the sitting."""
    student = fixtures.create_oriented_student(
        full_name="Mara Quinn", email="mara.quinn@example.org"
    )
    event = fixtures.schedule_test_event(
        student["id"],
        PRE_TEST_SCHEDULED_FOR,
        purpose=TestEventPurpose.PRE_TEST,
        test_form=TestForm.CASAS_R_900,
    )
    fixtures.set_clock(PRE_TEST_SCHEDULED_FOR)
    return {"student_id": student["id"], "test_event_id": event["id"]}


def _setup_enrollment_with_no_hours():
    placed = fixtures.create_placed_student(
        scale_score=205,
        full_name="Lena Fox",
        email="lena.fox@example.org",
        pre_test_at=PRE_TEST_SCHEDULED_FOR,
    )
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        title="HSE Quarter Hours",
        instructor_user_id="instructor-2",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    fixtures.set_clock(ATTENDANCE_CLOCK)
    return enrollment["id"]


def test_01_intake_without_a_primary_track_is_a_malformed_request():
    """"**Request shape.** Required body fields present, types correct, enum values drawn
    from the declared set, and numeric constraints satisfied — otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/student_creation_missing_required_primary_track_rejected
    """
    assert _total_students() == 0

    response = api_client.create_student(
        {"full_name": "Fen Alvi", "email": "fen.alvi@example.org"},
        headers=make_program_coordinator_headers(),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

    # A refused body persists nothing, not even a partial learner row.
    assert _total_students() == 0


def test_02_an_undeclared_program_track_is_not_coerced():
    """"and the `primary_track` the learner enters on, which is `LITERACY`, `HSE_PREP` or
    `ESL`." and "enum values drawn from the declared set, and numeric constraints satisfied —
    otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/student_primary_track_invalid_enum_rejected
    """
    response = api_client.create_student(
        {
            "full_name": "Kori Bell",
            "email": "kori.bell@example.org",
            "primary_track": "GED_PREP",
        },
        headers=make_program_coordinator_headers(),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

    assert _total_students() == 0


def test_03_hours_off_the_quarter_hour_increment_never_reach_the_ledger():
    """"Hours must be greater than zero, no more than 8, and an exact multiple of 0.25 — the
    quarter-hour is the ledger's smallest unit, and a value like 1.3 is refused as a malformed
    request."

    Design: Corner/entities/attendance_hours_not_multiple_of_quarter_rejected
    """
    enrollment_id = _setup_enrollment_with_no_hours()

    response = api_client.create_attendance_entry(
        enrollment_id,
        factories.create_attendance_entry_payload(ATTENDANCE_DATE, OFF_INCREMENT_HOURS),
        headers=make_instructor_headers("instructor-2"),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

    enrollment = fixtures.read_enrollment(enrollment_id)
    assert_hours_value(enrollment["posted_hours"], 0)
    assert enrollment["post_test_eligible"] is False


def test_04_an_inverted_functioning_level_band_is_refused_at_creation():
    """"the inclusive functioning-level band it accepts as `min_efl_level` and
    `max_efl_level` — each between 1 and 6, with the maximum no lower than the minimum"

    Design: Corner/entities/class_section_max_efl_below_min_rejected
    """
    assert _total_class_sections() == 0

    response = api_client.create_class_section(
        factories.create_class_section_payload(
            program_track=ProgramTrack.LITERACY,
            title="Inverted Band",
            instructor_user_id="instructor-3",
            min_efl_level=4,
            max_efl_level=2,
            seats_total=10,
            weekly_hours=6.00,
        ),
        headers=make_program_coordinator_headers(),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

    assert _total_class_sections() == 0


def test_05_a_period_whose_window_is_empty_is_refused_before_any_pool_arithmetic():
    """"A `StateAuthority` opens one with a non-empty `label`, a `start_date` as the first UTC
    date inside the outcome window and an `end_date` as the first UTC date after it — so the
    window is inclusive of its start and exclusive of its end, and `end_date` must be later
    than `start_date`"

    Design: Corner/entities/funding_period_end_date_not_after_start_rejected
    """
    response = api_client.create_funding_period(
        factories.create_funding_period_payload(
            label="PY-EMPTY",
            start_date="2026-07-01",
            end_date="2026-07-01",
            rate_cents_per_weight=10000,
            total_cents=100000,
        ),
        headers=make_state_authority_headers(),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

    _, meta = validate_paginated(
        api_client.list_funding_periods(
            headers=make_state_authority_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0


def test_06_a_standardized_score_above_the_instrument_range_leaves_the_event_scheduled():
    """"An `Instructor` — and only an `Instructor` — scores a test event, supplying the raw
    `scale_score`, which for a standardized instrument must be an integer between 0 and 999
    inclusive."

    Design: Corner/entities/test_event_scale_score_above_range_rejected
    """
    context = _setup_scheduled_pre_test()

    response = api_client.score_test_event(
        context["test_event_id"],
        factories.score_test_event_payload(OUT_OF_RANGE_SCALE_SCORE),
        headers=make_instructor_headers(),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

    event = fixtures.read_test_event(context["test_event_id"])
    assert event["status"] == TestEventStatus.SCHEDULED
    assert event["scale_score"] is None
    assert event["efl_level"] is None
    assert event["test_date"] is None
    assert fixtures.read_student(context["student_id"])["placement_efl_level"] is None


def test_07_a_lowercase_state_code_is_refused_rather_than_normalised():
    """"Only a `StateAuthority` registers a **testing centre**, supplying a non-empty display
    `name` and the `state_code` of the state that owns the authorisation, which must be
    exactly two uppercase letters."

    Design: Corner/entities/testing_center_state_code_lowercase_rejected
    """
    response = api_client.create_testing_center(
        factories.create_testing_center_payload(name="Lowercase Center", state_code="or"),
        headers=make_state_authority_headers(),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

    _, meta = validate_paginated(
        api_client.list_testing_centers(
            headers=make_state_authority_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
