"""Derived figures at the corners of their own arithmetic.

The selector prefers the better-matched reviewer, a saturated pool empties, the
contract rate rounds before it multiplies, the strike total is floored at every
step, the sampling floor beats the percentage, and the projection basis has both
a status default and an explicit override.
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
    assert_scorecard_events,
    assert_status,
    contract_rate_cents,
    qc_sample_target_size,
    selector_score,
)
from test_helpers.factories import auto_assign_payload, batch_payload
from test_helpers.fixtures import REVIEWER_CLEO
from test_helpers.test_users import (
    ENGAGEMENT_MANAGER,
    STAFFING_COORDINATOR,
    make_client_counsel_headers,
)


class TestAutoAssignPicksTheHigherScoringReviewer:
    """Two eligible reviewers, one subject-matter tag between them."""

    def test_the_reviewer_matching_the_subject_matter_wins_the_batch(
        self, score_gap_pool
    ):
        """PRD §3.6: "The score is then forty-five hundredths of the normalised
        accuracy, plus thirty hundredths of the normalised pace *after that capped pace
        figure has itself been divided by 1.5*, plus fifteen hundredths of the language
        match ratio, plus ten hundredths of the subject match ratio, minus the strike
        penalty — with all four ratios computed at full precision before weighting and
        the final score rounded half up to four decimal places."

        The subject-matter component is the only difference between the two candidates,
        and it decides the selection.

        Design: Corner/calculations/auto_assign_picks_the_higher_scoring_reviewer
        """
        ladder = score_gap_pool["ladder"]
        batch_id = score_gap_pool["batch_id"]

        assert selector_score(1.0000, 0.00, 55, 2, 2, 1, 1, 0) == 0.7000
        assert selector_score(1.0000, 0.00, 55, 2, 2, 0, 1, 0) == 0.6000

        chosen = validate_success(
            ladder.api.auto_assign(
                batch_id,
                auto_assign_payload(score_gap_pool["batch_version"], "FIRST_PASS"),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert chosen["reviewer_id"] == score_gap_pool["ada_id"]
        assert_money(
            chosen["effective_per_document_cents"], 213, "effective_per_document_cents"
        )
        assert_money(chosen["committed_amount_cents"], 85200, "committed_amount_cents")

        batch = ladder.read_batch(batch_id)
        assert_status(batch, "ASSIGNED")
        assert batch["version"] == 2

        assert_status(
            ladder.read_reviewer(score_gap_pool["ada_id"]), "ENGAGED", "engagement_status"
        )
        assert_status(
            ladder.read_reviewer(score_gap_pool["dara_id"]),
            "CLEARED",
            "engagement_status",
        )

        matter = validate_success(
            ladder.api.get_matter(score_gap_pool["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")
        assert matter["staffed_reviewer_count"] == 2


class TestCapacitySaturatedReviewerLeavesThePoolEmpty:
    """The only candidate is already carrying her permitted load."""

    def test_a_saturated_sole_candidate_empties_the_pool_and_writes_nothing(
        self, staffed_matter
    ):
        """PRD §3.6: "An empty pool is answered with `ERR_NO_ELIGIBLE_REVIEWER` and
        nothing is written."

        Two live assignments exhaust the reviewer's concurrency, so the third batch
        finds nobody at all and stays exactly as it was.

        Design: Corner/calculations/capacity_saturated_reviewer_leaves_the_pool_empty
        """
        ladder = staffed_matter["ladder"]
        ada_id = staffed_matter["ada_id"]

        first = ladder.carve_batch(400)
        ladder.assign(first["id"], ada_id, "FIRST_PASS", first["version"])
        second = ladder.carve_batch(150)
        ladder.assign(second["id"], ada_id, "FIRST_PASS", second["version"])
        third = ladder.carve_batch(50)

        validate_error(
            ladder.api.auto_assign(
                third["id"],
                auto_assign_payload(third["version"], "FIRST_PASS"),
                STAFFING_COORDINATOR,
            ),
            e.ERR_NO_ELIGIBLE_REVIEWER,
            409,
        )

        reviewer = ladder.read_reviewer(ada_id)
        assert reviewer["active_assignment_count"] == 2
        assert reviewer["max_concurrent_batches"] == 2

        batch = ladder.read_batch(third["id"])
        assert_status(batch, "CREATED")
        assert batch["version"] == 1

        matter = validate_success(
            ladder.api.get_matter(staffed_matter["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 117150, "committed_spend_cents")

        assignments, _ = validate_paginated(
            ladder.api.list_assignments(STAFFING_COORDINATOR, batch_id=third["id"])
        )
        assert assignments == []


class TestContractRateRoundsHalfUpAtTheHalfCent:
    """A standard-tier rate lands exactly on a half cent."""

    def test_the_rate_is_rounded_before_it_multiplies_the_document_count(
        self, standard_tier_matter
    ):
        """PRD §2.8: "The order of rounding relative to multiplication is part of the
        contract, not an implementation detail: for per-document pricing the
        per-document rate is rounded to whole cents *first* and multiplied by the
        document count *second*, and performing those two operations in the opposite
        order produces a different and incorrect total."

        One hundred documents at a hundred and seventy-two and a half cents bill as
        seventeen thousand three hundred, not seventeen thousand two.

        Design: Corner/calculations/contract_rate_rounds_half_up_at_the_half_cent
        """
        ladder = standard_tier_matter["ladder"]
        matter_id = standard_tier_matter["matter_id"]

        batch = ladder.carve_batch(100)
        assert batch["qc_sample_target_size"] == qc_sample_target_size(100, 0.10) == 10

        assert contract_rate_cents(150, "STANDARD") == 173

        projection = validate_success(
            ladder.api.get_spend_projection(matter_id, ENGAGEMENT_MANAGER)
        )
        assert projection["basis_applied"] == "REMAINING_WORK_BASIS"
        assert_money(
            projection["remaining_work_basis_cents"],
            17300,
            "remaining_work_basis_cents",
        )
        assert_money(
            projection["ledger_replay_basis_cents"], 0, "ledger_replay_basis_cents"
        )
        assert_money(projection["variance_cents"], 17300, "variance_cents")
        assert_money(
            projection["budget_headroom_cents"], 382700, "budget_headroom_cents"
        )


class TestStrikeRunningTotalFloorsAtZeroAtEveryStep:
    """A credit against nothing is absorbed rather than banked."""

    def _three_batches_worked_and_sampled(self, staffed_matter):
        ladder = staffed_matter["ladder"]
        ada_id = staffed_matter["ada_id"]
        cleo = ladder.source_reviewer(REVIEWER_CLEO)

        paces = []
        batches = []
        for document_count, minutes in ((400, 500), (150, 150), (50, 60)):
            batch = ladder.carve_batch(document_count)
            assignment = ladder.assign(
                batch["id"], ada_id, "FIRST_PASS", batch["version"]
            )
            ladder.start(assignment["id"], ada_id)
            ladder.progress(assignment["id"], ada_id, document_count, minutes)
            paces.append(ladder.submit(assignment["id"], ada_id)["pace_dph"])
            batches.append(batch["id"])
            if len(batches) < 3:
                sample = ladder.draw_sample(batch["id"], cleo["id"])
                ladder.validate_sample(sample["id"], 0, 0)
        return ladder, paces

    def test_the_two_clean_credits_are_absorbed_and_the_last_shortfall_stands(
        self, staffed_matter
    ):
        """PRD §3.3: "Every observation the system makes about a reviewer appends a
        scorecard event, and the reviewer's `scorecard_strikes` is the replay of that
        stream: starting from 0, walk the reviewer's events in `created_at` ascending
        order and, for each one, set the running total to the greater of 0 and the
        running total plus that event's `strike_delta`."

        The four events replay to one, nought, nought and one, so a single strike stands
        rather than the naive sum of nothing.

        Design: Corner/calculations/strike_running_total_floors_at_zero_at_every_step
        """
        ladder, paces = self._three_batches_worked_and_sampled(staffed_matter)
        ada_id = staffed_matter["ada_id"]

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(ada_id, STAFFING_COORDINATOR, limit=100)
        )
        assert_scorecard_events(
            events,
            [
                ("PACE_SHORTFALL", 1),
                ("CLEARED_STRIKE", -1),
                ("CLEARED_STRIKE", -1),
                ("PACE_SHORTFALL", 1),
            ],
        )

        reviewer = ladder.read_reviewer(ada_id)
        assert reviewer["scorecard_strikes"] == 1

        assert_pace_2dp(paces[0], 48.00)
        assert_pace_2dp(paces[1], 60.00)
        assert_pace_2dp(paces[2], 50.00)

        assert_rate_4dp(reviewer["accuracy_score"], 1.0000, "accuracy_score")
        assert_status(reviewer, "ENGAGED", "engagement_status")
        assert_pace_2dp(reviewer["pace_dph"], 50.70)


class TestQcMinSampleFloorDominatesASmallBatch:
    """The sampling floor of ten beats a small percentage."""

    def test_a_fifty_document_batch_still_carries_a_ten_document_sample(
        self, matter_in_staffing
    ):
        """PRD §3.6: "The floor of 10 documents dominates on small batches: a
        50-document batch under a ten-percent sampling plan still yields a target of 10,
        not 5."

        Ten per cent of fifty is five, which the floor lifts to ten, while the larger
        batch takes its percentage unchanged.

        Design: Corner/calculations/qc_min_sample_floor_dominates_a_small_batch
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]

        small = validate_success(
            ladder.api.create_batch(matter_id, batch_payload(50), ENGAGEMENT_MANAGER),
            expected_status=201,
        )
        assert small["qc_sample_target_size"] == qc_sample_target_size(50, 0.10) == 10

        large = validate_success(
            ladder.api.create_batch(matter_id, batch_payload(400), ENGAGEMENT_MANAGER),
            expected_status=201,
        )
        assert large["qc_sample_target_size"] == qc_sample_target_size(400, 0.10) == 40

        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert matter["unbatched_document_count"] == 150


