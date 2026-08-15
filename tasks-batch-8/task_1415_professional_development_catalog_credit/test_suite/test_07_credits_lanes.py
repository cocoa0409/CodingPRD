"""Credit conversion variants, transcript rollup rounding, and lane advancement."""
import pytest

from test_helpers import (
    TEST_USERS, complete_registration, list_transcript, make_building,
    make_course, make_section, make_teacher, add_meeting, publish_section,
    prepare_completable_registration, register_teacher, run_ops, set_clock,
    setup_catalog_scenario, setup_completed_course, validate_error,
    validate_success,
)


def _complete_course_for(teacher_id, building_id, instructor_id, *,
                         course_code, clock_hours, starts_at, ends_at,
                         reg_closes_at, meeting_start, meeting_end,
                         in_session_clock):
    """One full completion chain for a single course/section. Returns the
    COMPLETED registration."""
    # Distinct room per course: PRD §3.2 enforces the 30-minute turnover gap
    # against EVERY existing meeting in a room, so reusing the default room
    # would collide with the seed scenario's meeting.
    room = f"RM-{course_code}"
    course = make_course(course_code=course_code, clock_hours=clock_hours,
                         fee_cents=0, delivery_mode="VIRTUAL")
    section = make_section(course["id"], instructor_id, building_id,
                           starts_at=starts_at, ends_at=ends_at,
                           registration_closes_at=reg_closes_at,
                           room=room)
    meeting = add_meeting(section["id"], meeting_start, meeting_end, room)
    publish_section(section["id"])
    registration = register_teacher(teacher_id, section["id"])
    prepare_completable_registration(registration["id"], instructor_id, [meeting],
                                     survey="waive")
    # prepare_* parks the clock at 2026-08-16; move to this section's window.
    set_clock(in_session_clock)
    run_ops()
    return complete_registration(registration["id"])


class TestDualVariantCreditConversion:
    """One 24-hour completion carries both conversion variants on one entry."""

    def _completed_24h(self):
        return setup_completed_course(clock_hours=24, fee_cents=0,
                                      course_overrides={"course_code": "MATH-24",
                                                        "title": "Deep Math"},
                                      teacher_lane="MA")

    def test_district_credit_floored_per_entry(self, api):
        """PRD §2.6: "**District lane credit** accrues at fifteen hours per
        credit and is truncated — floored — to one decimal place per transcript
        entry, so a 24-hour course yields 1.6 district credits on that entry."
        PRD §3.5: "a `TranscriptEntry` is minted: `source_type`
        `COURSE_COMPLETION`, `source_id` pointing at the registration,
        `clock_hours` equal to the course's `clock_hours`".

        Design: Difficulty/dual_variant_calc/dual_variant_credit_conversion_district_vs_state
        """
        sc = self._completed_24h()
        assert len(sc.entries) == 1
        entry = sc.entries[0]
        assert entry["source_type"] == "COURSE_COMPLETION"
        assert entry["clock_hours"] == pytest.approx(24)
        assert entry["district_credit"] == pytest.approx(1.6), (
            "floor(24*2/3)/10 — truncated per entry")

    def test_state_ceu_rounded_half_up_and_lane_flag(self, api):
        """PRD §2.6: "**State CEU** accrues at ten hours per CEU and is rounded
        half-up to two decimal places per entry, so the same 24 hours yield 2.40
        CEUs." PRD §3.5: "its `counts_toward_lane` is `false` when the source
        course carries a `compliance_tag`, `true` otherwise."

        Design: Difficulty/dual_variant_calc/dual_variant_credit_conversion_district_vs_state
        """
        sc = self._completed_24h()
        entry = sc.entries[0]
        assert entry["state_ceu"] == pytest.approx(2.4), "round(24/10, 2) half-up"
        assert entry["district_credit"] != pytest.approx(entry["state_ceu"]), (
            "two valid conversions of identical hours diverge on one entry")
        assert entry["counts_toward_lane"] is True, "no compliance tag"


