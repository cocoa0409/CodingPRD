"""Exact edges: one raw question either side of a pass mark, and one second either side of
the two epoch boundaries a certificate crosses.
"""
from test_helpers import (
    assert_compliance_run,
    assert_same_instant,
    certify_one_server,
    get_certificate_row,
    get_enrollment_row,
    get_server,
    get_session,
    get_trainer_row,
    open_attempt,
    register_alcohol_server,
    run_compliance,
    set_clock,
    setup_training_base,
    stage_exam_open,
    submit_attempt,
)

RETAKE_ELIGIBLE_CLOCK = "2026-08-11T14:05:00Z"
EXPIRY_INSTANT = "2028-08-10T18:30:00Z"
ONE_SECOND_BEFORE_EXPIRY = "2028-08-10T18:29:59Z"
GRACE_EDGE_INSTANT = "2028-09-09T18:30:00Z"
ONE_SECOND_BEFORE_GRACE_EDGE = "2028-09-09T18:29:59Z"


def _two_seats_across_the_threshold():
    """One seat scores exactly the pass mark, the next scores one raw question less."""
    base = setup_training_base()
    first_server = register_alcohol_server(base["jurisdiction"]["id"])
    second_server = register_alcohol_server(
        base["jurisdiction"]["id"], full_name="Bo Nakamura", email="bo@example.com")
    staged = stage_exam_open(base, servers=[first_server, second_server])
    proctor = staged["proctor_headers"]

    on_the_mark = submit_attempt(
        open_attempt(staged["enrollments"][0]["id"], proctor)["id"], 28, True, proctor)
    below_the_mark = submit_attempt(
        open_attempt(staged["enrollments"][1]["id"], proctor)["id"], 27, True, proctor)
    return base, staged, on_the_mark, below_the_mark


class TestPassMarkIsInclusive:
    def test_exactly_the_pass_mark_passes_and_one_question_less_fails(self, api):
        """PRD §3.6: "The score is always computed the same way: `score_pct` is
        `raw_correct_count` divided by the attempt's own snapshotted `question_count`,
        multiplied by 100, rounded half up to two decimal places."
        PRD §3.6: "When `proctor_attestation` is true and `score_pct` is greater than or equal
        to `min_passing_score_pct`, the attempt's `outcome` is `PASS` and the seat moves
        `EXAM_IN_PROGRESS → PASSED`."
        PRD §3.6: "When `proctor_attestation` is true and `score_pct` is strictly below
        `min_passing_score_pct`, the attempt's `outcome` is `FAIL` and the seat moves
        `EXAM_IN_PROGRESS → EXAM_FAILED`."
        PRD §2.7: "All percentage-valued fields — `score_pct`, `pass_rate_pct`,
        `min_passing_score_pct`, `compliance_rate_strict_pct`,
        `compliance_rate_grace_inclusive_pct`, `account_compliance_rate_pct`,
        `strict_compliance_rate_pct`, `discount_pct`, `last_purchase_discount_pct` — are
        numbers carried to exactly two decimal places, rounded half up."

        Design: Difficulty/boundary_precision_check/exam_score_exactly_at_passing_threshold_passes_while_one_question_less_fails
        """
        base, staged, on_the_mark, below_the_mark = _two_seats_across_the_threshold()

        assert on_the_mark["score_pct"] == 70.00, (
            f"28 of 40 is exactly 70.00, got {on_the_mark['score_pct']}")
        assert on_the_mark["outcome"] == "PASS", (
            "the threshold comparison is inclusive, got "
            f"{on_the_mark['outcome']}")

        assert below_the_mark["score_pct"] == 67.50, (
            "27 of 40 is 67.50 to two decimals, not 67 and not 68, got "
            f"{below_the_mark['score_pct']}")
        assert below_the_mark["outcome"] == "FAIL"

    def test_the_two_seats_diverge_and_the_trainer_metrics_wait_for_completion(self, api):
        """PRD §3.6: "The seat's `attempt_count` rises by one, `best_score_pct` is recomputed,
        `last_counted_attempt_ended_at` is stamped with the logical clock, and
        `retake_eligible_at` becomes that instant plus the jurisdiction's
        `retake_cooling_off_hours` hours."
        PRD §3.6: "The seat's `attempt_count` rises by one, `best_score_pct` is recomputed, and
        the session's `passed_count` rises by one."
        PRD §3.4: "Teaching metrics are recomputed whenever one of this trainer's classes
        completes, never on read."
        PRD §3.4: "When `graded_enrollments_count` is zero the rate reads 0.00 rather than
        being left undefined."

        Design: Difficulty/boundary_precision_check/exam_score_exactly_at_passing_threshold_passes_while_one_question_less_fails
        """
        base, staged, on_the_mark, below_the_mark = _two_seats_across_the_threshold()

        passer = get_enrollment_row(staged["enrollments"][0]["id"])
        assert passer["enrollment_state"] == "PASSED"
        assert passer["best_score_pct"] == 70.00

        failer = get_enrollment_row(staged["enrollments"][1]["id"])
        assert failer["enrollment_state"] == "EXAM_FAILED"
        assert failer["best_score_pct"] == 67.50
        assert_same_instant(failer["retake_eligible_at"], RETAKE_ELIGIBLE_CLOCK,
                            "retake_eligible_at")

        session = get_session(staged["session"]["id"])
        assert session["enrolled_count"] == 2
        assert session["passed_count"] == 1, (
            "only the seat on the pass mark counts, got "
            f"{session['passed_count']}")

        trainer = get_trainer_row(base["trainer"]["id"])
        assert trainer["sessions_taught_count"] == 0
        assert trainer["pass_rate_pct"] == 0.00, (
            "the class has not completed, so nothing has been recomputed yet, got "
            f"{trainer['pass_rate_pct']}")


