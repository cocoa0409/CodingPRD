"""Seat-time accumulation under the daily cap and exam progression (PRD §3.6, §3.7).

Covers the raw-vs-creditable divergence, per-day cap splitting, completion
fraction rounding, the inclusive SEAT_TIME_MET threshold, the void regression
loop, and exam attempt slot accounting.
"""
from test_helpers import (
    ApiErrorId,
    assert_enrollment,
    enroll,
    enroll_with_seat_time,
    get_enrollment,
    get_success_data,
    record_attendance,
    schedule_attempt,
    score_attempt,
    setup_publishable_school,
    validate_error,
    validate_success,
    verify_attempt,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    DIRECTOR,
    REGISTRAR,
    create_credentialed_instructor,
    create_proctor,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/seat_time_raw_vs_creditable_daily_cap
# ---------------------------------------------------------------------------

class TestSeatTimeRawVsCreditableDailyCap:
    def test_single_overcap_day_diverges_raw_and_creditable(self, api):
        """PRD §3.6: "So a single 500-minute session day contributes 500 to the
        verified total but only 480 to the creditable one, and the two fields
        diverge whenever any day exceeds the cap."

        Design: Difficulty/dual_variant_calc/seat_time_raw_vs_creditable_daily_cap
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=500)
        enr = get_enrollment(enr["id"])
        assert enr["verified_seat_minutes"] == 500, "raw variant is uncapped"
        assert enr["creditable_seat_minutes"] == 480, "daily cap clips to 480"
        assert enr["completion_fraction_bps"] == 1600  # round_half_up(480*10000/3000)
        assert enr["academic_status"] == "IN_PROGRESS"  # 480 < 3000

    def test_completion_fraction_derives_from_capped_variant(self, api):
        """PRD §3.6: "From the creditable total the system derives
        `completion_fraction_bps`: the creditable minutes multiplied by 10000,
        divided by the course's `required_seat_minutes`, and rounded half-up to
        an integer basis-point value".

        Design: Difficulty/dual_variant_calc/seat_time_raw_vs_creditable_daily_cap
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=500)
        enr = get_enrollment(enr["id"])
        # Fraction keys on the CAPPED total: 480*10000/3000 = 1600, not the raw
        # 500*10000/3000 = 1666.67 -> 1667.
        assert enr["completion_fraction_bps"] == 1600
        assert enr["verified_seat_minutes"] != enr["creditable_seat_minutes"]


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/seat_time_exact_threshold_met
# ---------------------------------------------------------------------------

class TestSeatTimeExactThreshold:
    def test_below_threshold_stays_in_progress(self, api):
        """PRD §3.6: "When a recomputation brings `creditable_seat_minutes` to at
        least `required_seat_minutes` — equality qualifies — the enrollment moves
        from `IN_PROGRESS` to `SEAT_TIME_MET`." At 2880 of 3000 the threshold is
        not yet reached.

        Design: Difficulty/boundary_precision_check/seat_time_exact_threshold_met
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        for day in range(1, 7):  # six 480-minute days -> 2880
            record_attendance(enr["id"], env["instructor"]["id"],
                              session_date=f"2026-09-0{day}", minutes=480)
        enr = get_enrollment(enr["id"])
        assert enr["creditable_seat_minutes"] == 2880
        assert enr["academic_status"] == "IN_PROGRESS", "2880 < 3000 must not flip"

    def test_exact_equality_flips_to_seat_time_met(self, api):
        """PRD §3.6: "When a recomputation brings `creditable_seat_minutes` to at
        least `required_seat_minutes` — equality qualifies — the enrollment moves
        from `IN_PROGRESS` to `SEAT_TIME_MET`."

        Design: Difficulty/boundary_precision_check/seat_time_exact_threshold_met
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        for day in range(1, 7):
            record_attendance(enr["id"], env["instructor"]["id"],
                              session_date=f"2026-09-0{day}", minutes=480)
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-07", minutes=120)
        enr = get_enrollment(enr["id"])
        assert enr["creditable_seat_minutes"] == 3000, "exactly at requirement"
        assert enr["academic_status"] == "SEAT_TIME_MET", "equality qualifies"
        assert enr["completion_fraction_bps"] == 10000


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/enrollment_parallel_dimensions_with_regression
# ---------------------------------------------------------------------------

