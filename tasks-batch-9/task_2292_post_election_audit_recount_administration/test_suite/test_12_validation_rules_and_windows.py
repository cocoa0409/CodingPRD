"""Validation rules: seal attestation, accounting identities, windows and dependency order."""

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
    make_tally_team_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]

CANVASS_DAY = constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"]
REQUEST_DEADLINE = "2026-11-10T09:00:00Z"
CERTIFICATION_DEADLINE = "2026-11-24T17:00:00Z"
CANDIDATE_REP_ONE = "u-cand-1"
CANDIDATE_REP_TWO = "u-cand-2"
BOARD_ONE = constants.TEST_DEFAULTS["BOARD_DEM_USER_ID"]


class TestSealAttestation:
    """The seal rule reads one way going out of storage and the opposite coming back."""

    def test_a_wrong_seal_blocks_retrieval_and_a_reused_seal_blocks_the_reseal(self):
        """PRD §3.2: "the `observed_seal_number` must equal the batch's `current_seal_number`
        — a mismatch is refused as a seal-number mismatch". §3.2: "the `reseal_number` must
        differ from the batch's `current_seal_number`, since reapplying the same seal number
        would leave the log unable to distinguish one custody cycle from the next; reuse is
        refused as a seal-number mismatch."

        Design: Corner/validations/seal_number_must_match_on_check_out_and_must_differ_on_check_in
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        drawn = scenario["audit_batches"][0]
        physical = fixtures.read_batch(drawn["ballot_batch_id"])
        assert physical["batch_label"] == "B-003"
        assert physical["current_seal_number"] == "SEAL-003"
        assert physical["custody_status"] == "SEALED"
        assert physical["version"] == 2

        wrong_seal = api_client.retrieve_audit_batch(
            drawn["id"],
            factories.retrieve_audit_batch_payload(physical["version"], "SEAL-999"),
            CUSTODY_OFFICER,
        )
        validate_error(wrong_seal, ApiErrorId.ERR_SEAL_NUMBER_MISMATCH.value, 409)
        still_sealed = fixtures.read_batch(physical["id"])
        assert still_sealed["custody_status"] == "SEALED"
        assert still_sealed["version"] == 2

        fixtures.retrieve_batch(drawn["id"], physical["id"], "SEAL-003")
        reused_seal = api_client.return_audit_batch(
            drawn["id"], {"reseal_number": "SEAL-003"}, CUSTODY_OFFICER
        )
        validate_error(reused_seal, ApiErrorId.ERR_SEAL_NUMBER_MISMATCH.value, 409)
        assert fixtures.read_batch(physical["id"])["custody_status"] == "CHECKED_OUT"

        returned = fixtures.return_batch(
            drawn["id"], "SEAL-003R", note="Resealed in ROOM-A"
        )

        assert returned["retrieval_status"] == "RETURNED"
        assert returned["tally_status"] == "NOT_STARTED"
        resealed = fixtures.read_batch(physical["id"])
        assert resealed["custody_status"] == "RESEALED"
        assert resealed["current_seal_number"] == "SEAL-003R"
        assert resealed["open_checkout_count"] == 0
        assert resealed["checkout_cycle_count"] == 1
        assertions.assert_same_instant(
            resealed["last_resealed_at"], CANVASS_DAY, "last_resealed_at"
        )
        events, meta = validate_paginated(
            api_client.list_ballot_batch_custody_events(
                physical["id"], CUSTODY_OFFICER, params={"limit": 100}
            )
        )
        assert meta["total_count"] == 4
        assertions.assert_custody_log_ordered(events)
        check_in = events[3]
        assert check_in["sequence_no"] == 4
        assert check_in["event_type"] == "CHECK_IN"
        assert check_in["seal_number_before"] == "SEAL-003"
        assert check_in["seal_number_after"] == "SEAL-003R"
        assert check_in["note"] == "Resealed in ROOM-A"


class TestSubmissionBallotAccounting:
    """The count must close against the batch before any error figure is computed."""

    def test_a_995_ballot_sheet_is_refused_and_the_corrected_sheet_submits(self):
        """PRD §3.5: "the sum of `counted_votes`, plus `ambiguous_ballot_count`, plus
        `no_vote_count`, must equal the drawn batch's `ballot_count` exactly, or the submission
        is refused for a ballot-count mismatch". §3.5: "`relative_taint` is `net_error_votes`
        multiplied by the contest's `margin_votes`, divided by twice the drawn batch's
        `ballot_count`, rounded half up to four decimal places."

        Design: Corner/validations/submit_requires_exact_ballot_accounting_then_succeeds_after_correction
        """
        scenario = fixtures.setup_draft_tally(
            counted_votes={"ALVAREZ": 520, "BRENNAN": 475}
        )
        tally_id = scenario["manual_tally"]["id"]
        team_id = scenario["team"]["id"]
        lead_headers = make_tally_team_lead_headers(team_id)

        refused = api_client.submit_manual_tally(tally_id, lead_headers)

        validate_error(refused, ApiErrorId.ERR_TALLY_BALLOT_COUNT_MISMATCH.value, 422)
        still_draft = fixtures.read_manual_tally(tally_id)
        assert still_draft["status"] == "DRAFT"
        assert still_draft["net_error_votes"] is None
        assert still_draft["version"] == 1

        corrected = validate_success(
            api_client.patch_manual_tally(
                tally_id, {"counted_votes": {"ALVAREZ": 520, "BRENNAN": 480}}, lead_headers
            )
        )
        assert corrected["version"] == 2
        submitted = fixtures.submit_manual_tally(tally_id, team_id)

        assertions.assert_manual_tally(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["net_error_votes"] == 10
        assert submitted["relative_taint"] == pytest.approx(1.5000, abs=0.00005)
        assert submitted["machine_margin_votes"] == 50
        assert submitted["manual_margin_votes"] == 40
        assert submitted["submitted_by_user_id"] == team_id
        assertions.assert_ballot_accounting_identity(submitted, 1000)
        assert (
            fixtures.read_audit_batch(scenario["target_audit_batch"]["id"])["tally_status"]
            == "COUNTED"
        )
        findings, meta = validate_paginated(
            api_client.list_discrepancies(
                AUDIT_MANAGER, params={"manual_tally_id": tally_id, "limit": 10}
            )
        )
        assert meta["total_count"] == 1
        assert findings[0]["discrepancy_type"] == "OVERSTATEMENT"
        assert findings[0]["magnitude_votes"] == 10
        assert findings[0]["status"] == "OPEN"
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["round_measure"] == pytest.approx(0.0100, abs=0.00005)
        assert audit_round["status"] == "REVIEW_REQUIRED"
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "DISCREPANCY_REVIEW"
        assert fixtures.read_election(scenario["election"]["id"])[
            "certification_risk_flag"
        ] is True


class TestCertificationWaitsForEveryRecount:
    """An unfunded request still blocks certification; withdrawing it unblocks the same call."""

    def test_a_requested_recount_blocks_certification_until_it_is_withdrawn(self):
        """PRD §3.1: "Certification additionally requires ... that every recount of those
        contests has reached `COMPLETED`, `WITHDRAWN` or `DENIED`, failing which the request is
        refused for a non-terminal recount". §3.8: "When `deposit_status` is still `PENDING`
        nothing is charged and it stays `PENDING`. Either way `status` becomes `WITHDRAWN` and
        the contest's `open_recount_count` is decreased by one."

        Design: Corner/validations/certify_is_blocked_while_a_recount_is_live_and_allowed_once_withdrawn
        """
        scenario = fixtures.setup_canvassed_contest()
        election_id = scenario["election"]["id"]
        contest_id = scenario["contest"]["id"]
        recount = fixtures.file_recount(
            contest_id,
            requester_user_id=CANDIDATE_REP_ONE,
            requested_by_candidate_name="BRENNAN",
        )
        assert recount["status"] == "REQUESTED"
        assert recount["deposit_status"] == "PENDING"
        assert recount["required_deposit_cents"] == 200000

        blocked = api_client.certify_election(election_id, DIRECTOR)

        validate_error(blocked, ApiErrorId.ERR_RECOUNT_NOT_TERMINAL.value, 409)
        assert fixtures.read_election(election_id)["status"] == "CANVASSED"

        withdrawn = validate_success(
            api_client.withdraw_recount(
                recount["id"],
                {"reason": "Margin accepted"},
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["deposit_status"] == "PENDING"
        assert withdrawn["deposit_paid_cents"] == 0
        assert withdrawn["refunded_cents"] == 0
        assert withdrawn["forfeited_cents"] == 0
        assert withdrawn["admin_retained_cents"] == 0
        assert withdrawn["refund_variant"] == "NONE"
        assertions.assert_deposit_ledger_conserved(withdrawn)

        certified = validate_success(api_client.certify_election(election_id, DIRECTOR))

        assert certified["status"] == "CERTIFIED"
        assertions.assert_same_instant(
            certified["certified_at"], CANVASS_DAY, "certified_at"
        )
        contest = fixtures.read_contest(contest_id)
        assert contest["status"] == "CERTIFIED"
        assert contest["open_recount_count"] == 0


class TestRecountStartWaitsForTheElection:
    """A canvassed contest may file, but only a canvassed election may start."""

    def test_the_start_is_refused_until_the_sibling_contest_is_canvassed(self):
        """PRD §2.9: "Starting a recount requires the election to be `CANVASSED` and reports
        `ERR_ELECTION_NOT_CANVASSED` when it is not, because there the path entity (the
        recount) is itself in a legal state and only the election lags." §3.8: "The election
        must be `CANVASSED`, or the request is refused because the election is not canvassed".

        Design: Corner/validations/recount_start_requires_the_whole_election_to_be_canvassed
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election(jurisdiction_code="ST-07")
        first_contest = fixtures.create_contest(election["id"])
        second_contest = fixtures.create_contest(
            election["id"],
            contest_label="C2",
            office_name="State Treasurer",
            candidate_names=["CHEN", "DAVIS"],
            ballots_cast=3000,
        )
        canvassed = fixtures.canvass_contest(
            first_contest["id"], reported_votes={"ALVAREZ": 3010, "BRENNAN": 2990}
        )
        assert canvassed["margin_votes"] == 20
        assert canvassed["margin_pct"] == pytest.approx(0.3333, abs=0.00005)
        assert canvassed["automatic_recount_required"] is True
        assert fixtures.read_election(election["id"])["status"] == "OPEN"
        recount = fixtures.file_recount(
            first_contest["id"],
            requester_user_id="dir-1",
            role="ElectionsDirector",
            trigger_type="AUTOMATIC_MARGIN",
        )
        assert recount["deposit_status"] == "NOT_REQUIRED"
        assert recount["required_deposit_cents"] == 0

        too_early = api_client.start_recount(recount["id"], DIRECTOR)

        validate_error(too_early, ApiErrorId.ERR_ELECTION_NOT_CANVASSED.value, 409)
        assert fixtures.read_recount(recount["id"])["status"] == "REQUESTED"

        fixtures.canvass_contest(
            second_contest["id"], reported_votes={"CHEN": 1575, "DAVIS": 1425}
        )
        started = validate_success(api_client.start_recount(recount["id"], DIRECTOR))

        assert started["status"] == "IN_PROGRESS"
        assert started["deposit_paid_cents"] == 0
        assert started["deposit_status"] == "NOT_REQUIRED"
        assert fixtures.read_election(election["id"])["status"] == "CANVASSED"


