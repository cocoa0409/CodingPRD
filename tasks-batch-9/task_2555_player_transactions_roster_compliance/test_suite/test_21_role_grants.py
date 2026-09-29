"""The role matrix from both sides: what each grant opens and what it closes."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as fac
from test_helpers.api_errors import ERR_ACTOR_SCOPE_VIOLATION, ERR_UNAUTHORIZED
from test_helpers.fixtures import League
from test_helpers.test_users import (
    make_agent_headers,
    make_cap_analyst_headers,
    make_medical_officer_headers,
)

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"

TERMS = {
    "years": 3,
    "base_salary_cents": 80_000_000,
    "signing_bonus_cents": 10_000_000,
    "start_season_year": 2026,
}


def _club(league: League) -> Dict[str, Any]:
    """One club with room to spare."""
    return league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
    )


class TestEachRoleRunsItsOwnExclusiveOperation:
    """Four roles, four writes only that role may make, all four accepted."""

    @staticmethod
    def _club_two_players_and_one_tender(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        signee = league.register_player(full_name="Ray Alder", position="QB")
        tendered = league.register_player(
            full_name="Dov Keller", position="DB", accrued_active_days=400
        )
        tender = league.issue_tender(
            club["id"], tendered["id"], "RESTRICTED_TENDER", "FIRST_ROUND",
            50_000_000,
        )
        return {
            "club": club,
            "signee": signee,
            "tendered": tendered,
            "tender": tender,
        }

    def test_all_four_roles_are_served_on_the_writes_reserved_to_them(
        self, league: League
    ) -> None:
        """Registration, filing, scheduling and responding each find their owner.

        PRD 4: "| POST | `/players` | Registers a player with the prior-service day
        buckets the league has on file; all service and eligibility fields are derived.
        | `LeagueOfficer` |"

        PRD 4: "| POST | `/transactions` | Opens a draft filing, carrying contract
        terms, a cited injury designation or a target designation according to type. |
        `TeamCapAnalyst` |"

        PRD 4: "| POST | `/physical-exams` | Schedules a physical inside a half-open
        examination window, one scheduled window per player at a time. |
        `TeamMedicalOfficer` |"

        PRD 4: "| POST | `/qualifying-offers/{id}/respond` | Accepts or declines a
        tender; acceptance cascades into a draft signing filing, a pending contract and
        a cap recompute. | `PlayerAgent` |"

        Design: Corner/rbac/each_role_can_run_its_own_exclusive_operation
        """
        world = self._club_two_players_and_one_tender(league)

        registered = get_success_data(
            league.api.create_player(
                fac.player_payload(full_name="Milo Sarr", position="WR"),
                league.officer,
            ),
            201,
        )
        assert registered["roster_designation"] == "UNROSTERED", (
            "the league office's new player belongs to nobody yet, got "
            f"{registered['roster_designation']}"
        )

        filing = get_success_data(
            league.api.create_transaction(
                fac.signing_payload(
                    world["club"]["id"], world["signee"]["id"],
                    world["club"]["version"], **TERMS,
                ),
                make_cap_analyst_headers(world["club"]["id"]),
            ),
            201,
        )
        assert filing["status"] == "DRAFT", (
            f"the analyst's filing is born a draft, got {filing['status']}"
        )

        exam = get_success_data(
            league.api.create_physical_exam(
                fac.physical_exam_payload(
                    world["signee"]["id"], world["club"]["id"], "ENTRY_PHYSICAL",
                    EXAM_START, EXAM_END, transaction_id=filing["id"],
                ),
                make_medical_officer_headers(world["club"]["id"]),
            ),
            201,
        )
        assert exam["status"] == "SCHEDULED", (
            f"the medical officer's exam is booked, got {exam['status']}"
        )

        answered = get_success_data(
            league.api.respond_to_tender(
                world["tender"]["id"], fac.tender_response_payload("DECLINE"),
                make_agent_headers(world["tendered"]["id"]),
            )
        )
        assert answered["status"] == "DECLINED", (
            f"the agent's answer is recorded, got {answered['status']}"
        )

    def test_the_analysts_draft_already_consumes_the_clubs_provisional_room(
        self, league: League
    ) -> None:
        """The filing that only the analyst may open moves money immediately.

        PRD 3.3: "That is the moment a not-yet-approved contract begins consuming
        provisional cap space, which is why a `SIGNING` create is itself subject to the
        provisional cap ceiling and can be refused with `ERR_CAP_LIMIT_EXCEEDED`."

        Design: Corner/rbac/each_role_can_run_its_own_exclusive_operation
        """
        world = self._club_two_players_and_one_tender(league)

        league.open_filing(
            fac.signing_payload(
                world["club"]["id"], world["signee"]["id"],
                world["club"]["version"], **TERMS,
            ),
            world["club"]["id"],
        )

        club = league.club(world["club"]["id"])
        assert club["provisional_cap_committed_cents"] == 83_333_333, (
            "the draft filing's pending contract already counts against the "
            f"provisional variant, got {club['provisional_cap_committed_cents']}"
        )
        assert club["final_cap_committed_cents"] == 0, (
            "while the final variant still ignores it, got "
            f"{club['final_cap_committed_cents']}"
        )


class TestClubRolesCannotReachTheLeagueOfficersDecision:
    """Even the analyst who filed cannot decide, because the role is not granted."""

    @staticmethod
    def _filed_signing(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"], **TERMS
        )
        league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
        )
        league.submit_filing(filing["id"], club["id"])
        return {"club": club, "player": player, "filing_id": filing["id"]}

    def test_neither_club_role_may_decide_a_filing(self, league: League) -> None:
        """The filing is perfectly decidable; the club-side roles simply are not.

        PRD 2.8: "The role is listed among the endpoint's authorised roles — otherwise
        `ERR_UNAUTHORIZED` (403)."

        PRD 4: "| POST | `/transactions/{id}/decide` | Approves or rejects a submitted
        filing, applying every roster, contract, bonus, cap and compliance side effect
        on approval. | `LeagueOfficer` |"

        Design: Corner/rbac/club_roles_cannot_reach_the_league_officers_decision
        """
        world = self._filed_signing(league)

        analyst_answer = league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(),
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(analyst_answer, ERR_UNAUTHORIZED, 403)

        medic_answer = league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(),
            make_medical_officer_headers(world["club"]["id"]),
        )
        validate_error(medic_answer, ERR_UNAUTHORIZED, 403)

        filing = league.filing(world["filing_id"])
        assert filing["status"] == "FILED", (
            f"neither refusal moved the filing, got {filing['status']}"
        )
        assert filing["decided_at"] is None, (
            f"and neither stamped a decision, got {filing['decided_at']}"
        )

    def test_the_same_decision_from_the_league_office_runs_the_cascade(
        self, league: League
    ) -> None:
        """The refusal was about the role, so the officer's identical call succeeds.

        PRD 3.3: "- **`SIGNING`**: the linked contract moves `PENDING_APPROVAL →
        ACTIVE`; its bonus allocation rows are created; `option_status` becomes `PENDING`
        when the contract carries an option and stays `NOT_APPLICABLE` otherwise; the
        player's designation becomes `PRACTICE_SQUAD` for a practice-squad contract and
        `ACTIVE` otherwise; and `current_team_id` becomes the filing club."

        Design: Corner/rbac/club_roles_cannot_reach_the_league_officers_decision
        """
        world = self._filed_signing(league)
        league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(),
            make_cap_analyst_headers(world["club"]["id"]),
        )
        league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(),
            make_medical_officer_headers(world["club"]["id"]),
        )

        approved = league.approve_filing(world["filing_id"])
        assert approved["status"] == "APPROVED", (
            f"the league office may decide, got {approved['status']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            f"the player joins the active roster, got {player['roster_designation']}"
        )
        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 1, (
            f"the club's headcount follows, got {club['active_roster_count']}"
        )
        assert club["final_cap_committed_cents"] == 83_333_333, (
            "and an approved contract now counts in the final variant too, got "
            f"{club['final_cap_committed_cents']}"
        )


class TestTheCapDeskAndTheMedicalRoomAreClosedToEachOther:
    """Two peer roles behind one club id, each barred from the other's write."""

    @staticmethod
    def _draft_filing_and_a_scheduled_exam(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"], **TERMS
        )
        exam = league.schedule_exam(
            club["id"], player["id"], "ENTRY_PHYSICAL", EXAM_START, EXAM_END,
            transaction_id=filing["id"],
        )
        return {
            "club": club,
            "player": player,
            "filing_id": filing["id"],
            "exam_id": exam["id"],
        }

    def test_each_club_role_is_refused_on_the_others_write(
        self, league: League
    ) -> None:
        """Sharing the club's identifier grants nothing across the wall.

        PRD 2.8: "The role is listed among the endpoint's authorised roles — otherwise
        `ERR_UNAUTHORIZED` (403)."

        PRD 4: "| POST | `/transactions/{id}/file` | Submits a draft filing to the
        league office, inside the processing window and on or before its filing
        deadline. | `TeamCapAnalyst` |"

        PRD 4: "| POST | `/physical-exams/{id}/record-result` | Records a physical's
        outcome; a failed trade physical voids its trade and releases both clubs' review
        slots. | `TeamMedicalOfficer` |"

        Design: Corner/rbac/the_cap_desk_and_the_medical_room_are_closed_to_each_other
        """
        world = self._draft_filing_and_a_scheduled_exam(league)

        medic_files = league.api.file_transaction(
            world["filing_id"], make_medical_officer_headers(world["club"]["id"])
        )
        validate_error(medic_files, ERR_UNAUTHORIZED, 403)

        analyst_records = league.api.record_exam_result(
            world["exam_id"], fac.exam_result_payload("PASSED", CLOCK),
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(analyst_records, ERR_UNAUTHORIZED, 403)

        filing = league.filing(world["filing_id"])
        assert filing["status"] == "DRAFT", (
            f"the filing was never submitted, got {filing['status']}"
        )
        exam = league.exam(world["exam_id"])
        assert exam["status"] == "SCHEDULED", (
            f"and the exam was never recorded, got {exam['status']}"
        )

    def test_each_write_succeeds_for_the_role_that_owns_it(
        self, league: League
    ) -> None:
        """The medical officer records, the analyst files, and both stamps land.

        PRD 3.5: "A passed result moves the exam `SCHEDULED → PASSED` and sets
        `expires_at` to `performed_at` plus 14 days."

        PRD 3.3: "On success the server records `filed_at` as the logical clock and
        `filed_by_user_id` as the acting identifier."

        Design: Corner/rbac/the_cap_desk_and_the_medical_room_are_closed_to_each_other
        """
        world = self._draft_filing_and_a_scheduled_exam(league)
        league.api.file_transaction(
            world["filing_id"], make_medical_officer_headers(world["club"]["id"])
        )
        league.api.record_exam_result(
            world["exam_id"], fac.exam_result_payload("PASSED", CLOCK),
            make_cap_analyst_headers(world["club"]["id"]),
        )

        passed = league.record_exam(
            world["exam_id"], world["club"]["id"], "PASSED", CLOCK
        )
        assert passed["status"] == "PASSED", (
            f"the medical officer's own write is accepted, got {passed['status']}"
        )
        assert passed["expires_at"] == "2026-08-24T14:00:00.000Z", (
            f"a pass is valid for 14 days, got {passed['expires_at']}"
        )

        filed = league.submit_filing(world["filing_id"], world["club"]["id"])
        assert filed["status"] == "FILED", (
            f"and the analyst's own write is too, got {filed['status']}"
        )
        assert filed["filed_by_user_id"] == world["club"]["id"], (
            "the filer of record is the acting analyst's club, got "
            f"{filed['filed_by_user_id']}"
        )


class TestAnEntityBackedRoleNeedsARealBackingRecord:
    """The grant is right, the identifier is not the kind of record it must be."""

    def test_an_analyst_presenting_a_player_id_is_refused(
        self, league: League
    ) -> None:
        """The endpoint admits the role, so the backing-entity rule is what answers.

        PRD 2.8: "For an entity-backed role, `X-User-ID` is the `id` of an existing
        instance of its backing entity — a `Team` for `TeamCapAnalyst` and
        `TeamMedicalOfficer`, a `Player` for `PlayerAgent` — otherwise
        `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/an_entity_backed_role_needs_a_real_backing_record
        """
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")

        response = league.api.create_transaction(
            fac.signing_payload(
                club["id"], player["id"], club["version"], **TERMS
            ),
            make_cap_analyst_headers(player["id"]),
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)

        filings, filing_meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert filing_meta["total_count"] == 0, (
            f"no filing should exist, got {filing_meta['total_count']}"
        )
        assert filings == [], f"the filing list should be empty, got {filings}"

        contracts, contract_meta = validate_paginated(
            league.api.list_contracts(league.officer)
        )
        assert contract_meta["total_count"] == 0, (
            f"and no contract either, got {contract_meta['total_count']}"
        )
        assert contracts == [], f"the contract list should be empty, got {contracts}"

        after = league.club(club["id"])
        assert after["version"] == 1, (
            f"the refused create bumped no club version, got {after['version']}"
        )


class TestOnlyTheTenderedPlayersOwnAgentMayRespond:
    """An agent for a real but different player is inside the role and outside the scope."""

    @staticmethod
    def _tender_and_a_stranger(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        tendered = league.register_player(
            full_name="Dov Keller", position="DB", accrued_active_days=400
        )
        stranger = league.register_player(full_name="Ray Alder", position="QB")
        tender = league.issue_tender(
            club["id"], tendered["id"], "RESTRICTED_TENDER", "FIRST_ROUND",
            50_000_000,
        )
        return {
            "club": club,
            "tendered": tendered,
            "stranger": stranger,
            "tender": tender,
        }

    def test_another_players_agent_cannot_answer_this_tender(
        self, league: League
    ) -> None:
        """The identifier is a real player, which is exactly why scope answers.

        PRD 2.8: "Actor scope: the acting club owns the resource (compared against
        `Transaction.team_id`, `WaiverRequest.from_team_id`, `WaiverClaim.claiming_team_id`,
        `Contract.team_id`, `InjuryDesignation.team_id` or `PhysicalExam.team_id`) or,
        for trade actions, is the club whose turn the negotiation assigns; the acting
        player is the contract's `player_id` or the tender's `player_id` — otherwise
        `ERR_ACTOR_SCOPE_VIOLATION` (403)."

        Design: Corner/rbac/only_the_tendered_players_own_agent_may_respond
        """
        world = self._tender_and_a_stranger(league)

        response = league.api.respond_to_tender(
            world["tender"]["id"], fac.tender_response_payload("ACCEPT"),
            make_agent_headers(world["stranger"]["id"]),
        )
        validate_error(response, ERR_ACTOR_SCOPE_VIOLATION, 403)

        tender = league.tender(world["tender"]["id"])
        assert tender["status"] == "ISSUED", (
            f"the tender still awaits its own agent, got {tender['status']}"
        )
        assert tender["player_id"] == world["tendered"]["id"], (
            f"and still names the tendered player, got {tender['player_id']}"
        )
        assert tender["resulting_transaction_id"] is None, (
            "the refused acceptance cascaded nothing, got "
            f"{tender['resulting_transaction_id']}"
        )

        filings, meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert meta["total_count"] == 0, (
            f"no signing filing was created, got {meta['total_count']}"
        )
        assert filings == [], f"the filing list should be empty, got {filings}"

    def test_the_rightful_agent_is_served_immediately_afterwards(
        self, league: League
    ) -> None:
        """The refusal was about which player, not about the role or the tender.

        PRD 3.8: "A decline moves the tender `ISSUED → DECLINED` and changes nothing
        else — no filing is created."

        PRD 3.8: "Either answer stamps `responded_at` with the logical clock."

        Design: Corner/rbac/only_the_tendered_players_own_agent_may_respond
        """
        world = self._tender_and_a_stranger(league)
        league.api.respond_to_tender(
            world["tender"]["id"], fac.tender_response_payload("ACCEPT"),
            make_agent_headers(world["stranger"]["id"]),
        )

        answered = league.respond_to_tender(
            world["tender"]["id"], world["tendered"]["id"], "DECLINE"
        )
        assert answered["status"] == "DECLINED", (
            f"the tendered player's agent may answer, got {answered['status']}"
        )
        assert answered["responded_at"] == "2026-08-10T14:00:00.000Z", (
            f"the answer is stamped on the clock, got {answered['responded_at']}"
        )
        assert answered["amount_cents"] == 66_000_000, (
            "the derived amount is untouched by either call, got "
            f"{answered['amount_cents']}"
        )
        assert answered["resulting_transaction_id"] is None, (
            "a decline writes nothing else, got "
            f"{answered['resulting_transaction_id']}"
        )


class TestTheOptionDecisionIsSharedByTheClubAndTheAgent:
    """One endpoint, two role families, each on the option kind that is theirs."""

    @staticmethod
    def _two_optioned_contracts(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        team_side = league.register_player(full_name="Ray Alder", position="QB")
        player_side = league.register_player(full_name="Dov Keller", position="DB")
        team_option = league.sign_onto_roster(
            club["id"], team_side["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=club["version"],
            option_type="TEAM_OPTION",
            option_deadline_at="2026-12-01T14:00:00Z",
            option_salary_cents=40_000_000,
            **TERMS,
        )
        player_option = league.sign_onto_roster(
            club["id"], player_side["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            option_type="PLAYER_OPTION",
            option_deadline_at="2026-12-01T14:00:00Z",
            option_salary_cents=15_000_000,
            years=1, base_salary_cents=12_000_000, signing_bonus_cents=0,
            start_season_year=2026,
        )
        return {
            "club": club,
            "team_side": team_side,
            "player_side": player_side,
            "team_option_contract_id": team_option["contract_id"],
            "player_option_contract_id": player_option["contract_id"],
        }

    def test_both_role_families_are_served_on_the_shared_endpoint(
        self, league: League
    ) -> None:
        """The analyst exercises the club's option and the agent exercises the player's.

        PRD 4: "| POST | `/contracts/{id}/option-decision` | Exercises or declines a
        contract option, writing the option dimension independently of contract status.
        | `TeamCapAnalyst`, `PlayerAgent` |"

        PRD 3.4: "An `EXERCISE` decision moves `option_status` `PENDING → EXERCISED`,
        replaces `base_salary_cents` with `option_salary_cents`, adds one to `years`,
        then recomputes the contract's current-season charge and the owning club's cap
        fields."

        Design: Corner/rbac/the_option_decision_is_shared_by_the_club_and_the_agent
        """
        world = self._two_optioned_contracts(league)

        before_team = league.contract(world["team_option_contract_id"])
        assert before_team["option_status"] == "PENDING", (
            f"the club's option awaits a decision, got {before_team['option_status']}"
        )
        before_player = league.contract(world["player_option_contract_id"])
        assert before_player["option_status"] == "PENDING", (
            f"and so does the player's, got {before_player['option_status']}"
        )

        by_analyst = league.decide_option(
            world["team_option_contract_id"], "EXERCISE",
            make_cap_analyst_headers(world["club"]["id"]),
            expected_contract_version=before_team["version"],
        )
        assert by_analyst["option_status"] == "EXERCISED", (
            "the analyst may exercise a team option, got "
            f"{by_analyst['option_status']}"
        )
        assert by_analyst["base_salary_cents"] == 40_000_000, (
            "the option salary replaces the base, got "
            f"{by_analyst['base_salary_cents']}"
        )
        assert by_analyst["years"] == 4, (
            f"and the deal gains a year, got {by_analyst['years']}"
        )

        by_agent = league.decide_option(
            world["player_option_contract_id"], "EXERCISE",
            make_agent_headers(world["player_side"]["id"]),
            expected_contract_version=before_player["version"],
        )
        assert by_agent["option_status"] == "EXERCISED", (
            f"the agent may exercise a player option, got {by_agent['option_status']}"
        )
        assert by_agent["base_salary_cents"] == 15_000_000, (
            f"on the same terms, got {by_agent['base_salary_cents']}"
        )
        assert by_agent["years"] == 2, (
            f"with the same extra year, got {by_agent['years']}"
        )

    def test_neither_exercise_disturbs_the_roster_or_the_contracts(
        self, league: League
    ) -> None:
        """Two exercised options, two active contracts, two rostered players.

        PRD 3.4: "In both cases the contract's `status` must be `ACTIVE`, the logical
        clock must be at or before `option_deadline_at` — a decision landing exactly on
        the deadline instant is accepted, and only a clock strictly later is refused with
        `ERR_OPTION_DEADLINE_PASSED` — and the request must carry
        `expected_contract_version` matching the contract's current `version`."

        PRD 3.4: "Who may decide is determined by which party holds the option."

        Design: Corner/rbac/the_option_decision_is_shared_by_the_club_and_the_agent
        """
        world = self._two_optioned_contracts(league)

        league.decide_option(
            world["team_option_contract_id"], "EXERCISE",
            make_cap_analyst_headers(world["club"]["id"]),
        )
        league.decide_option(
            world["player_option_contract_id"], "EXERCISE",
            make_agent_headers(world["player_side"]["id"]),
        )

        team_contract = league.contract(world["team_option_contract_id"])
        assert team_contract["status"] == "ACTIVE", (
            f"the club's contract is still active, got {team_contract['status']}"
        )
        player_contract = league.contract(world["player_option_contract_id"])
        assert player_contract["status"] == "ACTIVE", (
            f"and so is the player's, got {player_contract['status']}"
        )

        assert league.player(world["team_side"]["id"])["roster_designation"] == "ACTIVE", (
            "the first player is still on the active roster, got "
            f"{league.player(world['team_side']['id'])['roster_designation']}"
        )
        assert league.player(world["player_side"]["id"])["roster_designation"] == "ACTIVE", (
            "and so is the second, got "
            f"{league.player(world['player_side']['id'])['roster_designation']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 2, (
            f"the club fields both of them, got {club['active_roster_count']}"
        )
