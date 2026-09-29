"""Values sitting exactly on a documented boundary.

A discrepancy rate equal to the maximum fails rather than passes, a commitment
equal to the budget cap is permitted rather than refused, and a minute count
already divisible by six is not pushed up to the next block.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import (
    assert_ledger_movements,
    assert_money,
    assert_pace_2dp,
    assert_rate_4dp,
    assert_status,
    billable_minutes,
    hourly_commitment_cents,
    qc_sample_target_size,
)
from test_helpers.factories import assignment_payload, qc_sample_payload
from test_helpers.test_users import ENGAGEMENT_MANAGER, QC_LEAD, STAFFING_COORDINATOR


class TestDiscrepancyRateAtThresholdFails:
    """The maximum discrepancy rate is itself a failing rate."""

    def test_a_rate_exactly_equal_to_the_maximum_fails_the_sample(self, drawn_sample):
        """PRD §3.8: "The threshold comparison is **inclusive at the boundary**: the
        outcome is `FAILED` when `discrepancy_rate` is greater than *or equal to* the
        protocol's `max_discrepancy_pct`, and `PASSED` only when it is strictly below."

        Two errors over forty sampled documents is exactly five hundredths, which is at
        the maximum and therefore fails.

        Design: Difficulty/boundary_precision_check/qc_discrepancy_rate_at_threshold_fails
        """
        ladder = drawn_sample["ladder"]

        sample = validate_success(
            ladder.api.get_qc_sample(drawn_sample["sample_id"], QC_LEAD)
        )
        assert sample["sampled_document_count"] == qc_sample_target_size(400, 0.10)
        assert sample["sampled_document_count"] == 40

        validated = ladder.validate_sample(drawn_sample["sample_id"], 2, 0)
        assert_rate_4dp(validated["discrepancy_rate"], 0.0500, "discrepancy_rate")
        assert validated["outcome"] == "FAILED"

        assert_status(ladder.read_batch(drawn_sample["batch_id"]), "QC_FAILED")
        assert_status(
            ladder.read_assignment(drawn_sample["assignment_id"]), "REOPENED"
        )

    def test_a_rate_strictly_below_the_maximum_passes_after_rework(self, drawn_sample):
        """PRD §3.8: "Validation stores both counts, computes `discrepancy_rate` as
        their sum divided by `sampled_document_count` rounded half up to four decimal
        places, stamps `validated_at`, and sets `outcome`."

        One error over the same forty documents sits under the maximum, so the reworked
        batch passes and the reviewer keeps a single strike.

        Design: Difficulty/boundary_precision_check/qc_discrepancy_rate_at_threshold_fails
        """
        ladder = drawn_sample["ladder"]
        ada_id = drawn_sample["ada_id"]
        batch_id = drawn_sample["batch_id"]

        ladder.validate_sample(drawn_sample["sample_id"], 2, 0)
        ladder.start(drawn_sample["assignment_id"], ada_id)
        ladder.submit(drawn_sample["assignment_id"], ada_id)

        second = validate_success(
            ladder.api.create_qc_sample(
                batch_id, qc_sample_payload(drawn_sample["cleo_id"]), QC_LEAD
            ),
            expected_status=201,
        )
        assert second["sampled_document_count"] == 40

        validated = ladder.validate_sample(second["id"], 1, 0)
        assert_rate_4dp(validated["discrepancy_rate"], 0.0250, "discrepancy_rate")
        assert validated["outcome"] == "PASSED"
        assert_status(ladder.read_batch(batch_id), "QC_PASSED")

        reviewer = ladder.read_reviewer(ada_id)
        assert reviewer["scorecard_strikes"] == 1
        # Three errors across eighty sampled documents, above the removal floor.
        assert_rate_4dp(reviewer["accuracy_score"], 0.9625, "accuracy_score")
        assert_status(reviewer, "ENGAGED", "engagement_status")


class TestBudgetCapEqualityPermittedThenExceeded:
    """New commitments may reach the cap exactly but never pass it."""

    def test_a_commitment_that_lands_exactly_on_the_cap_is_permitted(
        self, capped_matter
    ):
        """PRD §3.6: "Landing exactly on the cap is permitted; going one cent beyond it
        is refused with `ERR_BUDGET_WOULD_EXCEED` and HTTP 402, and nothing at all is
        written."

        A commitment of 85200 against a cap of 85200 leaves no headroom and is still
        accepted.

        Design: Difficulty/boundary_precision_check/budget_cap_equality_permitted_then_exceeded
        """
        ladder = capped_matter["ladder"]

        created = validate_success(
            ladder.api.create_assignment(
                capped_matter["batch_one_id"],
                assignment_payload(
                    capped_matter["batch_one_version"],
                    capped_matter["ada_id"],
                    "FIRST_PASS",
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_money(created["committed_amount_cents"], 85200, "committed_amount_cents")

        matter = validate_success(
            ladder.api.get_matter(capped_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")

        projection = validate_success(
            ladder.api.get_spend_projection(
                capped_matter["matter_id"],
                ENGAGEMENT_MANAGER,
                basis="LEDGER_REPLAY_BASIS",
            )
        )
        assert_money(
            projection["budget_headroom_cents"], 0, "budget_headroom_cents"
        )

    def test_the_next_commitment_is_refused_and_leaves_the_ledger_untouched(
        self, capped_matter
    ):
        """PRD §2.5: "A violation is `ERR_BUDGET_WOULD_EXCEED` (HTTP 402), on
        named-reviewer assignment creation and auto-assignment."

        One cent of further commitment would pass the cap, so the second batch stays
        unstaffed and the committed total does not move.

        Design: Difficulty/boundary_precision_check/budget_cap_equality_permitted_then_exceeded
        """
        ladder = capped_matter["ladder"]

        validate_success(
            ladder.api.create_assignment(
                capped_matter["batch_one_id"],
                assignment_payload(
                    capped_matter["batch_one_version"],
                    capped_matter["ada_id"],
                    "FIRST_PASS",
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        refused = ladder.api.create_assignment(
            capped_matter["batch_two_id"],
            assignment_payload(
                capped_matter["batch_two_version"],
                capped_matter["ada_id"],
                "FIRST_PASS",
            ),
            STAFFING_COORDINATOR,
        )
        validate_error(refused, e.ERR_BUDGET_WOULD_EXCEED, 402)

        assignments, _ = validate_paginated(
            ladder.api.list_assignments(
                STAFFING_COORDINATOR, batch_id=capped_matter["batch_two_id"]
            )
        )
        assert assignments == []
        assert_status(ladder.read_batch(capped_matter["batch_two_id"]), "CREATED")

        matter = validate_success(
            ladder.api.get_matter(capped_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")


class TestHourlySixMinuteIncrementRoundsUp:
    """Logged minutes are billed in whole six-minute blocks."""

    def _both_assignments_submitted(self, hourly_matter):
        ladder = hourly_matter["ladder"]
        ada_id = hourly_matter["ada_id"]

        ladder.start(hourly_matter["assignment_one_id"], ada_id)
        ladder.progress(hourly_matter["assignment_one_id"], ada_id, 100, 109)
        first = ladder.submit(hourly_matter["assignment_one_id"], ada_id)

        ladder.start(hourly_matter["assignment_two_id"], ada_id)
        ladder.progress(hourly_matter["assignment_two_id"], ada_id, 100, 108)
        second = ladder.submit(hourly_matter["assignment_two_id"], ada_id)
        return ladder, first, second

    def test_a_part_block_rounds_up_while_an_exact_multiple_does_not_move(
        self, hourly_matter
    ):
        """PRD §3.7: "For a matter priced `HOURLY`, `billable_minutes` is first computed
        as `minutes_logged` rounded up to the next whole 6-minute block, equalling
        `minutes_logged` exactly when that figure is already a multiple of 6 and
        otherwise always rounding up even for a single extra minute;
        `billable_amount_cents` is then the matter's `hourly_rate_cents` multiplied by
        `billable_minutes`, divided by 60, rounded half up to whole cents."

        One hundred and nine minutes bill as one hundred and fourteen, while one hundred
        and eight are already a whole number of blocks.

        Design: Difficulty/boundary_precision_check/hourly_six_minute_increment_rounds_up
        """
        _, first, second = self._both_assignments_submitted(hourly_matter)

        assert first["billable_minutes"] == billable_minutes(109) == 114
        assert_money(first["billable_amount_cents"], 12350, "billable_amount_cents")

        assert second["billable_minutes"] == billable_minutes(108) == 108
        assert_money(second["billable_amount_cents"], 11700, "billable_amount_cents")

        assert_money(
            first["effective_per_document_cents"], 0, "effective_per_document_cents"
        )

    def test_the_commitment_uses_the_pace_basis_rather_than_the_logged_minutes(
        self, hourly_matter
    ):
        """PRD §3.6: "On an `HOURLY` matter, the commitment projects the time the batch
        ought to take: the projected minutes are the batch's `document_count` divided by
        the approved protocol's `min_pace_dph` and multiplied by 60, and
        `committed_amount_cents` is the matter's `hourly_rate_cents` multiplied by those
        projected minutes, divided by 60, rounded half up to whole cents — equivalently,
        the `hourly_rate_cents` multiplied by the batch's `document_count` and divided
        by `min_pace_dph`, rounded half up."

        Each commitment prices the time the batch ought to take at the pace floor, so
        the actuals diverge from it in both directions.

        Design: Difficulty/boundary_precision_check/hourly_six_minute_increment_rounds_up
        """
        ladder, first, second = self._both_assignments_submitted(hourly_matter)

        expected_commitment = hourly_commitment_cents(6500, 100, 55)
        assert expected_commitment == 11818
        assert_money(
            first["committed_amount_cents"], 11818, "committed_amount_cents"
        )

        rows, _ = validate_paginated(
            ladder.api.list_matter_budget_ledger(
                hourly_matter["matter_id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert_ledger_movements(
            rows,
            [
                ("COMMITMENT", 11818),
                ("COMMITMENT", 11818),
                ("REVERSAL", -11818),
                ("ACTUAL_HOURLY", 12350),
                ("REVERSAL", -11818),
                ("ACTUAL_HOURLY", 11700),
            ],
        )

        matter = validate_success(
            ladder.api.get_matter(hourly_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 24050, "committed_spend_cents")

        assert_pace_2dp(first["pace_dph"], 55.05)
        assert_pace_2dp(second["pace_dph"], 55.56)
        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(
                hourly_matter["ada_id"], QC_LEAD, limit=100
            )
        )
        assert events == []
