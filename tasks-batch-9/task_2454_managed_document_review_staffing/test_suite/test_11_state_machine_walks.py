"""Declared entry states, legal transitions and refused ones.

Every row starts where the engagement says it starts, the client-review loop is
re-entrant, the second-level fork and join move the batch exactly once, and a
terminal state refuses further work.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import (
    assert_money,
    assert_pace_2dp,
    assert_rate_4dp,
    assert_status,
    effective_per_document_cents,
    invoice_waterfall,
    premium_language_count,
)
from test_helpers.constants import CLOCK_START_UTC
from test_helpers.factories import (
    assignment_payload,
    execute_payload,
    protocol_payload,
    reviewer_payload,
    screening_payload,
    suspension_payload,
)
from test_helpers.fixtures import REVIEWER_ADA
from test_helpers.test_users import (
    ENGAGEMENT_MANAGER,
    QC_LEAD,
    STAFFING_COORDINATOR,
    make_reviewer_headers,
)


class TestNewRowsStartInDeclaredInitialStates:
    """Three different rows, three different documented opening states."""

    def test_a_protocol_a_reviewer_and_a_screening_all_open_where_declared(
        self, matter_in_intake
    ):
        """PRD §3.2: "A revision begins in `DRAFT` with `change_notes` null and
        `approved_at` null."

        Minting revision one also carries the matter off intake, while the reviewer's
        two standing axes open independently of each other.

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        ladder = matter_in_intake["ladder"]
        matter_id = matter_in_intake["matter_id"]

        protocol = validate_success(
            ladder.api.create_protocol(
                matter_id, protocol_payload(1), ENGAGEMENT_MANAGER
            ),
            expected_status=201,
        )
        assert_status(protocol, "DRAFT")
        assert protocol["revision_number"] == 1
        assert protocol["approved_at"] is None

        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert_status(matter, "PROTOCOL_PENDING")
        assert matter["version"] == 2

        reviewer = validate_success(
            ladder.api.create_reviewer(
                reviewer_payload(**REVIEWER_ADA), STAFFING_COORDINATOR
            ),
            expected_status=201,
        )
        assert_status(reviewer, "UNVERIFIED", "credential_status")
        assert_status(reviewer, "SOURCED", "engagement_status")

        screening = validate_success(
            ladder.api.create_screening(
                screening_payload(reviewer["id"], matter_id), STAFFING_COORDINATOR
            ),
            expected_status=201,
        )
        assert_status(screening, "PENDING")
        assert screening["screened_at"] is None
        assert screening["waiver_granted"] is False


class TestProtocolRequestChangesLoopThenApprove:
    """The client may send a protocol back as often as they like."""

    def test_the_client_review_loop_is_re_entrant_before_the_approval(
        self, matter_with_draft_protocol
    ):
        """PRD §3.2: "On `REQUEST_CHANGES`, a non-blank `change_notes` must be supplied;
        the protocol moves `CLIENT_REVIEW → DRAFT`, the supplied text is stored in
        `change_notes`, and the protocol's `version` increments."

        A requested change returns the revision to draft without approving it, and the
        second trip through ends in approval on the same revision.

        Design: Corner/state_machines/protocol_request_changes_loop_then_approve
        """
        ladder = matter_with_draft_protocol["ladder"]
        protocol_id = matter_with_draft_protocol["protocol_id"]

        assert_status(ladder.submit_protocol(protocol_id), "CLIENT_REVIEW")

        returned = ladder.request_protocol_changes(
            "add a FOREIGN_LANGUAGE issue code", protocol_id
        )
        assert_status(returned, "DRAFT")
        assert returned["change_notes"] == "add a FOREIGN_LANGUAGE issue code"
        assert returned["approved_at"] is None

        assert_status(ladder.submit_protocol(protocol_id), "CLIENT_REVIEW")

        approved = ladder.approve_protocol(protocol_id)
        assert_status(approved, "APPROVED")
        assert approved["approved_at"].startswith(CLOCK_START_UTC[:19])
        assert approved["revision_number"] == 1

        matter = validate_success(
            ladder.api.get_matter(
                matter_with_draft_protocol["matter_id"], ENGAGEMENT_MANAGER
            )
        )
        assert_status(matter, "STAFFING")
        assert matter["staffed_reviewer_count"] == 0