class TestRequestWindowBound:
    """The request window includes its last instant and excludes the next second."""

    def test_a_filing_at_the_deadline_is_accepted_and_one_second_later_is_refused(self):
        """PRD §2.9: "The clock is at or before the contest's `recount_request_deadline_at` —
        otherwise `ERR_RECOUNT_REQUEST_WINDOW_CLOSED`." §3.1: "The same step sets
        `recount_request_deadline_at` to five days after `canvassed_at`."

        Design: Corner/validations/candidate_request_window_closes_one_second_after_the_deadline
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]
        assertions.assert_same_instant(
            scenario["contest"]["recount_request_deadline_at"],
            REQUEST_DEADLINE,
            "recount_request_deadline_at",
        )
        fixtures.set_clock(REQUEST_DEADLINE)
        on_the_bound = fixtures.file_recount(
            contest_id,
            requester_user_id=CANDIDATE_REP_ONE,
            requested_by_candidate_name="BRENNAN",
        )
        assert on_the_bound["status"] == "REQUESTED"
        validate_success(
            api_client.withdraw_recount(
                on_the_bound["id"],
                {"reason": "Filed to preserve the window, then withdrawn"},
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            )
        )

        fixtures.set_clock("2026-11-10T09:00:01Z")
        contest = fixtures.read_contest(contest_id)
        one_second_late = api_client.create_recount(
            factories.create_recount_payload(
                contest_id,
                contest["version"],
                requested_by_candidate_name="BRENNAN",
            ),
            make_candidate_representative_headers(CANDIDATE_REP_ONE),
        )

        validate_error(
            one_second_late, ApiErrorId.ERR_RECOUNT_REQUEST_WINDOW_CLOSED.value, 409
        )
        rows, meta = validate_paginated(
            api_client.list_recounts(
                DIRECTOR, params={"contest_id": contest_id, "limit": 10}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "WITHDRAWN"
        final_contest = fixtures.read_contest(contest_id)
        assert final_contest["open_recount_count"] == 0
        assertions.assert_same_instant(
            final_contest["recount_request_deadline_at"],
            REQUEST_DEADLINE,
            "recount_request_deadline_at",
        )


class TestCertificationDeadlineBound:
    """The certification bound is strict: the deadline instant itself is too late."""

    def test_one_second_before_the_deadline_certifies_and_the_deadline_instant_does_not(self):
        """PRD §2.9: "The clock is strictly before the election's
        `effective_certification_deadline_at` — otherwise `ERR_CERTIFICATION_DEADLINE_PASSED`."
        §3.1: "the clock is strictly before the election's
        `effective_certification_deadline_at`, failing which the request is refused because the
        deadline has passed."

        Design: Corner/validations/certification_is_refused_at_the_deadline_instant_but_allowed_one_second_earlier
        """
        fixtures.set_clock(CANVASS_DAY)
        early_election = fixtures.create_election(jurisdiction_code="ST-10")
        early_contest = fixtures.create_contest(early_election["id"])
        fixtures.canvass_contest(early_contest["id"])
        late_election = fixtures.create_election(jurisdiction_code="ST-11")
        late_contest = fixtures.create_contest(late_election["id"])
        fixtures.canvass_contest(late_contest["id"])
        for election_id in (early_election["id"], late_election["id"]):
            assertions.assert_same_instant(
                fixtures.read_election(election_id)[
                    "effective_certification_deadline_at"
                ],
                CERTIFICATION_DEADLINE,
                "effective_certification_deadline_at",
            )

        fixtures.set_clock("2026-11-24T16:59:59Z")
        certified = validate_success(
            api_client.certify_election(early_election["id"], DIRECTOR)
        )
        fixtures.set_clock(CERTIFICATION_DEADLINE)
        refused = api_client.certify_election(late_election["id"], DIRECTOR)

        assert certified["status"] == "CERTIFIED"
        assertions.assert_same_instant(
            certified["certified_at"], "2026-11-24T16:59:59Z", "certified_at"
        )
        validate_error(
            refused, ApiErrorId.ERR_CERTIFICATION_DEADLINE_PASSED.value, 409
        )
        uncertified = fixtures.read_election(late_election["id"])
        assert uncertified["status"] == "CANVASSED"
        assert uncertified["certified_at"] is None
        assert uncertified["version"] == 2
        assert fixtures.read_contest(late_contest["id"])["status"] == "CANVASSED"
        assert fixtures.read_contest(early_contest["id"])["status"] == "CERTIFIED"


class TestAggregateBallotAccounting:
    """Each batch is legal on its own; only the running total against ballots_cast offends."""

    def test_the_bulk_call_is_all_or_nothing_and_the_exact_remainder_is_accepted(self):
        """PRD §3.2: "the sum of `ballot_count` over all batches of the contest must not exceed
        the contest's `ballots_cast`, or the registration is refused as exceeded ballot
        accounting". §3.2: "The bulk call is strictly all-or-nothing: if any entry fails any
        check — ... a total that would push the contest's batched ballots past `ballots_cast`
        ... — the whole call is rejected and nothing is created. When it succeeds it reports the
        `created_count`, the `batch_labels` it created and the corresponding `batch_ids`".

        Design: Corner/validations/batched_ballots_may_not_exceed_ballots_cast_in_aggregate
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election(jurisdiction_code="ST-08")
        contest = fixtures.create_contest(election["id"], ballots_cast=2500)
        three_thousand = [
            factories.batch_line(
                f"B-00{index}", 1000, {"ALVAREZ": 525, "BRENNAN": 475}, f"SEAL-00{index}"
            )
            for index in (1, 2, 3)
        ]

        over_in_bulk = api_client.bulk_create_ballot_batches(
            factories.bulk_ballot_batches_payload(
                election["id"], contest["id"], three_thousand
            ),
            CUSTODY_OFFICER,
        )

        validate_error(
            over_in_bulk, ApiErrorId.ERR_BALLOT_ACCOUNTING_EXCEEDED.value, 422
        )
        _, empty_meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER, params={"contest_id": contest["id"], "limit": 100}
            )
        )
        assert empty_meta["total_count"] == 0

        accepted_bulk = get_success_data(
            api_client.bulk_create_ballot_batches(
                factories.bulk_ballot_batches_payload(
                    election["id"], contest["id"], three_thousand[:2]
                ),
                CUSTODY_OFFICER,
            )
        )
        assert accepted_bulk["created_count"] == 2
        assert accepted_bulk["batch_labels"] == ["B-001", "B-002"]
        assert len(accepted_bulk["batch_ids"]) == 2

        over_singly = api_client.create_ballot_batch(
            factories.create_ballot_batch_payload(
                election["id"],
                contest["id"],
                batch_label="B-003",
                ballot_count=600,
                machine_votes={"ALVAREZ": 320, "BRENNAN": 280},
                current_seal_number="SEAL-003",
            ),
            CUSTODY_OFFICER,
        )
        validate_error(
            over_singly, ApiErrorId.ERR_BALLOT_ACCOUNTING_EXCEEDED.value, 422
        )

        exactly_full = validate_success(
            api_client.create_ballot_batch(
                factories.create_ballot_batch_payload(
                    election["id"],
                    contest["id"],
                    batch_label="B-003",
                    ballot_count=500,
                    machine_votes={"ALVAREZ": 260, "BRENNAN": 240},
                    current_seal_number="SEAL-003",
                ),
                CUSTODY_OFFICER,
            ),
            201,
        )

        assertions.assert_ballot_batch(exactly_full)
        assert exactly_full["batch_label"] == "B-003"
        assert exactly_full["ballot_count"] == 500
        assert exactly_full["custody_status"] == "SEALED"
        rows, meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER, params={"contest_id": contest["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 3
        assert [row["batch_label"] for row in rows] == ["B-001", "B-002", "B-003"]


class TestAuditConfigurationCoherence:
    """Which parameters are legal is decided by audit_type, not by the schema."""

    def test_three_incoherent_configurations_are_refused_and_the_coherent_one_is_planned(self):
        """PRD §3.3: "A risk-limiting or comparison audit requires a `risk_limit_alpha` that is
        exactly one of 0.10, 0.05 or 0.01 and must leave `fixed_percentage_pct` null; a
        fixed-percentage audit requires a `fixed_percentage_pct` greater than zero and no
        greater than one hundred and must leave `risk_limit_alpha` null. Any other combination
        is refused as an invalid audit configuration — a cross-field test that reads nothing
        beyond the request body. A comparison audit may additionally supply `prior_error_rate`
        ... which ... defaults to 0.10 when omitted."

        Design: Corner/validations/audit_parameters_must_match_the_audit_type
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]

        both_parameters = api_client.create_audit(
            {
                "contest_id": contest_id,
                "audit_type": "RISK_LIMITING",
                "risk_limit_alpha": 0.05,
                "fixed_percentage_pct": 5,
            },
            AUDIT_MANAGER,
        )
        alpha_on_a_fixed_audit = api_client.create_audit(
            {
                "contest_id": contest_id,
                "audit_type": "FIXED_PERCENTAGE",
                "fixed_percentage_pct": 5,
                "risk_limit_alpha": 0.05,
            },
            AUDIT_MANAGER,
        )
        missing_alpha = api_client.create_audit(
            {"contest_id": contest_id, "audit_type": "RISK_LIMITING"}, AUDIT_MANAGER
        )
        coherent = api_client.create_audit(
            {
                "contest_id": contest_id,
                "audit_type": "COMPARISON",
                "risk_limit_alpha": 0.05,
            },
            AUDIT_MANAGER,
        )

        validate_error(both_parameters, ApiErrorId.ERR_AUDIT_CONFIG_INVALID.value, 422)
        validate_error(
            alpha_on_a_fixed_audit, ApiErrorId.ERR_AUDIT_CONFIG_INVALID.value, 422
        )
        validate_error(missing_alpha, ApiErrorId.ERR_AUDIT_CONFIG_INVALID.value, 422)
        planned = validate_success(coherent, 201)
        assertions.assert_audit(planned)
        assert planned["prior_error_rate"] == pytest.approx(0.1, abs=0.00005)
        assert planned["planned_sample_size"] == 2
        assert planned["measure_variant"] == "MAX_RELATIVE_OVERSTATEMENT"
        assert planned["fixed_percentage_pct"] is None
        assert planned["status"] == "PLANNED"
        _, meta = validate_paginated(
            api_client.list_audits(
                AUDIT_MANAGER, params={"contest_id": contest_id, "limit": 10}
            )
        )
        assert meta["total_count"] == 1
        assert fixtures.read_election(scenario["election"]["id"])["open_audit_count"] == 1


class TestClosePreconditionsInDependencyOrder:
    """Counting before custody, custody before findings: fixing one exposes the next."""

    def test_the_close_reports_the_earliest_incomplete_stage_each_time(self):
        """PRD §3.4: "requires that the audit be finished in four respects, tested in this order
        so that the earliest incomplete stage is the one reported: every drawn batch of every
        non-superseded round must have `tally_status` `COUNTED`, or the request is refused for
        an incomplete tally; every physical batch drawn by those rows must have
        `custody_status` `RESEALED`, or the request is refused for a batch not returned; ... and
        no discrepancy of those tallies may be `OPEN` or `ESCALATED`, or the request is refused
        for an unresolved discrepancy."

        Design: Corner/validations/audit_close_preconditions_are_reported_in_dependency_order
        """
        scenario = fixtures.setup_canvassed_contest()
        team_id = fixtures.create_bipartisan_team(scenario["election"]["id"])["id"]
        scenario.update(
            fixtures.setup_audit_round_one(
                scenario["contest"]["id"], audit_type="FIXED_PERCENTAGE"
            )
        )
        audit_id = scenario["audit"]["id"]
        first_drawn, second_drawn = scenario["audit_batches"]
        assert scenario["round"]["selection_sequence"] == ["B-003", "B-004"]
        first_physical = fixtures.read_batch(first_drawn["ballot_batch_id"])
        fixtures.retrieve_batch(
            first_drawn["id"], first_physical["id"], first_physical["current_seal_number"]
        )
        first_tally = fixtures.open_manual_tally(
            first_drawn["id"],
            team_id,
            session_start_at=CANVASS_DAY,
            session_end_at="2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478},
        )
        fixtures.submit_manual_tally(first_tally["id"], team_id)

        uncounted = api_client.close_audit(audit_id, AUDIT_MANAGER)

        validate_error(uncounted, ApiErrorId.ERR_TALLY_INCOMPLETE.value, 409)

        second_physical = fixtures.read_batch(second_drawn["ballot_batch_id"])
        fixtures.retrieve_batch(
            second_drawn["id"],
            second_physical["id"],
            second_physical["current_seal_number"],
        )
        second_tally = fixtures.open_manual_tally(
            second_drawn["id"],
            team_id,
            session_start_at="2026-11-05T11:00:00Z",
            session_end_at="2026-11-05T13:00:00Z",
            counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        )
        fixtures.submit_manual_tally(second_tally["id"], team_id)

        not_returned = api_client.close_audit(audit_id, AUDIT_MANAGER)

        validate_error(not_returned, ApiErrorId.ERR_BATCH_NOT_RETURNED.value, 409)

        fixtures.return_batch(first_drawn["id"], "SEAL-003R")
        fixtures.return_batch(second_drawn["id"], "SEAL-004R")

        open_finding = api_client.close_audit(audit_id, AUDIT_MANAGER)

        validate_error(open_finding, ApiErrorId.ERR_UNRESOLVED_DISCREPANCY.value, 409)

        finding = fixtures.only_discrepancy(first_tally["id"])
        fixtures.document_discrepancy(
            finding["id"], "Six-vote overstatement on B-003.", BOARD_ONE
        )
        fixtures.resolve_discrepancy(
            finding["id"], "Hand count accepted as correct.", BOARD_ONE
        )
        closed = validate_success(api_client.close_audit(audit_id, AUDIT_MANAGER))

        assert closed["status"] == "COMPLETE"
        assert closed["public_report_published"] is True
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["status"] == "COMPLETE"
        assert audit_round["counted_ballots"] == 2000
        assert audit_round["discrepancy_count"] == 1
        assert audit_round["round_measure"] == pytest.approx(0.0030, abs=0.00005)
        assert fixtures.read_manual_tally(first_tally["id"])["status"] == "CERTIFIED"
        assert fixtures.read_manual_tally(second_tally["id"])["status"] == "CERTIFIED"
        resolved = fixtures.read_discrepancy(finding["id"])
        assert resolved["status"] == "RESOLVED"
        assertions.assert_same_instant(
            resolved["resolved_at"], CANVASS_DAY, "resolved_at"
        )
        election = fixtures.read_election(scenario["election"]["id"])
        assert election["open_audit_count"] == 0
        assert election["certification_risk_flag"] is False


class TestCountingRequiresOpenCustody:
    """Resealed ballots are back in the vault, so no count may be opened on them."""

    def test_a_returned_batch_refuses_a_new_hand_count_session(self):
        """PRD §3.5: "The physical batch must not be `QUARANTINED`, and it must be
        `CHECKED_OUT`, or the request is refused because the batch is not checked out — ballots
        cannot be counted while they are sealed in storage." §2.9: "Ballots cannot be counted
        while sealed in storage, nor after they have been resealed."

        Design: Corner/validations/hand_count_cannot_be_opened_on_a_resealed_batch
        """
        scenario = fixtures.setup_round_one_with_checked_out_batch()
        drawn_id = scenario["target_audit_batch"]["id"]
        team_id = scenario["team"]["id"]
        returned = fixtures.return_batch(drawn_id, "SEAL-003R")
        assert returned["retrieval_status"] == "RETURNED"
        assert returned["tally_status"] == "NOT_STARTED"

        refused = api_client.create_manual_tally(
            factories.create_manual_tally_payload(
                drawn_id,
                team_id,
                CANVASS_DAY,
                "2026-11-05T11:00:00Z",
                counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
            ),
            make_tally_team_lead_headers(team_id),
        )

        validate_error(refused, ApiErrorId.ERR_BATCH_NOT_CHECKED_OUT.value, 409)
        batch = fixtures.read_batch(scenario["target_batch"]["id"])
        assert batch["custody_status"] == "RESEALED"
        assert batch["open_checkout_count"] == 0
        assert batch["checkout_cycle_count"] == 1
        _, meta = validate_paginated(
            api_client.list_manual_tallies(
                AUDIT_MANAGER, params={"audit_batch_id": drawn_id, "limit": 10}
            )
        )
        assert meta["total_count"] == 0
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == "SELECTED"
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "SAMPLING"


class TestRequestEligibleMarginCeiling:
    """The ceiling binds candidate requests only, and it binds before any pricing."""

    def test_a_twelve_percent_margin_is_refused_while_five_percent_is_priced(self):
        """PRD §3.8: "For a candidate-requested recount the contest's `margin_pct` must be no
        greater than 10.0000 percent, or the filing is refused because the margin is not
        recount-eligible". §3.8: "A `CANDIDATE_REQUESTED` recount is priced as the filing fee of
        50000 cents plus the applicable rate multiplied by `ballots_in_scope`".

        Design: Corner/validations/candidate_request_is_refused_above_the_ten_percent_margin_ceiling
        """
        scenario = fixtures.setup_election_with_contest_and_batches()
        election_id = scenario["election"]["id"]
        landslide = fixtures.create_contest(
            election_id,
            contest_label="CW",
            office_name="City Council Ward",
            candidate_names=["SOTO", "TRAN"],
            ballots_cast=1000,
        )
        close_contest = fixtures.canvass_contest(scenario["contest"]["id"])
        landslide = fixtures.canvass_contest(
            landslide["id"], reported_votes={"SOTO": 560, "TRAN": 440}
        )
        assert close_contest["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        assert landslide["margin_votes"] == 120
        assert landslide["margin_pct"] == pytest.approx(12.0000, abs=0.00005)
        assert landslide["automatic_recount_required"] is False

        refused = api_client.create_recount(
            factories.create_recount_payload(
                landslide["id"],
                landslide["version"],
                requested_by_candidate_name="TRAN",
            ),
            make_candidate_representative_headers(CANDIDATE_REP_TWO),
        )

        validate_error(
            refused, ApiErrorId.ERR_MARGIN_NOT_RECOUNT_ELIGIBLE.value, 409
        )
        assert fixtures.read_contest(landslide["id"])["open_recount_count"] == 0
        _, landslide_meta = validate_paginated(
            api_client.list_recounts(
                DIRECTOR, params={"contest_id": landslide["id"], "limit": 10}
            )
        )
        assert landslide_meta["total_count"] == 0

        accepted = validate_success(
            api_client.create_recount(
                factories.create_recount_payload(
                    close_contest["id"],
                    close_contest["version"],
                    requested_by_candidate_name="BRENNAN",
                ),
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            ),
            201,
        )

        assertions.assert_recount(accepted)
        assert accepted["required_deposit_cents"] == 200000
        assert accepted["deposit_status"] == "PENDING"
        assert accepted["status"] == "REQUESTED"
        assert accepted["requested_by_user_id"] == CANDIDATE_REP_ONE
        assert fixtures.read_contest(close_contest["id"])["open_recount_count"] == 1
