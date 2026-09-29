"""Operations whose legality is decided by the state of a different row.

Starting an assignment depends on paper that may have lapsed since it was
signed, and drawing a quality-control sample depends on who else happens to
hold work on the batch.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import assert_money, assert_status
from test_helpers.factories import qc_sample_payload
from test_helpers.test_users import ENGAGEMENT_MANAGER, QC_LEAD


class TestStartBlockedByLazilyExpiredAgreement:
    """Coverage that has run out is discovered by the request that needs it."""

    def test_starting_after_coverage_has_elapsed_is_refused_on_the_paper(
        self, assigned_batch
    ):
        """PRD §3.5: "An agreement **expires** lazily: an `EXECUTED` agreement whose
        `coverage_end_utc` is behind the logical clock becomes `EXPIRED` at the start of
        the next request that reads or consults it — any read of the agreement itself,
        any listing that includes it, and any operation whose validations consult it —
        and the expiry recomputes the matter's `staffed_reviewer_count`, dropping the
        matter `IN_REVIEW → STAFFING` when it falls short, and increments the
        agreement's `version`."

        The reviewer's credential and the assignment status are both fine; it is the
        elapsed confidentiality coverage that refuses the start.

        Design: Difficulty/cross_entity_state_dependency/assignment_start_blocked_by_lazily_expired_agreement
        """
        ladder = assigned_batch["ladder"]
        ladder.set_clock("2026-11-01T00:00:00Z")

        response = ladder.api.start_assignment(
            assigned_batch["assignment_id"], assigned_batch["ada_headers"]
        )
        body = validate_error(response, e.ERR_CONFIDENTIALITY_NOT_EXECUTED, 409)
        assert body["error_id"] != e.ERR_CREDENTIAL_NOT_VERIFIED
        assert body["error_id"] != e.ERR_INVALID_STATE

    def test_the_expiry_drops_staffing_but_voids_no_assignment(self, assigned_batch):
        """PRD §3.5: "Expiry deliberately does **not** void existing assignments: they
        keep their status but can no longer be started, progressed or submitted, because
        those operations demand live coverage and otherwise answer
        `ERR_CONFIDENTIALITY_NOT_EXECUTED`."

        Consulting the agreement expires it and drops the matter out of review, while
        the assignment keeps its status and its commitment.

        Design: Difficulty/cross_entity_state_dependency/assignment_start_blocked_by_lazily_expired_agreement
        """
        ladder = assigned_batch["ladder"]
        ladder.set_clock("2026-11-01T00:00:00Z")
        ladder.api.start_assignment(
            assigned_batch["assignment_id"], assigned_batch["ada_headers"]
        )

        agreement = validate_success(
            ladder.api.get_agreement(
                assigned_batch["ada"]["agreement_id"], ENGAGEMENT_MANAGER
            )
        )
        assert_status(agreement, "EXPIRED")

        matter = validate_success(
            ladder.api.get_matter(assigned_batch["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["staffed_reviewer_count"] == 0
        assert_status(matter, "STAFFING")
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")

        assignment = ladder.read_assignment(assigned_batch["assignment_id"])
        assert_status(assignment, "ASSIGNED")
        assert_money(
            assignment["committed_amount_cents"], 85200, "committed_amount_cents"
        )

        reviewer = ladder.read_reviewer(assigned_batch["ada_id"])
        assert_status(reviewer, "VERIFIED", "credential_status")
        assert_status(reviewer, "ENGAGED", "engagement_status")


class TestSampleValidatorMustNotHoldBatchAssignment:
    """Nobody scores a batch they worked on."""

    def test_naming_the_batch_s_own_reviewer_as_validator_is_refused(
        self, qc_validator
    ):
        """PRD §3.8: "Segregation of duties is enforced strictly: that reviewer must not
        hold **any** assignment on the batch being sampled whose status is anything
        other than `VOIDED`, and a validator who does is refused with
        `ERR_QC_VALIDATOR_CONFLICT`."

        The reviewer who coded the documents cannot be the one who checks them.

        Design: Difficulty/cross_entity_state_dependency/qc_sample_validator_must_not_hold_batch_assignment
        """
        ladder = qc_validator["ladder"]

        response = ladder.api.create_qc_sample(
            qc_validator["batch_id"],
            qc_sample_payload(qc_validator["ada_id"]),
            QC_LEAD,
        )
        validate_error(response, e.ERR_QC_VALIDATOR_CONFLICT, 409)

        samples, _ = validate_paginated(
            ladder.api.list_qc_samples(QC_LEAD, batch_id=qc_validator["batch_id"])
        )
        assert samples == []
        assert_status(ladder.read_batch(qc_validator["batch_id"]), "QC_SAMPLING")

    def test_an_uninvolved_validator_is_accepted_and_draws_a_single_sample(
        self, qc_validator
    ):
        """PRD §3.8: "The draw freezes `sampled_document_count` as a copy of the batch's
        `qc_sample_target_size` at that instant, itself the greater of 10 and the
        batch's `document_count` multiplied by the protocol's `qc_sample_pct` rounded
        up, and then capped at the batch's own `document_count` so that a batch of 4
        documents can never carry a sample of 10."

        A reviewer who holds no assignment on the batch may score it, and the refused
        attempt left no half-drawn sample behind.

        Design: Difficulty/cross_entity_state_dependency/qc_sample_validator_must_not_hold_batch_assignment
        """
        ladder = qc_validator["ladder"]

        ladder.api.create_qc_sample(
            qc_validator["batch_id"],
            qc_sample_payload(qc_validator["ada_id"]),
            QC_LEAD,
        )
        drawn = validate_success(
            ladder.api.create_qc_sample(
                qc_validator["batch_id"],
                qc_sample_payload(qc_validator["cleo_id"]),
                QC_LEAD,
            ),
            expected_status=201,
        )
        assert drawn["validated_by_reviewer_id"] == qc_validator["cleo_id"]
        assert drawn["sampled_document_count"] == 40

        samples, _ = validate_paginated(
            ladder.api.list_qc_samples(QC_LEAD, batch_id=qc_validator["batch_id"])
        )
        assert len(samples) == 1
        assert samples[0]["outcome"] == "PENDING"

        assert_status(ladder.read_batch(qc_validator["batch_id"]), "QC_SAMPLING")
        assignment = ladder.read_assignment(qc_validator["assignment_id"])
        assert_status(assignment, "SUBMITTED")
        assert_money(
            assignment["billable_amount_cents"], 85200, "billable_amount_cents"
        )
