"""Cross-cutting layers: the three version guards, the cumulative rate and the roll-up counters."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    constants,
    factories,
    fixtures,
    make_candidate_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]

CANVASS_DAY = constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"]
CANDIDATE_REP_ONE = "u-cand-1"
CANDIDATE_REP_TWO = "u-cand-2"


class TestOptimisticConcurrencyOnEveryDeclaredGuard:
    """Each of the three version fields rejects the value read one step too early."""

    def test_stale_audit_batch_and_contest_versions_are_each_refused_then_accepted(self):
        """PRD §2.6: "**Creating an audit round** (`POST /audits/{id}/rounds`) requires
        `expected_audit_version` matching the target `Audit`'s current `version`. ... The
        mismatch is rejected with `ERR_STALE_AUDIT_VERSION` (HTTP 412)." §2.6: "**Retrieving a
        drawn batch from secure storage** (`POST /audit-batches/{id}/retrieve`) requires
        `expected_ballot_batch_version` matching the referenced `BallotBatch`'s current
        `version`. ... The mismatch is rejected with `ERR_STALE_BALLOT_BATCH_VERSION` (HTTP
        412)". §2.6: "**Filing a recount** (`POST /recounts`) requires `expected_contest_version`
        matching the target `Contest`'s current `version`. A contest legitimately supports more
        than one recount as long as the batch scopes do not overlap, so a repeat filing is
        valid on its own; a stale value means the requester priced the deposit and judged the
        margin from superseded canvass totals". §3.8: "Two partial recounts over disjoint sets
        of batches are, by contrast, perfectly legal, which is exactly why the version guard of
        §2.6 is needed to catch a filing priced from superseded totals."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_is_rejected_on_each_declared_concurrency_rule
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]
        canvassed_contest_version = scenario["contest"]["version"]
        planned = fixtures.create_audit(contest_id)
        version_at_planning = planned["version"]
        seeded = fixtures.seed_audit(planned["id"])
        batches_before_the_round = fixtures.list_batches(contest_id)
        third_batch_before = fixtures.batch_by_label(batches_before_the_round, "B-003")
        version_before_authorization = third_batch_before["version"]
        first_batch = fixtures.batch_by_label(batches_before_the_round, "B-001")
        second_batch = fixtures.batch_by_label(batches_before_the_round, "B-002")
        assert canvassed_contest_version == 2
        assert version_at_planning == 1
        assert seeded["version"] == 2
        assert version_before_authorization == 1

        validate_error(
            api_client.create_audit_round(
                planned["id"],
                factories.create_audit_round_payload(version_at_planning),
                AUDIT_MANAGER,
            ),
            ApiErrorId.ERR_STALE_AUDIT_VERSION.value,
            412,
        )

        audit_after_refusal = fixtures.read_audit(planned["id"])
        assert audit_after_refusal["status"] == "SEEDED"
        assert audit_after_refusal["version"] == 2

        round_one = validate_success(
            api_client.create_audit_round(
                planned["id"],
                factories.create_audit_round_payload(seeded["version"]),
                AUDIT_MANAGER,
            ),
            201,
        )
        assertions.assert_audit_round(round_one)
        assert fixtures.read_audit(planned["id"])["version"] == 3

        drawn_rows = sorted(
            fixtures.list_audit_batches(round_one["id"]),
            key=lambda row: row["selection_index"],
        )
        first_drawn = drawn_rows[0]
        third_batch_after = fixtures.read_batch(first_drawn["ballot_batch_id"])
        assert third_batch_after["batch_label"] == "B-003"

        validate_error(
            api_client.retrieve_audit_batch(
                first_drawn["id"],
                factories.retrieve_audit_batch_payload(
                    version_before_authorization,
                    third_batch_after["current_seal_number"],
                ),
                CUSTODY_OFFICER,
            ),
            ApiErrorId.ERR_STALE_BALLOT_BATCH_VERSION.value,
            412,
        )

        assert third_batch_after["version"] == 2
        retrieved = fixtures.retrieve_batch(
            first_drawn["id"],
            third_batch_after["id"],
            third_batch_after["current_seal_number"],
        )
        assert retrieved["retrieval_status"] == "RETRIEVED"
        assert fixtures.read_batch(third_batch_after["id"])["version"] == 3

        representative = make_candidate_representative_headers(CANDIDATE_REP_ONE)
        first_recount = validate_success(
            api_client.create_recount(
                factories.create_recount_payload(
                    contest_id,
                    canvassed_contest_version,
                    scope="PARTIAL_BATCHES",
                    scope_batch_ids=[first_batch["id"]],
                    requested_by_candidate_name="BRENNAN",
                ),
                representative,
            ),
            201,
        )
        assertions.assert_recount(first_recount)

        validate_error(
            api_client.create_recount(
                factories.create_recount_payload(
                    contest_id,
                    canvassed_contest_version,
                    scope="PARTIAL_BATCHES",
                    scope_batch_ids=[second_batch["id"]],
                    requested_by_candidate_name="BRENNAN",
                ),
                representative,
            ),
            ApiErrorId.ERR_STALE_CONTEST_VERSION.value,
            412,
        )

        re_read = validate_success(api_client.get_contest(contest_id, representative))
        assert re_read["version"] == 3
        second_recount = validate_success(
            api_client.create_recount(
                factories.create_recount_payload(
                    contest_id,
                    re_read["version"],
                    scope="PARTIAL_BATCHES",
                    scope_batch_ids=[second_batch["id"]],
                    requested_by_candidate_name="BRENNAN",
                ),
                representative,
            ),
            201,
        )
        assert second_recount["status"] == "REQUESTED"
        assert second_recount["scope_batch_ids"] == [second_batch["id"]]
        _, meta = validate_paginated(
            api_client.list_recounts(
                DIRECTOR, params={"contest_id": contest_id, "limit": 100}
            )
        )
        assert meta["total_count"] == 2
        assert fixtures.read_contest(contest_id)["open_recount_count"] == 2


