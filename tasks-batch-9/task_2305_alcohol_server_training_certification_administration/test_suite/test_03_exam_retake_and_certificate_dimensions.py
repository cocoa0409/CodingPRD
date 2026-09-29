"""Two lifecycles that are not straight lines.

A seat re-enters EXAM_IN_PROGRESS from two different predecessors, and a certificate carries
two state dimensions that advance without disturbing each other.
"""
from test_helpers import (
    CLOCK_COMPLETION,
    acknowledge_accept,
    assert_certificate,
    assert_compliance_run,
    assert_enrollment,
    assert_exam_attempt,
    assert_registry_submission,
    assert_same_instant,
    attempts_for_enrollment,
    certify_one_server,
    get_certificate_row,
    get_enrollment_row,
    get_server,
    get_session,
    open_attempt,
    run_compliance,
    set_clock,
    setup_training_base,
    stage_exam_open,
    submit_attempt,
    transmit_certificate,
    validate_paginated,
)

FIRST_FAIL_CLOCK = "2026-08-10T15:00:00Z"
RETAKE_ELIGIBLE_CLOCK = "2026-08-11T15:00:00Z"
TRANSMIT_CLOCK = "2026-08-20T10:00:00Z"
REGISTRY_DUE_INSTANT = "2026-08-25T18:30:00Z"
EXPIRY_INSTANT = "2028-08-10T18:30:00Z"


def _retake_cycle():
    """Fail an attempt, have the retake voided, then pass on the reopened seat."""
    base = setup_training_base()
    staged = stage_exam_open(base)
    enrollment_id = staged["enrollments"][0]["id"]
    proctor = staged["proctor_headers"]

    first = open_attempt(enrollment_id, proctor)
    set_clock(FIRST_FAIL_CLOCK)
    first = submit_attempt(first["id"], 27, True, proctor)

    set_clock(RETAKE_ELIGIBLE_CLOCK)
    second = open_attempt(enrollment_id, proctor)
    second = submit_attempt(second["id"], 30, False, proctor)

    third = open_attempt(enrollment_id, proctor)
    third = submit_attempt(third["id"], 28, True, proctor)
    return base, staged, enrollment_id, first, second, third