class TestEnrollmentParallelDimensionsWithRegression:
    def test_academic_and_payment_dimensions_evolve_independently(self, api):
        """PRD §3.5: "The new enrollment starts with `academic_status` `ENROLLED`
        and `payment_status` `PENDING` — two parallel dimensions that evolve
        independently."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_dimensions_with_regression
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 120})
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        assert enr["academic_status"] == "ENROLLED"
        assert enr["payment_status"] == "PENDING"
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=60)
        paid = get_success_data(api.pay_enrollment(
            enr["id"], {"amount_cents": enr["charge_total_cents"]}, REGISTRAR))
        assert paid["academic_status"] == "IN_PROGRESS", "pay does not advance academics"
        assert paid["payment_status"] == "PAID"

    def test_void_regresses_seat_time_while_payment_stays_paid(self, api):
        """PRD §3.6: "Voiding is the instructor's correction mechanism: a
        record's status flips from `VERIFIED` to `VOID`, the totals are
        recomputed, and if the creditable total drops back below the requirement
        the enrollment regresses from `SEAT_TIME_MET` to `IN_PROGRESS` — the
        seat-time dimension loops rather than ratchets."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_dimensions_with_regression
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 120})
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=60)
        paid = get_success_data(api.pay_enrollment(
            enr["id"], {"amount_cents": enr["charge_total_cents"]}, REGISTRAR))
        second = record_attendance(enr["id"], env["instructor"]["id"],
                                   session_date="2026-09-04", minutes=60)
        enr = get_enrollment(enr["id"])
        assert enr["creditable_seat_minutes"] == 120
        assert enr["academic_status"] == "SEAT_TIME_MET"
        assert enr["payment_status"] == "PAID"
        get_success_data(api.void_attendance_record(
            second["id"], {"X-User-ID": env["instructor"]["id"],
                           "X-User-Role": "Instructor",
                           "Content-Type": "application/json"}))
        enr = get_enrollment(enr["id"])
        assert enr["creditable_seat_minutes"] == 60
        assert enr["academic_status"] == "IN_PROGRESS", "void regressed the seat-time dimension"
        assert enr["payment_status"] == "PAID", "payment dimension untouched by the void"


# ---------------------------------------------------------------------------
# Corner/calculations/cn_daily_cap_split_sessions
# ---------------------------------------------------------------------------

def test_daily_cap_splits_two_same_day_sessions(api):
    """PRD §3.6: "each record is credited the lesser of its own `minutes` and the
    headroom remaining under that day's cap (never less than zero). The
    creditable total is the sum of those credited values". Two 300-minute
    sessions on one day credit 300 + 180 = 480 while the raw total stays 600.

    Design: Corner/calculations/cn_daily_cap_split_sessions
    """
    env = setup_publishable_school()
    _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
    record_attendance(enr["id"], env["instructor"]["id"],
                      session_date="2026-09-03", minutes=300)
    record_attendance(enr["id"], env["instructor"]["id"],
                      session_date="2026-09-03", minutes=300)
    enr = get_enrollment(enr["id"])
    assert enr["verified_seat_minutes"] == 600
    assert enr["creditable_seat_minutes"] == 480  # 300 + min(300, 480-300)


# ---------------------------------------------------------------------------
# Corner/calculations/cn_completion_fraction_rounding
# ---------------------------------------------------------------------------

def test_completion_fraction_rounds_half_up(api):
    """PRD §3.6: "From the creditable total the system derives
    `completion_fraction_bps`: the creditable minutes multiplied by 10000,
    divided by the course's `required_seat_minutes`, and rounded half-up to an
    integer basis-point value". 455 of 3000 minutes -> 1516.66... -> 1517 bps.

    Design: Corner/calculations/cn_completion_fraction_rounding
    """
    env = setup_publishable_school()
    _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
    record_attendance(enr["id"], env["instructor"]["id"],
                      session_date="2026-09-03", minutes=455)
    enr = get_enrollment(enr["id"])
    assert enr["completion_fraction_bps"] == 1517  # round_half_up(455*10000/3000)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/attempt_requires_seat_time_met