class TestTranscriptRollupRoundingOrder:
    def _two_completions(self):
        """Same teacher completes a 7-hour course and an 8-hour course."""
        set_clock()
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "SEED", "clock_hours": 5,
                              "fee_cents": 0})
        teacher = make_teacher(sc.building["id"], email="t4@x.com",
                               full_name="T Four")
        r7 = _complete_course_for(
            teacher["id"], sc.building["id"], sc.instructor["id"],
            course_code="C-7H", clock_hours=7,
            starts_at="2026-08-15T09:00:00Z", ends_at="2026-08-20T17:00:00Z",
            reg_closes_at="2026-08-10T00:00:00Z",
            meeting_start="2026-08-15T10:00:00Z",
            meeting_end="2026-08-15T11:00:00Z",
            in_session_clock="2026-08-16T00:00:00Z")
        r8 = _complete_course_for(
            teacher["id"], sc.building["id"], sc.instructor["id"],
            course_code="C-8H", clock_hours=8,
            starts_at="2026-08-22T09:00:00Z", ends_at="2026-08-27T17:00:00Z",
            reg_closes_at="2026-08-18T00:00:00Z",
            meeting_start="2026-08-22T10:00:00Z",
            meeting_end="2026-08-22T11:00:00Z",
            in_session_clock="2026-08-23T00:00:00Z")
        return sc, teacher, r7, r8

    def test_per_entry_values_then_sum(self, api):
        """PRD §2.6: "Rollups never re-round: transcript totals are the sum of
        the per-entry rounded values, not a conversion applied to summed hours.
        An employee with a 7-hour entry and an 8-hour entry holds 0.4 plus 0.5
        equals 0.9 district credits — not the 1.0 that converting the aggregate
        15 hours would produce."

        Design: Difficulty/combinatorial_formula/combinatorial_transcript_rollup_rounding_order
        """
        _sc, teacher, _r7, _r8 = self._two_completions()
        entries, _meta = list_transcript(teacher["id"])
        assert len(entries) == 2
        credits = sorted(e["district_credit"] for e in entries)
        assert credits[0] == pytest.approx(0.4), "floor(7*2/3)/10 per entry"
        assert credits[1] == pytest.approx(0.5), "floor(8*2/3)/10 per entry"

    def test_balance_uses_per_entry_sum_not_aggregate(self, api):
        """PRD §2.6: "The aggregate-then-convert alternative is explicitly
        forbidden." PRD §3.9: "it is the sum of `district_credit` over the
        employee's `AWARDED` transcript entries that count toward the lane, minus
        12.0 for each completed lane advancement."

        Design: Difficulty/combinatorial_formula/combinatorial_transcript_rollup_rounding_order
        """
        _sc, teacher, _r7, _r8 = self._two_completions()
        employee = validate_success(api.get_employee(
            teacher["id"], TEST_USERS["coordinator_headers"]), 200)
        assert employee["lane_credit_balance"] == pytest.approx(0.9), (
            "0.4 + 0.5 — the aggregate-convert 1.0 is the rejected alternative")


def test_credit_conversion_floor_at_14_hours(api):
    """PRD §2.6: "**District lane credit** accrues at fifteen hours per credit
    and is truncated — floored — to one decimal place per transcript entry".
    PRD §2.6: "**State CEU** accrues at ten hours per CEU and is rounded half-up
    to two decimal places per entry".

    Design: Corner/calculations/credit_conversion_floor_at_14_hours
    """
    sc = setup_completed_course(clock_hours=14, fee_cents=0,
                                course_overrides={"course_code": "CF-14"})
    assert len(sc.entries) == 1
    entry = sc.entries[0]
    assert entry["district_credit"] == pytest.approx(0.9), (
        "floor(14*2/3)/10 truncates — not 0.93 or 1.0")
    assert entry["state_ceu"] == pytest.approx(1.4)


