"""Error vocabulary and the precedence between neighbouring refusals."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    constants,
    factories,
    fixtures,
    get_success_data,
    make_candidate_representative_headers,
    make_canvassing_board_member_headers,
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
BOARD_ONE = constants.TEST_DEFAULTS["BOARD_DEM_USER_ID"]
BOARD_TWO = constants.TEST_DEFAULTS["BOARD_REP_USER_ID"]
BOARD_THREE = constants.TEST_DEFAULTS["BOARD_DEM_2_USER_ID"]
BOARD_FOUR = "u-board-4"
TEAM_DEM = constants.TEST_DEFAULTS["TEAM_DEM_USER_ID"]
CANDIDATE_REP_ONE = "u-cand-1"
CANDIDATE_REP_TWO = "u-cand-2"

SOLO_ROSTER = {"members": [{"user_id": TEAM_DEM, "party": "DEM", "seat_role": "LEAD"}]}


class TestPathResolutionVocabulary:
    """Twelve unknown identifiers, twelve different 404s."""

    def test_each_route_names_its_own_entity_when_the_identifier_is_unknown(self):
        """PRD §2.5: "Path parameters are resolved strictly left to right, and the first
        identifier that does not resolve to a stored row determines the response. The 404 error
        id names the entity that owns the collection segment the identifier sits in:
        `ERR_ELECTION_NOT_FOUND`, `ERR_CONTEST_NOT_FOUND`, `ERR_BALLOT_BATCH_NOT_FOUND`,
        `ERR_CUSTODY_EVENT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_AUDIT_ROUND_NOT_FOUND`,
        `ERR_AUDIT_BATCH_NOT_FOUND`, `ERR_TALLY_TEAM_NOT_FOUND`, `ERR_MANUAL_TALLY_NOT_FOUND`,
        `ERR_DISCREPANCY_NOT_FOUND`, `ERR_BALLOT_INTERPRETATION_NOT_FOUND`,
        `ERR_RECOUNT_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_NOT_FOUND` or
        `ERR_OBSERVER_CREDENTIAL_NOT_FOUND`."

        Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        fixtures.set_clock(CANVASS_DAY)
        unknown = [f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 13)]

        reads = [
            (api_client.get_contest(unknown[0], DIRECTOR), ApiErrorId.ERR_CONTEST_NOT_FOUND),
            (
                api_client.get_ballot_batch(unknown[1], DIRECTOR),
                ApiErrorId.ERR_BALLOT_BATCH_NOT_FOUND,
            ),
            (
                api_client.get_custody_event(unknown[2], DIRECTOR),
                ApiErrorId.ERR_CUSTODY_EVENT_NOT_FOUND,
            ),
            (
                api_client.get_audit_round(unknown[3], DIRECTOR),
                ApiErrorId.ERR_AUDIT_ROUND_NOT_FOUND,
            ),
            (
                api_client.get_audit_batch(unknown[4], DIRECTOR),
                ApiErrorId.ERR_AUDIT_BATCH_NOT_FOUND,
            ),
            (
                api_client.get_tally_team(unknown[5], DIRECTOR),
                ApiErrorId.ERR_TALLY_TEAM_NOT_FOUND,
            ),
            (
                api_client.get_manual_tally(unknown[6], DIRECTOR),
                ApiErrorId.ERR_MANUAL_TALLY_NOT_FOUND,
            ),
            (
                api_client.get_discrepancy(unknown[7], DIRECTOR),
                ApiErrorId.ERR_DISCREPANCY_NOT_FOUND,
            ),
            (
                api_client.get_ballot_interpretation(unknown[8], DIRECTOR),
                ApiErrorId.ERR_BALLOT_INTERPRETATION_NOT_FOUND,
            ),
            (api_client.get_recount(unknown[9], DIRECTOR), ApiErrorId.ERR_RECOUNT_NOT_FOUND),
            (
                api_client.get_corrective_action(unknown[10], DIRECTOR),
                ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_FOUND,
            ),
            (
                api_client.get_observer_credential(unknown[11], DIRECTOR),
                ApiErrorId.ERR_OBSERVER_CREDENTIAL_NOT_FOUND,
            ),
        ]

        for response, expected in reads:
            validate_error(response, expected.value, 404)


