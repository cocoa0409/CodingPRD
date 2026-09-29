"""Concurrency guards, version arithmetic and one inclusive threshold.

Both version tokens are enforced on the parent row, every mutation moves that
row's counter by exactly one while reads leave it alone, and the pace floor is
inclusive at the protocol's own figure.
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
    assert_scorecard_events,
    assert_status,
)
from test_helpers.factories import (
    assignment_payload,
    auto_assign_payload,
    protocol_payload,
)
from test_helpers.fixtures import REVIEWER_ADA
from test_helpers.test_users import ENGAGEMENT_MANAGER, STAFFING_COORDINATOR

FIVE_ISSUE_CODES = [
    "RESPONSIVE",
    "NOT_RESPONSIVE",
    "PRIVILEGED",
    "HOT",
    "FOREIGN_LANGUAGE",
]


class TestStaleMatterVersionRejectedOnProtocolRevision:
    """The token captured at creation is two mutations behind."""

    def test_the_freshly_read_version_supersedes_the_approved_revision(
        self, matter_in_staffing
    ):
        """PRD §2.7: "If it does not equal the matter's current `version`, the request
        is rejected with `ERR_STALE_MATTER_VERSION` and HTTP 412."

        The mint and the approval cascade each moved the matter, so only the version
        read back now fits the guard.

        Design: Corner/cross_cutting_complexity_layers/stale_matter_version_rejected_on_protocol_revision
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]
        first_protocol_id = matter_in_staffing["protocol_id"]

        validate_error(
            ladder.api.create_protocol(
                matter_id,
                protocol_payload(
                    1, issue_codes=FIVE_ISSUE_CODES, second_level_required=False
                ),
                ENGAGEMENT_MANAGER,
            ),
            e.ERR_STALE_MATTER_VERSION,
            412,
        )
        assert_status(
            validate_success(
                ladder.api.get_protocol(first_protocol_id, ENGAGEMENT_MANAGER)
            ),
            "APPROVED",
        )
        protocols, _ = validate_paginated(
            ladder.api.list_protocols(ENGAGEMENT_MANAGER, matter_id=matter_id)
        )
        assert len(protocols) == 1

        current = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert current["version"] == 3

        second = validate_success(
            ladder.api.create_protocol(
                matter_id,
                protocol_payload(
                    current["version"],
                    issue_codes=FIVE_ISSUE_CODES,
                    second_level_required=False,
                ),
                ENGAGEMENT_MANAGER,
            ),
            expected_status=201,
        )
        assert second["revision_number"] == 2
        assert_status(second, "DRAFT")
        assert_status(
            validate_success(
                ladder.api.get_protocol(first_protocol_id, ENGAGEMENT_MANAGER)
            ),
            "SUPERSEDED",
        )

        after = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert_status(after, "PROTOCOL_PENDING")
        assert after["version"] == 4


