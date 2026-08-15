"""Composite audition scoring, attendance rate computation, and member standing."""
import pytest

from test_helpers import (
    ApiErrorId,
    audition_decision_payload,
    book_audition,
    create_member,
    create_open_season_with_section,
    create_rehearsal,
    enroll_member,
    find_attendance_record,
    record_member_attendance,
    run_checkpoint,
    score_audition,
    set_clock,
    setup_rehearsing_season_with_active_member,
    validate_error,
    validate_success,
)


class TestCompositeScore:
    def test_composite_score_weighted_precision(self, api, director_headers):
        """PRD §3.2: "The system computes `composite_score` as forty percent of
        the tone score, plus thirty-five percent of the pitch score, plus
        twenty-five percent of the sight score, rounded half up to two decimal
        places."

        Design: Corner/calculations/composite_score_weighted_precision
        """
        season, _section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"])
        scored = validate_success(api.score_audition(
            audition["id"],
            {"tone_score": 9, "pitch_score": 8, "sight_score": 7},
            director_headers))
        # 0.40*9 + 0.35*8 + 0.25*7 = 3.6 + 2.8 + 1.75 = 8.15
        assert scored["composite_score"] == pytest.approx(8.15, abs=1e-9)
        assert scored["status"] == "COMPLETED"
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "AUDITIONED"

    def test_composite_score_exact_accept_threshold(self, api,
                                                    director_headers):
        """PRD §3.2: "for `ACCEPT` or `WAITLIST` the composite must be at least
        7.0, else `ERR_SCORE_BELOW_THRESHOLD`" — 7/7/7 yields exactly 7.0 and
        the boundary is inclusive.

        Design: Corner/calculations/composite_score_exact_accept_threshold
        """
        season, section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"])
        scored = score_audition(audition["id"], 7, 7, 7)
        assert scored["composite_score"] == pytest.approx(7.0, abs=1e-9)

        decided = validate_success(api.decide_audition(
            audition["id"],
            audition_decision_payload("ACCEPT", section["id"]),
            director_headers))
        assert decided["decision"] == "ACCEPTED"
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "ENROLLED", \
            "composite exactly 7.0 admits ACCEPT (inclusive threshold)"
        assert member_data["section_id"] == section["id"]

    def test_composite_below_threshold_rejected_but_waitlistable(
            self, api, director_headers):
        """PRD §3.2: "for `ACCEPT` or `WAITLIST` the composite must be at least
        7.0, else `ERR_SCORE_BELOW_THRESHOLD`" — 6/7/8 yields
        0.40*6 + 0.35*7 + 0.25*8 = 6.85, below the bar.
        PRD §3.2: "a rejection moves them to `REJECTED`, which is terminal."

        Design: Corner/calculations/composite_below_threshold_rejected_but_waitlistable
        """
        season, section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"])
        scored = score_audition(audition["id"], 6, 7, 8)
        assert scored["composite_score"] == pytest.approx(6.85, abs=1e-9)

        resp = api.decide_audition(
            audition["id"],
            audition_decision_payload("ACCEPT", section["id"]),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD)

        # WAITLIST is gated by the same score bar.
        resp = api.decide_audition(
            audition["id"], audition_decision_payload("WAITLIST"),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD)

        decided = validate_success(api.decide_audition(
            audition["id"], audition_decision_payload("REJECT"),
            director_headers))
        assert decided["decision"] == "REJECTED"
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "REJECTED"


