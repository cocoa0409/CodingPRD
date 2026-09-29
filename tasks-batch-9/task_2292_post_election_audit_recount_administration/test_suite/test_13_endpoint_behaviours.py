"""Endpoint behaviours: partial amendment, guarded actions, bulk atomicity and public reads."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    constants,
    factories,
    fixtures,
    get_success_data,
    make_candidate_representative_headers,
    make_observer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]

CANVASS_DAY = constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"]
AUDIT_SEED = constants.TEST_DEFAULTS["AUDIT_SEED"]
AMENDED_NAME = "2026 General Election (amended)"
CANDIDATE_REP_ONE = "u-cand-1"
FULL_DRAW_ORDER = ["B-003", "B-004", "B-005", "B-001", "B-002", "B-006"]


class TestElectionAmendment:
    """A name-only amendment touches nothing derived; a deadline amendment rebases everything."""

    def test_the_deadline_amendment_alone_reprojects_the_audit_and_the_window(self):
        """PRD §3.1: "While the election is not yet certified, the director may amend its
        `election_name`, its `certification_deadline_at`, or both. Because the statutory deadline
        is the reference point of every projection, amending it re-runs the certification
        timeline projection for every audit of the election, and re-derives the election's own
        `effective_certification_deadline_at`, `contest_window_ends_at` and `timeline_status`."

        Design: Corner/endpoints/election_patch_updates_only_the_supplied_fields_and_rebases_the_timeline
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        election_id = scenario["election"]["id"]
        audit_id = scenario["audit"]["id"]

        renamed = validate_success(
            api_client.patch_election(
                election_id, {"election_name": AMENDED_NAME}, DIRECTOR
            )
        )

        assert renamed["election_name"] == AMENDED_NAME
        assertions.assert_same_instant(
            renamed["certification_deadline_at"],
            "2026-11-24T17:00:00Z",
            "certification_deadline_at",
        )
        assertions.assert_same_instant(
            renamed["contest_window_ends_at"],
            "2026-12-04T17:00:00Z",
            "contest_window_ends_at",
        )
        assert fixtures.read_audit(audit_id)["slack_hours"] == pytest.approx(
            416.00, abs=0.005
        )

        rescheduled = validate_success(
            api_client.patch_election(
                election_id, {"certification_deadline_at": "2026-11-30T17:00:00Z"}, DIRECTOR
            )
        )

        assert rescheduled["election_name"] == AMENDED_NAME
        assertions.assert_same_instant(
            rescheduled["certification_deadline_at"],
            "2026-11-30T17:00:00Z",
            "certification_deadline_at",
        )
        assertions.assert_same_instant(
            rescheduled["contest_window_ends_at"],
            "2026-12-10T17:00:00Z",
            "contest_window_ends_at",
        )
        assert rescheduled["timeline_status"] == "ON_TRACK"
        audit = fixtures.read_audit(audit_id)
        assertions.assert_same_instant(
            audit["projected_completion_at"],
            "2026-11-07T09:00:00Z",
            "projected_completion_at",
        )
        assert audit["slack_hours"] == pytest.approx(560.00, abs=0.005)
        assert audit["effective_slack_hours"] == pytest.approx(560.00, abs=0.005)
        assert audit["extension_days_granted"] == 0
        assert audit["status"] == "SAMPLING"
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == "SELECTED"


class TestTeamDisbandDependsOnItsCounts:
    """The blocking condition lives on the tally, and the refusal is reported there."""

    def test_a_draft_count_blocks_the_disband_until_it_is_submitted(self):
        """PRD §3.4: "A `READY` team may be disbanded once no hand tally of that team is `DRAFT`
        or `PENDING_ADJUDICATION`; a `FORMING` team may be disbanded only when no hand tally
        references it at all. In both cases the blocking condition is reported against the
        blocking tally as an invalid tally state."

        Design: Corner/endpoints/team_disband_is_refused_while_a_draft_count_is_open
        """
        scenario = fixtures.setup_draft_tally()
        team_id = scenario["team"]["id"]
        tally_id = scenario["manual_tally"]["id"]

        blocked = api_client.disband_tally_team(team_id, DIRECTOR)

        validate_error(blocked, ApiErrorId.ERR_INVALID_TALLY_STATE.value, 409)
        team = fixtures.read_tally_team(team_id)
        assert team["status"] == "READY"
        assert team["is_bipartisan"] is True
        assert team["version"] == 2

        submitted = fixtures.submit_manual_tally(tally_id, team_id)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["net_error_votes"] == 0
        _, meta = validate_paginated(
            api_client.list_discrepancies(
                AUDIT_MANAGER, params={"manual_tally_id": tally_id, "limit": 10}
            )
        )
        assert meta["total_count"] == 0

        disbanded = validate_success(api_client.disband_tally_team(team_id, DIRECTOR))

        assertions.assert_tally_team(disbanded)
        assert disbanded["status"] == "DISBANDED"
        assert disbanded["version"] == 3
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == "TALLYING"
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "TALLYING"


