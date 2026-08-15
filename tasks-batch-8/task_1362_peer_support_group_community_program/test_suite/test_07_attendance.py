"""Attendance check-in/out, streak conservation, and session summary rates
(PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_attendance_record,
    create_attendance_payload,
    get_success_data,
    make_active_participant,
    make_confirmed_enrollment,
    make_facilitator_headers,
    make_scheduled_session,
    make_session,
    reset_clock,
    schedule_session,
    setup_in_progress_session,
    setup_session_scenario,
    validate_error,
    validate_success,
)


def _attend_session(api, env, session_id, participant_id):
    """Check in + check out a participant on an in-window session."""
    fac_headers = make_facilitator_headers(env.facilitator["id"])
    record = get_success_data(api.check_in(
        env.program["id"], env.group["id"], session_id,
        create_attendance_payload(participant_id, access_modality="IN_PERSON"),
        fac_headers))
    return get_success_data(api.checkout_attendance(
        env.program["id"], env.group["id"], session_id, record["id"], fac_headers))


class TestSessionSummaryRates:
    def _setup_two_confirmed_one_attended(self, api):
        """IN_PROGRESS session; participants A and B CONFIRMED; A checked out
        (ATTENDED), B still CHECKED_IN."""
        env = setup_in_progress_session()
        pa, _ = make_active_participant(full_name="P A")
        pb, _ = make_active_participant(full_name="P B")
        make_confirmed_enrollment(env.program["id"], env.group["id"], pa["id"])
        make_confirmed_enrollment(env.program["id"], env.group["id"], pb["id"])
        fac_headers = make_facilitator_headers(env.facilitator["id"])
        rec_a = get_success_data(api.check_in(
            env.program["id"], env.group["id"], env.session["id"],
            create_attendance_payload(pa["id"], access_modality="IN_PERSON"),
            fac_headers))
        rec_b = get_success_data(api.check_in(
            env.program["id"], env.group["id"], env.session["id"],
            create_attendance_payload(pb["id"], access_modality="IN_PERSON"),
            fac_headers))
        get_success_data(api.checkout_attendance(
            env.program["id"], env.group["id"], env.session["id"],
            rec_a["id"], fac_headers))
        return env, pa, pb, rec_b

    def test_provisional_counts_checked_in_final_counts_only_attended(self, api):
        """PRD §3.6: "It reports `attendance_rate_provisional` — the count of
        the session's records in `CHECKED_IN` or `ATTENDED`, divided by the
        number of the group's enrollments in `CONFIRMED`, with the denominator
        floored at 1 — and `attendance_rate_final`, which counts only
        `ATTENDED` records over the same floored denominator and so excludes
        check-ins that never checked out. Both rates are rounded half-up to
        four decimal places."

        Design: Difficulty/dual_variant_calc/attendance_rate_provisional_vs_final_on_session
        """
        env, _pa, _pb, _rec_b = self._setup_two_confirmed_one_attended(api)
        session = validate_success(
            api.get_session(env.program["id"], env.group["id"], env.session["id"], ADMIN))
        assert session["status"] == "IN_PROGRESS"

        summary = validate_success(api.get_session_summary(
            env.program["id"], env.group["id"], env.session["id"], ADMIN))
        assert summary["confirmed_count"] == 2
        assert summary["attendance_rate_provisional"] == pytest.approx(1.0, abs=0.0001), (
            f"provisional = (CHECKED_IN + ATTENDED)/CONFIRMED = 2/2, got "
            f"{summary['attendance_rate_provisional']}")
        assert summary["attendance_rate_final"] == pytest.approx(0.5, abs=0.0001), (
            f"final = ATTENDED/CONFIRMED = 1/2, got {summary['attendance_rate_final']}")

    def test_completion_reconciles_open_check_ins_then_rates_agree(self, api):
        """PRD §3.5: "Both forms decrement the program's
        `scheduled_session_count` and trigger attendance reconciliation,
        marking any record still `CHECKED_IN` without a checkout as `ATTENDED`
        once `end_at` has passed."
        PRD §3.6: "The provisional variant is the live view, used while the
        session is `SCHEDULED` or `IN_PROGRESS`; the final variant is the
        reporting figure once the session is `COMPLETED` or
        `COMPLETED_WITH_INCIDENT`."

        Design: Difficulty/dual_variant_calc/attendance_rate_provisional_vs_final_on_session
        """
        env, _pa, pb, rec_b = self._setup_two_confirmed_one_attended(api)
        # Complete after end_at but inside the fifteen-minute no-show grace.
        reset_clock("2026-08-02T11:05:00Z")
        completed = validate_success(api.complete_session(
            env.program["id"], env.group["id"], env.session["id"], ADMIN))
        assert completed["status"] == "COMPLETED"

        reconciled = validate_success(api.get_attendance(
            env.program["id"], env.group["id"], env.session["id"], rec_b["id"], ADMIN))
        assert reconciled["status"] == "ATTENDED", (
            "reconciliation must mark a still-CHECKED_IN record ATTENDED once "
            f"end_at has passed, got {reconciled['status']}")

        summary = validate_success(api.get_session_summary(
            env.program["id"], env.group["id"], env.session["id"], ADMIN))
        assert summary["attendance_rate_final"] == pytest.approx(1.0, abs=0.0001)
        assert summary["attendance_rate_provisional"] == pytest.approx(1.0, abs=0.0001)


class TestAttendanceStreakConservation:
    def _build_streak(self, api, env, participant_id, sessions):
        """Run the participant through completed sessions, one ATTENDED each."""
        fac_headers = make_facilitator_headers(env.facilitator["id"])
        for start_at, end_at, in_window, past_end in sessions:
            session = make_scheduled_session(
                env.program["id"], env.group["id"], env.facilitator["id"],
                start_at=start_at, end_at=end_at, room_id=env.room["id"])
            reset_clock(in_window)
            _attend_session(api, env, session["id"], participant_id)
            reset_clock(past_end)
            get_success_data(api.complete_session(
                env.program["id"], env.group["id"], session["id"], fac_headers))

    def test_void_restores_streak_to_prior_value(self, api):
        """PRD §3.6: "Voiding — by an admin or an assigned facilitator — is the
        compensating action for an erroneous check-in: it moves `CHECKED_IN` to
        `VOIDED`, restores the participant's `attendance_streak` to the value
        it held before, and leaves `total_no_shows` unchanged, since a voided
        record was never a completed attendance."

        Design: Difficulty/compensating_invariant/attendance_streak_conservation_void_restores_streak
        """
        env = setup_session_scenario(
            modality="IN_PERSON",
            start_at="2026-08-02T08:00:00Z", end_at="2026-08-02T09:00:00Z")
        participant, _ = make_active_participant(full_name="A")
        make_confirmed_enrollment(env.program["id"], env.group["id"], participant["id"])
        # Three attended sessions build a streak of 3. (The scenario session
        # itself is the first; two more follow with buffer-safe gaps.)
        reset_clock("2026-08-02T08:30:00Z")
        fac_headers = make_facilitator_headers(env.facilitator["id"])
        _attend_session(api, env, env.session["id"], participant["id"])
        reset_clock("2026-08-02T09:30:00Z")
        get_success_data(api.complete_session(
            env.program["id"], env.group["id"], env.session["id"], fac_headers))
        self._build_streak(api, env, participant["id"], [
            ("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
             "2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z"),
            ("2026-08-02T12:30:00Z", "2026-08-02T13:30:00Z",
             "2026-08-02T13:00:00Z", "2026-08-02T14:00:00Z"),
        ])

        before = validate_success(api.get_participant(participant["id"], ADMIN))
        assert before["attendance_streak"] == 3, (
            f"three ATTENDED records must yield streak 3, got {before['attendance_streak']}")
        assert before["total_no_shows"] == 0

        # A fresh check-in, then the compensating void.
        new_session = make_scheduled_session(
            env.program["id"], env.group["id"], env.facilitator["id"],
            start_at="2026-08-02T15:00:00Z", end_at="2026-08-02T16:00:00Z",
            room_id=env.room["id"])
        reset_clock("2026-08-02T15:30:00Z")
        record = get_success_data(api.check_in(
            env.program["id"], env.group["id"], new_session["id"],
            create_attendance_payload(participant["id"], access_modality="IN_PERSON"),
            fac_headers))
        mid = validate_success(api.get_participant(participant["id"], ADMIN))
        assert mid["attendance_streak"] == 3, "check-in alone must not change the streak"

        voided = validate_success(api.void_attendance(
            env.program["id"], env.group["id"], new_session["id"],
            record["id"], fac_headers))
        assert voided["status"] == "VOIDED"
        after = validate_success(api.get_participant(participant["id"], ADMIN))
        assert after["attendance_streak"] == 3, (
            f"void must restore the streak to its prior value 3, got {after['attendance_streak']}")
        assert after["total_no_shows"] == 0, "void must leave total_no_shows unchanged"

    def test_checkout_increments_streak_and_void_keeps_no_shows_unchanged(self, api):
        """PRD §3.6: "Checkout — by an admin, a facilitator on the session, or
        the participant themself — moves `CHECKED_IN` to `ATTENDED`, allowed
        once the current time has reached the session's `start_at`; it stamps
        `check_out_at` and increments the participant's `attendance_streak`."
        PRD §3.6: "it moves `CHECKED_IN` to `VOIDED`, restores the
        participant's `attendance_streak` to the value it held before, and
        leaves `total_no_shows` unchanged"

        Design: Difficulty/compensating_invariant/attendance_streak_conservation_void_restores_streak
        """
        env = setup_session_scenario(
            modality="IN_PERSON",
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z")
        participant, _ = make_active_participant(full_name="A")
        make_confirmed_enrollment(env.program["id"], env.group["id"], participant["id"])
        fac_headers = make_facilitator_headers(env.facilitator["id"])

        reset_clock("2026-08-02T10:05:00Z")
        attended = _attend_session(api, env, env.session["id"], participant["id"])
        assert attended["status"] == "ATTENDED"
        assert attended.get("check_out_at") is not None, "checkout must stamp check_out_at"
        after_checkout = validate_success(api.get_participant(participant["id"], ADMIN))
        assert after_checkout["attendance_streak"] == 1, (
            f"checkout must increment the streak to 1, got {after_checkout['attendance_streak']}")

        # A second check-in that is voided: streak restored, no-shows untouched.
        second = make_scheduled_session(
            env.program["id"], env.group["id"], env.facilitator["id"],
            start_at="2026-08-02T12:00:00Z", end_at="2026-08-02T13:00:00Z",
            room_id=env.room["id"])
        reset_clock("2026-08-02T12:05:00Z")
        record = get_success_data(api.check_in(
            env.program["id"], env.group["id"], second["id"],
            create_attendance_payload(participant["id"], access_modality="IN_PERSON"),
            fac_headers))
        get_success_data(api.void_attendance(
            env.program["id"], env.group["id"], second["id"], record["id"], fac_headers))
        final = validate_success(api.get_participant(participant["id"], ADMIN))
        assert final["attendance_streak"] == 1
        assert final["total_no_shows"] == 0


class TestCheckInModality:
    def test_in_person_check_in_on_virtual_group_rejected(self, api):
        """PRD §3.6: "The declared access modality must be compatible with the
        group's modality: an `IN_PERSON` group accepts only `IN_PERSON`
        check-ins, a `VIRTUAL` group accepts only `VIRTUAL` check-ins, and a
        `HYBRID` group accepts either. ... Any incompatibility or bad token is
        rejected with `ERR_MODALITY_MISMATCH` (HTTP 422)."

        Design: Corner/errors/error_modality_mismatch_in_person_on_virtual_group
        """
        env = setup_in_progress_session(modality="VIRTUAL")
        participant, _ = make_active_participant(full_name="A")
        make_confirmed_enrollment(env.program["id"], env.group["id"], participant["id"])
        resp = api.check_in(
            env.program["id"], env.group["id"], env.session["id"],
            {"participant_id": participant["id"], "access_modality": "IN_PERSON"},
            make_facilitator_headers(env.facilitator["id"]))
        validate_error(resp, ApiErrorId.ERR_MODALITY_MISMATCH)