class TestSubmitOnApprovedProtocolRejected:
    """Two illegal transitions both report the state, not a domain rule."""

    def test_resubmitting_an_approved_protocol_and_closing_from_staffing_both_fail(
        self, matter_in_staffing
    ):
        """PRD §3.2: "Sending a protocol out for client sign-off moves it `DRAFT →
        CLIENT_REVIEW` and increments its `version`; it is an `EngagementManager`
        action, is legal only from `DRAFT`, and is refused with `ERR_MATTER_SUSPENDED`
        while the governing matter is suspended."

        Closing is declared only out of closeout, so an attempt from staffing is an
        illegal transition rather than an unmet closure precondition.

        Design: Corner/state_machines/submit_on_approved_protocol_rejected
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]
        version_before = ladder.matter_version(matter_id)

        validate_error(
            ladder.api.submit_protocol(
                matter_in_staffing["protocol_id"], ENGAGEMENT_MANAGER
            ),
            e.ERR_INVALID_STATE,
            409,
        )
        assert_status(
            validate_success(
                ladder.api.get_protocol(
                    matter_in_staffing["protocol_id"], ENGAGEMENT_MANAGER
                )
            ),
            "APPROVED",
        )

        body = validate_error(
            ladder.api.close_matter(matter_id, ENGAGEMENT_MANAGER),
            e.ERR_INVALID_STATE,
            409,
        )
        assert body["error_id"] != e.ERR_MATTER_NOT_CLOSEABLE

        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert_status(matter, "STAFFING")
        assert matter["version"] == version_before


class TestSecondExecuteOnAgreementRejected:
    """Executed paper cannot be executed twice."""

    def test_a_second_signature_is_refused_and_staffing_is_not_double_counted(
        self, matter_in_staffing
    ):
        """PRD §3.5: "Execution is legal only from `PENDING`, is refused while the
        matter is `SUSPENDED`, and is refused when the logical clock has already passed
        `coverage_end_utc` — signing paper whose coverage has elapsed is not permitted."

        The stored signature and execution stamp survive the second attempt, and the
        matter still counts one staffed reviewer.

        Design: Corner/state_machines/second_execute_on_agreement_rejected
        """
        ladder = matter_in_staffing["ladder"]
        ada = ladder.onboard(REVIEWER_ADA)

        validate_error(
            ladder.api.execute_agreement(
                ada["agreement_id"],
                execute_payload("Ada Ishikawa (again)"),
                make_reviewer_headers(ada["reviewer_id"]),
            ),
            e.ERR_INVALID_STATE,
            409,
        )

        agreement = validate_success(
            ladder.api.get_agreement(ada["agreement_id"], STAFFING_COORDINATOR)
        )
        assert_status(agreement, "EXECUTED")
        assert agreement["signature_name"] == "Ada Ishikawa"
        assert agreement["executed_at"].startswith(CLOCK_START_UTC[:19])

        matter = validate_success(
            ladder.api.get_matter(matter_in_staffing["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["staffed_reviewer_count"] == 1

        agreements, _ = validate_paginated(
            ladder.api.list_agreements(
                STAFFING_COORDINATOR, reviewer_id=ada["reviewer_id"]
            )
        )
        assert len(agreements) == 1


class TestSecondLevelForkAndJoin:
    """A protocol demanding a second pass forks the batch and later joins it."""

    def _first_pass_submitted(self, second_level_matter):
        ladder = second_level_matter["ladder"]
        ada_id = second_level_matter["ada_id"]
        first = ladder.assign(
            second_level_matter["batch_id"],
            ada_id,
            "FIRST_PASS",
            second_level_matter["batch_version"],
        )
        ladder.start(first["id"], ada_id)
        ladder.progress(first["id"], ada_id, 400, 420)
        ladder.submit(first["id"], ada_id)
        ladder.active_session(second_level_matter["ben_id"])
        return ladder, first

    def test_the_same_reviewer_cannot_take_the_second_pass_of_her_own_batch(
        self, second_level_matter
    ):
        """PRD §2.5: "A batch's `SECOND_LEVEL` assignment names a different reviewer
        than that batch's `FIRST_PASS` assignment — otherwise
        `ERR_SECOND_LEVEL_SAME_REVIEWER` (HTTP 409), on named-reviewer assignment
        creation and auto-assignment."

        The batch forked to second level rather than sampling, and the reviewer who
        coded it is refused on identity before her tier is even considered.

        Design: Corner/state_machines/second_level_fork_and_join
        """
        ladder, _ = self._first_pass_submitted(second_level_matter)
        batch_id = second_level_matter["batch_id"]

        assert_status(ladder.read_batch(batch_id), "SECOND_LEVEL")

        body = validate_error(
            ladder.api.create_assignment(
                batch_id,
                assignment_payload(
                    ladder.batch_version(batch_id),
                    second_level_matter["ada_id"],
                    "SECOND_LEVEL",
                ),
                STAFFING_COORDINATOR,
            ),
            e.ERR_SECOND_LEVEL_SAME_REVIEWER,
            409,
        )
        assert body["error_id"] != e.ERR_TIER_MISMATCH

    def test_the_second_level_submit_prices_the_pass_down_and_joins_the_paths(
        self, second_level_matter
    ):
        """PRD §3.6: "Then multiply by the pass multiplier, which is 1.00 for a
        `FIRST_PASS` assignment and 0.60 for a `SECOND_LEVEL` one."

        The second pass is priced at three fifths of the premium rate, and only its
        submit carries the batch into sampling.

        Design: Corner/state_machines/second_level_fork_and_join
        """
        ladder, first = self._first_pass_submitted(second_level_matter)
        batch_id = second_level_matter["batch_id"]
        ben_id = second_level_matter["ben_id"]

        second = validate_success(
            ladder.api.create_assignment(
                batch_id,
                assignment_payload(ladder.batch_version(batch_id), ben_id, "SECOND_LEVEL"),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        premium = premium_language_count(["EN", "JA"], ["EN", "JA"])
        expected_rate = effective_per_document_cents(
            150, "COMPLEX", premium, "SECOND_LEVEL"
        )
        assert expected_rate == 128
        assert_money(
            second["effective_per_document_cents"], 128, "effective_per_document_cents"
        )
        assert_money(second["committed_amount_cents"], 51200, "committed_amount_cents")

        ladder.start(second["id"], ben_id)
        ladder.progress(second["id"], ben_id, 400, 300)
        settled = ladder.submit(second["id"], ben_id)
        assert_money(settled["billable_amount_cents"], 51200, "billable_amount_cents")
        assert_status(ladder.read_batch(batch_id), "QC_SAMPLING")

        first_pass = ladder.read_assignment(first["id"])
        assert_money(
            first_pass["billable_amount_cents"], 85200, "billable_amount_cents"
        )
        assert_status(first_pass, "SUBMITTED")

        matter = validate_success(
            ladder.api.get_matter(second_level_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 136400, "committed_spend_cents")


class TestReleaseRequiresValidatedPrivilegeQuota:
    """A passed batch still cannot be released on an empty privilege log."""

    def test_an_empty_privilege_log_blocks_the_release_and_every_cascade(
        self, qc_validator
    ):
        """PRD §2.5: "At release, the number of the batch's privilege log entries in
        `VALIDATED` is at least the batch's privilege validation quota, and no entry of
        the batch is `CHALLENGED` — otherwise `ERR_PRIVILEGE_LOG_INCOMPLETE` (HTTP 409),
        on batch release."

        The floor of two validated entries dominates an empty log, so nothing completes,
        nothing closes out, and the clean-sample credit is absorbed.

        Design: Corner/state_machines/release_requires_validated_privilege_quota
        """
        ladder = qc_validator["ladder"]
        batch_id = qc_validator["batch_id"]

        sample = ladder.draw_sample(batch_id, qc_validator["cleo_id"])
        validated = ladder.validate_sample(sample["id"], 0, 0)
        assert validated["outcome"] == "PASSED"
        assert_rate_4dp(validated["discrepancy_rate"], 0.0000, "discrepancy_rate")
        assert_status(ladder.read_batch(batch_id), "QC_PASSED")

        validate_error(
            ladder.api.release_batch(batch_id, QC_LEAD),
            e.ERR_PRIVILEGE_LOG_INCOMPLETE,
            409,
        )

        batch = ladder.read_batch(batch_id)
        assert_status(batch, "QC_PASSED")
        assert batch["released_at"] is None

        assert_status(ladder.read_assignment(qc_validator["assignment_id"]), "SUBMITTED")
        assert_status(
            validate_success(
                ladder.api.get_matter(qc_validator["matter_id"], ENGAGEMENT_MANAGER)
            ),
            "IN_REVIEW",
        )
        assert ladder.read_reviewer(qc_validator["ada_id"])["scorecard_strikes"] == 0


class TestReleaseBubblesMatterToCloseoutThenCloseCompletes:
    """The last release carries the matter to closeout; closure then bills."""

    def test_the_release_and_the_closure_walk_the_matter_to_its_terminal_state(
        self, released_batch
    ):
        """PRD §3.8: "When that release leaves every batch of the matter either
        `RELEASED` or `DISSOLVED` **and** the matter's `unbatched_document_count` at 0,
        the matter itself moves `IN_REVIEW → QC_CLOSEOUT`."

        Releasing the only batch finalises the privilege log and completes the
        assignment, and the closed matter reads out its invoice.

        Design: Corner/state_machines/release_bubbles_matter_to_closeout_then_close_completes
        """
        ladder = released_batch["ladder"]
        matter_id = released_batch["matter_id"]

        batch = ladder.read_batch(released_batch["batch_id"])
        assert_status(batch, "RELEASED")
        assert batch["released_at"].startswith(CLOCK_START_UTC[:19])

        assert_status(ladder.read_assignment(released_batch["assignment_id"]), "COMPLETED")
        for entry_id in (released_batch["first_entry_id"], released_batch["second_entry_id"]):
            assert_status(
                validate_success(ladder.api.get_privilege_entry(entry_id, QC_LEAD)),
                "FINAL",
            )
        assert_status(
            validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER)),
            "QC_CLOSEOUT",
        )

        closed = ladder.close_matter(matter_id)
        assert_status(closed, "CLOSED")
        assert closed["unbatched_document_count"] == 0

        assignment = ladder.read_assignment(released_batch["assignment_id"])
        assert_money(
            assignment["billable_amount_cents"], 127800, "billable_amount_cents"
        )
        assert_pace_2dp(assignment["pace_dph"], 55.38)

        projection = validate_success(
            ladder.api.get_spend_projection(matter_id, ENGAGEMENT_MANAGER)
        )
        expected = invoice_waterfall(127800, 0.10)
        assert projection["basis_applied"] == "LEDGER_REPLAY_BASIS"
        assert_money(
            projection["ledger_replay_basis_cents"], 127800, "ledger_replay_basis_cents"
        )
        assert_money(projection["qc_surcharge_cents"], 2556, "qc_surcharge_cents")
        assert_money(
            projection["provisional_total_cents"], 130356, "provisional_total_cents"
        )
        assert_rate_4dp(
            projection["volume_discount_pct"], 0.03, "volume_discount_pct"
        )
        assert_money(
            projection["volume_discount_cents"], 3911, "volume_discount_cents"
        )
        assert_money(projection["invoice_total_cents"], 126445, "invoice_total_cents")
        assert_money(
            projection["invoice_total_cents"],
            expected["invoice_total_cents"],
            "invoice_total_cents",
        )


class TestClosedMatterAndReleasedBatchRejectFurtherWrites:
    """Terminal states refuse work rather than absorbing it."""

    def test_a_second_release_and_a_suspension_are_both_illegal_transitions(
        self, closed_matter
    ):
        """PRD §3.8: "`RELEASED` is terminal for a batch and `FINAL` is terminal for a
        privilege log entry."

        Neither refusal touches the released batch, the closed matter or the money
        already settled.

        Design: Corner/state_machines/closed_matter_and_released_batch_reject_further_writes
        """
        ladder = closed_matter["ladder"]
        matter_id = closed_matter["matter_id"]
        released_at = ladder.read_batch(closed_matter["batch_id"])["released_at"]

        validate_error(
            ladder.api.release_batch(closed_matter["batch_id"], QC_LEAD),
            e.ERR_INVALID_STATE,
            409,
        )
        assert ladder.read_batch(closed_matter["batch_id"])["released_at"] == released_at

        validate_error(
            ladder.api.set_matter_suspension(
                matter_id,
                suspension_payload(
                    True, suspension_reason="attempt to suspend a closed matter"
                ),
                ENGAGEMENT_MANAGER,
            ),
            e.ERR_INVALID_STATE,
            409,
        )

        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert_status(matter, "CLOSED")
        assert matter["suspension_reason"] is None
        assert_money(matter["committed_spend_cents"], 127800, "committed_spend_cents")

        assert_status(ladder.read_assignment(closed_matter["assignment_id"]), "COMPLETED")