class TestVoidedRetakeIsInvisibleToTheCycleCounters:
    def test_the_voided_attempt_neither_consumes_a_number_nor_a_retake(self, api):
        """PRD §3.6: "An accepted attempt is created with `attempt_number` equal to one plus
        the number of prior attempts on this seat whose `outcome` is not `VOIDED`, with
        `question_count` snapshotted from the course at this instant, with `outcome` at
        `IN_PROGRESS`, with `started_at` stamped from the logical clock, and with
        `raw_correct_count`, `score_pct`, `proctor_attestation`, `submitted_at` and
        `void_reason` unset."
        PRD §3.6: "When `proctor_attestation` is false, the attempt is `VOIDED` and
        `void_reason` is set to `PROCTOR_ATTESTATION_WITHHELD`."
        PRD §3.6: "The score is always computed the same way: `score_pct` is
        `raw_correct_count` divided by the attempt's own snapshotted `question_count`,
        multiplied by 100, rounded half up to two decimal places."
        PRD §3.6: "It does, however, remain listed among the seat's attempts."

        Design: Difficulty/non_linear_state_machine/enrollment_retake_cycle_reenters_exam_in_progress_and_voided_attempt_costs_no_retake
        """
        base, staged, enrollment_id, first, second, third = _retake_cycle()

        assert_exam_attempt(first)
        assert first["attempt_number"] == 1
        assert first["score_pct"] == 67.50, (
            f"27 of 40 is 67.50 percent, got {first['score_pct']}")
        assert first["outcome"] == "FAIL"

        assert second["attempt_number"] == 2
        assert second["score_pct"] == 75.00, (
            "a withheld attestation still records the raw score, got "
            f"{second['score_pct']}")
        assert second["outcome"] == "VOIDED"
        assert second["void_reason"] == "PROCTOR_ATTESTATION_WITHHELD"

        assert third["attempt_number"] == 2, (
            "the voided row is not a prior attempt for numbering purposes, got "
            f"{third['attempt_number']}")
        assert third["score_pct"] == 70.00
        assert third["outcome"] == "PASS"

        listed, meta = validate_paginated(
            api.list_exam_attempts(enrollment_id, base["trainer_headers"]))
        assert meta["total_count"] == 3, (
            f"all three rows including the voided one are listed, got {meta['total_count']}")

    def test_the_seat_passes_on_its_second_counted_attempt(self, api):
        """PRD §3.6: "Crucially, the seat's `attempt_count`, `best_score_pct`,
        `last_counted_attempt_ended_at` and `retake_eligible_at` are all left exactly as they
        were: a voided attempt never consumes a retake and is invisible to both the cap and
        the cooling-off clock."
        PRD §3.6: "`attempt_count` counts the seat's attempts whose `outcome` is not
        `VOIDED`."
        PRD §3.6: "`best_score_pct` is the maximum `score_pct` over the seat's attempts whose
        `outcome` is `PASS` or `FAIL`, and stays null while no such attempt exists."
        PRD §3.6: "The seat's `attempt_count` rises by one, `best_score_pct` is recomputed,
        `last_counted_attempt_ended_at` is stamped with the logical clock, and
        `retake_eligible_at` becomes that instant plus the jurisdiction's
        `retake_cooling_off_hours` hours."
        PRD §3.6: "When `proctor_attestation` is true and `score_pct` is greater than or equal
        to `min_passing_score_pct`, the attempt's `outcome` is `PASS` and the seat moves
        `EXAM_IN_PROGRESS → PASSED`."
        PRD §3.6: "Attempts on a seat can be listed in ascending `created_at`, voided ones
        included."

        Design: Difficulty/non_linear_state_machine/enrollment_retake_cycle_reenters_exam_in_progress_and_voided_attempt_costs_no_retake
        """
        base, staged, enrollment_id, first, second, third = _retake_cycle()

        enrollment = get_enrollment_row(enrollment_id)
        assert_enrollment(enrollment)
        assert enrollment["enrollment_state"] == "PASSED"
        assert enrollment["attempt_count"] == 2, (
            "one FAIL plus one PASS; the VOIDED row is excluded, got "
            f"{enrollment['attempt_count']}")
        assert enrollment["best_score_pct"] == 70.00
        assert_same_instant(enrollment["retake_eligible_at"], RETAKE_ELIGIBLE_CLOCK,
                            "retake_eligible_at")
        assert_same_instant(enrollment["last_counted_attempt_ended_at"],
                            RETAKE_ELIGIBLE_CLOCK, "last_counted_attempt_ended_at")

        session = get_session(staged["session"]["id"])
        assert session["passed_count"] == 1

        rows = attempts_for_enrollment(enrollment_id, base["trainer_headers"])
        assert [row["outcome"] for row in rows] == ["FAIL", "VOIDED", "PASS"], (
            f"attempts list in ascending created_at, got {[r['outcome'] for r in rows]}")


