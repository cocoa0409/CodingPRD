"""One write, and everything it derives is already true.

The commitment is pinned into the creating response itself, and the matter, the
reviewer, the batch and the ledger all speak for it on the very next read.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import assert_money, assert_status
from test_helpers.factories import assignment_payload
from test_helpers.test_users import ENGAGEMENT_MANAGER, STAFFING_COORDINATOR


class TestDerivedFiguresAreReadableImmediatelyAfterTheWrite:
    """No settling step stands between the assignment and its consequences."""

    def test_the_creating_response_and_the_next_reads_agree_without_a_lag(
        self, batched_matter
    ):
        """PRD §2.10: "When an operation changes something a derived figure depends on,
        that figure is recomputed inside the same request, and every row the
        recomputation touches is mutated — `updated_at` refreshed, `version` incremented
        — as part of that same request."

        The rate and the commitment are frozen in the reply itself, and the four rows
        that depend on them are already consistent when read straight after.

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response
        """
        ladder = batched_matter["ladder"]
        batch_id = batched_matter["batch_id"]
        ada_id = batched_matter["ada_id"]

        created = validate_success(
            ladder.api.create_assignment(
                batch_id,
                assignment_payload(
                    batched_matter["batch_version"], ada_id, "FIRST_PASS"
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_money(
            created["effective_per_document_cents"],
            213,
            "effective_per_document_cents",
        )
        assert_money(
            created["committed_amount_cents"], 85200, "committed_amount_cents"
        )

        matter = validate_success(
            ladder.api.get_matter(batched_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")

        reviewer = ladder.read_reviewer(ada_id)
        assert_status(reviewer, "ENGAGED", "engagement_status")
        assert reviewer["active_assignment_count"] == 1

        rows, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                created["id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
            ("COMMITMENT", 85200)
        ]
        assert rows[0]["created_at"].startswith("2026-08-01T00:00:00")

        assert ladder.read_batch(batch_id)["version"] == 2