class TestEpochBoundariesFireExactly:
    def test_grace_waits_for_the_expiry_instant_itself(self, api):
        """PRD §2.6: "Moving the clock forward does **not**, by itself, lapse a credential,
        expire an approval, grace or lapse a certificate, emit a reminder, or restrict a
        server."
        PRD §3.9: "A certificate whose `validity_state` is `ACTIVE` and whose `expires_at` the
        clock has reached moves `ACTIVE → GRACE`, incrementing `certificates_graced_count`."
        PRD §3.9: "At most one reminder is emitted per certificate per run, and only while
        `validity_state` is `ACTIVE` or `GRACE` and the clock has reached `expires_at` minus the
        jurisdiction's `reminder_lead_days`."

        Design: Difficulty/boundary_precision_check/certificate_grace_and_lapse_fire_only_at_the_exact_boundary_instants
        """
        base = setup_training_base()
        walk = certify_one_server(base)
        certificate = walk["certificate"]
        assert_same_instant(certificate["expires_at"], EXPIRY_INSTANT, "expires_at")
        assert certificate["reminder_sent_count"] == 0

        set_clock(ONE_SECOND_BEFORE_EXPIRY)
        first_run = run_compliance()
        assert_compliance_run(first_run)
        assert first_run["certificates_graced_count"] == 0, (
            "one second before expiry the card has not expired, got "
            f"{first_run['certificates_graced_count']}")
        assert first_run["certificates_lapsed_count"] == 0
        assert first_run["reminders_sent_count"] == 1
        assert get_certificate_row(certificate["id"])["validity_state"] == "ACTIVE"

        set_clock(EXPIRY_INSTANT)
        second_run = run_compliance()
        assert second_run["certificates_graced_count"] == 1, (
            "the clock has now reached expires_at exactly, got "
            f"{second_run['certificates_graced_count']}")
        assert second_run["certificates_lapsed_count"] == 0
        assert second_run["reminders_sent_count"] == 1
        assert get_certificate_row(certificate["id"])["validity_state"] == "GRACE"

    def test_lapse_waits_for_the_grace_edge_and_the_reminders_stop_at_two(self, api):
        """PRD §3.9: "A certificate whose `validity_state` is `GRACE` and where the clock has
        reached `expires_at` plus the jurisdiction's `renewal_grace_days` moves `GRACE →
        LAPSED`, incrementing `certificates_lapsed_count`."
        PRD §3.9: "Each reminder raises `reminder_sent_count` by one and stamps
        `last_reminder_at` from the clock, and reminders stop once `reminder_sent_count` reaches
        2."
        PRD §3.9: "A `LAPSED` certificate moves its holder `GRACE → RESTRICTED`, stamping
        `restricted_since`."
        PRD §3.9: "Assignments moving `ACTIVE → WORK_RESTRICTED` increment
        `assignments_restricted_count`; assignments moving `WORK_RESTRICTED → ACTIVE` increment
        `assignments_restored_count`."

        Design: Difficulty/boundary_precision_check/certificate_grace_and_lapse_fire_only_at_the_exact_boundary_instants
        """
        base = setup_training_base()
        walk = certify_one_server(base)
        certificate = walk["certificate"]

        set_clock(ONE_SECOND_BEFORE_EXPIRY)
        run_compliance()
        set_clock(EXPIRY_INSTANT)
        run_compliance()

        set_clock(ONE_SECOND_BEFORE_GRACE_EDGE)
        third_run = run_compliance()
        assert third_run["certificates_lapsed_count"] == 0, (
            "one second before the grace edge the card still holds grace, got "
            f"{third_run['certificates_lapsed_count']}")
        assert third_run["certificates_graced_count"] == 0
        assert third_run["reminders_sent_count"] == 0, (
            "the reminder allowance of two is already spent, got "
            f"{third_run['reminders_sent_count']}")
        assert get_certificate_row(certificate["id"])["validity_state"] == "GRACE"

        set_clock(GRACE_EDGE_INSTANT)
        fourth_run = run_compliance()
        assert fourth_run["certificates_lapsed_count"] == 1
        assert fourth_run["certificates_graced_count"] == 0
        assert fourth_run["reminders_sent_count"] == 0
        assert fourth_run["assignments_restricted_count"] == 0, (
            "this server holds no assignment, got "
            f"{fourth_run['assignments_restricted_count']}")

        lapsed = get_certificate_row(certificate["id"])
        assert lapsed["validity_state"] == "LAPSED"
        assert lapsed["reminder_sent_count"] == 2

        server = get_server(walk["server"]["id"])
        assert server["work_eligibility"] == "RESTRICTED"
        assert_same_instant(server["restricted_since"], GRACE_EDGE_INSTANT,
                            "restricted_since")
