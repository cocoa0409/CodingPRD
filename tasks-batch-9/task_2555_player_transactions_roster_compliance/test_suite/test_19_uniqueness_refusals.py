"""One open record per subject: the league's uniqueness answers."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_CLAIM_ALREADY_SUBMITTED,
    ERR_DUPLICATE_MARKET_CODE,
    ERR_DUPLICATE_WAIVER_PRIORITY,
    ERR_INJURY_DESIGNATION_ALREADY_OPEN,
    ERR_TENDER_ALREADY_ISSUED,
    ERR_WAIVER_ALREADY_PENDING,
)
from test_helpers.assertions import ids_of
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers, make_medical_officer_headers

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"

TERMS = {
    "years": 3,
    "base_salary_cents": 80_000_000,
    "signing_bonus_cents": 10_000_000,
    "start_season_year": 2026,
}


def _club(league: League, **overrides: Any) -> Dict[str, Any]:
    """One club with room to spare."""
    defaults = {
        "name": "Harbor Kings", "market_code": "HKG",
        "salary_cap_limit_cents": 500_000_000, "waiver_priority_rank": 1,
    }
    return league.register_club(**{**defaults, **overrides})


def _rostered(league: League, club: Dict[str, Any],
              player: Dict[str, Any]) -> Dict[str, Any]:
    """Sign one player onto one club on a three-year deal."""
    return league.sign_onto_roster(
        club["id"], player["id"],
        window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
        expected_team_version=club["version"], **TERMS,
    )


class TestASecondWaiverPlacementForOnePlayer:
    """The same release filing cannot authorise two wires at once."""

    @staticmethod
    def _player_already_on_the_wire(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        _rostered(league, club, player)
        released = league.release_onto_wire(club["id"], player["id"])
        return {
            "club": club,
            "player": player,
            "release_id": released["release_transaction_id"],
            "wire": released["waiver_request"],
        }

    def test_a_second_placement_on_the_same_release_is_refused(
        self, league: League
    ) -> None:
        """Every other placement precondition still holds; only the wire is taken.

        PRD 3.6: "The acting analyst's identifier must equal `from_team_id`, the cited
        filing must be an `APPROVED` filing of type `RELEASE` for the same player and
        the same club (otherwise `ERR_RELEASE_FILING_MISMATCH`), the player must
        currently be `WAIVED_PENDING`, and no other placement for that player may still
        be `PENDING` — a second one is refused with `ERR_WAIVER_ALREADY_PENDING`."

        PRD 3.6: "And `revocability` is evaluated once, at `placed_at`, and frozen: a
        placement made strictly before 2026-08-25T16:00:00Z is `REVOCABLE`, and a
        placement made at or after that instant is `IRREVOCABLE`."

        Design: Corner/errors/a_second_waiver_wire_for_the_same_player_is_refused
        """
        world = self._player_already_on_the_wire(league)

        assert world["wire"]["revocability"] == "REVOCABLE", (
            "a placement well before the cutoff is revocable, got "
            f"{world['wire']['revocability']}"
        )
        player_before = league.player(world["player"]["id"])
        assert player_before["roster_designation"] == "WAIVED_PENDING", (
            "the player satisfies the designation precondition, got "
            f"{player_before['roster_designation']}"
        )

        response = league.api.create_waiver_request(
            fac.waiver_request_payload(
                world["player"]["id"], world["club"]["id"], world["release_id"]
            ),
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_WAIVER_ALREADY_PENDING, 409)

    def test_the_refused_placement_leaves_exactly_one_wire(
        self, league: League
    ) -> None:
        """One wire, still pending, with its original clearance clock.

        PRD 3.6: "`clearance_deadline_at` is `placed_at` plus 24 hours for a
        `REVOCABLE` placement or plus 48 hours for an `IRREVOCABLE` one, snapped into
        the daily processing window per §2.5."

        Design: Corner/errors/a_second_waiver_wire_for_the_same_player_is_refused
        """
        world = self._player_already_on_the_wire(league)

        league.api.create_waiver_request(
            fac.waiver_request_payload(
                world["player"]["id"], world["club"]["id"], world["release_id"]
            ),
            make_cap_analyst_headers(world["club"]["id"]),
        )

        wires, meta = validate_paginated(
            league.api.list_waiver_requests(league.officer)
        )
        assert meta["total_count"] == 1, (
            f"exactly one wire should exist, got {meta['total_count']}"
        )
        assert ids_of(wires) == [world["wire"]["id"]], (
            f"and it should be the first one, got {ids_of(wires)}"
        )

        wire = league.wire(world["wire"]["id"])
        assert wire["status"] == "PENDING", (
            f"the surviving wire is still pending, got {wire['status']}"
        )
        assert wire["clearance_deadline_at"] == "2026-08-11T14:00:00.000Z", (
            "a revocable placement clears 24 hours later, inside the window, got "
            f"{wire['clearance_deadline_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "WAIVED_PENDING", (
            f"the player is still awaiting clearance, got {player['roster_designation']}"
        )


class TestASecondOpenDesignationForOnePlayer:
    """A different designation type is still a second open designation."""

    @staticmethod
    def _player_with_one_open_designation(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        _rostered(league, club, player)
        designation = league.open_injury_designation(
            club["id"], player["id"], "INJURED_RESERVE"
        )
        return {"club": club, "player": player, "designation": designation}

    def test_opening_a_second_designation_of_another_type_is_refused(
        self, league: League
    ) -> None:
        """The player is eligible and the type is new, but one is already open.

        PRD 3.5: "A player may hold only one open designation at a time; if any
        designation for that player is currently in `PENDING_PAPERWORK`,
        `PAPERWORK_FILED`, `ACTIVE` or `RETURN_WINDOW_OPEN`, the request is refused
        with `ERR_INJURY_DESIGNATION_ALREADY_OPEN`."

        PRD 3.5: "The player must already be owned by that club and must currently be
        either `ACTIVE` or `RESERVE` — an injured-reserve or practice-squad player
        cannot be freshly designated."

        Design: Corner/errors/a_second_open_designation_for_the_same_player_is_refused
        """
        world = self._player_with_one_open_designation(league)

        assert world["designation"]["status"] == "PENDING_PAPERWORK", (
            "the open designation has not yet been documented, got "
            f"{world['designation']['status']}"
        )

        response = league.api.create_injury_designation(
            fac.injury_designation_payload(
                world["player"]["id"], world["club"]["id"],
                "INJURED_RESERVE_RETURN_ELIGIBLE",
            ),
            make_medical_officer_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_INJURY_DESIGNATION_ALREADY_OPEN, 409)

    def test_the_refused_designation_leaves_the_first_one_alone(
        self, league: League
    ) -> None:
        """One designation, still injured reserve, still a 21-day minimum stay.

        PRD 3.5: "On creation the designation records `placed_at` as the logical clock,
        lands in `PENDING_PAPERWORK`, and fixes `minimum_stay_days` from the type: 21
        days for `INJURED_RESERVE`, 14 days for `INJURED_RESERVE_RETURN_ELIGIBLE` and
        28 days for `NON_ROSTER_INJURY`."

        Design: Corner/errors/a_second_open_designation_for_the_same_player_is_refused
        """
        world = self._player_with_one_open_designation(league)

        league.api.create_injury_designation(
            fac.injury_designation_payload(
                world["player"]["id"], world["club"]["id"],
                "INJURED_RESERVE_RETURN_ELIGIBLE",
            ),
            make_medical_officer_headers(world["club"]["id"]),
        )

        designations, meta = validate_paginated(
            league.api.list_injury_designations(league.officer)
        )
        assert meta["total_count"] == 1, (
            f"exactly one designation should exist, got {meta['total_count']}"
        )
        assert ids_of(designations) == [world["designation"]["id"]], (
            f"and it should be the first one, got {ids_of(designations)}"
        )

        designation = league.designation(world["designation"]["id"])
        assert designation["designation_type"] == "INJURED_RESERVE", (
            "the refused request did not change the open type, got "
            f"{designation['designation_type']}"
        )
        assert designation["status"] == "PENDING_PAPERWORK", (
            f"nor its status, got {designation['status']}"
        )
        assert designation["minimum_stay_days"] == 21, (
            "injured reserve fixes a 21-day minimum stay, got "
            f"{designation['minimum_stay_days']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "ACTIVE", (
            "no designation moves a player by itself, got "
            f"{player['roster_designation']}"
        )
        assert player["medical_status"] == "CLEARED", (
            f"and his medical standing is untouched, got {player['medical_status']}"
        )


class TestASecondTenderForOnePair:
    """A different offer type and level cannot reopen a settled pair."""

    @staticmethod
    def _pair_with_one_issued_tender(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(
            full_name="Ray Alder", position="QB", accrued_active_days=400
        )
        tender = league.issue_tender(
            club["id"], player["id"], "RESTRICTED_TENDER", "FIRST_ROUND",
            50_000_000,
        )
        return {"club": club, "player": player, "tender": tender}

    def test_a_second_tender_for_the_same_club_and_player_is_refused(
        self, league: League
    ) -> None:
        """The pair, not the offer's shape, is what must be unique.

        PRD 3.8: "The club must not be `NON_COMPLIANT` or `TRANSACTION_FROZEN`; the
        player must currently be `UNROSTERED`; the player's `medical_status` must not be
        `FAILED_PHYSICAL`; the player's `contract_rights_class` must be `RESTRICTED` or
        `ARBITRATION_ELIGIBLE`, and an `ARBITRATION_TENDER` specifically requires
        `ARBITRATION_ELIGIBLE`, with any other rights class refused as
        `ERR_RESTRICTED_RIGHTS_REQUIRED`; and the same club-and-player pair may not
        already hold an `ISSUED` tender, which would be `ERR_TENDER_ALREADY_ISSUED`."

        PRD 3.8: "Three worked cases: a prior base of 50,000,000 cents at `FIRST_ROUND`
        for a player with two service years, issued as a `RESTRICTED_TENDER`, has a
        floor of 60,000,000 cents and an amount of 66,000,000 cents; the same prior base
        at `ORIGINAL_ROUND` for a player with three service years, issued as an
        `ARBITRATION_TENDER`, has a floor of 50,000,000 cents and an amount of
        60,000,000 cents; and the same inputs issued as a plain `QUALIFYING_OFFER` have
        a floor of 50,000,000 cents and an amount of 50,000,000 cents."

        Design: Corner/errors/a_second_tender_for_the_same_club_and_player_is_refused
        """
        world = self._pair_with_one_issued_tender(league)

        assert world["tender"]["amount_cents"] == 66_000_000, (
            "the first-round floor of 60,000,000 times the restricted multiplier of "
            f"1.10 is 66,000,000, got {world['tender']['amount_cents']}"
        )
        player = league.player(world["player"]["id"])
        assert player["contract_rights_class"] == "RESTRICTED", (
            "the player's rights make him tenderable, so eligibility is not what "
            f"fails, got {player['contract_rights_class']}"
        )

        response = league.api.create_tender(
            fac.tender_payload(
                world["player"]["id"], world["club"]["id"],
                "QUALIFYING_OFFER", "ORIGINAL_ROUND", 50_000_000,
            ),
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_TENDER_ALREADY_ISSUED, 409)

    def test_the_refused_tender_leaves_the_issued_one_intact(
        self, league: League
    ) -> None:
        """One tender, still issued, still worth 66,000,000 on its own clock.

        PRD 3.8: "Issuance stamps `issued_at` with the logical clock, leaves the tender
        `ISSUED`, and computes `deadline_at` as `issued_at` plus 72 hours, snapped into
        the daily processing window per §2.5."

        Design: Corner/errors/a_second_tender_for_the_same_club_and_player_is_refused
        """
        world = self._pair_with_one_issued_tender(league)

        league.api.create_tender(
            fac.tender_payload(
                world["player"]["id"], world["club"]["id"],
                "QUALIFYING_OFFER", "ORIGINAL_ROUND", 50_000_000,
            ),
            make_cap_analyst_headers(world["club"]["id"]),
        )

        tenders, meta = validate_paginated(league.api.list_tenders(league.officer))
        assert meta["total_count"] == 1, (
            f"exactly one tender should exist, got {meta['total_count']}"
        )
        assert ids_of(tenders) == [world["tender"]["id"]], (
            f"and it should be the first one, got {ids_of(tenders)}"
        )

        tender = league.tender(world["tender"]["id"])
        assert tender["status"] == "ISSUED", (
            f"the surviving tender still awaits an answer, got {tender['status']}"
        )
        assert tender["amount_cents"] == 66_000_000, (
            f"its derived amount is untouched, got {tender['amount_cents']}"
        )
        assert tender["deadline_at"] == "2026-08-13T14:00:00.000Z", (
            "and so is its 72-hour deadline, which already sits inside the window, got "
            f"{tender['deadline_at']}"
        )


class TestARepeatClaimFromOneClub:
    """A fresh version satisfies the OCC gate and still cannot buy a second claim."""

    @staticmethod
    def _wire_with_one_claim_from_the_claimant(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        releasing = _club(league)
        claiming = _club(
            league, name="Basin Otters", market_code="BSN", waiver_priority_rank=2,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        _rostered(league, releasing, player)
        released = league.release_onto_wire(releasing["id"], player["id"])
        claim = league.submit_claim(
            released["waiver_request_id"], claiming["id"],
            expected_team_version=claiming["version"],
        )
        return {
            "releasing": releasing,
            "claiming": claiming,
            "player": player,
            "wire_id": released["waiver_request_id"],
            "claim": claim,
        }

    def test_a_repeat_claim_carrying_the_refreshed_version_is_refused(
        self, league: League
    ) -> None:
        """The club re-reads itself first, so only the pair's uniqueness can fail.

        PRD 3.6: "The acting identifier must equal that club, the claiming club may not
        be the releasing club, the claiming club must not be `NON_COMPLIANT` or
        `TRANSACTION_FROZEN`, and the same club may not claim the same wire twice — a
        repeat is `ERR_CLAIM_ALREADY_SUBMITTED`."

        PRD 3.6: "Submitting a claim increments the wire's `claim_count` and the
        claiming club's `version` by 1."

        PRD 3.6: "`priority_rank_snapshot` copies the claiming club's
        `waiver_priority_rank` and is the ranking key the award pipeline uses."

        Design: Corner/errors/a_second_claim_from_the_same_club_on_one_wire_is_refused
        """
        world = self._wire_with_one_claim_from_the_claimant(league)

        assert world["claim"]["status"] == "SUBMITTED", (
            f"the first claim is on the wire, got {world['claim']['status']}"
        )
        assert world["claim"]["priority_rank_snapshot"] == 2, (
            "the claimant's rank is snapshotted at claim time, got "
            f"{world['claim']['priority_rank_snapshot']}"
        )
        refreshed = league.version_of(world["claiming"]["id"])
        assert refreshed == 2, (
            f"the first claim bumped the claiming club's version, got {refreshed}"
        )

        response = league.api.submit_waiver_claim(
            world["wire_id"],
            fac.waiver_claim_payload(world["claiming"]["id"], refreshed),
            make_cap_analyst_headers(world["claiming"]["id"]),
        )
        validate_error(response, ERR_CLAIM_ALREADY_SUBMITTED, 409)

    def test_the_refused_claim_bumps_nothing(self, league: League) -> None:
        """One claim on the wire, one version on the club, no award.

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/errors/a_second_claim_from_the_same_club_on_one_wire_is_refused
        """
        world = self._wire_with_one_claim_from_the_claimant(league)
        refreshed = league.version_of(world["claiming"]["id"])

        league.api.submit_waiver_claim(
            world["wire_id"],
            fac.waiver_claim_payload(world["claiming"]["id"], refreshed),
            make_cap_analyst_headers(world["claiming"]["id"]),
        )

        claims, meta = validate_paginated(
            league.api.list_waiver_claims(league.officer)
        )
        assert meta["total_count"] == 1, (
            f"exactly one claim should exist, got {meta['total_count']}"
        )
        assert ids_of(claims) == [world["claim"]["id"]], (
            f"and it should be the first one, got {ids_of(claims)}"
        )
        assert league.claim(world["claim"]["id"])["status"] == "SUBMITTED", (
            "the surviving claim is untouched, got "
            f"{league.claim(world['claim']['id'])['status']}"
        )

        claiming = league.club(world["claiming"]["id"])
        assert claiming["version"] == refreshed, (
            f"the refused claim bumped no version, got {claiming['version']}"
        )

        wire = league.wire(world["wire_id"])
        assert wire["status"] == "PENDING", (
            f"the wire is still pending, got {wire['status']}"
        )
        assert wire["awarded_to_team_id"] is None, (
            f"and nothing has been awarded, got {wire['awarded_to_team_id']}"
        )
        assert wire["claim_count"] == 1, (
            f"the wire counts one claim, got {wire['claim_count']}"
        )


class TestAReusedMarketCode:
    """Two clubs may differ in everything else and still collide on three letters."""

    def test_registering_a_club_on_a_taken_market_code_is_refused(
        self, league: League
    ) -> None:
        """The name, cap and rank are all fresh; only the code repeats.

        PRD 3.1: "Registration carries the club's `name` — between 1 and 80 characters,
        and not blank — and its `market_code`, which is exactly three uppercase letters
        A through Z and must be unique across every club in the league; a collision is
        refused with `ERR_DUPLICATE_MARKET_CODE`."

        Design: Corner/errors/reusing_a_market_code_is_refused
        """
        league.set_clock(CLOCK)
        first = _club(league)

        response = league.api.create_team(
            fac.team_payload(
                name="Harbor Kings Reserve", market_code="HKG",
                salary_cap_limit_cents=400_000_000, waiver_priority_rank=7,
            ),
            league.officer,
        )
        validate_error(response, ERR_DUPLICATE_MARKET_CODE, 409)

        clubs, meta = validate_paginated(league.api.list_teams(league.officer))
        assert meta["total_count"] == 1, (
            f"the second registration created nothing, got {meta['total_count']}"
        )
        assert ids_of(clubs) == [first["id"]], (
            f"only the first club is on the books, got {ids_of(clubs)}"
        )

        club = league.club(first["id"])
        assert club["salary_cap_limit_cents"] == 500_000_000, (
            "the incumbent's cap was not overwritten by the refused body, got "
            f"{club['salary_cap_limit_cents']}"
        )
        assert club["waiver_priority_rank"] == 1, (
            f"nor its waiver rank, got {club['waiver_priority_rank']}"
        )


class TestAReusedWaiverPriorityRank:
    """The ranking key is the tie-break of every award, so it too is unique."""

    def test_registering_a_club_on_a_taken_waiver_rank_is_refused(
        self, league: League
    ) -> None:
        """A fresh market code cannot save a repeated rank.

        PRD 3.1: "Registration also fixes the club's `salary_cap_limit_cents`, which may
        not be negative and which the league conventionally sets to its standard figure
        of 500,000,000 cents, and its `waiver_priority_rank`, an integer of at least 1
        that must likewise be unique league-wide — rank 1 claims ahead of rank 2, and a
        duplicate is refused with `ERR_DUPLICATE_WAIVER_PRIORITY`."

        Design: Corner/errors/reusing_a_waiver_priority_rank_is_refused
        """
        league.set_clock(CLOCK)
        first = _club(league)

        response = league.api.create_team(
            fac.team_payload(
                name="Basin Otters", market_code="BSN",
                salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
            ),
            league.officer,
        )
        validate_error(response, ERR_DUPLICATE_WAIVER_PRIORITY, 409)

        clubs, meta = validate_paginated(league.api.list_teams(league.officer))
        assert meta["total_count"] == 1, (
            f"the second registration created nothing, got {meta['total_count']}"
        )
        assert ids_of(clubs) == [first["id"]], (
            f"only the first club is on the books, got {ids_of(clubs)}"
        )

        club = league.club(first["id"])
        assert club["waiver_priority_rank"] == 1, (
            f"rank 1 still belongs to the incumbent, got {club['waiver_priority_rank']}"
        )
        assert club["market_code"] == "HKG", (
            f"and so does its market code, got {club['market_code']}"
        )
