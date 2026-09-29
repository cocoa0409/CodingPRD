"""The three audit-filing gates and the high-risk verification deadline."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant

ATTESTATION = (
    "Caller attended the emergency department, was treated and released the same "
    "evening."
)


@pytest.fixture
def ed_now_advice_with_an_open_callback(world):
    """An ED_NOW disposition whose HIGH_RISK callback is still PENDING."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        protocol={"base_severity": 62},
    )
    _, _, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    task = world.callback_for(disposition["id"])
    return disposition, task


class TestAuditFilingGates:
    def test_the_outcome_cannot_be_filed_while_the_callback_is_open(
        self, world, ed_now_advice_with_an_open_callback
    ):
        """PRD §3.10: "and where the disposition's `requires_callback` is true, the
        callback task for it must have reached one of `VERIFIED`, `ESCALATED`, `EXPIRED`
        or `CANCELLED`, with a task still `PENDING`, `ATTEMPTED` or `REACHED` refused as
        `ERR_CALLBACK_NOT_RESOLVED`."

        Design: Corner/validations/audit_record_rejects_an_open_callback_a_backdated_outcome_and_a_duplicate
        """
        disposition, task = ed_now_advice_with_an_open_callback
        assert task["status"] == "PENDING"

        response = world.api.create_audit_record(
            disposition["id"],
            f.audit_record_payload(
                reported_outcome="ED_TREATED_RELEASED",
                outcome_observed_at="2026-08-03T14:30:00Z",
                outcome_source="ED_FEED",
            ),
            world.auditor,
        )

        validate_error(response, ApiErrorId.ERR_CALLBACK_NOT_RESOLVED, 409)

    def test_an_outcome_observed_a_minute_before_the_advice_is_backdated(
        self, world, ed_now_advice_with_an_open_callback
    ):
        """PRD §3.10: "and `outcome_observed_at`, the instant the outcome was observed,
        which must be at or after the disposition's `created_at` and is otherwise
        refused with `ERR_OUTCOME_PREDATES_DISPOSITION`."

        Design: Corner/validations/audit_record_rejects_an_open_callback_a_backdated_outcome_and_a_duplicate
        """
        disposition, task = ed_now_advice_with_an_open_callback
        world.record_attempt(task["id"], "nurse_a", "REACHED")
        world.verify_callback(
            task["id"], "nurse_c", "IMPROVED", True, verifier_attestation=ATTESTATION
        )

        response = world.api.create_audit_record(
            disposition["id"],
            f.audit_record_payload(
                reported_outcome="ED_TREATED_RELEASED",
                outcome_observed_at="2026-08-03T14:29:00Z",
                outcome_source="ED_FEED",
            ),
            world.auditor,
        )

        validate_error(response, ApiErrorId.ERR_OUTCOME_PREDATES_DISPOSITION, 422)

    def test_the_dispositions_own_instant_is_accepted_and_reads_concordant(
        self, world, ed_now_advice_with_an_open_callback
    ):
        """PRD §3.10: "A `CONCORDANT` record advances it
        `OUTCOME_RECORDED → CONCORDANT_CLOSED`, which is terminal and quiet."

        Design: Corner/validations/audit_record_rejects_an_open_callback_a_backdated_outcome_and_a_duplicate
        """
        disposition, task = ed_now_advice_with_an_open_callback
        world.record_attempt(task["id"], "nurse_a", "REACHED")
        world.verify_callback(
            task["id"], "nurse_c", "IMPROVED", True, verifier_attestation=ATTESTATION
        )
        world.api.create_audit_record(
            disposition["id"],
            f.audit_record_payload(
                reported_outcome="ED_TREATED_RELEASED",
                outcome_observed_at="2026-08-03T14:29:00Z",
                outcome_source="ED_FEED",
            ),
            world.auditor,
        )

        record = world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_TREATED_RELEASED",
            outcome_observed_at="2026-08-03T14:30:00Z",
            outcome_source="ED_FEED",
        )

        assert record["variance_class"] == "CONCORDANT"
        assert record["variance_severity_points"] == 0
        assert record["outcome_ordinal"] == 4
        assert record["disposition_level_ordinal"] == 4
        assert world.disposition(disposition["id"])["audit_status"] == "CONCORDANT_CLOSED"

    def test_a_second_filing_is_refused_as_already_recorded(
        self, world, ed_now_advice_with_an_open_callback
    ):
        """PRD §3.10: "its `audit_status` must be `AWAITING_OUTCOME`, and a disposition
        that already carries an audit record is refused with
        `ERR_OUTCOME_ALREADY_RECORDED` because records are immutable and
        one-per-disposition".

        Design: Corner/validations/audit_record_rejects_an_open_callback_a_backdated_outcome_and_a_duplicate
        """
        disposition, task = ed_now_advice_with_an_open_callback
        world.record_attempt(task["id"], "nurse_a", "REACHED")
        world.verify_callback(
            task["id"], "nurse_c", "IMPROVED", True, verifier_attestation=ATTESTATION
        )
        world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_TREATED_RELEASED",
            outcome_observed_at="2026-08-03T14:30:00Z",
            outcome_source="ED_FEED",
        )

        response = world.api.create_audit_record(
            disposition["id"],
            f.audit_record_payload(
                reported_outcome="ED_ADMITTED",
                outcome_observed_at="2026-08-03T14:35:00Z",
                outcome_source="EHR_CLAIM",
            ),
            world.auditor,
        )

        validate_error(response, ApiErrorId.ERR_OUTCOME_ALREADY_RECORDED, 409)
        _, meta = validate_paginated(
            world.api.list_audit_records(disposition["id"], world.auditor, None)
        )
        assert meta["total_count"] == 1
        practice = world.practice()
        assert practice["open_variance_count"] == 0
        assert practice["compliance_posture"] == "NORMAL"


