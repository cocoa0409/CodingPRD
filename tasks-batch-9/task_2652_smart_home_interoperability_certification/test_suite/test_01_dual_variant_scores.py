"""Both of the service's dual-variant computations, driven to divergence.

The readiness score's two variants read the same stored sessions and disagree on
which of them count, on whether BLOCKED passes, and on whether lateness is
charged. The laboratory competency score's two variants read the same completed
sessions and disagree only on the window they look through.
"""

from test_helpers import (
    LAB_AUTHORIZED,
    LAB_SUSPENDED,
    SESSION_IN_PROGRESS,
    append_results,
    build_program,
    complete_session,
    feature,
    new_session,
    read_competency,
    read_laboratory,
    read_readiness,
    read_session,
    read_submission,
    result_line,
    set_clock,
    start_session,
)
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_score, assert_states
from test_helpers.factories import competency_review_payload, dispute_line_payload
from test_helpers.test_users import ADMIN_HEADERS, CONFORMANCE_HEADERS
from test_helpers.fixtures import read_test_plan

THREE_LIGHTING_FEATURES = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_DIM", "MANDATORY", 10),
    feature("OPT_SCENE", "OPTIONAL", 8),
]


def _readiness_divergence_program():
    """One COMPLETE late session carrying a BLOCKED line plus one IN_PROGRESS
    session carrying the optional pass."""
    ctx = build_program(
        stage="issued",
        features=THREE_LIGHTING_FEATURES,
        declared_codes=["CORE_ONOFF", "CORE_DIM", "OPT_SCENE"],
    )
    ctx.session_a = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T13:00:00Z",
    )
    ctx.session_b = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=2,
        window_start="2026-09-03T09:00:00Z",
        window_end="2026-09-03T11:00:00Z",
    )
    start_session(ctx.session_a["id"], ctx.laboratory_id)
    append_results(
        ctx.session_a["id"],
        ctx.laboratory_id,
        [
            result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS"),
            result_line(ctx.feature_set_ids["CORE_DIM"], "BLOCKED"),
        ],
    )
    set_clock("2026-09-02T14:00:00Z")
    complete_session(ctx.session_a["id"], ctx.laboratory_id)
    start_session(ctx.session_b["id"], ctx.laboratory_id)
    append_results(
        ctx.session_b["id"],
        ctx.laboratory_id,
        [result_line(ctx.feature_set_ids["OPT_SCENE"], "PASS")],
    )
    return ctx