class TestRehearsalRecordingGate:
    def test_rehearsal_attendance_before_held_rejected(self, api,
                                                       director_headers):
        """PRD §3.3: "The rehearsal must already have taken place — its
        `scheduled_at` at or before the clock — or the recording is rejected
        with `ERR_REHEARSAL_NOT_HELD`"

        Design: Corner/state_machines/rehearsal_attendance_before_held_rejected
        """
        season, _section, member = setup_rehearsing_season_with_active_member()
        rehearsal = create_rehearsal(season["id"], "2026-08-26T19:00:00Z")
        # Clock is still the startup instant 2026-08-01, before the rehearsal.
        resp = api.record_attendance(
            rehearsal["id"], [{"member_id": member["id"],
                               "status": "PRESENT"}],
            director_headers)
        validate_error(resp, ApiErrorId.ERR_REHEARSAL_NOT_HELD)

        rehearsal_data = validate_success(
            api.get_rehearsal(rehearsal["id"], director_headers))
        assert rehearsal_data["status"] == "SCHEDULED"


def _four_rehearsals_with_records(season_id, member_id, marks):
    """Create 4 rehearsals (Aug 5/12/19/26), move the clock past them, record."""
    ids = [
        create_rehearsal(season_id, "2026-08-05T19:00:00Z")["id"],
        create_rehearsal(season_id, "2026-08-12T19:00:00Z")["id"],
        create_rehearsal(season_id, "2026-08-19T19:00:00Z")["id"],
        create_rehearsal(season_id, "2026-08-26T19:00:00Z")["id"],
    ]
    set_clock("2026-08-27T00:00:00Z")
    for rid, mark in zip(ids, marks):
        record_member_attendance(rid, member_id, mark)
    return ids