class TestCustodyStateErrorsAreDistinct:
    """One container drawn twice: the drawn row and the physical batch fail differently."""

    def test_the_second_drawing_reports_the_physical_state_and_succeeds_after_the_reseal(self):
        """PRD §3.2: "The physical batch must be `SEALED` or `RESEALED`, its
        `retrieval_authorized_at` must be set, it must not be `QUARANTINED`, the
        `observed_seal_number` must equal the batch's `current_seal_number` ... and the drawn
        batch must still be `PENDING_RETRIEVAL`." §3.2: "The same physical batch may be drawn by
        more than one audit of the same contest, and is retrieved once per drawing. The second
        and later cycles start from `RESEALED` rather than `SEALED`."

        Design: Corner/errors/physical_batch_state_and_drawn_batch_state_report_different_errors
        """
        scenario = fixtures.setup_two_audits_sharing_first_batch()
        first_drawn = scenario["rla_target"]
        second_drawn = scenario["comparison_target"]
        physical = scenario["shared_batch"]
        attested_seal = physical["current_seal_number"]
        reseal = f"{attested_seal}R"
        assert first_drawn["retrieval_status"] == "RETRIEVED"
        assert second_drawn["retrieval_status"] == "PENDING_RETRIEVAL"
        assert physical["custody_status"] == "CHECKED_OUT"

        repeat = api_client.retrieve_audit_batch(
            first_drawn["id"],
            factories.retrieve_audit_batch_payload(physical["version"], attested_seal),
            CUSTODY_OFFICER,
        )
        validate_error(repeat, ApiErrorId.ERR_INVALID_AUDIT_BATCH_STATE.value, 409)

        second_audit_attempt = api_client.retrieve_audit_batch(
            second_drawn["id"],
            factories.retrieve_audit_batch_payload(physical["version"], attested_seal),
            CUSTODY_OFFICER,
        )
        validate_error(second_audit_attempt, ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409)
        assert (
            fixtures.read_audit_batch(second_drawn["id"])["retrieval_status"]
            == "PENDING_RETRIEVAL"
        )

        returned = fixtures.return_batch(first_drawn["id"], reseal)
        assert returned["retrieval_status"] == "RETURNED"
        resealed = fixtures.read_batch(physical["id"])
        assert resealed["custody_status"] == "RESEALED"
        assert resealed["current_seal_number"] == reseal

        second_cycle = validate_success(
            api_client.retrieve_audit_batch(
                second_drawn["id"],
                factories.retrieve_audit_batch_payload(resealed["version"], reseal),
                CUSTODY_OFFICER,
            )
        )

        assert second_cycle["retrieval_status"] == "RETRIEVED"
        final = fixtures.read_batch(physical["id"])
        assert final["custody_status"] == "CHECKED_OUT"
        assert final["open_checkout_count"] == 1
        assert final["checkout_cycle_count"] == 1
        assert final["current_seal_number"] == reseal
        events, meta = validate_paginated(
            api_client.list_ballot_batch_custody_events(
                physical["id"], CUSTODY_OFFICER, params={"limit": 100}
            )
        )
        assert meta["total_count"] == 6
        ordered = sorted(events, key=lambda event: event["sequence_no"])
        assertions.assert_custody_log_ordered(ordered)
        assert [event["event_type"] for event in ordered] == [
            "INTAKE",
            "AUTHORIZED",
            "AUTHORIZED",
            "CHECK_OUT",
            "CHECK_IN",
            "CHECK_OUT",
        ]