# ---------------------------------------------------------------------------

class TestAttemptRequiresSeatTimeMet:
    def test_attempt_rejected_while_enrolled(self, api):
        """PRD §3.7: "Once an enrollment stands `SEAT_TIME_MET`, the `Registrar`
        schedules a proctored final-exam attempt... Scheduling from any other
        academic state fails with `ERR_SEAT_TIME_NOT_MET`."

        Design: Difficulty/cross_entity_state_dependency/attempt_requires_seat_time_met
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        resp = api.create_exam_attempt(
            enr["id"],
            {"scheduled_at": "2026-09-11T14:00:00Z",
             "proctor_instructor_id": proctor["id"]},
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_SEAT_TIME_NOT_MET)

    def test_attempt_allowed_after_seat_time_met(self, api):
        """PRD §3.7: "The new attempt's `attempt_number` is `exam_attempts_used`
        plus 1, and it starts `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/attempt_requires_seat_time_met
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        attempt = schedule_attempt(enr["id"], proctor["id"])
        assert attempt["attempt_number"] == 1
        assert attempt["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/calculations/cn_attempt_slot_counting_and_exhaustion
# ---------------------------------------------------------------------------

class TestAttemptSlotCountingAndExhaustion:
    def test_no_show_consumes_a_slot_and_exhaustion_blocks_third(self, api):
        """PRD §3.7: "Attempts abandoned without invalidation are swept: an
        attempt still `SCHEDULED` more than 24 hours after its `scheduled_at`
        moves to `NO_SHOW`, which does consume a slot." and "scheduling is
        rejected when that count already equals the course's
        `max_exam_attempts` (`ERR_EXAM_ATTEMPTS_EXHAUSTED`). With the default
        maximum of 2, attempt number 2 is allowed and a third is refused."

        Design: Corner/calculations/cn_attempt_slot_counting_and_exhaustion
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        a1 = schedule_attempt(enr["id"], proctor["id"],
                              scheduled_at="2026-09-11T14:00:00Z")
        a2 = schedule_attempt(enr["id"], proctor["id"],
                              scheduled_at="2026-09-12T14:00:00Z")
        assert a1["attempt_number"] == 1 and a2["attempt_number"] == 2
        from test_helpers.fixtures import run_sweep, set_clock
        set_clock("2026-09-14T00:00:00Z")
        summary = run_sweep()
        assert summary["attempts_no_show"] == 2, "both SCHEDULED attempts past the 24h grace"
        resp = api.create_exam_attempt(
            enr["id"],
            {"scheduled_at": "2026-09-15T14:00:00Z",
             "proctor_instructor_id": proctor["id"]},
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_EXAM_ATTEMPTS_EXHAUSTED)
        enr = get_enrollment(enr["id"])
        assert enr["exam_attempts_used"] == 2
        assert enr["academic_status"] == "SEAT_TIME_MET", "NO_SHOW does not fail the student"

    def test_attempt_numbers_assigned_sequentially(self, api):
        """PRD §3.7: "`exam_attempts_used` counts the enrollment's attempts in
        `SCHEDULED`, `PROCTORED`, `SCORED`, or `NO_SHOW` — `INVALIDATED` attempts
        consume no slot — ... The new attempt's `attempt_number` is
        `exam_attempts_used` plus 1".

        Design: Corner/calculations/cn_attempt_slot_counting_and_exhaustion
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        a1 = schedule_attempt(enr["id"], proctor["id"],
                              scheduled_at="2026-09-11T14:00:00Z")
        a2 = schedule_attempt(enr["id"], proctor["id"],
                              scheduled_at="2026-09-12T14:00:00Z")
        assert (a1["attempt_number"], a2["attempt_number"]) == (1, 2)