class TestStaleBatchVersionRejectedOnBothAssignmentPaths:
    """Both write paths carry the same guard on the same parent row."""

    def test_the_named_path_and_the_selector_path_refuse_the_same_stale_token(
        self, score_gap_pool
    ):
        """PRD §2.5: "`expected_batch_version` equals the batch's current `version` —
        otherwise `ERR_STALE_BATCH_VERSION` (HTTP 412), on named-reviewer assignment
        creation and on auto-assignment."

        The first assignment lifted the batch, so the token captured at carve time is
        stale for either way of creating the next assignment.

        Design: Corner/cross_cutting_complexity_layers/stale_batch_version_rejected_on_both_assignment_paths
        """
        ladder = score_gap_pool["ladder"]
        batch_id = score_gap_pool["batch_id"]
        stale = score_gap_pool["batch_version"]
        ladder.assign(batch_id, score_gap_pool["ada_id"], "FIRST_PASS", stale)

        validate_error(
            ladder.api.create_assignment(
                batch_id,
                assignment_payload(stale, score_gap_pool["dara_id"], "FIRST_PASS"),
                STAFFING_COORDINATOR,
            ),
            e.ERR_STALE_BATCH_VERSION,
            412,
        )
        validate_error(
            ladder.api.auto_assign(
                batch_id, auto_assign_payload(stale, "FIRST_PASS"), STAFFING_COORDINATOR
            ),
            e.ERR_STALE_BATCH_VERSION,
            412,
        )

        batch = ladder.read_batch(batch_id)
        assert batch["version"] == 2
        assert_status(batch, "ASSIGNED")

        assignments, _ = validate_paginated(
            ladder.api.list_assignments(STAFFING_COORDINATOR, batch_id=batch_id)
        )
        assert len(assignments) == 1

        matter = validate_success(
            ladder.api.get_matter(score_gap_pool["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")
        rows, _ = validate_paginated(
            ladder.api.list_matter_budget_ledger(
                score_gap_pool["matter_id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
            ("COMMITMENT", 85200)
        ]

        passed_over = ladder.read_reviewer(score_gap_pool["dara_id"])
        assert_status(passed_over, "CLEARED", "engagement_status")
        assert passed_over["active_assignment_count"] == 0


class TestVersionIncrementsOnEveryWriteButNotOnReads:
    """Each mutation moves the counter by exactly one; reads never do."""

    def test_the_staffing_cascade_counts_as_a_mutation_and_reads_do_not(
        self, matter_in_intake
    ):
        """PRD §2.6: "`version` — an integer that starts at 1 and increments by exactly
        1 on every mutation of the row."

        The submit touches no matter field at all, while the execution's cascade into
        review is itself a mutation of the matter.

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_but_not_on_reads
        """
        ladder = matter_in_intake["ladder"]
        matter_id = matter_in_intake["matter_id"]
        assert ladder.read_matter(matter_id)["version"] == 1

        protocol = ladder.mint_protocol(expected_matter_version=1)
        assert ladder.read_matter(matter_id)["version"] == 2

        ladder.submit_protocol(protocol["id"])
        assert ladder.read_matter(matter_id)["version"] == 2

        ladder.approve_protocol(protocol["id"])
        after_approval = ladder.read_matter(matter_id)
        assert_status(after_approval, "STAFFING")
        assert after_approval["version"] == 3

        ada = ladder.onboard(REVIEWER_ADA)
        after_execution = ladder.read_matter(matter_id)
        assert_status(after_execution, "IN_REVIEW")
        assert after_execution["version"] > after_approval["version"]

        batch = ladder.carve_batch(400)
        assert batch["version"] == 1
        after_carve = ladder.read_matter(matter_id)
        assert after_carve["version"] == after_execution["version"] + 1

        ladder.assign(batch["id"], ada["reviewer_id"], "FIRST_PASS", batch["version"])
        assert ladder.read_batch(batch["id"])["version"] == 2

        settled = ladder.read_matter(matter_id)["version"]
        assert ladder.read_matter(matter_id)["version"] == settled
        assert ladder.read_batch(batch["id"])["version"] == 2


class TestPaceThresholdIsInclusiveAtTheProtocolFloor:
    """Fifty-five documents an hour meets a floor of fifty-five."""

    def test_one_minute_either_side_of_the_floor_decides_the_strike(
        self, staffed_matter
    ):
        """PRD §3.7: "When the pace is strictly below the minimum, a scorecard event of
        type `PACE_SHORTFALL` with `strike_delta` of +1 is appended for the reviewer,
        its `source_batch_number` naming the batch, and the removal evaluation of
        Section 3.3 runs immediately afterwards — so a slow submit can, on its own,
        remove a reviewer and cascade into the voiding of all their other live
        assignments."

        Exactly on the floor appends nothing, and a single further minute takes the same
        document count below it.

        Design: Corner/cross_cutting_complexity_layers/pace_threshold_is_inclusive_at_the_protocol_floor
        """
        ladder = staffed_matter["ladder"]
        ada_id = staffed_matter["ada_id"]

        first_batch = ladder.carve_batch(55)
        second_batch = ladder.carve_batch(55)
        first = ladder.assign(
            first_batch["id"], ada_id, "FIRST_PASS", first_batch["version"]
        )
        second = ladder.assign(
            second_batch["id"], ada_id, "FIRST_PASS", second_batch["version"]
        )

        ladder.start(first["id"], ada_id)
        ladder.progress(first["id"], ada_id, 55, 60)
        on_the_floor = ladder.submit(first["id"], ada_id)
        assert_pace_2dp(on_the_floor["pace_dph"], 55.00)

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(ada_id, STAFFING_COORDINATOR, limit=100)
        )
        assert events == []
        assert ladder.read_reviewer(ada_id)["scorecard_strikes"] == 0

        ladder.start(second["id"], ada_id)
        ladder.progress(second["id"], ada_id, 55, 61)
        below_the_floor = ladder.submit(second["id"], ada_id)
        assert_pace_2dp(below_the_floor["pace_dph"], 54.10)

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(ada_id, STAFFING_COORDINATOR, limit=100)
        )
        assert_scorecard_events(events, [("PACE_SHORTFALL", 1)])

        reviewer = ladder.read_reviewer(ada_id)
        assert reviewer["scorecard_strikes"] == 1
        assert_status(reviewer, "ENGAGED", "engagement_status")
        assert_pace_2dp(reviewer["pace_dph"], 54.55)

        for assignment_id in (first["id"], second["id"]):
            assert_money(
                ladder.read_assignment(assignment_id)["billable_amount_cents"],
                11715,
                "billable_amount_cents",
            )