class TestBulkRegistrationAtomicity:
    """A label repeated inside the payload rejects the whole call, committing nothing."""

    def test_a_repeated_label_rejects_the_bulk_and_the_single_endpoint_agrees(self):
        """PRD §3.2: "The bulk call is strictly all-or-nothing: if any entry fails any check — an
        invalid shape, a candidate key that does not match the contest, a label that duplicates
        an existing batch, a label repeated inside the payload itself, ... — the whole call is
        rejected and nothing is created." §3.2: "a repeated `batch_label` within the contest is
        refused as a duplicate batch label".

        Design: Corner/endpoints/bulk_batch_create_is_all_or_nothing_on_a_repeated_label
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election(jurisdiction_code="ST-09")
        contest = fixtures.create_contest(election["id"])
        machine_votes = {"ALVAREZ": 525, "BRENNAN": 475}
        repeated_label = [
            factories.batch_line("B-001", 1000, machine_votes, "SEAL-001"),
            factories.batch_line("B-002", 1000, machine_votes, "SEAL-002"),
            factories.batch_line(
                "B-001", 1000, machine_votes, "SEAL-003", storage_location_code="VAULT-2"
            ),
        ]

        refused_bulk = api_client.bulk_create_ballot_batches(
            factories.bulk_ballot_batches_payload(
                election["id"], contest["id"], repeated_label
            ),
            CUSTODY_OFFICER,
        )

        validate_error(refused_bulk, ApiErrorId.ERR_DUPLICATE_BATCH_LABEL.value, 409)
        _, empty_meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER, params={"contest_id": contest["id"], "limit": 100}
            )
        )
        assert empty_meta["total_count"] == 0

        accepted = get_success_data(
            api_client.bulk_create_ballot_batches(
                factories.bulk_ballot_batches_payload(
                    election["id"], contest["id"], repeated_label[:2]
                ),
                CUSTODY_OFFICER,
            )
        )
        assert accepted["created_count"] == 2
        assert accepted["batch_labels"] == ["B-001", "B-002"]

        clashing_single = api_client.create_ballot_batch(
            factories.create_ballot_batch_payload(
                election["id"],
                contest["id"],
                batch_label="B-002",
                current_seal_number="SEAL-009",
            ),
            CUSTODY_OFFICER,
        )
        validate_error(clashing_single, ApiErrorId.ERR_DUPLICATE_BATCH_LABEL.value, 409)

        third = validate_success(
            api_client.create_ballot_batch(
                factories.create_ballot_batch_payload(
                    election["id"],
                    contest["id"],
                    batch_label="B-003",
                    current_seal_number="SEAL-003",
                ),
                CUSTODY_OFFICER,
            ),
            201,
        )

        assert third["batch_label"] == "B-003"
        rows, meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER, params={"contest_id": contest["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 3
        assert [row["batch_label"] for row in rows] == ["B-001", "B-002", "B-003"]
        for row in rows:
            assert row["custody_status"] == "SEALED"


class TestPartialRecountScope:
    """scope_batch_ids is tested against the recounted contest, not against mere existence."""

    def test_a_sibling_contest_batch_is_refused_and_two_own_batches_price_at_130000(self):
        """PRD §2.9: "Every batch named in a partial recount's `scope_batch_ids` belongs to the
        recounted contest — otherwise `ERR_BATCH_NOT_IN_CONTEST`." §3.8: "for a
        `PARTIAL_BATCHES` recount, `ballots_in_scope` is the sum of `ballot_count` over the
        batches named in `scope_batch_ids` and the rate is 40 cents per ballot".

        Design: Corner/endpoints/partial_recount_scope_must_name_batches_of_its_own_contest
        """
        scenario = fixtures.setup_election_with_contest_and_batches()
        election_id = scenario["election"]["id"]
        sibling = fixtures.create_contest(
            election_id,
            contest_label="C2",
            office_name="State Treasurer",
            candidate_names=["CHEN", "DAVIS"],
            ballots_cast=2000,
        )
        sibling_batches = fixtures.create_batches(
            election_id,
            sibling["id"],
            [
                factories.batch_line(
                    "B-101", 1000, {"CHEN": 600, "DAVIS": 400}, "SEAL-101", "VAULT-2"
                ),
                factories.batch_line(
                    "B-102", 1000, {"CHEN": 600, "DAVIS": 400}, "SEAL-102", "VAULT-2"
                ),
            ],
        )
        recounted = fixtures.canvass_contest(scenario["contest"]["id"])
        fixtures.canvass_contest(sibling["id"], reported_votes={"CHEN": 1200, "DAVIS": 800})
        assert recounted["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        own_batches = fixtures.list_batches(recounted["id"])

        foreign_scope = api_client.create_recount(
            factories.create_recount_payload(
                recounted["id"],
                recounted["version"],
                scope="PARTIAL_BATCHES",
                scope_batch_ids=[sibling_batches[0]["id"]],
                requested_by_candidate_name="BRENNAN",
            ),
            make_candidate_representative_headers(CANDIDATE_REP_ONE),
        )

        validate_error(foreign_scope, ApiErrorId.ERR_BATCH_NOT_IN_CONTEST.value, 422)
        _, empty_meta = validate_paginated(
            api_client.list_recounts(
                DIRECTOR, params={"contest_id": recounted["id"], "limit": 10}
            )
        )
        assert empty_meta["total_count"] == 0

        filed = validate_success(
            api_client.create_recount(
                factories.create_recount_payload(
                    recounted["id"],
                    recounted["version"],
                    scope="PARTIAL_BATCHES",
                    scope_batch_ids=[
                        fixtures.batch_by_label(own_batches, "B-003")["id"],
                        fixtures.batch_by_label(own_batches, "B-004")["id"],
                    ],
                    requested_by_candidate_name="BRENNAN",
                ),
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            ),
            201,
        )

        assertions.assert_recount(filed)
        assert filed["scope"] == "PARTIAL_BATCHES"
        assert filed["required_deposit_cents"] == 130000
        assert filed["status"] == "REQUESTED"
        assert filed["deposit_status"] == "PENDING"
        assert filed["deposit_paid_cents"] == 0
        assert fixtures.read_contest(recounted["id"])["open_recount_count"] == 1
        assert fixtures.read_contest(sibling["id"])["open_recount_count"] == 0


class TestPublicReportForAnObserver:
    """A terminated audit that counted nothing still publishes its reproducible draw."""

    def test_the_credentialed_observer_reads_the_seed_and_the_selection(self):
        """PRD §3.9: "The elections director, the audit manager and a candidate representative
        may read the report without a credential. An observer reads it through a credential: the
        identity supplied must resolve to a stored credential, that credential must be
        `ACTIVE` ... and the clock must be inside the credential's access window". §3.4: "On
        success `status` becomes `TERMINATED`, the `terminated_reason` is recorded,
        `public_report_published` becomes true, every non-terminal round becomes `SUPERSEDED`".

        Design: Corner/endpoints/public_report_reproduces_the_draw_for_a_credentialed_observer
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        credential = fixtures.create_observer_credential(
            scenario["election"]["id"],
            access_start_at="2026-11-05T08:00:00Z",
            access_end_at="2026-11-06T00:00:00Z",
        )
        terminated = fixtures.terminate_audit(scenario["audit"]["id"])
        assert terminated["public_report_published"] is True

        report = validate_success(
            api_client.get_audit_public_report(
                scenario["audit"]["id"], make_observer_headers(credential["id"])
            )
        )

        assert report["status"] == "TERMINATED"
        assert report["published"] is True
        assert report["contest_label"] == "C1"
        assert report["random_seed"] == AUDIT_SEED
        assert report["selection_sequence"] == ["B-003", "B-004", "B-005"]
        assert report["counted_ballots"] == 0
        assert report["discrepancy_measure"] == pytest.approx(0.0, abs=0.00005)
        assert report["discrepancy_count"] == 0
        assert report["escalation_level"] == 0
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == "SUPERSEDED"
        election = fixtures.read_election(scenario["election"]["id"])
        assert election["open_audit_count"] == 0
        assert election["certification_risk_flag"] is False


