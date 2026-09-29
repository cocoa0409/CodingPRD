"""Role authorisation, peer isolation and the two segregation-of-duties bars."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    constants,
    factories,
    fixtures,
    make_candidate_representative_headers,
    make_canvassing_board_member_headers,
    make_observer_headers,
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
AUDIT_SEED = constants.TEST_DEFAULTS["AUDIT_SEED"]
BOARD_ONE = constants.TEST_DEFAULTS["BOARD_DEM_USER_ID"]
BOARD_TWO = constants.TEST_DEFAULTS["BOARD_REP_USER_ID"]
BOARD_THREE = constants.TEST_DEFAULTS["BOARD_DEM_2_USER_ID"]
TEAM_DEM = constants.TEST_DEFAULTS["TEAM_DEM_USER_ID"]
TEAM_REP = constants.TEST_DEFAULTS["TEAM_REP_USER_ID"]
CANDIDATE_REP_ONE = "u-cand-1"
WINDOW_START = "2026-11-05T08:00:00Z"
WINDOW_END = "2026-11-06T00:00:00Z"


class TestExclusiveOperationsRefuseEveryOtherRole:
    """Authorisation is decided before state, precondition and payload."""

    def test_ten_cross_role_attempts_are_all_refused_and_change_nothing(self):
        """PRD §2.9: "The acting role is authorized for the endpoint — otherwise
        `ERR_UNAUTHORIZED`. Applies to every endpoint. A `CustodyOfficer` attempting the seed
        ceremony is the canonical case." §2.9: "The server evaluates the checks below in exactly
        this order and responds to the **first** violation it finds; no later check is
        evaluated." §5 maps `ERR_UNAUTHORIZED` to 403, so re-canvassing an already `CANVASSED`
        contest as the audit manager reports the authorisation failure rather than the illegal
        contest transition of the later tier.

        Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
        """
        scenario = fixtures.setup_round_one_with_checked_out_batch()
        election_id = scenario["election"]["id"]
        contest_id = scenario["contest"]["id"]
        team_id = scenario["team"]["id"]
        second_drawn = scenario["audit_batches"][1]
        third_drawn = scenario["audit_batches"][2]
        counted = fixtures.open_manual_tally(
            scenario["target_audit_batch"]["id"],
            team_id,
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478},
        )
        fixtures.submit_manual_tally(counted["id"], team_id)
        finding = fixtures.only_discrepancy(counted["id"])
        first_batch = fixtures.batch_by_label(
            fixtures.list_batches(contest_id), "B-001"
        )
        recount = fixtures.file_recount(
            contest_id,
            requester_user_id=CANDIDATE_REP_ONE,
            scope="PARTIAL_BATCHES",
            scope_batch_ids=[first_batch["id"]],
            requested_by_candidate_name="BRENNAN",
        )
        second_physical = fixtures.read_batch(second_drawn["ballot_batch_id"])

        refusals = [
            api_client.create_election(
                factories.create_election_payload(
                    jurisdiction_code="ST-06", election_name="Runoff"
                ),
                AUDIT_MANAGER,
            ),
            api_client.set_clock("2026-11-06T09:00:00Z", AUDIT_MANAGER),
            api_client.submit_canvass_results(
                contest_id,
                {"reported_votes": {"ALVAREZ": 3200, "BRENNAN": 2800}},
                AUDIT_MANAGER,
            ),
            api_client.create_audit(
                {
                    "contest_id": contest_id,
                    "audit_type": "COMPARISON",
                    "risk_limit_alpha": 0.05,
                },
                CUSTODY_OFFICER,
            ),
            api_client.create_ballot_batch(
                factories.create_ballot_batch_payload(
                    election_id,
                    contest_id,
                    batch_label="B-007",
                    ballot_count=500,
                    machine_votes={"ALVAREZ": 260, "BRENNAN": 240},
                    current_seal_number="SEAL-007",
                ),
                AUDIT_MANAGER,
            ),
            api_client.retrieve_audit_batch(
                second_drawn["id"],
                factories.retrieve_audit_batch_payload(
                    second_physical["version"], second_physical["current_seal_number"]
                ),
                AUDIT_MANAGER,
            ),
            api_client.create_manual_tally(
                factories.create_manual_tally_payload(
                    second_drawn["id"],
                    team_id,
                    CANVASS_DAY,
                    "2026-11-05T11:00:00Z",
                    counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
                ),
                make_canvassing_board_member_headers(BOARD_ONE),
            ),
            api_client.document_discrepancy(
                finding["id"],
                {"documentation_note": "Not my duty."},
                make_tally_team_lead_headers(team_id),
            ),
            api_client.post_recount_deposit(
                recount["id"], {"amount_cents": 100000}, DIRECTOR
            ),
            api_client.close_audit(scenario["audit"]["id"], DIRECTOR),
        ]

        for response in refusals:
            validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        contest = fixtures.read_contest(contest_id)
        assert contest["reported_votes"] == {"ALVAREZ": 3150, "BRENNAN": 2850}
        assert contest["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        assert contest["status"] == "CANVASSED"
        _, election_meta = validate_paginated(
            api_client.list_elections(DIRECTOR, params={"limit": 10})
        )
        assert election_meta["total_count"] == 1
        _, batch_meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER, params={"contest_id": contest_id, "limit": 100}
            )
        )
        assert batch_meta["total_count"] == 6
        assert (
            fixtures.read_audit_batch(second_drawn["id"])["retrieval_status"]
            == "PENDING_RETRIEVAL"
        )
        assert fixtures.read_discrepancy(finding["id"])["status"] == "OPEN"
        assert fixtures.read_recount(recount["id"])["deposit_status"] == "PENDING"
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "DISCREPANCY_REVIEW"
        third_physical = fixtures.read_batch(third_drawn["ballot_batch_id"])
        fixtures.retrieve_batch(
            third_drawn["id"],
            third_physical["id"],
            third_physical["current_seal_number"],
        )
        assertions.assert_same_instant(
            fixtures.read_batch(third_physical["id"])["last_checked_out_at"],
            CANVASS_DAY,
            "last_checked_out_at",
        )


class TestSharedOperationsAdmitEveryListedRole:
    """Two filing roles, four reading roles, and one role outside both lists."""

    def test_the_recount_and_report_surfaces_admit_their_whole_role_list(self):
        """PRD §4: the recount filing endpoint is authorized for
        `CandidateRepresentative, ElectionsDirector` and the public report for
        `ElectionsDirector, AuditManager, CandidateRepresentative, Observer`. §3.8: "A recount
        whose `trigger_type` is `AUTOMATIC_MARGIN` or `AUDIT_ESCALATION` is free:
        `required_deposit_cents` is zero and `deposit_status` is `NOT_REQUIRED`." §2.11:
        "`ElectionsDirector`, `AuditManager` and `CandidateRepresentative` callers may read the
        same report without holding a credential; the credential, its `ACTIVE` status and its
        access window are the `Observer` role's ticket."

        Design: Corner/rbac/shared_operations_admit_every_listed_role
        """
        # C2 is registered before C1 is canvassed: PRD §3.1 requires the election to
        # still be `OPEN` when a canvass is recorded, and the election cascades out of
        # `OPEN` as soon as every one of its contests is `CANVASSED`.
        scenario = fixtures.setup_canvassed_contest(
            reported_votes={"ALVAREZ": 3010, "BRENNAN": 2990},
            sibling_contests=[
                {
                    "contest_label": "C2",
                    "office_name": "State Treasurer",
                    "candidate_names": ["CHEN", "DAVIS"],
                    "ballots_cast": 2000,
                    "cvr_available": False,
                }
            ],
        )
        election_id = scenario["election"]["id"]
        margin_contest = scenario["contest"]
        assert margin_contest["margin_pct"] == pytest.approx(0.3333, abs=0.00005)
        assert margin_contest["automatic_recount_required"] is True
        requested_contest = scenario["sibling_contests"][0]
        requested_contest = fixtures.canvass_contest(
            requested_contest["id"], reported_votes={"CHEN": 1050, "DAVIS": 950}
        )
        assert requested_contest["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        scenario.update(fixtures.setup_audit_round_one(margin_contest["id"]))
        audit = fixtures.terminate_audit(
            scenario["audit"]["id"], terminated_reason="Superseded by recount"
        )
        credential = fixtures.create_observer_credential(
            election_id,
            party_affiliation="UNAFFILIATED",
            access_start_at=WINDOW_START,
            access_end_at=WINDOW_END,
        )
        margin_version = fixtures.read_contest(margin_contest["id"])["version"]
        requested_version = requested_contest["version"]

        director_filing = validate_success(
            api_client.create_recount(
                {
                    "contest_id": margin_contest["id"],
                    "expected_contest_version": margin_version,
                    "trigger_type": "AUTOMATIC_MARGIN",
                    "scope": "FULL_CONTEST",
                },
                DIRECTOR,
            ),
            201,
        )
        representative_filing = validate_success(
            api_client.create_recount(
                {
                    "contest_id": requested_contest["id"],
                    "expected_contest_version": requested_version,
                    "trigger_type": "CANDIDATE_REQUESTED",
                    "scope": "FULL_CONTEST",
                    "requested_by_candidate_name": "DAVIS",
                },
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            ),
            201,
        )
        officer_filing = api_client.create_recount(
            {
                "contest_id": requested_contest["id"],
                "expected_contest_version": requested_version,
                "trigger_type": "CANDIDATE_REQUESTED",
                "scope": "FULL_CONTEST",
                "requested_by_candidate_name": "CHEN",
            },
            CUSTODY_OFFICER,
        )

        assertions.assert_recount(director_filing)
        assert director_filing["status"] == "REQUESTED"
        assert director_filing["deposit_status"] == "NOT_REQUIRED"
        assert director_filing["required_deposit_cents"] == 0
        assert representative_filing["status"] == "REQUESTED"
        assert representative_filing["deposit_status"] == "PENDING"
        assert representative_filing["required_deposit_cents"] == 100000
        validate_error(officer_filing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        for headers in (
            DIRECTOR,
            AUDIT_MANAGER,
            make_candidate_representative_headers(CANDIDATE_REP_ONE),
        ):
            report = validate_success(
                api_client.get_audit_public_report(audit["id"], headers)
            )
            assert report["published"] is True
            assert report["status"] == "TERMINATED"
        observer_report = validate_success(
            api_client.get_audit_public_report(
                audit["id"], make_observer_headers(credential["id"])
            )
        )
        # PRD §3.3: this contest's margin fraction is 20/6000, so a 0.05 risk-limiting
        # audit needs ceil(2 * 2.996 / (20/6000)^2) = 539280 ballots, i.e. 540 batches
        # of the 1000-ballot average, and `planned_sample_size` is "the smaller of the
        # total batch count and the larger of two and the raw batch requirement" — the
        # whole six-batch pool.  PRD §3.4's generator, run six times over the
        # label-ascending pool from seed 0459231087, yields this order.
        assert observer_report["selection_sequence"] == [
            "B-003",
            "B-004",
            "B-005",
            "B-001",
            "B-002",
            "B-006",
        ]
        validate_error(
            api_client.get_audit_public_report(audit["id"], CUSTODY_OFFICER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        election = fixtures.read_election(election_id)
        assert election["open_recount_count"] == 2
        assert election["open_audit_count"] == 0


class TestObserverRoleScope:
    """The credential buys one route and nothing else."""

    def test_the_observer_reaches_only_the_public_report(self):
        """PRD §4: "**All six operator roles** is shorthand for `ElectionsDirector`,
        `AuditManager`, `CustodyOfficer`, `TallyTeamLead`, `CanvassingBoardMember` and
        `CandidateRepresentative` — every role except `Observer`, whose only endpoint is the
        public audit report." §2.9: "The acting role is authorized for the endpoint — otherwise
        `ERR_UNAUTHORIZED`", and that tier is evaluated ahead of the tier that resolves a path
        identifier, so reading the credential that authenticates the caller is a 403 and not a
        404.

        Design: Corner/rbac/observer_holds_no_exclusive_operation_and_only_the_report_path
        """
        scenario = fixtures.setup_terminated_audit()
        audit_id = scenario["audit"]["id"]
        credential = fixtures.create_observer_credential(
            scenario["election"]["id"],
            party_affiliation="UNAFFILIATED",
            access_start_at=WINDOW_START,
            access_end_at=WINDOW_END,
        )
        observer = make_observer_headers(credential["id"])

        refusals = [
            api_client.list_elections(observer, params={"limit": 10}),
            api_client.get_observer_credential(credential["id"], observer),
            api_client.get_audit(audit_id, observer),
            api_client.create_audit(
                {
                    "contest_id": scenario["contest"]["id"],
                    "audit_type": "COMPARISON",
                    "risk_limit_alpha": 0.05,
                },
                observer,
            ),
        ]
        report = validate_success(
            api_client.get_audit_public_report(audit_id, observer)
        )

        for response in refusals:
            validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        assert report["published"] is True
        assert report["status"] == "TERMINATED"
        assert report["random_seed"] == AUDIT_SEED
        _, audit_meta = validate_paginated(
            api_client.list_audits(
                AUDIT_MANAGER,
                params={"contest_id": scenario["contest"]["id"], "limit": 10},
            )
        )
        assert audit_meta["total_count"] == 1
        assert fixtures.read_observer_credential(credential["id"])["status"] == "ACTIVE"


class TestLeadActsOnlyOnItsOwnCount:
    """Lead identity is the team id, and the mismatch outranks the duplicate."""

    def test_a_second_teams_lead_is_refused_on_all_four_writes(self):
        """PRD §2.1: "When `X-User-Role` is `TallyTeamLead`, `X-User-ID` is the `id` of the
        acting `TallyTeam`; ownership checks on any resource that references a `TallyTeam`
        compare the resource's `tally_team_id` to `X-User-ID`, and a lead acting on another
        team's tally is refused with `ERR_TALLY_TEAM_MISMATCH`." §2.9: "For the entity-backed
        `TallyTeamLead`, `X-User-ID` resolves to a `TallyTeam` and that team owns the tally
        being acted on — otherwise `ERR_TALLY_TEAM_MISMATCH`. Applies to hand-tally creation,
        hand-tally editing, submission, reopening and ballot-interpretation referral." That
        tier is numbered 6, ahead of the duplicate-tally tier the same creation would also
        break.

        Design: Corner/rbac/a_lead_may_act_only_on_their_own_teams_count
        """
        scenario = fixtures.setup_round_one_with_checked_out_batch()
        owning_team = scenario["team"]
        other_team = fixtures.create_bipartisan_team(
            scenario["election"]["id"],
            team_label="T-2",
            room_code="ROOM-B",
            dem_user_id="u-dem-2",
            rep_user_id="u-rep-2",
        )
        drawn = scenario["target_audit_batch"]
        own_tally = fixtures.open_manual_tally(
            drawn["id"],
            owning_team["id"],
            counted_votes={"ALVAREZ": 520, "BRENNAN": 478},
            ambiguous_ballot_count=2,
            no_vote_count=0,
        )
        intruder = make_tally_team_lead_headers(other_team["id"])

        validate_error(
            api_client.create_manual_tally(
                factories.create_manual_tally_payload(
                    drawn["id"],
                    owning_team["id"],
                    "2026-11-05T13:00:00Z",
                    "2026-11-05T15:00:00Z",
                    counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
                ),
                intruder,
            ),
            ApiErrorId.ERR_TALLY_TEAM_MISMATCH.value,
            403,
        )
        validate_error(
            api_client.patch_manual_tally(
                own_tally["id"],
                {"counted_votes": {"ALVAREZ": 519, "BRENNAN": 479}},
                intruder,
            ),
            ApiErrorId.ERR_TALLY_TEAM_MISMATCH.value,
            403,
        )
        assert fixtures.read_manual_tally(own_tally["id"])["counted_votes"]["ALVAREZ"] == 520
        validate_error(
            api_client.submit_manual_tally(own_tally["id"], intruder),
            ApiErrorId.ERR_TALLY_TEAM_MISMATCH.value,
            403,
        )
        still_draft = fixtures.read_manual_tally(own_tally["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["version"] == 1

        submitted = fixtures.submit_manual_tally(own_tally["id"], owning_team["id"])

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == owning_team["id"]
        assert submitted["net_error_votes"] == 8
        validate_error(
            api_client.create_ballot_interpretation(
                factories.create_ballot_interpretation_payload(
                    own_tally["id"],
                    ballot_ref="BAL-1",
                    ambiguity_type="OVERVOTE",
                    proposed_determination="ALVAREZ",
                ),
                intruder,
            ),
            ApiErrorId.ERR_TALLY_TEAM_MISMATCH.value,
            403,
        )
        referral = fixtures.refer_ballot_interpretation(
            own_tally["id"],
            owning_team["id"],
            ballot_ref="BAL-1",
            ambiguity_type="OVERVOTE",
            proposed_determination="ALVAREZ",
        )
        assert referral["status"] == "PENDING"
        assert fixtures.read_manual_tally(own_tally["id"])["status"] == "PENDING_ADJUDICATION"
        _, tally_meta = validate_paginated(
            api_client.list_manual_tallies(
                DIRECTOR, params={"tally_team_id": other_team["id"], "limit": 10}
            )
        )
        assert tally_meta["total_count"] == 0


class TestCountersMayNotAdjudicateTheirOwnBallots:
    """The bar is team membership, not the board role."""

    def test_the_producing_teams_members_are_refused_and_outsiders_reach_quorum(self):
        """PRD §2.9: "Segregation of duties holds: the acting `X-User-ID` is not a member of
        the tally team that produced the tally under adjudication, and the verifier of a
        corrective action is not the user who completed it — otherwise
        `ERR_SEGREGATION_OF_DUTIES`. Applies to casting a board vote and to advancing a
        corrective action." §3.7: "a greater `accept_count` than `reject_count` makes it
        `ADJUDICATED` with `final_determination` equal to the `proposed_determination`". §3.7:
        "When no referral of the tally remains `PENDING` — whether the last one was adjudicated
        or deadlocked — the tally moves from `PENDING_ADJUDICATION` back to `SUBMITTED`".

        Design: Corner/rbac/counters_may_not_adjudicate_the_ballots_they_counted
        """
        scenario = fixtures.setup_submitted_tally(
            counted_votes={"ALVAREZ": 520, "BRENNAN": 478}, ambiguous_ballot_count=2
        )
        tally_id = scenario["manual_tally"]["id"]
        referral = fixtures.refer_ballot_interpretation(
            tally_id,
            scenario["team"]["id"],
            ballot_ref="BAL-1",
            ambiguity_type="OVERVOTE",
            proposed_determination="ALVAREZ",
        )

        validate_error(
            api_client.cast_ballot_interpretation_vote(
                referral["id"],
                {"party": "DEM", "vote": "ACCEPT"},
                make_canvassing_board_member_headers(TEAM_DEM),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            409,
        )
        validate_error(
            api_client.cast_ballot_interpretation_vote(
                referral["id"],
                {"party": "REP", "vote": "REJECT"},
                make_canvassing_board_member_headers(TEAM_REP),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            409,
        )
        untouched = fixtures.read_ballot_interpretation(referral["id"])
        assert untouched["votes_cast"] == 0
        assert untouched["version"] == 1
        assert untouched["status"] == "PENDING"

        fixtures.cast_board_vote(referral["id"], BOARD_ONE, "DEM", "ACCEPT")
        fixtures.cast_board_vote(referral["id"], BOARD_TWO, "REP", "ACCEPT")
        adjudicated = fixtures.cast_board_vote(
            referral["id"], BOARD_THREE, "DEM", "REJECT"
        )

        assertions.assert_ballot_interpretation(adjudicated)
        assert adjudicated["votes_cast"] == 3
        assert adjudicated["accept_count"] == 2
        assert adjudicated["reject_count"] == 1
        assert adjudicated["quorum_met"] is True
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["final_determination"] == "ALVAREZ"
        tally = fixtures.read_manual_tally(tally_id)
        assert tally["counted_votes"]["ALVAREZ"] == 521
        assert tally["ambiguous_ballot_count"] == 1
        assert tally["net_error_votes"] == 7
        assert tally["status"] == "SUBMITTED"
        assertions.assert_ballot_accounting_identity(tally, 1000)


class TestCorrectiveActionSelfVerification:
    """The completer may not be the verifier, and the refusal changes nothing."""

    def test_the_member_who_completed_the_fix_cannot_verify_it(self):
        """PRD §3.6: "`COMPLETED` may become `VERIFIED`, which requires that the acting
        member's identity differ from `completed_by_user_id` — a self-verification is refused
        for segregation of duties — and which stamps `verified_by_user_id` and `verified_at`."
        §2.11: "the user who marks a corrective action complete may not be the user who
        verifies it; verification is recorded in `verified_by_user_id` and must differ from
        `completed_by_user_id`."

        Design: Corner/rbac/a_corrective_action_may_not_be_verified_by_its_own_completer
        """
        scenario = fixtures.setup_documented_discrepancy(
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478}
        )
        finding = scenario["discrepancy"]
        action = fixtures.create_corrective_action(
            finding["id"],
            category="EQUIPMENT",
            description="Recalibrate the VAULT-1 scanner.",
            due_at="2026-11-20T17:00:00Z",
        )
        fixtures.transition_corrective_action(
            action["id"], "IN_PROGRESS", board_user_id=BOARD_ONE
        )
        completed = fixtures.transition_corrective_action(
            action["id"], "COMPLETED", board_user_id=BOARD_ONE, note="Recalibrated."
        )
        assert completed["completed_by_user_id"] == BOARD_ONE
        assert completed["version"] == 3
        assertions.assert_same_instant(
            completed["completed_at"], CANVASS_DAY, "completed_at"
        )

        validate_error(
            api_client.transition_corrective_action(
                action["id"],
                {"to_status": "VERIFIED"},
                make_canvassing_board_member_headers(BOARD_ONE),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            409,
        )

        unchanged = fixtures.read_corrective_action(action["id"])
        assert unchanged["status"] == "COMPLETED"
        assert unchanged["verified_by_user_id"] is None
        assert unchanged["verified_at"] is None
        assert unchanged["version"] == 3

        verified = fixtures.transition_corrective_action(
            action["id"], "VERIFIED", board_user_id=BOARD_TWO
        )

        assertions.assert_corrective_action(verified)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == BOARD_TWO
        assert verified["version"] == 4
        assertions.assert_same_instant(
            verified["verified_at"], CANVASS_DAY, "verified_at"
        )
        assert fixtures.read_discrepancy(finding["id"])["status"] == "DOCUMENTED"


class TestEveryRoleCompletesItsOwnOperations:
    """One audit carried from planning to certification, each step by its owner."""

    def test_the_six_operator_roles_drive_one_audit_to_a_certified_election(self):
        """PRD §3.3: "For a `FIXED_PERCENTAGE` audit there is no ballot term at all: the raw
        batch requirement is the total batch count multiplied by `fixed_percentage_pct`, divided
        by one hundred, and rounded up to the next whole batch", and "`planned_sample_size` is
        then the smaller of the total batch count and the larger of two and the raw batch
        requirement". §2.7: "Certifying an election is the director's final act". §3.8: "Either
        way `status` becomes `WITHDRAWN` and the contest's `open_recount_count` is decreased by
        one." §2.7: "On success the election's `status` becomes `CERTIFIED`, `certified_at` is
        stamped from the clock, every contest of the election moves from `CANVASSED` to
        `CERTIFIED`".

        Design: Corner/rbac/every_role_completes_its_own_exclusive_operations_end_to_end
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election()
        contest = fixtures.create_contest(election["id"])
        fixtures.create_batches(election["id"], contest["id"])
        contest = fixtures.canvass_contest(contest["id"])
        assert contest["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        team = fixtures.create_bipartisan_team(election["id"])

        audit = validate_success(
            api_client.create_audit(
                {
                    "contest_id": contest["id"],
                    "audit_type": "FIXED_PERCENTAGE",
                    "fixed_percentage_pct": 5,
                },
                AUDIT_MANAGER,
            ),
            201,
        )
        seeded = validate_success(
            api_client.seed_audit(audit["id"], {"random_seed": AUDIT_SEED}, AUDIT_MANAGER)
        )
        assert seeded["planned_sample_size"] == 2
        audit_round = validate_success(
            api_client.create_audit_round(
                audit["id"], {"expected_audit_version": seeded["version"]}, AUDIT_MANAGER
            ),
            201,
        )
        assert audit_round["selection_sequence"] == ["B-003", "B-004"]
        drawn_rows, _ = validate_paginated(
            api_client.list_audit_batches(
                CUSTODY_OFFICER,
                params={"audit_round_id": audit_round["id"], "limit": 100},
            )
        )
        counted_votes_by_index = [
            {"ALVAREZ": 522, "BRENNAN": 478},
            {"ALVAREZ": 525, "BRENNAN": 475},
        ]
        session_windows = [
            (CANVASS_DAY, "2026-11-05T11:00:00Z"),
            ("2026-11-05T11:00:00Z", "2026-11-05T13:00:00Z"),
        ]
        physical_batches = []
        tallies = []
        for row in sorted(drawn_rows, key=lambda drawn: drawn["selection_index"]):
            index = row["selection_index"]
            physical = fixtures.read_batch(row["ballot_batch_id"])
            fixtures.retrieve_batch(
                row["id"], physical["id"], physical["current_seal_number"]
            )
            tally = fixtures.open_manual_tally(
                row["id"],
                team["id"],
                session_start_at=session_windows[index][0],
                session_end_at=session_windows[index][1],
                counted_votes=counted_votes_by_index[index],
                ambiguous_ballot_count=0,
                no_vote_count=0,
            )
            tallies.append(fixtures.submit_manual_tally(tally["id"], team["id"]))
            physical_batches.append(physical)
        for row, physical in zip(
            sorted(drawn_rows, key=lambda drawn: drawn["selection_index"]),
            physical_batches,
        ):
            fixtures.return_batch(row["id"], f"{physical['current_seal_number']}R")
        finding = fixtures.only_discrepancy(tallies[0]["id"])
        fixtures.document_discrepancy(
            finding["id"], documentation_note="Six-vote overstatement."
        )
        fixtures.resolve_discrepancy(
            finding["id"], resolution_note="Hand count accepted."
        )

        closed = validate_success(api_client.close_audit(audit["id"], AUDIT_MANAGER))
        contest_for_filing = validate_success(
            api_client.get_contest(
                contest["id"], make_candidate_representative_headers(CANDIDATE_REP_ONE)
            )
        )
        filed = validate_success(
            api_client.create_recount(
                {
                    "contest_id": contest["id"],
                    "expected_contest_version": contest_for_filing["version"],
                    "trigger_type": "CANDIDATE_REQUESTED",
                    "scope": "FULL_CONTEST",
                    "requested_by_candidate_name": "BRENNAN",
                },
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            ),
            201,
        )
        withdrawn = validate_success(
            api_client.withdraw_recount(
                filed["id"],
                {"reason": "Margin accepted"},
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            )
        )
        certified = validate_success(
            api_client.certify_election(election["id"], DIRECTOR)
        )

        assert closed["status"] == "COMPLETE"
        assert closed["public_report_published"] is True
        assert withdrawn["status"] == "WITHDRAWN"
        assert fixtures.read_contest(contest["id"])["open_recount_count"] == 0
        assertions.assert_election(certified)
        assert certified["status"] == "CERTIFIED"
        assertions.assert_same_instant(
            certified["certified_at"], CANVASS_DAY, "certified_at"
        )
        assert fixtures.read_contest(contest["id"])["status"] == "CERTIFIED"
        for tally in tallies:
            assert fixtures.read_manual_tally(tally["id"])["status"] == "CERTIFIED"
        for physical in physical_batches:
            assert fixtures.read_batch(physical["id"])["custody_status"] == "RESEALED"
        assert fixtures.read_discrepancy(finding["id"])["status"] == "RESOLVED"
        assert fixtures.read_election(election["id"])["open_audit_count"] == 0
        final_round = fixtures.read_audit_round(audit_round["id"])
        assert final_round["status"] == "COMPLETE"
        assert final_round["counted_ballots"] == 2000
        assert final_round["round_measure"] == pytest.approx(0.0030, abs=0.00005)


class TestObserverCredentialGates:
    """Two independent gates on one credential, and a half-open window."""

    def test_revocation_and_the_window_edge_each_close_the_report(self):
        """PRD §3.9: "An observer reads it through a credential: the identity supplied must
        resolve to a stored credential, that credential must be `ACTIVE` — a revoked credential
        loses report access even inside its stated window — and the clock must be inside the
        credential's access window, which includes `access_start_at` and excludes
        `access_end_at`, so a request at exactly `access_end_at` is outside the window and is
        refused." §3.9: "The director may revoke an `ACTIVE` credential with a `revoked_reason`.
        Revocation sets `status` to `REVOKED`, which is terminal, records the reason".

        Design: Corner/rbac/observer_access_is_bounded_by_credential_status_and_window
        """
        scenario = fixtures.setup_terminated_audit()
        audit_id = scenario["audit"]["id"]
        election_id = scenario["election"]["id"]
        revoked_credential = fixtures.create_observer_credential(
            election_id,
            organization_name="League of Voters",
            party_affiliation="UNAFFILIATED",
            room_code="ROOM-B",
            access_start_at=WINDOW_START,
            access_end_at=WINDOW_END,
        )
        surviving_credential = fixtures.create_observer_credential(
            election_id,
            organization_name="State Press Pool",
            party_affiliation="PRESS",
            room_code="ROOM-B",
            access_start_at=WINDOW_START,
            access_end_at=WINDOW_END,
        )

        inside_window = validate_success(
            api_client.get_audit_public_report(
                audit_id, make_observer_headers(revoked_credential["id"])
            )
        )
        revoked = validate_success(
            api_client.revoke_observer_credential(
                revoked_credential["id"],
                {"revoked_reason": "Credential surrendered"},
                DIRECTOR,
            )
        )
        after_revocation = api_client.get_audit_public_report(
            audit_id, make_observer_headers(revoked_credential["id"])
        )
        fixtures.set_clock(WINDOW_END)
        at_window_end = api_client.get_audit_public_report(
            audit_id, make_observer_headers(surviving_credential["id"])
        )
        repeat_revocation = api_client.revoke_observer_credential(
            revoked_credential["id"], {"revoked_reason": "Repeat revocation"}, DIRECTOR
        )

        assert inside_window["published"] is True
        assertions.assert_observer_credential(revoked)
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_reason"] == "Credential surrendered"
        validate_error(
            after_revocation, ApiErrorId.ERR_OBSERVER_CREDENTIAL_REVOKED.value, 403
        )
        validate_error(
            at_window_end, ApiErrorId.ERR_OBSERVER_ACCESS_WINDOW_CLOSED.value, 403
        )
        validate_error(
            repeat_revocation, ApiErrorId.ERR_INVALID_CREDENTIAL_STATE.value, 409
        )
        assert (
            fixtures.read_observer_credential(surviving_credential["id"])["status"]
            == "ACTIVE"
        )
        assert fixtures.read_observer_credential(revoked_credential["id"])["version"] == 2