def test_lane_advancement_waterfall_carry(api):
    """PRD §3.9: "Success moves the `current_lane` one step up the fixed ladder —
    `BA` to `BA15` to `MA` to `MA15` to `MA30` to `DOC` — subtracts 12.0 from the
    `lane_credit_balance` with any remainder carrying over, stamps
    `last_advancement_fiscal_year` with the current fiscal year, and bumps the
    employee's `version`."

    Design: Corner/calculations/lane_advancement_waterfall_carry
    """
    sc = setup_completed_course(clock_hours=210, fee_cents=0,
                                course_overrides={"course_code": "LA-210",
                                                  "delivery_mode": "HYBRID"},
                                teacher_lane="MA")
    before = validate_success(api.get_employee(
        sc.teacher["id"], TEST_USERS["coordinator_headers"]), 200)
    assert before["lane_credit_balance"] == pytest.approx(14.0), (
        "floor(210*2/3)/10")
    # The completion flow parked the clock at 2026-08-16 — August, inside the
    # advancement window; August 2026 belongs to fiscal year 2026 (PRD §2.4).
    advanced = validate_success(api.advance_lane(
        sc.teacher["id"], TEST_USERS["coordinator_headers"]), 200)
    assert advanced["current_lane"] == "MA15", "one step up from MA"
    assert advanced["lane_credit_balance"] == pytest.approx(2.0), "14.0 - 12.0 carried"
    assert advanced["last_advancement_fiscal_year"] == 2026


def test_advance_lane_outside_window_rejected(api):
    """PRD §3.9: "Lane advancement is a coordinator action gated by six checks,
    evaluated in order: ... the logical clock's month must be August or September
    (`ERR_ADVANCEMENT_WINDOW_CLOSED`)".

    Design: Corner/validations/advance_lane_outside_window_rejected
    """
    sc = setup_completed_course(clock_hours=210, fee_cents=0,
                                course_overrides={"course_code": "AW-210",
                                                  "delivery_mode": "HYBRID"},
                                teacher_lane="MA")
    before = validate_success(api.get_employee(
        sc.teacher["id"], TEST_USERS["coordinator_headers"]), 200)
    assert before["lane_credit_balance"] == pytest.approx(14.0)
    set_clock("2026-10-01T00:00:00Z")  # month 10 — outside {8, 9}
    res = api.advance_lane(sc.teacher["id"], TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_ADVANCEMENT_WINDOW_CLOSED", expected_status=400)


def test_advance_lane_insufficient_credits_rejected(api):
    """PRD §3.9: "their `lane_credit_balance` must be at least 12.0 credits
    (`ERR_LANE_CREDITS_INSUFFICIENT`)".

    Design: Corner/validations/advance_lane_insufficient_credits_rejected
    """
    sc = setup_completed_course(clock_hours=24, fee_cents=0,
                                course_overrides={"course_code": "IC-24"},
                                teacher_lane="MA")
    before = validate_success(api.get_employee(
        sc.teacher["id"], TEST_USERS["coordinator_headers"]), 200)
    assert before["lane_credit_balance"] == pytest.approx(1.6)
    # Clock parked at 2026-08-16 by the completion flow — window open.
    res = api.advance_lane(sc.teacher["id"], TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_LANE_CREDITS_INSUFFICIENT", expected_status=400)


def test_lane_max_reached_rejected(api):
    """PRD §3.9: "their `current_lane` must not already be `DOC`, the top of the
    ladder (`ERR_LANE_MAX_REACHED`)".

    Design: Corner/validations/lane_max_reached_rejected
    """
    set_clock()
    building = make_building(name="LM Bldg", building_code="LM1")
    teacher = make_teacher(building["id"], lane="DOC", email="tlm@x.com")
    # Clock is 2026-08-01 — August, inside the advancement window.
    res = api.advance_lane(teacher["id"], TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_LANE_MAX_REACHED", expected_status=400)


def test_advancement_already_this_fy_rejected(api):
    """PRD §3.9: "their `last_advancement_fiscal_year` must differ from the
    current fiscal year (`ERR_ADVANCEMENT_ALREADY_THIS_FY`)".

    Design: Corner/validations/advancement_already_this_fy_rejected
    """
    sc = setup_completed_course(clock_hours=390, fee_cents=0,
                                course_overrides={"course_code": "AF-390",
                                                  "delivery_mode": "HYBRID"},
                                teacher_lane="MA")
    first = validate_success(api.advance_lane(
        sc.teacher["id"], TEST_USERS["coordinator_headers"]), 200)
    assert first["current_lane"] == "MA15"
    assert first["lane_credit_balance"] == pytest.approx(14.0), "26.0 - 12.0"
    assert first["last_advancement_fiscal_year"] == 2026
    res = api.advance_lane(sc.teacher["id"], TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_ADVANCEMENT_ALREADY_THIS_FY", expected_status=400)