class TestAttendanceRateWeighted:
    def test_attendance_rate_weighted_conditional(self, api, director_headers):
        """PRD §3.3: "The `attendance_rate` is a weighted fraction over the
        member's counted rehearsals: the season's `COMPLETED` rehearsals
        scheduled at or after the member's `enrolled_at` (cancelled rehearsals
        excluded). ... the numerator weights each record — full credit for
        `PRESENT`, half credit (0.5) for `LATE`, three-quarter credit (0.75)
        for `ABSENT_EXCUSED`, and zero for `ABSENT_UNEXCUSED` — and the
        denominator is the number of counted rehearsals ... The result is
        rounded half up to four decimal places."

        Design: Difficulty/combinatorial_formula/attendance_rate_weighted_conditional
        """
        season, _section, member = (
            setup_rehearsing_season_with_active_member())
        r5 = create_rehearsal(season["id"], "2026-08-27T19:00:00Z")
        cancelled = validate_success(
            api.cancel_rehearsal(r5["id"], director_headers))
        assert cancelled["status"] == "CANCELLED"

        _four_rehearsals_with_records(
            season["id"], member["id"],
            ["PRESENT", "LATE", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED"])

        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        # (1 + 0.5 + 0.75 + 0) / 4 = 0.5625; the cancelled rehearsal is not
        # in the counted set, so the denominator is 4, not 5.
        assert member_data["attendance_rate"] == pytest.approx(0.5625,
                                                               abs=1e-9)

    def test_attendance_rate_excludes_rehearsals_before_enrollment(
            self, api, director_headers):
        """PRD §3.3: "The `attendance_rate` is a weighted fraction over the
        member's counted rehearsals: the season's `COMPLETED` rehearsals
        scheduled at or after the member's `enrolled_at` (cancelled rehearsals
        excluded)." — a rehearsal held before the member enrolled is outside
        the counted set even though the member has no record in it.

        Design: Difficulty/combinatorial_formula/attendance_rate_weighted_conditional
        """
        season, _section, anchor = (
            setup_rehearsing_season_with_active_member())
        # A rehearsal held and completed before the second member enrolls.
        early = create_rehearsal(season["id"], "2026-08-05T19:00:00Z")
        set_clock("2026-08-06T00:00:00Z")
        record_member_attendance(early["id"], anchor["id"], "PRESENT")

        # The second member enrolls on 2026-08-06, after the early rehearsal.
        late_joiner = enroll_member(season["id"], _section["id"],
                                    "Ben", "ben@x.org",
                                    "2026-08-02T11:00:00Z")
        assert late_joiner["status"] == "ENROLLED"

        later = create_rehearsal(season["id"], "2026-08-07T19:00:00Z")
        set_clock("2026-08-08T00:00:00Z")
        record_member_attendance(later["id"], late_joiner["id"], "PRESENT")

        member_data = validate_success(
            api.get_member(late_joiner["id"], director_headers))
        # Only the post-enrollment rehearsal is counted: rate 1.0, not 0.5.
        assert member_data["attendance_rate"] == pytest.approx(1.0, abs=1e-9)


class TestExcuseRecomputesRate:
    def test_excuse_converts_unexcused_and_recomputes_rate(
            self, api, director_headers):
        """PRD §3.3: "The only permitted edit to a recorded mark is excusing
        it: the director converts `ABSENT_UNEXCUSED` to `ABSENT_EXCUSED`, the
        record captures who excused it in `excused_by_user_id`, and the
        member's rate is recomputed"

        Design: Corner/state_machines/excuse_converts_unexcused_and_recomputes_rate
        """
        season, _section, member = (
            setup_rehearsing_season_with_active_member())
        ids = _four_rehearsals_with_records(
            season["id"], member["id"],
            ["PRESENT", "PRESENT", "PRESENT", "ABSENT_UNEXCUSED"])

        before = validate_success(api.get_member(member["id"], director_headers))
        assert before["attendance_rate"] == pytest.approx(0.75, abs=1e-9)

        record = find_attendance_record(ids[3], member["id"])
        excused = validate_success(
            api.excuse_attendance_record(record["id"], director_headers))
        assert excused["status"] == "ABSENT_EXCUSED"
        assert excused["excused_by_user_id"] == "dir-1"

        after = validate_success(api.get_member(member["id"], director_headers))
        # (3 + 0.75) / 4 = 0.9375
        assert after["attendance_rate"] == pytest.approx(0.9375, abs=1e-9)


class TestAttendanceThresholdBoundary:
    def test_attendance_threshold_exact_boundary(self, api, director_headers):
        """PRD §3.3: "Performance eligibility is a three-way conjunction
        recomputed whenever any input changes: `performance_eligible` is true
        exactly when the member's status is `ACTIVE`, their `attendance_rate`
        is at least the season's `attendance_threshold`, and their
        `dues_balance_cents` is zero. The rate boundary is inclusive — a member
        exactly at the threshold qualifies."

        Design: Difficulty/boundary_precision_check/attendance_threshold_exact_boundary
        """
        season, _section, member = (
            setup_rehearsing_season_with_active_member())
        _four_rehearsals_with_records(
            season["id"], member["id"],
            ["PRESENT", "PRESENT", "PRESENT", "ABSENT_UNEXCUSED"])

        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["attendance_rate"] == pytest.approx(0.75, abs=1e-9)
        assert member_data["status"] == "ACTIVE"
        assert member_data["performance_eligible"] is True, \
            "rate exactly equal to the 0.75 threshold qualifies (>=)"

    def test_attendance_just_below_threshold_loses_eligibility(
            self, api, director_headers):
        """PRD §3.3: "`performance_eligible` is true exactly when the member's
        status is `ACTIVE`, their `attendance_rate` is at least the season's
        `attendance_threshold`, and their `dues_balance_cents` is zero."
        PRD §3.3: "At each checkpoint's attendance sweep, an `ACTIVE` member
        whose `attendance_rate` has fallen below the threshold drops to
        `PROBATION`"

        Design: Difficulty/boundary_precision_check/attendance_threshold_exact_boundary
        """
        season, _section, member = (
            setup_rehearsing_season_with_active_member())
        _four_rehearsals_with_records(
            season["id"], member["id"],
            ["PRESENT", "PRESENT", "ABSENT_UNEXCUSED", "ABSENT_UNEXCUSED"])

        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        # 2/4 = 0.5 < 0.75: the inclusive boundary no longer reached.
        assert member_data["attendance_rate"] == pytest.approx(0.5, abs=1e-9)
        assert member_data["performance_eligible"] is False

        run_checkpoint(season["id"])
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "PROBATION"


class TestMemberProbationCycle:
    def test_member_probation_cycle(self, api, director_headers):
        """PRD §3.3: "At each checkpoint's attendance sweep, an `ACTIVE` member
        whose `attendance_rate` has fallen below the threshold drops to
        `PROBATION`, and a `PROBATION` member whose rate is back at or above
        the threshold with a zero dues balance returns to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/member_probation_cycle
        """
        season, _section, member = (
            setup_rehearsing_season_with_active_member())
        ids = [
            create_rehearsal(season["id"], "2026-08-05T19:00:00Z")["id"],
            create_rehearsal(season["id"], "2026-08-12T19:00:00Z")["id"],
            create_rehearsal(season["id"], "2026-08-19T19:00:00Z")["id"],
            create_rehearsal(season["id"], "2026-08-26T19:00:00Z")["id"],
            create_rehearsal(season["id"], "2026-09-02T19:00:00Z")["id"],
        ]
        set_clock("2026-09-03T00:00:00Z")
        for rid, mark in zip(ids, ["PRESENT", "PRESENT", "PRESENT",
                                   "ABSENT_UNEXCUSED", "ABSENT_UNEXCUSED"]):
            record_member_attendance(rid, member["id"], mark)

        # First sweep: rate 3/5 = 0.6 < 0.75 -> PROBATION.
        run_checkpoint(season["id"])
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "PROBATION"
        assert member_data["performance_eligible"] is False

        # Excuse both absences: rate becomes (3 + 0.75 + 0.75)/5 = 0.9.
        for rid in (ids[3], ids[4]):
            record = find_attendance_record(rid, member["id"])
            validate_success(
                api.excuse_attendance_record(record["id"], director_headers))
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["attendance_rate"] == pytest.approx(0.9, abs=1e-9)
        assert member_data["status"] == "PROBATION", \
            "rate recovery alone does not move the member; the sweep does"

        # Second sweep completes the cycle back to ACTIVE.
        run_checkpoint(season["id"])
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "ACTIVE"
        assert member_data["performance_eligible"] is True

    def test_probation_return_requires_zero_dues_balance(
            self, api, director_headers, treasurer_headers):
        """PRD §3.3: "a `PROBATION` member whose rate is back at or above the
        threshold with a zero dues balance returns to `ACTIVE`" — with an open
        invoice the dues conjunct fails and the member stays on PROBATION even
        though the rate has recovered.

        Design: Difficulty/non_linear_state_machine/member_probation_cycle
        """
        season, _section, member = (
            setup_rehearsing_season_with_active_member())
        ids = [
            create_rehearsal(season["id"], "2026-08-05T19:00:00Z")["id"],
            create_rehearsal(season["id"], "2026-08-12T19:00:00Z")["id"],
        ]
        set_clock("2026-08-13T00:00:00Z")
        record_member_attendance(ids[0], member["id"], "PRESENT")
        record_member_attendance(ids[1], member["id"], "ABSENT_UNEXCUSED")

        run_checkpoint(season["id"])
        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "PROBATION"  # rate 0.5 < 0.75

        # A fresh unpaid invoice keeps dues_balance_cents positive.
        invoice = validate_success(api.create_invoice(
            {"member_id": member["id"]}, treasurer_headers), 201)
        assert invoice["balance_cents"] > 0

        # Repair the rate, then sweep again.
        record = find_attendance_record(ids[1], member["id"])
        validate_success(
            api.excuse_attendance_record(record["id"], director_headers))
        run_checkpoint(season["id"])

        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["attendance_rate"] == pytest.approx(0.875,
                                                               abs=1e-9)
        assert member_data["status"] == "PROBATION", \
            "positive dues balance blocks the PROBATION -> ACTIVE return"
        assert member_data["performance_eligible"] is False