class TestReadinessVariantsDiverge:
    """PROVISIONAL and FINAL readiness on one submission's stored evidence."""

    def test_01_provisional_counts_the_in_progress_session_and_passes_blocked(self):
        """PROVISIONAL counts the IN_PROGRESS session as well as the COMPLETE one,
        treats the BLOCKED mandatory line as a pass and pins timeliness, reaching
        85.00.

        PRD (§3.8): "the `PROVISIONAL` variant counts sessions whose `state` is
        `IN_PROGRESS` or `COMPLETE`, while the `FINAL` variant counts only those
        whose `state` is `COMPLETE`"

        Design: Difficulty/dual_variant_calc/readiness_provisional_vs_final_diverge_on_blocked_lines_and_lateness
        """
        ctx = _readiness_divergence_program()

        readiness = read_readiness(ctx.submission_id, variant="PROVISIONAL")

        assert_score(readiness["score"], "85.00", "PROVISIONAL readiness score")
        assert readiness["counted_session_count"] == 2, (
            "PROVISIONAL counts the COMPLETE and the IN_PROGRESS session, "
            "expected 2, got {}".format(readiness["counted_session_count"])
        )
        assert readiness["mandatory_passed_cases"] == 30, (
            "a BLOCKED mandatory line passes under PROVISIONAL, so all 30 "
            "mandatory cases count, got {}".format(readiness["mandatory_passed_cases"])
        )
        assert readiness["optional_passed_cases"] == 8, (
            "the optional pass recorded on the IN_PROGRESS session counts, "
            "expected 8, got {}".format(readiness["optional_passed_cases"])
        )
        assert readiness["late_session_count"] == 1, (
            "the late COMPLETE session is still visible in the count, expected 1, "
            "got {}".format(readiness["late_session_count"])
        )

    def test_02_final_drops_the_live_session_and_charges_the_blocked_line(self):
        """FINAL counts only the COMPLETE session, scores its BLOCKED mandatory
        line as a failure and charges the full lateness penalty, reaching 33.34.

        PRD (§3.8): "The `FINAL` pass set is strict and holds only `PASS` and
        `WAIVED`, so a case still `BLOCKED` at decision time counts as a failure."

        Design: Difficulty/dual_variant_calc/readiness_provisional_vs_final_diverge_on_blocked_lines_and_lateness
        """
        ctx = _readiness_divergence_program()

        readiness = read_readiness(ctx.submission_id, variant="FINAL")

        assert_score(readiness["score"], "33.34", "FINAL readiness score")
        assert readiness["counted_session_count"] == 1, (
            "FINAL counts only the COMPLETE session, expected 1, got {}".format(
                readiness["counted_session_count"]
            )
        )
        assert readiness["mandatory_passed_cases"] == 20, (
            "only CORE_ONOFF passes strictly, expected 20 mandatory cases, "
            "got {}".format(readiness["mandatory_passed_cases"])
        )
        assert readiness["optional_passed_cases"] == 0, (
            "the optional pass sits on an IN_PROGRESS session FINAL ignores, "
            "expected 0, got {}".format(readiness["optional_passed_cases"])
        )
        assert readiness["late_session_count"] == 1, (
            "the single counted session finished late, expected 1, got {}".format(
                readiness["late_session_count"]
            )
        )

    def test_03_timeliness_is_pinned_for_provisional_and_charged_for_final(self):
        """The same one late session out of one leaves PROVISIONAL timeliness at
        1.0000 while FINAL timeliness falls to 0.0000.

        PRD (§3.8): "The `PROVISIONAL` timeliness ratio is pinned at 1.0000 no
        matter what — nothing can be late before it is complete — while the
        `FINAL` timeliness ratio is 1.0000 minus the late ratio."

        Design: Difficulty/dual_variant_calc/readiness_provisional_vs_final_diverge_on_blocked_lines_and_lateness
        """
        ctx = _readiness_divergence_program()

        provisional = read_readiness(ctx.submission_id, variant="PROVISIONAL")
        final = read_readiness(ctx.submission_id, variant="FINAL")

        # 85.00 keeps its full 15 timeliness points; 33.34 is the mandatory
        # component alone, so FINAL has surrendered all 15 of them.
        assert_score(provisional["score"], "85.00", "PROVISIONAL readiness score")
        assert_score(final["score"], "33.34", "FINAL readiness score")
        assert final["late_session_count"] == final["counted_session_count"], (
            "every counted FINAL session is late, got {} late of {} counted".format(
                final["late_session_count"], final["counted_session_count"]
            )
        )

    def test_04_only_the_provisional_figure_is_persisted_before_a_decision(self):
        """Result-line submission writes `provisional_readiness_score` while
        `final_readiness_score` stays null until a conformance decision lands.

        PRD (§3.8): "The `PROVISIONAL` figure is recomputed and written to
        `provisional_readiness_score` after every result-line submission and after
        every plugfest outcome recording; it is null until the first result line
        exists."

        Design: Difficulty/dual_variant_calc/readiness_provisional_vs_final_diverge_on_blocked_lines_and_lateness
        """
        ctx = _readiness_divergence_program()

        submission = read_submission(ctx.submission_id)

        assert_score(
            submission["provisional_readiness_score"], "85.00", "provisional_readiness_score"
        )
        assert submission["final_readiness_score"] is None, (
            "final_readiness_score is pinned only by a conformance decision, "
            "got {!r}".format(submission["final_readiness_score"])
        )
        session_a = read_session(ctx.session_a["id"])
        session_b = read_session(ctx.session_b["id"])
        assert session_a["completed_late"] is True, (
            "session A completed after its window_end, so completed_late must be "
            "true, got {!r}".format(session_a["completed_late"])
        )
        assert session_b["state"] == SESSION_IN_PROGRESS, (
            "session B was never completed, expected IN_PROGRESS, got {}".format(
                session_b["state"]
            )
        )