class TestCumulativeThresholdOverTheRound:
    """Neither batch escalates alone; together they land exactly on 0.0050."""

    def test_the_second_submit_crosses_the_inclusive_threshold_on_the_round_denominator(self):
        """PRD §3.5: "Under `NET_MARGIN_SHIFT` — the variant of risk-limiting and
        fixed-percentage audits — `round_measure` is the absolute value of
        `cumulative_net_error_votes` divided by `counted_ballots`, rounded half up to four
        decimal places. It escalates when that value is greater than or equal to 0.0050". §3.5:
        "In both cases the comparison is inclusive, so a measure landing exactly on its
        threshold escalates." §3.5: "When the recomputed measure reaches the applicable
        escalation threshold the round moves from `TALLYING` to `REVIEW_REQUIRED`, which drives
        the audit from `TALLYING` to `DISCREPANCY_REVIEW` and recomputes the audit's
        `discrepancy_measure` and timeline fields, which in turn sets the election's
        `certification_risk_flag` to true."

        Design: Corner/cross_cutting_complexity_layers/cumulative_threshold_is_evaluated_over_the_round_not_the_batch
        """
        scenario = fixtures.setup_round_one_with_checked_out_batch()
        team_id = scenario["team"]["id"]
        round_id = scenario["round"]["id"]
        audit_id = scenario["audit"]["id"]
        election_id = scenario["election"]["id"]
        second_drawn = scenario["audit_batches"][1]
        second_physical = fixtures.read_batch(second_drawn["ballot_batch_id"])
        fixtures.retrieve_batch(
            second_drawn["id"],
            second_physical["id"],
            second_physical["current_seal_number"],
        )

        first_tally = fixtures.open_manual_tally(
            scenario["target_audit_batch"]["id"],
            team_id,
            session_start_at=CANVASS_DAY,
            session_end_at="2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 523, "BRENNAN": 477},
        )
        first_submitted = fixtures.submit_manual_tally(first_tally["id"], team_id)

        assert first_submitted["net_error_votes"] == 4
        round_after_one = fixtures.read_audit_round(round_id)
        assert round_after_one["counted_ballots"] == 1000
        assert round_after_one["cumulative_net_error_votes"] == 4
        assert round_after_one["round_measure"] == pytest.approx(0.0040, abs=0.00005)
        assert round_after_one["status"] == "TALLYING"
        assert fixtures.read_audit(audit_id)["status"] == "TALLYING"
        assert fixtures.read_election(election_id)["certification_risk_flag"] is False

        second_tally = fixtures.open_manual_tally(
            second_drawn["id"],
            team_id,
            session_start_at="2026-11-05T11:00:00Z",
            session_end_at="2026-11-05T13:00:00Z",
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478},
        )
        second_submitted = fixtures.submit_manual_tally(second_tally["id"], team_id)

        assert second_submitted["net_error_votes"] == 6
        round_after_two = fixtures.read_audit_round(round_id)
        assert round_after_two["cumulative_net_error_votes"] == 10
        assert round_after_two["counted_ballots"] == 2000
        assert round_after_two["round_measure"] == pytest.approx(0.0050, abs=0.00005)
        assertions.assert_four_decimal_places(
            round_after_two["round_measure"], "round_measure"
        )
        assert round_after_two["status"] == "REVIEW_REQUIRED"
        assert round_after_two["discrepancy_count"] == 2
        audit = fixtures.read_audit(audit_id)
        assert audit["status"] == "DISCREPANCY_REVIEW"
        assert audit["discrepancy_measure"] == pytest.approx(0.0050, abs=0.00005)
        assert audit["counted_ballots"] == 2000
        assert audit["cumulative_net_error_votes"] == 10
        assert fixtures.read_election(election_id)["certification_risk_flag"] is True
        findings, meta = validate_paginated(
            api_client.list_discrepancies(
                AUDIT_MANAGER, params={"status": "OPEN", "limit": 100}
            )
        )
        assert meta["total_count"] == 2
        for finding in findings:
            assertions.assert_discrepancy(finding)
        assert sorted(finding["magnitude_votes"] for finding in findings) == [4, 6]