@pytest.fixture
def reached_high_risk_task(world):
    """A HIGH_RISK callback due at 16:30 that nurse_a has already reached."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        protocol={"base_severity": 62},
    )
    _, _, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    task = world.callback_for(disposition["id"])
    world.record_attempt(task["id"], "nurse_a", "REACHED")
    return disposition, task


class TestHighRiskVerificationDeadline:
    def test_one_minute_past_the_due_instant_is_refused(
        self, world, reached_high_risk_task
    ):
        """PRD §3.8: "For a `HIGH_RISK` task there is also a hard deadline — the logical
        clock must be at or before the task's `due_by_utc`, and a clock strictly past
        that instant is refused with `ERR_CALLBACK_PAST_DUE`, because a late high-risk
        verification cannot be back-dated into compliance."

        Design: Corner/validations/high_risk_callback_verified_after_its_due_time_is_rejected
        """
        _, task = reached_high_risk_task
        assert task["risk_class"] == "HIGH_RISK"
        assert_instant(task["due_by_utc"], "2026-08-03T16:30:00Z", "due_by_utc")
        world.set_clock("2026-08-03T16:31:00Z")

        response = world.api.verify_callback(
            task["id"],
            f.verify_payload(
                "IMPROVED",
                True,
                verifier_attestation=(
                    "Independent nurse reached the caller one minute after the "
                    "high-risk callback window closed."
                ),
            ),
            world.nurse_headers("nurse_c"),
        )

        validate_error(response, ApiErrorId.ERR_CALLBACK_PAST_DUE, 409)
        assert world.callback(task["id"])["status"] == "REACHED", (
            "the refusal leaves the verification retryable"
        )

    def test_the_clock_sitting_exactly_on_the_due_instant_still_verifies(
        self, world, reached_high_risk_task
    ):
        """PRD §3.8: "All three are recorded, along with `verified_by_nurse_id` as the
        acting nurse's identifier and `verified_at` as the current logical-clock instant,
        and the task's `version` increases by one."

        Design: Corner/validations/high_risk_callback_verified_after_its_due_time_is_rejected
        """
        _, task = reached_high_risk_task
        world.set_clock("2026-08-03T16:31:00Z")
        world.api.verify_callback(
            task["id"], f.verify_payload("IMPROVED", True), world.nurse_headers("nurse_c")
        )
        world.set_clock("2026-08-03T16:30:00Z")

        verified = world.verify_callback(
            task["id"],
            "nurse_c",
            "IMPROVED",
            True,
            verifier_attestation=(
                "Independent nurse confirmed the caller followed the emergency "
                "department advice and is improving."
            ),
        )

        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_nurse_id"] == world.nurse_id("nurse_c")
        assert_instant(verified["verified_at"], "2026-08-03T16:30:00Z", "verified_at")

    def test_the_late_then_on_time_verification_settles_the_ledgers_once(
        self, world, reached_high_risk_task
    ):
        """PRD §3.8: "When `patient_condition` is `IMPROVED` or `UNCHANGED`, the task
        moves `REACHED → VERIFIED`, the practice's `open_callback_count` decreases by
        one, and the parent disposition has `callback_verified_at` stamped with the
        current logical-clock instant and its `version` increased by one."

        Design: Corner/validations/high_risk_callback_verified_after_its_due_time_is_rejected
        """
        disposition, task = reached_high_risk_task
        world.set_clock("2026-08-03T16:31:00Z")
        world.api.verify_callback(
            task["id"], f.verify_payload("IMPROVED", True), world.nurse_headers("nurse_c")
        )
        world.set_clock("2026-08-03T16:30:00Z")
        world.verify_callback(task["id"], "nurse_c", "IMPROVED", True)

        after = world.disposition(disposition["id"])

        assert_instant(
            after["callback_verified_at"],
            "2026-08-03T16:30:00Z",
            "callback_verified_at",
        )
        assert after["audit_status"] == "AWAITING_OUTCOME"
        assert world.practice()["open_callback_count"] == 0