def _competency_divergence_program():
    """Two clean early sessions and one late, half-disputed recent session, so the
    rolling window sees only the bad one."""
    ctx = build_program(
        stage="issued",
        clock="2026-02-01T00:00:00Z",
        spec_overrides={"effective_date": "2026-01-01T00:00:00Z"},
        lab_overrides={"bench_capacity": 4},
    )
    windows = [
        ("2026-03-01T09:00:00Z", "2026-03-01T11:00:00Z", "2026-03-01T09:30:00Z"),
        ("2026-03-02T09:00:00Z", "2026-03-02T11:00:00Z", "2026-03-02T09:30:00Z"),
        ("2026-08-25T09:00:00Z", "2026-08-25T11:00:00Z", "2026-08-25T12:00:00Z"),
    ]
    ctx.sessions = []
    for window_start, window_end, working_clock in windows:
        ctx.sessions.append(
            new_session(
                ctx.plan_id,
                ctx.laboratory_id,
                bench_index=1,
                window_start=window_start,
                window_end=window_end,
            )
        )

    core = ctx.feature_set_ids["CORE_ONOFF"]
    dim = ctx.feature_set_ids["CORE_DIM"]
    line_sets = [
        [result_line(core, "PASS"), result_line(dim, "PASS")],
        [result_line(core, "PASS"), result_line(dim, "PASS")],
        [
            result_line(core, "PASS", "s3-core-a"),
            result_line(dim, "PASS", "s3-dim-a"),
            result_line(core, "PASS", "s3-core-b"),
            result_line(dim, "PASS", "s3-dim-b"),
        ],
    ]
    for session, (_, _, working_clock), lines in zip(ctx.sessions, windows, line_sets):
        set_clock(working_clock)
        start_session(session["id"], ctx.laboratory_id)
        append_results(session["id"], ctx.laboratory_id, lines)
        complete_session(session["id"], ctx.laboratory_id)

    late_session_id = ctx.sessions[2]["id"]
    for line_index in (0, 1):
        response = api_client.dispute_line(
            late_session_id, dispute_line_payload(line_index), CONFORMANCE_HEADERS
        )
        assert response.status_code == 200, (
            "disputing line {} of the late session must succeed, got {}".format(
                line_index, response.status_code
            )
        )
    set_clock("2026-08-30T00:00:00Z")
    return ctx


