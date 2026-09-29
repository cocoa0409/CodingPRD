"""Quantities that must balance after an operation and its compensation.

The budget ledger is append-only, so undoing a commitment means adding an
offsetting row rather than removing one; and the document collection is
conserved, so dissolving a batch must return its documents to the pool.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import (
    assert_ledger_sums_to,
    assert_money,
    assert_status,
)
from test_helpers.constants import CLOCK_START_UTC
from test_helpers.factories import batch_payload
from test_helpers.test_users import ENGAGEMENT_MANAGER, STAFFING_COORDINATOR


class TestCommitmentThenVoidReturnsLedgerToZero:
    """A reversal offsets a commitment; nothing is ever deleted."""

    def test_voiding_an_unbilled_assignment_offsets_its_commitment_exactly(
        self, assigned_batch
    ):
        """PRD §3.6: "It appends a reversal ledger row of the negative of
        `committed_amount_cents` **only** when `billable_amount_cents` is still 0,
        meaning the commitment is genuinely still outstanding; an already-billed
        assignment keeps its actual row and receives no second reversal, and this is
        precisely what stops a rework void from double-reversing."

        Both ledger views hold the same two rows, and they sum to nothing.

        Design: Difficulty/compensating_invariant/commitment_then_void_returns_ledger_to_zero
        """
        ladder = assigned_batch["ladder"]
        assignment_id = assigned_batch["assignment_id"]

        ladder.void(assignment_id, "CLIENT_STAFFING_CHANGE")

        per_assignment, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                assignment_id, ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert [
            (row["entry_type"], row["amount_cents"]) for row in per_assignment
        ] == [("COMMITMENT", 85200), ("REVERSAL", -85200)]
        assert_ledger_sums_to(per_assignment, 0)

        matter_wide, _ = validate_paginated(
            ladder.api.list_matter_budget_ledger(
                assigned_batch["matter_id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert len(matter_wide) == 2
        assert_ledger_sums_to(matter_wide, 0)

        matter = validate_success(
            ladder.api.get_matter(assigned_batch["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 0, "committed_spend_cents")

    def test_the_void_stamps_the_clock_and_leaves_the_batch_restaffable(
        self, assigned_batch
    ):
        """PRD §3.6: "The batch moves `ASSIGNED → CREATED` or `IN_PROGRESS → CREATED`
        when no non-voided assignment of that same pass remains, whereas a batch already
        in `SECOND_LEVEL`, `QC_SAMPLING` or `QC_FAILED` keeps its status; a void from
        `REOPENED` in particular leaves the batch in `QC_FAILED`."

        The batch returns to the unstaffed state and the reviewer keeps her engagement,
        because her screening and paper both survive.

        Design: Difficulty/compensating_invariant/commitment_then_void_returns_ledger_to_zero
        """
        ladder = assigned_batch["ladder"]

        voided = ladder.void(assigned_batch["assignment_id"], "CLIENT_STAFFING_CHANGE")
        assert_status(voided, "VOIDED")
        assert voided["void_reason"] == "CLIENT_STAFFING_CHANGE"
        assert voided["voided_at"].startswith(CLOCK_START_UTC[:19])

        assert_status(ladder.read_batch(assigned_batch["batch_id"]), "CREATED")

        reviewer = ladder.read_reviewer(assigned_batch["ada_id"])
        assert_status(reviewer, "ENGAGED", "engagement_status")
        assert reviewer["scorecard_strikes"] == 0

        projection = validate_success(
            ladder.api.get_spend_projection(
                assigned_batch["matter_id"],
                ENGAGEMENT_MANAGER,
                basis="LEDGER_REPLAY_BASIS",
            )
        )
        assert_money(
            projection["ledger_replay_basis_cents"], 0, "ledger_replay_basis_cents"
        )
        assert_money(
            projection["budget_headroom_cents"], 600000, "budget_headroom_cents"
        )


class TestDocumentConservationAcrossBatchingAndDissolve:
    """Batched documents plus unbatched documents always equal the collection."""

    def _fully_batched_then_dissolved(self, staffed_matter):
        ladder = staffed_matter["ladder"]
        first = ladder.carve_batch(400)
        second = ladder.carve_batch(200)
        return ladder, first, second

    def test_dissolving_a_batch_returns_its_documents_without_deleting_the_row(
        self, staffed_matter
    ):
        """PRD §2.10: "**Documents are conserved**: a matter's
        `unbatched_document_count` is its `document_count` minus the sum of
        `document_count` over its batches whose `status` is anything other than
        `DISSOLVED`, so dissolving a batch returns its documents to the pool and carving
        one removes them."

        Carving accounts for the whole collection, and the dissolved batch keeps its own
        document count while the pool grows back.

        Design: Difficulty/compensating_invariant/document_conservation_across_batching_and_dissolve
        """
        ladder, first, second = self._fully_batched_then_dissolved(staffed_matter)

        before = validate_success(
            ladder.api.get_matter(staffed_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert before["unbatched_document_count"] == 0
        assert first["document_count"] + second["document_count"] + 0 == 600

        dissolved = ladder.dissolve_batch(second["id"])
        assert_status(dissolved, "DISSOLVED")
        assert dissolved["document_count"] == 200

        after = validate_success(
            ladder.api.get_matter(staffed_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert after["unbatched_document_count"] == 200
        assert first["document_count"] + 0 + 200 == 600

    def test_the_returned_documents_bound_the_next_carve(self, staffed_matter):
        """PRD §2.5: "A requested batch's `document_count` does not exceed the matter's
        `unbatched_document_count` — otherwise `ERR_INSUFFICIENT_UNBATCHED_DOCUMENTS`
        (HTTP 422), on batch carving."

        Only the two hundred documents that came back are available, so a request for
        two hundred and one is refused.

        Design: Difficulty/compensating_invariant/document_conservation_across_batching_and_dissolve
        """
        ladder, _, second = self._fully_batched_then_dissolved(staffed_matter)
        ladder.dissolve_batch(second["id"])

        response = ladder.api.create_batch(
            staffed_matter["matter_id"],
            batch_payload(201, priority_rank=3),
            ENGAGEMENT_MANAGER,
        )
        validate_error(response, e.ERR_INSUFFICIENT_UNBATCHED_DOCUMENTS, 422)

        batches, _ = validate_paginated(
            ladder.api.list_batches(
                STAFFING_COORDINATOR, matter_id=staffed_matter["matter_id"]
            )
        )
        assert len(batches) == 2
        assert sorted(
            (row["status"], row["document_count"]) for row in batches
        ) == [("CREATED", 400), ("DISSOLVED", 200)]

        matter = validate_success(
            ladder.api.get_matter(staffed_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 0, "committed_spend_cents")
