"""Arithmetic on the instructional side: the inclusive band floors, the per-instrument tables,
the definitive earliest pre-test, quarter-hour sums, and the two asymmetric post-test gates.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import (
    assert_hours_value,
    assert_skill_gain_read,
    assert_test_event,
)
from test_helpers.test_users import make_registrar_headers
from test_helpers.types import (
    IntakeStatus,
    MsgVariant,
    ProgramTrack,
    SectionStatus,
    TestEventPurpose,
    TestEventStatus,
    TestForm,
)

FIRST_PRE_TEST_AT = "2026-08-02T09:00:00Z"
SECOND_PRE_TEST_AT = "2026-08-05T09:00:00Z"

LEVEL_THREE_FLOOR = 220
LEVEL_FOUR_FLOOR = 221

QUARTER_HOUR_CLOCK = "2026-08-06T00:00:00Z"
QUARTER_HOUR_POSTINGS = (("2026-08-03", 0.25), ("2026-08-04", 0.75), ("2026-08-05", 2.50))

FORTY_HOUR_CLOCK = "2026-08-08T09:00:00Z"
FULL_DAY_DATES = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07")
FULL_DAY_HOURS = 8.00
TOO_EARLY_POST_TEST_AT = "2026-08-20T09:00:00Z"
THIRTIETH_DAY_CLOCK = "2026-09-01T09:00:00Z"
LATER_POST_TEST_AT = "2026-09-05T09:00:00Z"

MSG_PERIOD_LABEL = "PY26-MSG"
MSG_WINDOW = ("2026-07-01", "2026-09-30")
RATE_CENTS_PER_WEIGHT = 10000
POOL_CENTS = 500000


def _oriented_learner_with_scheduled_pre_test(full_name, email, primary_track, test_form):
    student = fixtures.create_oriented_student(
        full_name=full_name, email=email, primary_track=primary_track
    )
    event = fixtures.schedule_test_event(
        student["id"],
        FIRST_PRE_TEST_AT,
        purpose=TestEventPurpose.PRE_TEST,
        test_form=test_form,
    )
    fixtures.set_clock(FIRST_PRE_TEST_AT)
    return student["id"], event["id"]


def _score_on_form(full_name, email, primary_track, test_form, scale_score):
    student_id, event_id = _oriented_learner_with_scheduled_pre_test(
        full_name, email, primary_track, test_form
    )
    scored = assert_test_event(fixtures.score_test_event(event_id, scale_score))
    return student_id, scored


def _enrolled_learner(full_name, email, title, instructor_user_id, weekly_hours):
    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=FIRST_PRE_TEST_AT,
        full_name=full_name,
        email=email,
        primary_track=ProgramTrack.HSE_PREP,
    )
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=ProgramTrack.HSE_PREP,
        title=title,
        instructor_user_id=instructor_user_id,
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=weekly_hours,
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    return {
        "student_id": placed["student_id"],
        "section_id": section["id"],
        "enrollment_id": enrollment["id"],
    }


def test_01_a_score_resting_on_a_band_floor_is_read_as_the_lower_band():
    """"For `CASAS_R_900` the floors are level 1 from a score of 0, level 2 from 201, level 3
    from 211, level 4 from 221, level 5 from 236 and level 6 from 246." and "The derived level
    is the highest level whose floor the score reaches or exceeds."

    Design: Corner/calculations/efl_placement_band_floor_takes_the_higher_level
    """
    student_id, scored = _score_on_form(
        "Jae Lundy",
        "jae.lundy@example.org",
        ProgramTrack.HSE_PREP,
        TestForm.CASAS_R_900,
        LEVEL_THREE_FLOOR,
    )
    assert scored["status"] == TestEventStatus.SCORED
    assert scored["scale_score"] == LEVEL_THREE_FLOOR
    assert scored["efl_level"] == 3
    assert scored["test_date"] == FIRST_PRE_TEST_AT

    learner = fixtures.read_student(student_id)
    assert learner["placement_efl_level"] == 3
    assert learner["intake_status"] == IntakeStatus.PLACED


def test_02_one_more_point_lands_exactly_on_the_next_floor_and_takes_it():
    """"The **functioning-level bands** are per-instrument, ascending, and their lower bounds
    are inclusive: a score landing exactly on a band floor takes the higher of the two levels."

    Design: Corner/calculations/efl_placement_band_floor_takes_the_higher_level
    """
    student_id, scored = _score_on_form(
        "Kesh Ferro",
        "kesh.ferro@example.org",
        ProgramTrack.HSE_PREP,
        TestForm.CASAS_R_900,
        LEVEL_FOUR_FLOOR,
    )
    assert scored["scale_score"] == LEVEL_FOUR_FLOOR
    assert scored["efl_level"] == 4
    assert scored["test_date"] == FIRST_PRE_TEST_AT

    learner = fixtures.read_student(student_id)
    assert learner["placement_efl_level"] == 4
    assert learner["intake_status"] == IntakeStatus.PLACED


def test_03_the_same_raw_score_means_different_levels_on_different_instruments():
    """"For `CASAS_M_900` they are level 1 from 0, level 2 from 194, level 3 from 203, level 4
    from 214, level 5 from 227 and level 6 from 236. For `BEST_PLUS` they are level 1 from 0,
    level 2 from 401, level 3 from 418, level 4 from 439, level 5 from 473 and level 6 from 507."

    Design: Corner/calculations/efl_placement_bands_keyed_by_test_form
    """
    esl_id, esl_scored = _score_on_form(
        "Lior Adamo",
        "lior.adamo@example.org",
        ProgramTrack.ESL,
        TestForm.BEST_PLUS,
        439,
    )
    assert esl_scored["test_form"] == TestForm.BEST_PLUS
    assert esl_scored["efl_level"] == 4
    assert fixtures.read_student(esl_id)["placement_efl_level"] == 4

    hse_id, hse_scored = _score_on_form(
        "Mina Toure",
        "mina.toure@example.org",
        ProgramTrack.HSE_PREP,
        TestForm.CASAS_M_900,
        236,
    )
    assert hse_scored["test_form"] == TestForm.CASAS_M_900
    assert hse_scored["efl_level"] == 6
    assert fixtures.read_student(hse_id)["placement_efl_level"] == 6


def test_04_a_stronger_later_pre_test_leaves_the_original_placement_standing():
    """"A later pre-test never overwrites `placement_efl_level`; the earliest scored one is
    definitive." and "When the scored event's `purpose` is `PRE_TEST` and it is the learner's
    **earliest** scored pre-test — earliest by `test_date` ascending, ties broken by
    `created_at` ascending — the derived level is copied onto the learner as
    `placement_efl_level`"

    Design: Corner/calculations/efl_placement_uses_earliest_scored_pre_test_only
    """
    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=FIRST_PRE_TEST_AT,
        full_name="Noor Zaki",
        email="noor.zaki@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    assert placed["pre_test"]["efl_level"] == 2

    second = fixtures.schedule_test_event(
        placed["student_id"],
        SECOND_PRE_TEST_AT,
        purpose=TestEventPurpose.PRE_TEST,
        test_form=TestForm.CASAS_R_900,
    )
    fixtures.set_clock(SECOND_PRE_TEST_AT)
    rescored = fixtures.score_test_event(second["id"], 246)
    assert rescored["efl_level"] == 6
    assert rescored["test_date"] == SECOND_PRE_TEST_AT

    learner = fixtures.read_student(placed["student_id"])
    assert learner["placement_efl_level"] == 2
    assert learner["intake_status"] == IntakeStatus.PLACED

    page, meta = validate_paginated(
        api_client.list_test_events(
            headers=make_registrar_headers(),
            params={
                "student_id": placed["student_id"],
                "purpose": TestEventPurpose.PRE_TEST,
                "status": TestEventStatus.SCORED,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2
    levels_by_id = {row["id"]: row["efl_level"] for row in page}
    assert levels_by_id[placed["pre_test"]["id"]] == 2
    assert levels_by_id[second["id"]] == 6


def test_05_quarter_hour_postings_sum_without_drifting_off_the_increment():
    """"Both aggregates are carried to two decimal places, rounded half up, and because
    postings are always quarter-hour multiples the sums are themselves exact quarter-hour
    multiples." and "A learner's `total_instructional_hours` is the sum of `posted_hours`
    across every one of that learner's enrollments regardless of enrollment status"

    Design: Corner/calculations/instructional_hour_ledger_quarter_hour_precision
    """
    context = _enrolled_learner(
        "Otis Vane", "otis.vane@example.org", "Quarter Hours", "instructor-11", 6.00
    )
    fixtures.set_clock(QUARTER_HOUR_CLOCK)

    for attendance_date, hours in QUARTER_HOUR_POSTINGS:
        entry = fixtures.post_attendance(context["enrollment_id"], attendance_date, hours)
        assert_hours_value(entry["hours"], hours)

    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 3.50)
    assert enrollment["post_test_eligible"] is False

    learner = fixtures.read_student(context["student_id"])
    assert_hours_value(learner["total_instructional_hours"], 3.50)


def test_06_forty_banked_hours_flip_the_flag_but_do_not_buy_a_post_test():
    """"The stored `post_test_eligible` flag on an enrollment tracks the hour gate alone: it is
    true exactly when `posted_hours` has reached at least forty hours, and false otherwise." and
    "Of the two, the interval gate is evaluated first, so a learner who is short on both hours
    and days is told `ERR_POST_TEST_INTERVAL_NOT_MET`"

    Design: Corner/calculations/post_test_eligible_flag_tracks_the_hour_gate_only
    """
    context = _enrolled_learner(
        "Pav Ionescu", "pav.ionescu@example.org", "Two Gates", "instructor-12", 8.00
    )
    fixtures.set_clock(FORTY_HOUR_CLOCK)
    for attendance_date in FULL_DAY_DATES:
        fixtures.post_attendance(context["enrollment_id"], attendance_date, FULL_DAY_HOURS)

    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 40.00)
    assert enrollment["post_test_eligible"] is True

    response = api_client.create_test_event(
        factories.create_test_event_payload(
            context["student_id"],
            TOO_EARLY_POST_TEST_AT,
            purpose=TestEventPurpose.POST_TEST,
            test_form=TestForm.CASAS_R_900,
            enrollment_id=context["enrollment_id"],
        ),
        headers=make_registrar_headers(),
    )
    validate_error(response, ApiErrorId.POST_TEST_INTERVAL_NOT_MET, expected_status=409)

    assert_hours_value(
        fixtures.read_enrollment(context["enrollment_id"])["posted_hours"], 40.00
    )


def test_07_the_thirtieth_whole_day_is_enough_for_the_interval_gate():
    """"at least thirty whole UTC days must separate the learner's earliest scored pre-test's
    `test_date` from the logical clock's current instant, counting whole days and discarding any
    partial day, with the thirtieth day itself sufficient."

    Design: Corner/calculations/post_test_eligible_flag_tracks_the_hour_gate_only
    """
    context = _enrolled_learner(
        "Pav Ionescu", "pav.ionescu@example.org", "Two Gates", "instructor-12", 8.00
    )
    fixtures.set_clock(FORTY_HOUR_CLOCK)
    for attendance_date in FULL_DAY_DATES:
        fixtures.post_attendance(context["enrollment_id"], attendance_date, FULL_DAY_HOURS)
    fixtures.set_clock(THIRTIETH_DAY_CLOCK)

    booked = validate_success(
        api_client.create_test_event(
            factories.create_test_event_payload(
                context["student_id"],
                LATER_POST_TEST_AT,
                purpose=TestEventPurpose.POST_TEST,
                test_form=TestForm.CASAS_R_900,
                enrollment_id=context["enrollment_id"],
            ),
            headers=make_registrar_headers(),
        ),
        expected_status=201,
    )
    assert booked["status"] == TestEventStatus.SCHEDULED
    assert booked["purpose"] == TestEventPurpose.POST_TEST
    assert booked["enrollment_id"] == context["enrollment_id"]
    assert booked["scheduled_for"] == LATER_POST_TEST_AT

    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 40.00)
    assert enrollment["post_test_eligible"] is True


def test_08_a_learner_with_only_a_pre_test_reports_a_null_post_side():
    """"When there is no qualifying pre-test, or no qualifying post-test at all, no gain is
    claimed: the determination reports a null post side and no achievement." and "`BEST_POST`
    is the provisional, programmatic view and is what the skill-gain read returns by default."

    Design: Corner/calculations/msg_determination_without_a_post_test_reports_no_gain
    """
    period = fixtures.create_funding_period(
        label=MSG_PERIOD_LABEL,
        start_date=MSG_WINDOW[0],
        end_date=MSG_WINDOW[1],
        rate_cents_per_weight=RATE_CENTS_PER_WEIGHT,
        total_cents=POOL_CENTS,
    )
    placed = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=FIRST_PRE_TEST_AT,
        full_name="Quinn Baros",
        email="quinn.baros@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )

    determination = assert_skill_gain_read(
        fixtures.read_skill_gain(placed["student_id"], funding_period_id=period["id"])
    )
    assert determination["student_id"] == placed["student_id"]
    assert determination["variant"] == MsgVariant.BEST_POST
    assert determination["entry_efl_level"] == 2
    assert determination["post_efl_level"] is None
    assert determination["best_post_scale_score"] is None
    assert determination["latest_post_scale_score"] is None
    # The PRD defines ``levels_gained`` only as "the post level less the entry level"; with a
    # null post side that subtraction has no stated value, so no concrete reading is asserted.
    assert determination["msg_achieved"] is False
