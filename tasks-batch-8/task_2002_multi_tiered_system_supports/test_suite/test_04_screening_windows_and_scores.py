"""Screening window lifecycle gates and score-recording guards (PRD §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_screening_score,
    close_window,
    create_screening_window,
    define_cut_point,
    enroll_student,
    record_screening_score_payload,
    set_clock,
    setup_district_school,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["district_coordinator_headers"]
TEACHER = TEST_USERS["teacher_headers"]


class TestWindowLifecycleGates:
    def test_score_rejected_while_window_scheduled(self, api):
        """PRD §3.3: "Scoring requires the window to be `CLOSED` — attempting it
        in any other state is rejected with `ERR_INVALID_STATE` — and requires
        that every score in the window already carries a computed `risk_band`,
        which always holds because classification happens at record time."

        Design: Corner/state_machines/window_invalid_from_schedule_to_scored
        """
        district, school = setup_district_school(api, grade_span_low=0,
                                                 grade_span_high=5)
        window = create_screening_window(api, district["id"], school["id"],
                                         window_kind="FALL", opens_on="2026-09-01",
                                         closes_on="2026-09-30")
        # The logical clock sits before opens_on, so the window is SCHEDULED.
        set_clock(api, "2026-08-15T00:00:00Z")
        resp = api.score_screening_window(district["id"], school["id"],
                                          window["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_score_recording_requires_open_window_and_clock_in_range(self, api):
        """PRD §3.3: "Recording is only allowed while the window's `status` is
        `OPEN` and the logical clock falls within the inclusive `opens_on` to
        `closes_on` range; otherwise the submission is rejected with
        `ERR_WINDOW_NOT_OPEN` (HTTP 409)."
        PRD §2.7: "A `SCHEDULED` screening window transitions to `OPEN`
        automatically when the clock reaches its `opens_on` date, and an `OPEN`
        window transitions to `CLOSED` automatically once the clock passes its
        `closes_on` date."

        Boundary: the clock at the final second of the closes_on date is still
        inside the inclusive range, so the score is accepted.

        Design: Difficulty/resource_temporal_overlap/screening_window_adjacent_boundaries
        """
        district, school = setup_district_school(api)
        d_id, s_id = district["id"], school["id"]
        define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=3,
                         subject="READING", tier2_max_score=100,
                         tier3_max_score=70)
        window = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                         opens_on="2026-08-01",
                                         closes_on="2026-08-31")
        student = enroll_student(api, d_id, s_id, full_name="D1", grade_level=3)
        # Clock at the last second of the inclusive closes_on day.
        set_clock(api, "2026-08-31T23:59:59Z")
        resp = api.record_screening_score(
            d_id, s_id, window["id"],
            record_screening_score_payload(student["id"], subject="READING",
                                           raw_score=80),
            TEACHER)
        score = validate_success(resp, 201)
        assert_screening_score(score)
        assert score["raw_score"] == 80

    def test_score_recording_rejected_outside_window_range(self, api):
        """PRD §3.3: "Recording is only allowed while the window's `status` is
        `OPEN` and the logical clock falls within the inclusive `opens_on` to
        `closes_on` range; otherwise the submission is rejected with
        `ERR_WINDOW_NOT_OPEN` (HTTP 409)."
        PRD §2.7: "A `SCHEDULED` screening window transitions to `OPEN`
        automatically when the clock reaches its `opens_on` date, and an `OPEN`
        window transitions to `CLOSED` automatically once the clock passes its
        `closes_on` date."

        One second past closes_on the window is no longer open; before opens_on
        it is not open yet. A manually closed window is likewise not open.

        Design: Difficulty/resource_temporal_overlap/screening_window_adjacent_boundaries
        """
        district, school = setup_district_school(api)
        d_id, s_id = district["id"], school["id"]
        define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=3,
                         subject="READING", tier2_max_score=100,
                         tier3_max_score=70)
        student = enroll_student(api, d_id, s_id, full_name="D2", grade_level=3)

        # Case 1: clock before opens_on — window has not opened.
        early = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                        opens_on="2026-09-01",
                                        closes_on="2026-09-30")
        set_clock(api, "2026-08-15T00:00:00Z")
        resp = api.record_screening_score(
            d_id, s_id, early["id"],
            record_screening_score_payload(student["id"], raw_score=80), TEACHER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN, 409)

        # Case 2: clock one second past the inclusive closes_on day — the OPEN
        # window has transitioned to CLOSED automatically.
        late = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                       opens_on="2026-08-01",
                                       closes_on="2026-08-31")
        set_clock(api, "2026-09-01T00:00:00Z")
        resp = api.record_screening_score(
            d_id, s_id, late["id"],
            record_screening_score_payload(student["id"], raw_score=80), TEACHER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN, 409)

        # Case 3: a window closed manually ahead of schedule is no longer open.
        # Park the clock inside the range BEFORE creating the window: the
        # lifecycle runs SCHEDULED -> OPEN -> CLOSED -> SCORED with forward
        # transitions only (PRD §3.3), so a window created while the clock is
        # past its closes_on is already CLOSED and cannot be manually closed.
        set_clock(api, "2026-08-10T00:00:00Z")
        manual = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                         opens_on="2026-08-01",
                                         closes_on="2026-08-31")
        close_window(api, d_id, s_id, manual["id"])
        resp = api.record_screening_score(
            d_id, s_id, manual["id"],
            record_screening_score_payload(student["id"], raw_score=80), TEACHER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN, 409)


class TestCutPointLookup:
    def test_score_rejected_when_no_matching_cut_point(self, api):
        """PRD §3.3: "Then a benchmark cut point matching the school, the
        window's `window_kind`, the student's `grade_level`, and the score's
        `subject` must exist; if none does, the submission is rejected with
        `ERR_CUT_POINT_NOT_DEFINED` (HTTP 422)."

        Design: Corner/validations/cut_point_not_defined
        """
        district, school = setup_district_school(api)
        d_id, s_id = district["id"], school["id"]
        # Cut point exists for grade 4 only; the student is in grade 3.
        define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=4,
                         subject="READING", tier2_max_score=100,
                         tier3_max_score=70)
        window = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                         opens_on="2026-08-01",
                                         closes_on="2026-08-31")
        set_clock(api, "2026-08-05T00:00:00Z")
        student = enroll_student(api, d_id, s_id, full_name="P", grade_level=3)
        resp = api.record_screening_score(
            d_id, s_id, window["id"],
            record_screening_score_payload(student["id"], subject="READING",
                                           raw_score=80),
            TEACHER)
        validate_error(resp, ApiErrorId.ERR_CUT_POINT_NOT_DEFINED, 422)