class TestRollUpCountersReconcile:
    """Two filings, two terminations, and every counter lands back on zero."""

    def test_a_withdrawal_a_denial_and_two_terminations_return_the_counters_to_zero(self):
        """PRD §3.8: "Filing increases the contest's `open_recount_count` by one, which rolls up
        into the election's `open_recount_count`." §3.8: "Either way `status` becomes
        `WITHDRAWN` and the contest's `open_recount_count` is decreased by one." §3.8: "`status`
        becomes `DENIED` and the contest's `open_recount_count` is decreased by one." §3.3:
        "Planning also increases the election's `open_audit_count` by one." §3.3: "The election's
        `open_audit_count` is decreased by one, its `certification_risk_flag` re-derived, and
        the audit's `version` incremented by one."

        Design: Corner/cross_cutting_complexity_layers/derived_counters_reconcile_after_create_change_and_removal
        """
        # C2 is registered before C1 is canvassed: PRD §3.1 requires the election to
        # still be `OPEN` when a canvass is recorded, and the election cascades out of
        # `OPEN` as soon as every one of its contests is `CANVASSED`.
        scenario = fixtures.setup_canvassed_contest(
            sibling_contests=[
                {
                    "contest_label": "C2",
                    "office_name": "State Treasurer",
                    "candidate_names": ["CHEN", "DAVIS"],
                    "ballots_cast": 2000,
                    "cvr_available": False,
                }
            ]
        )
        election_id = scenario["election"]["id"]
        first_contest_id = scenario["contest"]["id"]
        second_contest = scenario["sibling_contests"][0]
        fixtures.canvass_contest(
            second_contest["id"], reported_votes={"CHEN": 1050, "DAVIS": 950}
        )
        second_contest_id = second_contest["id"]
        before = fixtures.read_election(election_id)
        assert before["open_recount_count"] == 0
        assert before["open_audit_count"] == 0

        first_recount = fixtures.file_recount(
            first_contest_id,
            requester_user_id=CANDIDATE_REP_ONE,
            requested_by_candidate_name="BRENNAN",
        )
        second_recount = fixtures.file_recount(
            second_contest_id,
            requester_user_id=CANDIDATE_REP_TWO,
            requested_by_candidate_name="DAVIS",
        )

        assert fixtures.read_election(election_id)["open_recount_count"] == 2
        assert fixtures.read_contest(first_contest_id)["open_recount_count"] == 1
        assert fixtures.read_contest(second_contest_id)["open_recount_count"] == 1

        withdrawn = validate_success(
            api_client.withdraw_recount(
                first_recount["id"],
                {"reason": "Margin accepted"},
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            )
        )
        denied = validate_success(
            api_client.deny_recount(
                second_recount["id"],
                {"denial_reason": "Filed by an unauthorised representative"},
                DIRECTOR,
            )
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Filed by an unauthorised representative"
        assert denied["actual_cost_cents"] == 0
        assert fixtures.read_election(election_id)["open_recount_count"] == 0
        assert fixtures.read_contest(first_contest_id)["open_recount_count"] == 0
        assert fixtures.read_contest(second_contest_id)["open_recount_count"] == 0

        risk_limiting = fixtures.create_audit(first_contest_id)
        fixed_percentage = validate_success(
            api_client.create_audit(
                {
                    "contest_id": first_contest_id,
                    "audit_type": "FIXED_PERCENTAGE",
                    "fixed_percentage_pct": 5,
                },
                AUDIT_MANAGER,
            ),
            201,
        )
        assert fixtures.read_election(election_id)["open_audit_count"] == 2

        fixtures.terminate_audit(risk_limiting["id"], terminated_reason="Superseded")
        assert fixtures.read_election(election_id)["open_audit_count"] == 1

        fixtures.terminate_audit(fixed_percentage["id"], terminated_reason="Superseded")

        final = fixtures.read_election(election_id)
        assert final["open_audit_count"] == 0
        assert final["open_recount_count"] == 0
        assert final["status"] == "CANVASSED"
        assert final["certification_risk_flag"] is False
        assertions.assert_election(final)