class TestPublicReportPublicationGate:
    """The gate is the audit's publication state, and it refuses every caller alike."""

    def test_a_sampling_audit_refuses_both_the_observer_and_its_own_manager(self):
        """PRD §3.9: "A report requested before the audit has published anything is refused
        because the public report is not published, whoever asks." §3.4: "Once an audit is closed
        or terminated its `public_report_published` flag is true and its report becomes
        readable."

        Design: Corner/endpoints/public_report_is_withheld_until_the_audit_closes_or_terminates
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        audit_id = scenario["audit"]["id"]
        credential = fixtures.create_observer_credential(scenario["election"]["id"])
        observer_headers = make_observer_headers(credential["id"])

        for response in (
            api_client.get_audit_public_report(audit_id, observer_headers),
            api_client.get_audit_public_report(audit_id, AUDIT_MANAGER),
        ):
            validate_error(
                response, ApiErrorId.ERR_PUBLIC_REPORT_NOT_PUBLISHED.value, 409
            )
        unpublished = fixtures.read_audit(audit_id)
        assert unpublished["status"] == "SAMPLING"
        assert unpublished["public_report_published"] is False

        fixtures.terminate_audit(audit_id, terminated_reason="Administrative order")
        report = validate_success(
            api_client.get_audit_public_report(audit_id, observer_headers)
        )

        assert report["published"] is True
        assert report["status"] == "TERMINATED"
        unchanged = fixtures.read_observer_credential(credential["id"])
        assert unchanged["status"] == "ACTIVE"
        assert unchanged["version"] == 1


class TestRoundDrawBoundedByThePool:
    """The override is bounded by the pool at both ends, and the drained pool refuses again."""

    def test_seven_is_refused_six_drains_the_pool_and_the_next_round_is_refused(self):
        """PRD §2.9: "The eligible pool is non-empty and large enough for the requested round —
        otherwise `ERR_NO_UNSAMPLED_BATCHES`." §3.4: "The eligible pool is every ballot batch of
        the audit's contest that is not `QUARANTINED` and that has not already been drawn by a
        non-superseded drawn-batch row of this audit, sorted by `batch_label` in ascending
        order. A generator state is initialised as the `random_seed` interpreted as a base-ten
        integer, plus the quantity of one less than `round_number` multiplied by the round stride
        7919, all reduced modulo 2147483648. Then, once for each batch to be drawn, in order: the
        state is advanced first — multiplied by 1103515245, increased by 12345, and reduced
        modulo 2147483648 — and only then used to draw, by taking the advanced state modulo the
        number of batches still remaining in the pool to obtain a zero-based index, and removing
        the batch at that index from the pool."

        Design: Corner/endpoints/round_creation_needs_a_pool_large_enough_and_refuses_once_it_is_drained
        """
        scenario = fixtures.setup_canvassed_contest()
        team_id = fixtures.create_bipartisan_team(scenario["election"]["id"])["id"]
        audit = fixtures.setup_seeded_audit(scenario["contest"]["id"])
        assert audit["planned_sample_size"] == 3

        too_large = api_client.create_audit_round(
            audit["id"],
            {"expected_audit_version": audit["version"], "sample_size_batches": 7},
            AUDIT_MANAGER,
        )

        validate_error(too_large, ApiErrorId.ERR_NO_UNSAMPLED_BATCHES.value, 409)
        assert fixtures.read_audit(audit["id"])["status"] == "SEEDED"

        whole_pool = fixtures.open_round(audit["id"], sample_size_batches=6)

        assert whole_pool["sample_size_batches"] == 6
        assert whole_pool["selection_sequence"] == FULL_DRAW_ORDER
        drawn_rows, meta = validate_paginated(
            api_client.list_audit_batches(
                CUSTODY_OFFICER,
                params={"audit_round_id": whole_pool["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 6
        assert sorted(row["selection_index"] for row in drawn_rows) == [0, 1, 2, 3, 4, 5]

        first_drawn = next(row for row in drawn_rows if row["selection_index"] == 0)
        first_physical = fixtures.read_batch(first_drawn["ballot_batch_id"])
        assert first_physical["batch_label"] == "B-003"
        fixtures.retrieve_batch(
            first_drawn["id"], first_physical["id"], first_physical["current_seal_number"]
        )
        tally = fixtures.open_manual_tally(
            first_drawn["id"],
            team_id,
            session_start_at=CANVASS_DAY,
            session_end_at="2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478},
        )
        submitted = fixtures.submit_manual_tally(tally["id"], team_id)
        assert submitted["status"] == "SUBMITTED"
        audit_round = fixtures.read_audit_round(whole_pool["id"])
        assert audit_round["round_measure"] == pytest.approx(0.0060, abs=0.00005)
        assert audit_round["status"] == "REVIEW_REQUIRED"
        under_review = fixtures.read_audit(audit["id"])
        assert under_review["status"] == "DISCREPANCY_REVIEW"

        drained = api_client.create_audit_round(
            audit["id"],
            {"expected_audit_version": under_review["version"]},
            AUDIT_MANAGER,
        )

        validate_error(drained, ApiErrorId.ERR_NO_UNSAMPLED_BATCHES.value, 409)
        _, rounds_meta = validate_paginated(
            api_client.list_audit_rounds(
                AUDIT_MANAGER, params={"audit_id": audit["id"], "limit": 10}
            )
        )
        assert rounds_meta["total_count"] == 1