class TestTeamCompositionGuardsTwoEndpoints:
    """Readiness guards the opening; bipartisan composition guards the submission."""

    def test_a_single_party_team_is_refused_the_batch_and_later_the_submission(self):
        """PRD §2.9: "The assigned tally team is `READY`, and therefore bipartisan and not
        `DISBANDED` — otherwise `ERR_TALLY_TEAM_NOT_READY`. Applies to opening a hand-count
        session. Submission is deliberately **not** covered here; a team that lost its bipartisan
        composition after the session opened is caught at tier 24 instead, so the two errors never
        shadow each other." §3.5: "A `READY` team whose replacement roster leaves it with no
        `DEM` member or no `REP` member falls back to `FORMING` with `is_bipartisan` false; its
        live hand tallies are deliberately **not** touched — they stay `DRAFT`, and it is
        submission that refuses them, for a team that is not bipartisan."

        Design: Corner/errors/team_readiness_is_checked_at_open_and_bipartisan_composition_again_at_submit
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        target_drawn = scenario["audit_batches"][0]
        target_physical = fixtures.read_batch(target_drawn["ballot_batch_id"])
        fixtures.retrieve_batch(
            target_drawn["id"],
            target_physical["id"],
            target_physical["current_seal_number"],
        )
        team = get_success_data(
            api_client.create_tally_team(
                factories.create_tally_team_payload(scenario["election"]["id"]), DIRECTOR
            )
        )
        forming = validate_success(
            api_client.set_tally_team_members(team["id"], SOLO_ROSTER, DIRECTOR)
        )
        assert forming["status"] == "FORMING"
        assert forming["is_bipartisan"] is False
        lead_headers = make_tally_team_lead_headers(team["id"])
        session = factories.create_manual_tally_payload(
            target_drawn["id"],
            team["id"],
            CANVASS_DAY,
            "2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        )

        not_ready = api_client.create_manual_tally(session, lead_headers)

        validate_error(not_ready, ApiErrorId.ERR_TALLY_TEAM_NOT_READY.value, 409)

        ready = validate_success(
            api_client.set_tally_team_members(
                team["id"], factories.bipartisan_members_payload(), DIRECTOR
            )
        )
        assert ready["status"] == "READY"
        tally = validate_success(api_client.create_manual_tally(session, lead_headers), 201)
        assert tally["status"] == "DRAFT"
        fallen_back = validate_success(
            api_client.set_tally_team_members(team["id"], SOLO_ROSTER, DIRECTOR)
        )
        assert fallen_back["status"] == "FORMING"

        not_bipartisan = api_client.submit_manual_tally(tally["id"], lead_headers)

        validate_error(not_bipartisan, ApiErrorId.ERR_TEAM_NOT_BIPARTISAN.value, 409)
        untouched = fixtures.read_manual_tally(tally["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["counted_votes"] == {"ALVAREZ": 525, "BRENNAN": 475}
        assert untouched["version"] == 1

        api_client.set_tally_team_members(
            team["id"], factories.bipartisan_members_payload(), DIRECTOR
        )
        submitted = validate_success(api_client.submit_manual_tally(tally["id"], lead_headers))

        assertions.assert_manual_tally(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert fixtures.read_tally_team(team["id"])["party_counts"] == {"DEM": 1, "REP": 1}
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == "TALLYING"
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "TALLYING"


class TestLabelScoping:
    """Contest and team labels are unique per election, not across the service."""

    def test_the_same_labels_are_refused_inside_one_election_and_accepted_in_another(self):
        """PRD §3.1: "a `contest_label` of one to thirty-two characters that must be unique among
        the contests of that election". §3.5: "a `team_label` of one to thirty-two characters
        unique among the teams of that election". §2.9: "Labels are unique inside their owning
        scope — otherwise `ERR_DUPLICATE_CONTEST_LABEL`, `ERR_DUPLICATE_BATCH_LABEL` or
        `ERR_DUPLICATE_TEAM_LABEL`."

        Design: Corner/errors/label_uniqueness_is_scoped_to_the_owning_election
        """
        fixtures.set_clock(CANVASS_DAY)
        first_election = fixtures.create_election()
        second_election = fixtures.create_election(
            jurisdiction_code=constants.TEST_DEFAULTS["E2_JURISDICTION_CODE"]
        )
        fixtures.create_contest(first_election["id"])
        fixtures.create_bipartisan_team(first_election["id"])

        clashing_contest = api_client.create_contest(
            factories.create_contest_payload(
                first_election["id"],
                office_name="State Treasurer",
                candidate_names=["CHEN", "DAVIS"],
                ballots_cast=3000,
            ),
            DIRECTOR,
        )
        validate_error(clashing_contest, ApiErrorId.ERR_DUPLICATE_CONTEST_LABEL.value, 409)

        clashing_team = api_client.create_tally_team(
            factories.create_tally_team_payload(first_election["id"], room_code="ROOM-B"),
            DIRECTOR,
        )
        validate_error(clashing_team, ApiErrorId.ERR_DUPLICATE_TEAM_LABEL.value, 409)

        elsewhere_contest = validate_success(
            api_client.create_contest(
                factories.create_contest_payload(second_election["id"]), DIRECTOR
            ),
            201,
        )
        elsewhere_team = validate_success(
            api_client.create_tally_team(
                factories.create_tally_team_payload(second_election["id"]), DIRECTOR
            ),
            201,
        )

        assert elsewhere_contest["contest_label"] == "C1"
        assert elsewhere_team["team_label"] == "T-1"
        for election_id in (first_election["id"], second_election["id"]):
            _, contest_meta = validate_paginated(
                api_client.list_contests(
                    DIRECTOR, params={"election_id": election_id, "limit": 10}
                )
            )
            assert contest_meta["total_count"] == 1
            _, team_meta = validate_paginated(
                api_client.list_tally_teams(
                    DIRECTOR, params={"election_id": election_id, "limit": 10}
                )
            )
            assert team_meta["total_count"] == 1


class TestWindowSanityRunsFirst:
    """One window rule over four payloads, and it precedes the room-capacity test."""

    def test_an_inverted_window_is_reported_instead_of_the_capacity_it_would_also_break(self):
        """PRD §2.9: "Time windows are sane — otherwise `ERR_INVALID_TIME_WINDOW`. Applies to
        hand-tally creation, observer credentialing, election registration, election amendment
        and corrective-action creation. `session_start_at` must be strictly before
        `session_end_at`, `access_start_at` strictly before `access_end_at`,
        `certification_deadline_at` strictly after midnight UTC on the election date, and `due_at`
        strictly after the current clock. This tier is checked before any overlap test." §3.9:
        "at most two `ACTIVE` credentials may overlap in the same `room_code` ... and a third
        overlapping credential is refused because the room capacity is exceeded".

        Design: Corner/errors/inverted_windows_are_rejected_before_any_overlap_or_capacity_test
        """
        scenario = fixtures.setup_round_one_with_checked_out_batch()
        election_id = scenario["election"]["id"]
        team_id = scenario["team"]["id"]
        for organization, party in (("League of Voters", "DEM"), ("Citizens Watch", "REP")):
            fixtures.create_observer_credential(
                election_id,
                organization_name=organization,
                party_affiliation=party,
                room_code="ROOM-A",
                access_start_at="2026-11-05T08:00:00Z",
                access_end_at="2026-11-06T00:00:00Z",
            )

        bad_registration = api_client.create_election(
            factories.create_election_payload(
                jurisdiction_code="ST-05",
                election_name="2026 Special Election",
                certification_deadline_at="2026-11-02T17:00:00Z",
            ),
            DIRECTOR,
        )
        validate_error(bad_registration, ApiErrorId.ERR_INVALID_TIME_WINDOW.value, 422)

        bad_amendment = api_client.patch_election(
            election_id, {"certification_deadline_at": "2026-11-01T17:00:00Z"}, DIRECTOR
        )
        validate_error(bad_amendment, ApiErrorId.ERR_INVALID_TIME_WINDOW.value, 422)
        assertions.assert_same_instant(
            fixtures.read_election(election_id)["certification_deadline_at"],
            "2026-11-24T17:00:00Z",
            "certification_deadline_at",
        )

        empty_session = api_client.create_manual_tally(
            factories.create_manual_tally_payload(
                scenario["target_audit_batch"]["id"],
                team_id,
                "2026-11-05T11:00:00Z",
                "2026-11-05T11:00:00Z",
                counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
            ),
            make_tally_team_lead_headers(team_id),
        )
        validate_error(empty_session, ApiErrorId.ERR_INVALID_TIME_WINDOW.value, 422)

        third_credential = api_client.create_observer_credential(
            factories.create_observer_credential_payload(
                election_id,
                organization_name="Third Observer",
                room_code="ROOM-A",
                access_start_at="2026-11-06T00:00:00Z",
                access_end_at="2026-11-05T08:00:00Z",
            ),
            DIRECTOR,
        )

        validate_error(third_credential, ApiErrorId.ERR_INVALID_TIME_WINDOW.value, 422)
        _, credential_meta = validate_paginated(
            api_client.list_observer_credentials(
                DIRECTOR, params={"room_code": "ROOM-A", "limit": 10}
            )
        )
        assert credential_meta["total_count"] == 2
        _, election_meta = validate_paginated(
            api_client.list_elections(DIRECTOR, params={"limit": 10})
        )
        assert election_meta["total_count"] == 1
        _, tally_meta = validate_paginated(
            api_client.list_manual_tallies(
                DIRECTOR, params={"tally_team_id": team_id, "limit": 10}
            )
        )
        assert tally_meta["total_count"] == 0


class TestCandidateVocabulary:
    """Every vote map and every determination is measured against candidate_names."""

    def test_four_payload_shapes_share_the_rule_and_no_vote_is_the_one_exception(self):
        """PRD §2.9: "Vote-map keys equal the contest's `candidate_names` exactly — otherwise
        `ERR_CANDIDATE_NAME_UNKNOWN`. Applies to recording canvass results, single and bulk
        ballot-batch registration, hand-tally editing, ballot-interpretation referral and recount
        completion. Missing candidate keys, unknown keys, and a `proposed_determination` that
        names neither a candidate nor the literal `NO_VOTE` all land here." §3.7: "a
        `proposed_determination` that must be either one of the contest's `candidate_names` or the
        literal string `NO_VOTE`; anything else is refused as an unknown candidate name."

        Design: Corner/errors/vote_maps_and_determinations_must_name_exactly_the_declared_candidates
        """
        # The sibling contest is registered before C1 is canvassed: PRD §3.1 requires
        # the election to still be `OPEN` when a canvass is recorded, and §2.9 tier 14
        # (`ERR_INVALID_ELECTION_STATE`) precedes tier 27
        # (`ERR_CANDIDATE_NAME_UNKNOWN`), so a sibling added after the election has
        # already cascaded to `CANVASSED` could never reach the vote-map rule.
        scenario = fixtures.setup_draft_tally(
            counted_votes={"ALVAREZ": 520, "BRENNAN": 478},
            ambiguous_ballot_count=2,
            sibling_contests=[
                {
                    "contest_label": "C2",
                    "office_name": "State Treasurer",
                    "candidate_names": ["CHEN", "DAVIS"],
                    "ballots_cast": 3000,
                }
            ],
        )
        election_id = scenario["election"]["id"]
        team_id = scenario["team"]["id"]
        tally_id = scenario["manual_tally"]["id"]
        lead_headers = make_tally_team_lead_headers(team_id)
        sibling = scenario["sibling_contests"][0]

        bad_canvass = api_client.submit_canvass_results(
            sibling["id"], {"reported_votes": {"CHEN": 1600, "ALVAREZ": 1400}}, DIRECTOR
        )
        validate_error(bad_canvass, ApiErrorId.ERR_CANDIDATE_NAME_UNKNOWN.value, 422)
        assert fixtures.read_contest(sibling["id"])["status"] == "PENDING_CANVASS"

        incomplete_machine_map = api_client.create_ballot_batch(
            factories.create_ballot_batch_payload(
                election_id,
                sibling["id"],
                batch_label="B-101",
                machine_votes={"CHEN": 1000},
                current_seal_number="SEAL-101",
            ),
            CUSTODY_OFFICER,
        )
        validate_error(incomplete_machine_map, ApiErrorId.ERR_CANDIDATE_NAME_UNKNOWN.value, 422)

        foreign_key_in_patch = api_client.patch_manual_tally(
            tally_id, {"counted_votes": {"ALVAREZ": 520, "CHEN": 478}}, lead_headers
        )
        validate_error(foreign_key_in_patch, ApiErrorId.ERR_CANDIDATE_NAME_UNKNOWN.value, 422)
        assert fixtures.read_manual_tally(tally_id)["counted_votes"] == {
            "ALVAREZ": 520,
            "BRENNAN": 478,
        }

        submitted = fixtures.submit_manual_tally(tally_id, team_id)
        assert submitted["net_error_votes"] == 8

        bad_determination = api_client.create_ballot_interpretation(
            factories.create_ballot_interpretation_payload(
                tally_id,
                ballot_ref="BAL-1",
                ambiguity_type="OVERVOTE",
                proposed_determination="CHEN",
            ),
            lead_headers,
        )
        validate_error(bad_determination, ApiErrorId.ERR_CANDIDATE_NAME_UNKNOWN.value, 422)

        accepted = validate_success(
            api_client.create_ballot_interpretation(
                factories.create_ballot_interpretation_payload(
                    tally_id,
                    ballot_ref="BAL-1",
                    ambiguity_type="OVERVOTE",
                    proposed_determination="NO_VOTE",
                ),
                lead_headers,
            ),
            201,
        )

        assertions.assert_ballot_interpretation(accepted)
        assert accepted["status"] == "PENDING"
        assert accepted["proposed_determination"] == "NO_VOTE"
        assert fixtures.read_manual_tally(tally_id)["status"] == "PENDING_ADJUDICATION"
        _, meta = validate_paginated(
            api_client.list_ballot_interpretations(
                DIRECTOR, params={"manual_tally_id": tally_id, "limit": 10}
            )
        )
        assert meta["total_count"] == 1


class TestAdjudicationBounds:
    """Referrals are bounded by the recorded ambiguity; votes are bounded by the member."""

    def test_a_repeat_reference_a_third_referral_and_a_second_vote_are_each_refused(self):
        """PRD §3.7: "The tally's `ambiguous_ballot_count` must exceed the number of referrals of
        that tally already `PENDING`, or the referral is refused because the interpretation limit
        is exceeded ... and a repeated `ballot_ref` within the tally is refused as a duplicate
        ballot reference." §3.7: "A member may vote at most once per referral: a second vote from
        the same identity is refused as a duplicate board vote." §3.7: "An adjudicated
        determination is applied to the tally immediately: the tally's `ambiguous_ballot_count` is
        decreased by one, and either its `no_vote_count` is increased by one when
        `final_determination` is `NO_VOTE`, or its `counted_votes` entry for the determined
        candidate is increased by one."

        Design: Corner/errors/adjudication_referrals_and_board_votes_are_each_bounded
        """
        scenario = fixtures.setup_submitted_tally(
            counted_votes={"ALVAREZ": 520, "BRENNAN": 478}, ambiguous_ballot_count=2
        )
        team_id = scenario["team"]["id"]
        tally_id = scenario["manual_tally"]["id"]
        lead_headers = make_tally_team_lead_headers(team_id)
        first_referral = fixtures.refer_ballot_interpretation(
            tally_id,
            team_id,
            ballot_ref="BAL-1",
            ambiguity_type="OVERVOTE",
            proposed_determination="ALVAREZ",
        )

        repeated_reference = api_client.create_ballot_interpretation(
            factories.create_ballot_interpretation_payload(
                tally_id,
                ballot_ref="BAL-1",
                ambiguity_type="STRAY_MARK",
                proposed_determination="BRENNAN",
            ),
            lead_headers,
        )
        validate_error(repeated_reference, ApiErrorId.ERR_DUPLICATE_BALLOT_REF.value, 409)

        second_referral = fixtures.refer_ballot_interpretation(
            tally_id,
            team_id,
            ballot_ref="BAL-2",
            ambiguity_type="PARTIAL_MARK",
            proposed_determination="ALVAREZ",
        )
        over_the_limit = api_client.create_ballot_interpretation(
            factories.create_ballot_interpretation_payload(
                tally_id,
                ballot_ref="BAL-3",
                ambiguity_type="DAMAGED",
                proposed_determination="NO_VOTE",
            ),
            lead_headers,
        )
        validate_error(over_the_limit, ApiErrorId.ERR_INTERPRETATION_LIMIT_EXCEEDED.value, 409)

        first_vote = fixtures.cast_board_vote(
            first_referral["id"], BOARD_ONE, "DEM", "ACCEPT"
        )
        assert first_vote["votes_cast"] == 1

        second_vote_same_member = api_client.cast_ballot_interpretation_vote(
            first_referral["id"],
            factories.board_vote_payload("DEM", "REJECT"),
            make_canvassing_board_member_headers(BOARD_ONE),
        )
        validate_error(second_vote_same_member, ApiErrorId.ERR_DUPLICATE_BOARD_VOTE.value, 409)
        after_refusal = fixtures.read_ballot_interpretation(first_referral["id"])
        assert after_refusal["votes_cast"] == 1
        assert after_refusal["accept_count"] == 1

        fixtures.cast_board_vote(first_referral["id"], BOARD_TWO, "REP", "ACCEPT")
        adjudicated = fixtures.cast_board_vote(
            first_referral["id"], BOARD_THREE, "DEM", "ACCEPT"
        )

        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["final_determination"] == "ALVAREZ"
        assert adjudicated["votes_cast"] == 3
        assert adjudicated["accept_count"] == 3
        assert adjudicated["quorum_met"] is True

        vote_after_adjudication = api_client.cast_ballot_interpretation_vote(
            first_referral["id"],
            factories.board_vote_payload("REP", "REJECT"),
            make_canvassing_board_member_headers(BOARD_FOUR),
        )
        validate_error(
            vote_after_adjudication, ApiErrorId.ERR_INVALID_INTERPRETATION_STATE.value, 409
        )
        tally = fixtures.read_manual_tally(tally_id)
        assert tally["ambiguous_ballot_count"] == 1
        assert tally["counted_votes"]["ALVAREZ"] == 521
        assert tally["net_error_votes"] == 7
        assert tally["status"] == "PENDING_ADJUDICATION"
        assertions.assert_ballot_accounting_identity(tally, 1000)
        assert fixtures.read_ballot_interpretation(second_referral["id"])["status"] == "PENDING"


class TestRecountFilerAndScopeGates:
    """The money is bound to the filer; the scope is bound to the live recount."""

    def test_another_representative_is_refused_and_an_overlapping_scope_is_refused(self):
        """PRD §2.1: "only the `CandidateRepresentative` whose `X-User-ID` was stored as a
        recount's `requested_by_user_id` may fund or withdraw it (any other representative is
        refused with `ERR_NOT_REQUESTING_PARTY`)". §2.9: "The requested recount scope does not
        overlap the scope of a live recount on the same contest — otherwise
        `ERR_RECOUNT_SCOPE_OVERLAP`."

        Design: Corner/errors/only_the_filing_representative_may_fund_and_scopes_may_not_overlap
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]
        batches = fixtures.list_batches(contest_id)
        first = fixtures.batch_by_label(batches, "B-001")["id"]
        second = fixtures.batch_by_label(batches, "B-002")["id"]
        third = fixtures.batch_by_label(batches, "B-003")["id"]
        fourth = fixtures.batch_by_label(batches, "B-004")["id"]
        filed = fixtures.file_recount(
            contest_id,
            requester_user_id=CANDIDATE_REP_ONE,
            scope="PARTIAL_BATCHES",
            scope_batch_ids=[first, second],
            requested_by_candidate_name="BRENNAN",
        )
        assert filed["required_deposit_cents"] == 130000
        stranger = make_candidate_representative_headers(CANDIDATE_REP_TWO)

        wrong_payer = api_client.post_recount_deposit(
            filed["id"], {"amount_cents": 130000}, stranger
        )
        validate_error(wrong_payer, ApiErrorId.ERR_NOT_REQUESTING_PARTY.value, 403)

        wrong_withdrawer = api_client.withdraw_recount(
            filed["id"], {"reason": "Not my filing"}, stranger
        )
        validate_error(wrong_withdrawer, ApiErrorId.ERR_NOT_REQUESTING_PARTY.value, 403)
        untouched = fixtures.read_recount(filed["id"])
        assert untouched["status"] == "REQUESTED"
        assert untouched["deposit_paid_cents"] == 0

        funded = validate_success(
            api_client.post_recount_deposit(
                filed["id"],
                {"amount_cents": 130000},
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            )
        )
        assert funded["deposit_status"] == "HELD"
        assert funded["status"] == "DEPOSIT_HELD"
        assert funded["deposit_paid_cents"] == 130000

        overlapping = api_client.create_recount(
            factories.create_recount_payload(
                contest_id,
                fixtures.read_contest(contest_id)["version"],
                scope="PARTIAL_BATCHES",
                scope_batch_ids=[second, third],
                requested_by_candidate_name="BRENNAN",
            ),
            make_candidate_representative_headers(CANDIDATE_REP_ONE),
        )
        validate_error(overlapping, ApiErrorId.ERR_RECOUNT_SCOPE_OVERLAP.value, 409)

        disjoint = validate_success(
            api_client.create_recount(
                factories.create_recount_payload(
                    contest_id,
                    fixtures.read_contest(contest_id)["version"],
                    scope="PARTIAL_BATCHES",
                    scope_batch_ids=[third, fourth],
                    requested_by_candidate_name="BRENNAN",
                ),
                make_candidate_representative_headers(CANDIDATE_REP_ONE),
            ),
            201,
        )

        assertions.assert_recount(disjoint)
        assert disjoint["required_deposit_cents"] == 130000
        assert disjoint["status"] == "REQUESTED"
        assert fixtures.read_contest(contest_id)["open_recount_count"] == 2