class TestCompetencyVariantsStraddleTheSuspensionThreshold:
    """ROLLING_90D and LIFETIME competency over one laboratory's history."""

    def test_05_the_rolling_window_sees_only_the_recent_bad_session(self):
        """On identical stored sessions the rolling window scores 20.00 from the
        one late, half-disputed session while the lifetime window scores 70.00.

        PRD (§3.3): "`ROLLING_90D` counts only sessions whose `completed_at` is at
        or after the logical clock's current instant reduced by 90 days, and the
        lower bound is inclusive, so a session completed at exactly ninety days ago
        is counted."

        Design: Difficulty/dual_variant_calc/laboratory_competency_rolling_vs_lifetime_straddle_suspension_threshold
        """
        ctx = _competency_divergence_program()

        rolling = read_competency(ctx.laboratory_id, variant="ROLLING_90D")
        lifetime = read_competency(ctx.laboratory_id, variant="LIFETIME")

        assert rolling["counted_session_count"] == 1, (
            "only the 2026-08-25 session falls inside the 90-day window, "
            "expected 1, got {}".format(rolling["counted_session_count"])
        )
        assert_score(rolling["on_time_ratio"], "0.0000", "ROLLING_90D on_time_ratio")
        assert_score(
            rolling["dispute_free_ratio"], "0.5000", "ROLLING_90D dispute_free_ratio"
        )
        assert_score(rolling["competency_score"], "20.00", "ROLLING_90D competency_score")

        assert lifetime["counted_session_count"] == 3, (
            "LIFETIME counts every COMPLETE session, expected 3, got {}".format(
                lifetime["counted_session_count"]
            )
        )
        assert_score(lifetime["on_time_ratio"], "0.6667", "LIFETIME on_time_ratio")
        assert_score(
            lifetime["dispute_free_ratio"], "0.7500", "LIFETIME dispute_free_ratio"
        )
        assert_score(lifetime["competency_score"], "70.00", "LIFETIME competency_score")

    def test_06_exactly_seventy_survives_while_the_rolling_score_suspends(self):
        """A LIFETIME review landing on exactly 70.00 leaves the laboratory
        AUTHORIZED; the ROLLING_90D review that follows scores 20.00 and suspends
        it inside the same request.

        PRD (§3.3): "if the freshly computed score is *strictly* less than 70.00
        while the laboratory is `AUTHORIZED`, the system itself drives `AUTHORIZED →
        SUSPENDED` as part of the same request; a score of exactly 70.00 leaves the
        laboratory `AUTHORIZED`."

        Design: Difficulty/dual_variant_calc/laboratory_competency_rolling_vs_lifetime_straddle_suspension_threshold
        """
        ctx = _competency_divergence_program()

        lifetime_response = api_client.competency_review(
            ctx.laboratory_id, competency_review_payload("LIFETIME"), ADMIN_HEADERS
        )
        assert lifetime_response.status_code == 200, (
            "the LIFETIME competency review must be accepted, got {}".format(
                lifetime_response.status_code
            )
        )
        after_lifetime = read_laboratory(ctx.laboratory_id)
        assert_score(
            after_lifetime["competency_score"], "70.00", "stored competency_score"
        )
        assert_states(
            after_lifetime,
            competency_variant="LIFETIME",
            accreditation_status=LAB_AUTHORIZED,
        )

        rolling_response = api_client.competency_review(
            ctx.laboratory_id, competency_review_payload("ROLLING_90D"), ADMIN_HEADERS
        )
        assert rolling_response.status_code == 200, (
            "the ROLLING_90D competency review must be accepted, got {}".format(
                rolling_response.status_code
            )
        )
        after_rolling = read_laboratory(ctx.laboratory_id)
        assert_score(
            after_rolling["competency_score"], "20.00", "stored competency_score"
        )
        assert_states(
            after_rolling,
            competency_variant="ROLLING_90D",
            accreditation_status=LAB_SUSPENDED,
        )

    def test_07_the_disputed_and_late_flags_behind_the_divergence_are_stored(self):
        """The evidence the two variants disagree over is itself observable: two
        disputed lines and a late completion on the recent session, both earlier
        sessions on time.

        PRD (§3.6): "Completion moves `IN_PROGRESS → COMPLETE`, stamps
        `completed_at`, and recomputes `completed_late`, which is true exactly when
        `completed_at` is not null and is strictly after `window_end`; a session
        that finishes precisely at its `window_end` is not late."

        Design: Difficulty/dual_variant_calc/laboratory_competency_rolling_vs_lifetime_straddle_suspension_threshold
        """
        ctx = _competency_divergence_program()

        first, second, third = (read_session(s["id"]) for s in ctx.sessions)

        assert third["disputed_line_count"] == 2, (
            "two of the four lines were disputed, expected disputed_line_count 2, "
            "got {}".format(third["disputed_line_count"])
        )
        assert third["completed_late"] is True, (
            "the recent session completed at 12:00 against an 11:00 window_end, so "
            "completed_late must be true, got {!r}".format(third["completed_late"])
        )
        assert first["completed_late"] is False, (
            "the first session completed inside its window, got completed_late "
            "{!r}".format(first["completed_late"])
        )
        assert second["completed_late"] is False, (
            "the second session completed inside its window, got completed_late "
            "{!r}".format(second["completed_late"])
        )
        plan = read_test_plan(ctx.plan_id)
        assert plan["mandatory_case_count"] == 30, (
            "the plan's mandatory closure is CORE_ONOFF plus CORE_DIM, expected 30 "
            "cases, got {}".format(plan["mandatory_case_count"])
        )
