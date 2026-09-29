"""Who may act: the identity ladder answering before any body is examined."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_ACTOR_SCOPE_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.fixtures import League
from test_helpers.test_users import NO_HEADERS

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"


def _club_and_free_agent(league: League) -> Dict[str, Any]:
    """One club with room to spare and one unrostered player to sign."""
    league.set_clock(CLOCK)
    club = league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
    )
    player = league.register_player(full_name="Ray Alder", position="QB")
    return {"club": club, "player": player}


def _signing_body(world: Dict[str, Any]) -> Dict[str, Any]:
    """A three-year offer whose every field is well formed."""
    return fac.signing_payload(
        world["club"]["id"], world["player"]["id"],
        world["club"]["version"], years=3,
        base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
        start_season_year=2026,
    )


class TestAnUnauthenticatedWrite:
    """A faultless body carried by no identity at all."""

    def test_a_filing_create_with_no_headers_is_refused_before_its_body_counts(
        self, league: League
    ) -> None:
        """The first rung fires on the missing headers, not on the payload.

        PRD 2.8: "Both `X-User-Role` and `X-User-ID` are present and non-blank —
        otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/errors/a_write_without_a_role_header_is_unauthenticated
        """
        world = _club_and_free_agent(league)

        response = league.api.create_transaction(_signing_body(world), NO_HEADERS)
        validate_error(response, ERR_UNAUTHENTICATED, 401)

        filings, meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert meta["total_count"] == 0, (
            f"the refused create wrote no filing, got {meta['total_count']}"
        )
        assert filings == [], f"the filing list should be empty, got {filings}"

        club = league.club(world["club"]["id"])
        assert club["version"] == 1, (
            "a create that never happened bumps no club version, got "
            f"{club['version']}"
        )
        assert club["provisional_cap_committed_cents"] == 0, (
            "and commits no provisional cap, got "
            f"{club['provisional_cap_committed_cents']}"
        )

        accepted = league.open_filing(_signing_body(world), world["club"]["id"])
        assert accepted["status"] == "DRAFT", (
            "the identical body is accepted once it carries an identity, which is "
            f"what makes the refusal a header refusal, got {accepted['status']}"
        )


class TestARoleThatIsNotAuthorisedForTheEndpoint:
    """An authenticated, entity-backed identity holding the wrong role."""

    def test_a_player_agent_cannot_open_a_filing_for_a_club(
        self, league: League
    ) -> None:
        """The agent exists and is authenticated; the endpoint is not his.

        PRD 2.8: "The role is listed among the endpoint's authorised roles —
        otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        PRD 4: "| POST | `/transactions` | Opens a draft filing, carrying contract
        terms, a cited injury designation or a target designation according to
        type. | `TeamCapAnalyst` |"

        Design: Corner/errors/a_player_agent_cannot_open_a_club_filing
        """
        world = _club_and_free_agent(league)

        response = league.api.create_transaction(
            _signing_body(world), League.agent(world["player"])
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)

        _, filing_meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert filing_meta["total_count"] == 0, (
            f"no filing should exist, got {filing_meta['total_count']}"
        )
        _, contract_meta = validate_paginated(
            league.api.list_contracts(league.officer)
        )
        assert contract_meta["total_count"] == 0, (
            "and no offered contract either, since the create never ran, got "
            f"{contract_meta['total_count']}"
        )

        club = league.club(world["club"]["id"])
        assert club["version"] == 1, (
            f"the club record is untouched, got version {club['version']}"
        )
        assert club["provisional_cap_committed_cents"] == 0, (
            "no contract is consuming provisional room, got "
            f"{club['provisional_cap_committed_cents']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player is still a free agent, got {player['roster_designation']}"
        )


class TestTheRightRoleAtTheWrongClub:
    """The role is authorised for the endpoint but the identity owns nothing here."""

    @staticmethod
    def _draft_filing_and_a_peer_club(league: League) -> Dict[str, Any]:
        world = _club_and_free_agent(league)
        world["peer"] = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        filing = league.open_signing(
            world["club"]["id"], world["player"]["id"],
            expected_team_version=world["club"]["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        world["filing_id"] = filing["id"]
        return world

    def test_a_peer_clubs_analyst_cannot_submit_another_clubs_filing(
        self, league: League
    ) -> None:
        """Scope is measured against the filing's own club, so the peer is refused.

        PRD 2.8: "Actor scope: the acting club owns the resource (compared against
        `Transaction.team_id`, `WaiverRequest.from_team_id`,
        `WaiverClaim.claiming_team_id`, `Contract.team_id`,
        `InjuryDesignation.team_id` or `PhysicalExam.team_id`) or, for trade
        actions, is the club whose turn the negotiation assigns; the acting player
        is the contract's `player_id` or the tender's `player_id` — otherwise
        `ERR_ACTOR_SCOPE_VIOLATION` (403). Applies to every team-scoped and
        player-scoped write."

        Design: Corner/errors/a_peer_clubs_analyst_cannot_file_another_clubs_filing
        """
        world = self._draft_filing_and_a_peer_club(league)

        response = league.api.file_transaction(
            world["filing_id"], League.analyst(world["peer"])
        )
        validate_error(response, ERR_ACTOR_SCOPE_VIOLATION, 403)

        filing = league.filing(world["filing_id"])
        assert filing["team_id"] == world["club"]["id"], (
            "the filing belongs to the other club, which is exactly why the scope "
            f"test failed, got {filing['team_id']}"
        )
        assert filing["status"] == "DRAFT", (
            f"the filing was never submitted, got {filing['status']}"
        )

    def test_the_refused_submission_records_no_filer_and_touches_no_peer(
        self, league: League
    ) -> None:
        """No filed_at, no filer, no peer-club write; the owner still succeeds.

        PRD 3.3: "On success the server records `filed_at` as the logical clock and
        `filed_by_user_id` as the acting identifier."

        Design: Corner/errors/a_peer_clubs_analyst_cannot_file_another_clubs_filing
        """
        world = self._draft_filing_and_a_peer_club(league)

        league.api.file_transaction(
            world["filing_id"], League.analyst(world["peer"])
        )

        filing = league.filing(world["filing_id"])
        assert filing["filed_at"] is None, (
            f"no submission instant should be stamped, got {filing['filed_at']}"
        )
        assert filing["filed_by_user_id"] is None, (
            "and no filer should be recorded, got "
            f"{filing['filed_by_user_id']}"
        )

        peer = league.club(world["peer"]["id"])
        assert peer["version"] == 1, (
            f"the peer club's record is untouched, got version {peer['version']}"
        )
        assert peer["provisional_cap_committed_cents"] == 0, (
            "the peer club committed nothing, got "
            f"{peer['provisional_cap_committed_cents']}"
        )

        submitted = league.submit_filing(world["filing_id"], world["club"]["id"])
        assert submitted["status"] == "FILED", (
            "the same submission from the owning club's analyst goes through, got "
            f"{submitted['status']}"
        )
        assert submitted["filed_by_user_id"] == world["club"]["id"], (
            "and the acting analyst's identifier is the club's own id, got "
            f"{submitted['filed_by_user_id']}"
        )


class TestTheFilerCannotDecideHisOwnFiling:
    """The officer role passes; the officer's identifier does not."""

    @staticmethod
    def _filing_filed_by_the_club(league: League) -> Dict[str, Any]:
        world = _club_and_free_agent(league)
        filing = league.open_signing(
            world["club"]["id"], world["player"]["id"],
            expected_team_version=world["club"]["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        league.pass_entry_physical(
            world["club"]["id"], world["player"]["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
        )
        world["filing"] = league.submit_filing(filing["id"], world["club"]["id"])
        world["filing_id"] = filing["id"]
        world["contract_id"] = filing["contract_id"]
        return world

    def test_an_officer_whose_id_equals_the_filer_is_refused(
        self, league: League
    ) -> None:
        """Everything else about the approval is impeccable.

        PRD 2.8: "Segregation of duties: the deciding `X-User-ID` differs from the
        filing's `filed_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
        Applies to `POST /transactions/{id}/decide`."

        PRD 3.3: "The officer supplies a `decision` of either `APPROVE` or `REJECT`,
        may supply a `rejection_reason`, and must not be the same identifier that
        filed."

        Design: Corner/errors/the_user_who_filed_a_filing_cannot_also_decide_it
        """
        world = self._filing_filed_by_the_club(league)

        assert world["filing"]["filed_by_user_id"] == world["club"]["id"], (
            "the club's own analyst filed, so the filer is the club id, got "
            f"{world['filing']['filed_by_user_id']}"
        )

        response = league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(),
            league.other_officer(world["club"]["id"]),
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

        filing = league.filing(world["filing_id"])
        assert filing["status"] == "FILED", (
            f"the filing still awaits a decision, got {filing['status']}"
        )
        assert filing["decided_at"] is None, (
            f"no decision instant should be stamped, got {filing['decided_at']}"
        )
        assert filing["decided_by_user_id"] is None, (
            f"and no decider should be recorded, got {filing['decided_by_user_id']}"
        )

    def test_the_refused_decision_runs_none_of_the_approval_cascade(
        self, league: League
    ) -> None:
        """No designation move, no headcount, and the contract stays pending.

        PRD 2.9: "If any precondition fails, nothing is written at all."

        PRD 3.3: "Once those hold, the approval writes: `status` becomes
        `APPROVED`; `decided_at` and `effective_at` are both set to the logical
        clock; `decided_by_user_id` records the deciding officer; and
        `prior_designation` snapshots the player's `roster_designation` as observed
        immediately *before* the designation side effects below run."

        Design: Corner/errors/the_user_who_filed_a_filing_cannot_also_decide_it
        """
        world = self._filing_filed_by_the_club(league)

        league.api.decide_transaction(
            world["filing_id"], fac.approve_payload(),
            league.other_officer(world["club"]["id"]),
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player joined nobody, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"an unrostered player has no club, got {player['current_team_id']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 0, (
            f"the active headcount is unchanged, got {club['active_roster_count']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "PENDING_APPROVAL", (
            f"the offered contract is still pending, got {contract['status']}"
        )

        approved = league.approve_filing(world["filing_id"])
        assert approved["status"] == "APPROVED", (
            "the identical decision from an officer who did not file goes through, "
            f"got {approved['status']}"
        )
        assert approved["prior_designation"] == "UNROSTERED", (
            "and the snapshot records where the player stood before the cascade, "
            f"got {approved['prior_designation']}"
        )