class TestCloseGateOrderWithADeadlock:
    """A deadlocked ballot is reported ahead of the finding that is also still open."""

    def test_the_deadlock_survives_the_resolution_and_termination_is_the_only_exit(self):
        """PRD §2.9: "Closing an audit requires every drawn batch `COUNTED`, every physical batch
        `RESEALED`, no interpretation `PENDING` or `DEADLOCKED`, and no finding `OPEN` or
        `ESCALATED` — otherwise `ERR_TALLY_INCOMPLETE`, `ERR_BATCH_NOT_RETURNED`,
        `ERR_DEADLOCKED_INTERPRETATION_PENDING` or `ERR_UNRESOLVED_DISCREPANCY`, evaluated in
        exactly that listed order so the earliest incomplete stage is the one reported." §3.7:
        "Once quorum is met, an equal `accept_count` and `reject_count` makes the referral
        `DEADLOCKED` with `final_determination` left null". §3.7: "Both `ADJUDICATED` and
        `DEADLOCKED` are terminal for the referral."

        Design: Corner/errors/a_deadlocked_determination_blocks_the_close_ahead_of_the_open_finding
        """
        scenario = fixtures.setup_canvassed_contest()
        team = fixtures.create_bipartisan_team(scenario["election"]["id"])
        scenario.update(
            fixtures.setup_audit_round_one(
                scenario["contest"]["id"], audit_type="FIXED_PERCENTAGE"
            )
        )
        audit_id = scenario["audit"]["id"]
        drawn = scenario["audit_batches"]
        assert len(drawn) == 2
        counts = [
            ({"ALVAREZ": 520, "BRENNAN": 478}, 2, (CANVASS_DAY, "2026-11-05T11:00:00Z")),
            (
                {"ALVAREZ": 525, "BRENNAN": 475},
                0,
                ("2026-11-05T11:30:00Z", "2026-11-05T13:30:00Z"),
            ),
        ]
        tallies = []
        for drawn_row, (votes, ambiguous, (start_at, end_at)) in zip(drawn, counts):
            physical = fixtures.read_batch(drawn_row["ballot_batch_id"])
            fixtures.retrieve_batch(
                drawn_row["id"], physical["id"], physical["current_seal_number"]
            )
            tally = fixtures.open_manual_tally(
                drawn_row["id"],
                team["id"],
                session_start_at=start_at,
                session_end_at=end_at,
                counted_votes=votes,
                ambiguous_ballot_count=ambiguous,
            )
            tallies.append(fixtures.submit_manual_tally(tally["id"], team["id"]))
        for drawn_row in drawn:
            physical = fixtures.read_batch(drawn_row["ballot_batch_id"])
            fixtures.return_batch(
                drawn_row["id"], f"{physical['current_seal_number']}R"
            )
        referral = fixtures.refer_ballot_interpretation(
            tallies[0]["id"],
            team["id"],
            ballot_ref="BAL-1",
            ambiguity_type="STRAY_MARK",
            proposed_determination="ALVAREZ",
        )
        fixtures.cast_board_vote(referral["id"], BOARD_ONE, "DEM", "ACCEPT")
        fixtures.cast_board_vote(referral["id"], BOARD_TWO, "REP", "REJECT")
        deadlocked = fixtures.cast_board_vote(referral["id"], BOARD_THREE, "DEM", "ABSTAIN")
        assert deadlocked["status"] == "DEADLOCKED"
        assert deadlocked["final_determination"] is None
        assert deadlocked["quorum_met"] is True
        assert deadlocked["accept_count"] == 1
        assert deadlocked["reject_count"] == 1
        finding = fixtures.document_discrepancy(
            fixtures.only_discrepancy(tallies[0]["id"])["id"]
        )
        blocking_tally = fixtures.read_manual_tally(tallies[0]["id"])
        assert blocking_tally["status"] == "SUBMITTED"
        assert blocking_tally["ambiguous_ballot_count"] == 2
        assert blocking_tally["net_error_votes"] == 8

        first_close = api_client.close_audit(audit_id, AUDIT_MANAGER)

        validate_error(
            first_close, ApiErrorId.ERR_DEADLOCKED_INTERPRETATION_PENDING.value, 409
        )

        resolved = fixtures.resolve_discrepancy(finding["id"])
        assert resolved["status"] == "RESOLVED"
        second_close = api_client.close_audit(audit_id, AUDIT_MANAGER)

        validate_error(
            second_close, ApiErrorId.ERR_DEADLOCKED_INTERPRETATION_PENDING.value, 409
        )

        terminated = fixtures.terminate_audit(
            audit_id, terminated_reason="Board deadlock on voter intent"
        )

        assert terminated["status"] == "TERMINATED"
        assert terminated["public_report_published"] is True
        assert terminated["terminated_reason"] == "Board deadlock on voter intent"
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == "SUPERSEDED"
        assert fixtures.read_election(scenario["election"]["id"])["open_audit_count"] == 0
        for tally in tallies:
            assert fixtures.read_manual_tally(tally["id"])["status"] == "SUBMITTED"