class TestProjectionBasisDefaultsByStatusAndExplicitParamWins:
    """The status picks a basis; a query parameter overrules it."""

    def test_the_explicit_basis_moves_the_headroom_but_not_the_variance(
        self, matter_in_staffing
    ):
        """PRD §3.9: "Which basis is *applied* is decided by an explicit `basis` query
        parameter when one is supplied, and otherwise by the matter's status:
        `REMAINING_WORK_BASIS` is the default for a matter in `INTAKE`,
        `PROTOCOL_PENDING`, `STAFFING` or `IN_REVIEW`, and `LEDGER_REPLAY_BASIS` is the
        default for a matter in `QC_CLOSEOUT`, `CLOSED` or `SUSPENDED`."

        Both bases are always computed, so only the applied basis and the headroom
        measured against it change between the two reads.

        Design: Corner/calculations/projection_basis_defaults_by_status_and_explicit_param_wins
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]
        ladder.carve_batch(400)

        default = validate_success(
            ladder.api.get_spend_projection(matter_id, ENGAGEMENT_MANAGER)
        )
        assert default["basis_applied"] == "REMAINING_WORK_BASIS"
        assert_money(
            default["budget_headroom_cents"], 478200, "budget_headroom_cents"
        )

        forced = validate_success(
            ladder.api.get_spend_projection(
                matter_id,
                make_client_counsel_headers(matter_in_staffing["client_id"]),
                basis="LEDGER_REPLAY_BASIS",
            )
        )
        assert forced["basis_applied"] == "LEDGER_REPLAY_BASIS"
        assert_money(forced["budget_headroom_cents"], 600000, "budget_headroom_cents")

        for readout in (default, forced):
            assert_money(
                readout["remaining_work_basis_cents"],
                121800,
                "remaining_work_basis_cents",
            )
            assert_money(
                readout["ledger_replay_basis_cents"], 0, "ledger_replay_basis_cents"
            )
            assert_money(readout["variance_cents"], 121800, "variance_cents")