class TestIndependentCertificateDimensions:
    def test_the_registry_dimension_advances_twice_while_validity_stays_active(self, api):
        """PRD §3.7: "A certificate carries two independent state dimensions on the same row,
        and neither constrains the other except through the two cross-dimension transitions
        described below."
        PRD §3.7: "The transmission record names the `certificate_id`, lands in
        `submission_state` `TRANSMITTED` with `acknowledged_at` null and `rejection_code` at
        `NONE`, stamps `transmitted_at` from the logical clock, takes `attempt_number` as one
        plus the number of prior transmissions for this certificate — rejected ones included —
        and snapshots `due_at` from the certificate's `registry_due_at`. The certificate's
        `registry_state` becomes `SUBMITTED`."
        PRD §3.7: "An accepted result moves the submission `TRANSMITTED → ACCEPTED` and sets
        the certificate's `registry_state` to `ACCEPTED`."
        PRD §3.7: "When `transmitted_at` is at or before `due_at`, `late_days` is zero."
        PRD §3.7: "`penalty_fee_cents` is `late_days` multiplied by the jurisdiction's
        `registry_late_fee_cents_per_day` multiplied by that escalation factor, rounded half up
        to whole cents once per submission."
        PRD §3.7: "when submission is required, `registry_due_at` is `issued_at` advanced by
        `registry_deadline_days` days, and when it is not required, `registry_due_at` stays
        null."

        Design: Difficulty/non_linear_state_machine/certificate_validity_and_registry_dimensions_advance_independently
        """
        base = setup_training_base()
        walk = certify_one_server(base)
        certificate = walk["certificate"]
        assert_certificate(certificate)
        assert certificate["registry_state"] == "PENDING_SUBMISSION"
        assert_same_instant(certificate["registry_due_at"], REGISTRY_DUE_INSTANT,
                            "registry_due_at")

        set_clock(TRANSMIT_CLOCK)
        submission = transmit_certificate(certificate["id"],
                                          payload={"batch_reference": "TX-BATCH-0001"})
        assert_registry_submission(submission)
        assert submission["attempt_number"] == 1
        assert submission["late_days"] == 0, (
            "transmitted before the due instant, got "
            f"{submission['late_days']} late days")
        assert submission["penalty_fee_cents"] == 0
        assert get_certificate_row(certificate["id"])["registry_state"] == "SUBMITTED"

        acknowledged = acknowledge_accept(submission["id"])
        assert acknowledged["submission_state"] == "ACCEPTED"
        assert_same_instant(acknowledged["acknowledged_at"], TRANSMIT_CLOCK,
                            "acknowledged_at")

        after = get_certificate_row(certificate["id"])
        assert after["registry_state"] == "ACCEPTED"
        assert after["validity_state"] == "ACTIVE", (
            "the registry round trip leaves the validity dimension alone, got "
            f"{after['validity_state']}")

    def test_the_validity_dimension_advances_later_without_touching_the_registry(self, api):
        """PRD §3.7: "A certificate may legitimately read `ACTIVE` with
        `PENDING_SUBMISSION`, or `GRACE` with `ACCEPTED`, or `SUSPENDED` with
        `RESUBMIT_REQUIRED`."
        PRD §3.9: "A certificate whose `validity_state` is `ACTIVE` and whose `expires_at` the
        clock has reached moves `ACTIVE → GRACE`, incrementing `certificates_graced_count`."
        PRD §3.9: "A `GRACE` certificate moves its holder `ELIGIBLE → GRACE`, and assignments
        stay `ACTIVE` — servers in grace may still work."
        PRD §3.9: "At most one reminder is emitted per certificate per run, and only while
        `validity_state` is `ACTIVE` or `GRACE` and the clock has reached `expires_at` minus
        the jurisdiction's `reminder_lead_days`."

        Design: Difficulty/non_linear_state_machine/certificate_validity_and_registry_dimensions_advance_independently
        """
        base = setup_training_base()
        walk = certify_one_server(base)
        certificate = walk["certificate"]
        assert_same_instant(certificate["issued_at"], CLOCK_COMPLETION, "issued_at")
        assert_same_instant(certificate["expires_at"], EXPIRY_INSTANT, "expires_at")

        set_clock(TRANSMIT_CLOCK)
        submission = transmit_certificate(certificate["id"],
                                          payload={"batch_reference": "TX-BATCH-0001"})
        acknowledge_accept(submission["id"])

        set_clock(EXPIRY_INSTANT)
        run = run_compliance()
        assert_compliance_run(run)
        assert run["certificates_graced_count"] == 1
        assert run["reminders_sent_count"] == 1

        after = get_certificate_row(certificate["id"])
        assert after["validity_state"] == "GRACE"
        assert after["registry_state"] == "ACCEPTED", (
            "the compliance run leaves the registry dimension where the acknowledgement put "
            f"it, got {after['registry_state']}")
        assert_same_instant(after["registry_due_at"], REGISTRY_DUE_INSTANT,
                            "registry_due_at")
        assert get_server(walk["server"]["id"])["work_eligibility"] == "GRACE"