class TestEquipmentActionGate:
    """Only the equipment action gates the finding, and only once it is verified."""

    def test_the_finding_stays_open_until_a_second_member_verifies_the_equipment_action(self):
        """PRD §3.6: "A finding is resolved from `DOCUMENTED` or from `ESCALATED` with a
        `resolution_note`, provided every corrective action of that finding whose `category` is
        `EQUIPMENT` has reached `VERIFIED` or `CANCELLED`; otherwise the request is refused for an
        unverified equipment action." §3.6: "`COMPLETED` may become `VERIFIED`, which requires
        that the acting member's identity differ from `completed_by_user_id` ... and which stamps
        `verified_by_user_id` and `verified_at`."

        Design: Corner/errors/equipment_findings_close_only_after_an_independent_verification
        """
        scenario = fixtures.setup_documented_discrepancy(
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478}
        )
        finding = scenario["discrepancy"]
        assert finding["magnitude_votes"] == 6
        assert finding["discrepancy_type"] == "OVERSTATEMENT"
        equipment = fixtures.create_corrective_action(
            finding["id"],
            category="EQUIPMENT",
            description="Recalibrate the precinct scanner that produced the overstatement.",
            due_at="2026-11-20T17:00:00Z",
        )
        process = fixtures.create_corrective_action(
            finding["id"],
            category="PROCESS",
            description="Retrain the counting board on blank-ballot handling.",
            due_at="2026-11-22T17:00:00Z",
        )
        board_one_headers = make_canvassing_board_member_headers(BOARD_ONE)
        closing_note = {"resolution_note": "Closing on scanner recalibration."}

        while_open = api_client.resolve_discrepancy(
            finding["id"], closing_note, board_one_headers
        )
        validate_error(while_open, ApiErrorId.ERR_EQUIPMENT_ACTION_UNVERIFIED.value, 409)

        fixtures.transition_corrective_action(equipment["id"], "IN_PROGRESS")
        while_in_progress = api_client.resolve_discrepancy(
            finding["id"], closing_note, board_one_headers
        )
        validate_error(while_in_progress, ApiErrorId.ERR_EQUIPMENT_ACTION_UNVERIFIED.value, 409)

        completed = fixtures.transition_corrective_action(
            equipment["id"], "COMPLETED", note="Scanner recalibrated."
        )
        assert completed["completed_by_user_id"] == BOARD_ONE
        while_completed = api_client.resolve_discrepancy(
            finding["id"], closing_note, board_one_headers
        )
        validate_error(while_completed, ApiErrorId.ERR_EQUIPMENT_ACTION_UNVERIFIED.value, 409)

        verified = fixtures.transition_corrective_action(
            equipment["id"], "VERIFIED", board_user_id=BOARD_TWO
        )

        assertions.assert_corrective_action(verified)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == BOARD_TWO
        assertions.assert_same_instant(verified["verified_at"], CANVASS_DAY, "verified_at")

        resolved = validate_success(
            api_client.resolve_discrepancy(finding["id"], closing_note, board_one_headers)
        )

        assert resolved["status"] == "RESOLVED"
        assertions.assert_same_instant(resolved["resolved_at"], CANVASS_DAY, "resolved_at")
        never_gating = fixtures.read_corrective_action(process["id"])
        assert never_gating["status"] == "OPEN"
        assert never_gating["version"] == 1
