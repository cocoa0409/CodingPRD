"""Endpoint surfaces: what each one returns and what it leaves behind."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_CLEARANCE_NOT_REACHED
from test_helpers.assertions import (
    assert_cap_position,
    assert_designation_counts,
    assert_pagination_meta,
)
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"


def _rostered(league: League, **terms: Any) -> Dict[str, Any]:
    """One club with one player signed to a 3-year deal charging 83,333,333."""
    league.set_clock(CLOCK)
    club = league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
    )
    player = league.register_player(full_name="Ray Alder", position="QB")
    signing = league.sign_onto_roster(
        club["id"], player["id"],
        window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
        expected_team_version=club["version"], years=3,
        base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
        start_season_year=2026, **terms,
    )
    return {
        "club": club,
        "player": player,
        "contract_id": signing["contract_id"],
        "signing_transaction_id": signing["transaction_id"],
    }


class TestTeamSurfacesAgreeOnOneRecord:
    """Create, read, list and patch a club without losing a field."""

    @staticmethod
    def _two_clubs(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        first = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
            active_roster_limit=26, reserve_roster_limit=4,
            injured_reserve_limit=3, practice_squad_limit=6,
        )
        second = league.register_club(
            name="Vale Foxes", market_code="VLF",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        return {"first": first, "second": second}

    def test_a_registered_club_reads_back_exactly_as_it_was_created(
        self, league: League
    ) -> None:
        """The read surface returns the registration inputs and the league defaults.

        PRD 3.1: "A freshly registered club starts with every headcount and every
        money total at zero, `cap_space_cents` equal to its `salary_cap_limit_cents`,
        and a `compliance_status` of `COMPLIANT`."
        PRD 2.3: "List responses carry all four pagination fields in `meta`: `limit`
        and `offset` echo the values actually applied, `total_count` is the number of
        records matching the filter before the page window is applied, and `has_more`
        is true exactly when records remain beyond the current page."

        Design: Corner/endpoints/team_create_read_list_and_limit_patch_round_trip
        """
        world = self._two_clubs(league)
        first = world["first"]

        read_back = validate_success(
            league.api.get_team(first["id"], League.analyst(first)), 200
        )
        assert read_back["name"] == "Harbor Kings", (
            f"the name should survive the round trip, got {read_back['name']}"
        )
        assert read_back["market_code"] == "HKG", (
            f"the market code should survive the round trip, got {read_back['market_code']}"
        )
        assert read_back["salary_cap_limit_cents"] == 500_000_000, (
            f"the cap limit is as registered, got {read_back['salary_cap_limit_cents']}"
        )
        assert read_back["version"] == first["version"] == 1, (
            "a read never advances the version, so both views should report 1, got "
            f"{read_back['version']} and {first['version']}"
        )
        assert read_back["created_at"] == "2026-08-10T14:00:00.000Z", (
            f"the creation instant is the logical clock, got {read_back['created_at']}"
        )
        assert read_back["compliance_status"] == "COMPLIANT", (
            f"a fresh club is COMPLIANT, got {read_back['compliance_status']}"
        )
        assert read_back["cap_space_cents"] == 500_000_000, (
            "a fresh club has its whole cap available, got "
            f"{read_back['cap_space_cents']}"
        )
        assert_designation_counts(
            read_back, active=0, reserve=0, injured_reserve=0, practice_squad=0
        )

        clubs, meta = validate_paginated(
            league.api.list_teams(
                league.officer,
                params={"compliance_status": "COMPLIANT", "limit": 1, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=2, has_more=True, limit=1, offset=0)
        assert len(clubs) == 1, (
            f"a page of one should carry one element, got {len(clubs)}"
        )
        assert clubs[0]["id"] in {first["id"], world["second"]["id"]}, (
            f"the page should hold one of the two registered clubs, got {clubs[0]['id']}"
        )

    def test_a_partial_limit_patch_moves_only_the_limit_it_names(
        self, league: League
    ) -> None:
        """One quota changes; the other three and every counter stay put.

        PRD 4: "Adjusts a club's roster limits, salary cap or waiver priority rank;
        applies immediately and may leave the club outside its new limits."
        PRD 2.4: "First, a club's `version` advances on writes that the client did
        not aim at the club directly: opening a filing, submitting a claim, adjusting
        limits, deciding a filing, revising one, placing a waiver, responding to a
        tender with an acceptance, and running a compliance sweep all bump the owning
        `Team`'s `version`."

        Design: Corner/endpoints/team_create_read_list_and_limit_patch_round_trip
        """
        world = self._two_clubs(league)

        patched = league.adjust_limits(world["first"]["id"], injured_reserve_limit=5)

        assert patched["injured_reserve_limit"] == 5, (
            "the named limit should have moved, got "
            f"{patched['injured_reserve_limit']}"
        )
        assert patched["active_roster_limit"] == 26, (
            f"the unnamed active limit stays where it was, got {patched['active_roster_limit']}"
        )
        assert patched["reserve_roster_limit"] == 4, (
            f"as does the reserve limit, got {patched['reserve_roster_limit']}"
        )
        assert patched["practice_squad_limit"] == 6, (
            f"and the practice-squad limit, got {patched['practice_squad_limit']}"
        )
        assert patched["version"] == 2, (
            f"adjusting limits bumps the club's version to 2, got {patched['version']}"
        )
        assert_designation_counts(
            patched, active=0, reserve=0, injured_reserve=0, practice_squad=0
        )
        assert patched["cap_space_cents"] == 500_000_000, (
            f"a limit patch spends no cap, got {patched['cap_space_cents']}"
        )


class TestEarningABonusMovesOneVariant:
    """The earn action is asymmetric by design."""

    def test_earning_a_not_likely_bonus_raises_the_final_total_alone(
        self, league: League
    ) -> None:
        """Provisional and cap space hold still while the final total climbs.

        PRD 3.4: "Earning stamps `earned_at` with the logical clock and moves
        `allocation_status` to `EARNED`, then recomputes the owning club's
        `provisional_cap_committed_cents`, `final_cap_committed_cents` and
        `cap_space_cents` and re-evaluates the club's posture in event mode."
        PRD 3.4: "The two performance kinds behave asymmetrically here, and both
        halves matter: a `PERFORMANCE_NLTBE` row enters the final cap variant for the
        first time at this moment while never having entered the provisional variant,
        whereas a `PERFORMANCE_LTBE` row leaves the provisional variant unchanged — it
        was already counted there — and raises only the final variant."
        PRD 3.1: "`cap_space_cents` is always the club's `salary_cap_limit_cents` less
        its **provisional** commitment, and it is permitted to go negative."

        Design: Corner/endpoints/earning_a_performance_bonus_raises_only_the_final_variant
        """
        world = _rostered(league, performance_nltbe_cents=7_000_000)
        rows = league.allocations(world["contract_id"])

        not_likely = rows[3]
        assert not_likely["bonus_type"] == "PERFORMANCE_NLTBE", (
            "the not-likely row follows the three proration rows, got "
            f"{[row['bonus_type'] for row in rows]}"
        )
        assert not_likely["counts_against_provisional"] is False, (
            "a not-likely bonus never enters the provisional variant"
        )
        assert not_likely["allocation_status"] == "SCHEDULED", (
            f"the row is born SCHEDULED, got {not_likely['allocation_status']}"
        )

        before = validate_success(
            league.api.get_cap_ledger(
                world["club"]["id"], League.analyst(world["club"])
            ),
            200,
        )
        assert before["provisional_cap_committed_cents"] == 83_333_333, (
            "before earning, only the contract charge is committed, got "
            f"{before['provisional_cap_committed_cents']}"
        )
        assert before["final_cap_committed_cents"] == 83_333_333, (
            "and the final variant agrees with it, got "
            f"{before['final_cap_committed_cents']}"
        )

        earned = league.earn_allocation(not_likely["id"])

        assert earned["allocation_status"] == "EARNED", (
            f"the row should now be EARNED, got {earned['allocation_status']}"
        )
        assert earned["earned_at"] == "2026-08-10T14:00:00.000Z", (
            f"the earn instant is the logical clock, got {earned['earned_at']}"
        )
        assert earned["amount_cents"] == 7_000_000, (
            f"earning does not re-value the row, got {earned['amount_cents']}"
        )
        assert earned["season_year"] == 2026, (
            "the row is charged against the start season, got "
            f"{earned['season_year']}"
        )

        after = validate_success(
            league.api.get_cap_ledger(
                world["club"]["id"], League.analyst(world["club"])
            ),
            200,
        )
        assert_cap_position(
            after, provisional=83_333_333, final=90_333_333,
            dead_money=0, cap_space=416_666_667,
        )

        proration_rows = league.allocations(world["contract_id"])[:3]
        for index, row in enumerate(proration_rows):
            assert row["allocation_status"] == "SCHEDULED", (
                "earning one row leaves the amortisation ledger alone, but row "
                f"{index} reads {row['allocation_status']}"
            )


class TestClaimLinksAWireToASecondClub:
    """One claim updates both ends of the link.

    PRD 3.6: "The claim is born `SUBMITTED`, stamps `submitted_at` with the logical
    clock, links back through `waiver_request_id`, and captures three figures."
    """

    @staticmethod
    def _wire_and_a_second_club(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        releasing = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        claiming = league.register_club(
            name="Vale Foxes", market_code="VLF",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            releasing["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=releasing["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        wire = league.release_onto_wire(releasing["id"], player["id"])
        return {
            "releasing": releasing,
            "claiming": claiming,
            "player": player,
            "contract_id": signing["contract_id"],
            "waiver_request_id": wire["waiver_request_id"],
            "waiver_request": wire["waiver_request"],
        }

    def test_a_new_claim_snapshots_the_claimant_and_counts_on_the_wire(
        self, league: League
    ) -> None:
        """The claim carries the three snapshots and the wire carries the count.

        PRD 3.6: "`priority_rank_snapshot` copies the claiming club's
        `waiver_priority_rank` and is the ranking key the award pipeline uses."
        PRD 3.6: "`cap_space_snapshot_cents` copies the claiming club's
        `cap_space_cents` — this value is retained for audit only and is **never** the
        eligibility input."
        PRD 3.6: "`required_cap_charge_cents` is the `base_salary_cents` of the wired
        contract, that is, the charge the claiming club would assume."
        PRD 3.6: "Submitting a claim increments the wire's `claim_count` and the
        claiming club's `version` by 1."

        Design: Corner/endpoints/waiver_claim_links_a_wire_to_a_second_club_in_both_directions
        """
        world = self._wire_and_a_second_club(league)

        assert world["waiver_request"]["origin_designation"] == "ACTIVE", (
            "the wire remembers where the player was before the release, got "
            f"{world['waiver_request']['origin_designation']}"
        )

        claim = league.submit_claim(
            world["waiver_request_id"], world["claiming"]["id"]
        )

        assert claim["waiver_request_id"] == world["waiver_request_id"], (
            f"the claim links back to its wire, got {claim['waiver_request_id']}"
        )
        assert claim["claiming_team_id"] == world["claiming"]["id"], (
            f"the claim names its own club, got {claim['claiming_team_id']}"
        )
        assert claim["status"] == "SUBMITTED", (
            f"a new claim is born SUBMITTED, got {claim['status']}"
        )
        assert claim["submitted_at"] == "2026-08-10T14:00:00.000Z", (
            f"the submission instant is the logical clock, got {claim['submitted_at']}"
        )
        assert claim["priority_rank_snapshot"] == 2, (
            f"the claimant holds waiver rank 2, got {claim['priority_rank_snapshot']}"
        )
        assert claim["cap_space_snapshot_cents"] == 500_000_000, (
            "the claimant has committed nothing, so its whole cap is snapshotted, "
            f"got {claim['cap_space_snapshot_cents']}"
        )
        assert claim["required_cap_charge_cents"] == 80_000_000, (
            "the charge the claimant would assume is the wired contract's base "
            f"salary, got {claim['required_cap_charge_cents']}"
        )

        wire = league.wire(world["waiver_request_id"])
        assert wire["status"] == "PENDING", (
            f"a claim does not resolve the wire, got {wire['status']}"
        )
        assert wire["claim_count"] == 1, (
            f"the wire should count its one claim, got {wire['claim_count']}"
        )
        assert wire["awarded_to_team_id"] is None, (
            f"nobody has been awarded the player yet, got {wire['awarded_to_team_id']}"
        )

    def test_the_claim_is_reachable_from_both_ends_and_moves_no_money(
        self, league: League
    ) -> None:
        """Both filtered listings find the one claim and neither club's cap moves.

        PRD 2.3: "Collection endpoints additionally accept the domain filters named
        in their §4 descriptions; a filter narrows `total_count` as well as the page."
        PRD 3.6: "A release does not by itself free a player."

        Design: Corner/endpoints/waiver_claim_links_a_wire_to_a_second_club_in_both_directions
        """
        world = self._wire_and_a_second_club(league)
        claim = league.submit_claim(
            world["waiver_request_id"], world["claiming"]["id"]
        )

        by_wire, wire_meta = validate_paginated(
            league.api.list_waiver_claims(
                league.officer,
                params={"waiver_request_id": world["waiver_request_id"]},
            )
        )
        assert wire_meta["total_count"] == 1, (
            f"the wire end finds exactly one claim, got {wire_meta['total_count']}"
        )
        assert [row["id"] for row in by_wire] == [claim["id"]], (
            f"and it is the claim just submitted, got {[row['id'] for row in by_wire]}"
        )

        by_club, club_meta = validate_paginated(
            league.api.list_waiver_claims(
                league.officer,
                params={"claiming_team_id": world["claiming"]["id"]},
            )
        )
        assert club_meta["total_count"] == 1, (
            f"the club end finds exactly one claim, got {club_meta['total_count']}"
        )
        assert [row["id"] for row in by_club] == [claim["id"]], (
            f"and it is the same claim, got {[row['id'] for row in by_club]}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the wired contract is still ACTIVE, got {contract['status']}"
        )
        assert contract["team_id"] == world["releasing"]["id"], (
            "and still owned by the releasing club, got "
            f"{contract['team_id']}"
        )

        claiming = league.club(world["claiming"]["id"])
        assert claiming["active_roster_count"] == 0, (
            "the claimant has not been awarded anybody, got "
            f"{claiming['active_roster_count']}"
        )
        assert claiming["provisional_cap_committed_cents"] == 0, (
            "and has committed nothing, got "
            f"{claiming['provisional_cap_committed_cents']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "WAIVED_PENDING", (
            f"the player is still on the wire, got {player['roster_designation']}"
        )


class TestCapLedgerOnAnEmptyRoster:
    """The degenerate input set still reports every field."""

    def test_a_club_with_no_contracts_reports_zeroes_and_its_whole_cap(
        self, league: League
    ) -> None:
        """Both variants are zero and cap space is the full limit.

        PRD 3.1: "Both variants are recomputed by every write that creates,
        terminates, transfers or re-values a contract or a bonus allocation, and they
        are also available as a computed read: the cap-ledger view recomputes both
        totals from the club's live contract and allocation rows and returns them side
        by side with `dead_money_cents` and `cap_space_cents`."
        PRD 3.1: "A freshly registered club starts with every headcount and every
        money total at zero, `cap_space_cents` equal to its `salary_cap_limit_cents`,
        and a `compliance_status` of `COMPLIANT`."
        PRD 3.1: "That view is strictly read-only and does not advance the club's
        `version`."

        Design: Corner/endpoints/cap_ledger_on_a_club_with_no_contracts_reports_zeroes_and_the_whole_cap
        """
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )

        ledger = validate_success(
            league.api.get_cap_ledger(club["id"], League.analyst(club)), 200
        )

        assert_cap_position(
            ledger, provisional=0, final=0, dead_money=0, cap_space=500_000_000,
        )
        assert ledger["compliance_status"] == "COMPLIANT", (
            f"an empty roster breaks nothing, got {ledger['compliance_status']}"
        )

        contracts, meta = validate_paginated(
            league.api.list_contracts(league.officer, params={"team_id": club["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the club owns no contract at all, got {meta['total_count']}"
        )
        assert contracts == [], f"and the page is empty, got {contracts}"

        after = league.club(club["id"])
        assert_designation_counts(
            after, active=0, reserve=0, injured_reserve=0, practice_squad=0
        )
        assert after["version"] == 1, (
            "a computed read must not advance the club's version, got "
            f"{after['version']}"
        )


class TestWireProcessingWaitsForClearance:
    """The same call is refused an hour in and accepted at the deadline."""

    @staticmethod
    def _unclaimed_wire(league: League) -> Dict[str, Any]:
        world = _rostered(league)
        wire = league.release_onto_wire(world["club"]["id"], world["player"]["id"])
        world["waiver_request_id"] = wire["waiver_request_id"]
        world["waiver_request"] = wire["waiver_request"]
        return world

    def test_processing_before_the_clearance_instant_is_refused(
        self, league: League
    ) -> None:
        """An hour after placement the wire is untouchable and untouched.

        PRD 3.6: "**Processing.** Once the logical clock has reached
        `clearance_deadline_at` — the boundary instant itself is enough, and a request
        made strictly earlier is refused with `ERR_CLEARANCE_NOT_REACHED` — a league
        officer processes the wire from inside the daily processing window."
        PRD 3.6: "While a wire is `PENDING` or after it is `WITHDRAWN`,
        `releasing_team_dead_money_cents` is 0."

        Design: Corner/endpoints/wire_processing_is_refused_before_clearance_and_admitted_at_it
        """
        world = self._unclaimed_wire(league)

        assert world["waiver_request"]["clearance_deadline_at"] == "2026-08-11T14:00:00.000Z", (
            "a revocable placement clears 24 hours later, got "
            f"{world['waiver_request']['clearance_deadline_at']}"
        )
        assert world["waiver_request"]["claim_count"] == 0, (
            f"nobody has claimed him, got {world['waiver_request']['claim_count']}"
        )

        league.set_clock("2026-08-10T15:00:00Z")
        response = league.api.process_waiver_request(
            world["waiver_request_id"], league.officer
        )
        validate_error(response, ERR_CLEARANCE_NOT_REACHED, 422)

        wire = league.wire(world["waiver_request_id"])
        assert wire["status"] == "PENDING", (
            f"the refused wire is still pending, got {wire['status']}"
        )
        assert wire["processed_at"] is None, (
            f"no processing instant should be stamped, got {wire['processed_at']}"
        )
        assert wire["releasing_team_dead_money_cents"] == 0, (
            "a pending wire books no dead money, got "
            f"{wire['releasing_team_dead_money_cents']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the contract is untouched, got {contract['status']}"
        )
        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "WAIVED_PENDING", (
            f"the player is untouched too, got {player['roster_designation']}"
        )

    def test_processing_at_exactly_the_clearance_instant_clears_the_wire(
        self, league: League
    ) -> None:
        """The boundary instant is enough, and the whole clearing cascade runs.

        PRD 3.6: "If no claim survives the three filters, the wire moves `PENDING →
        CLEARED` instead. `processed_at` is stamped, every `SUBMITTED` claim is moved
        to `INVALIDATED`, the player's `roster_designation` moves `WAIVED_PENDING →
        UNROSTERED` with `current_team_id` set to null, and the contract moves `ACTIVE
        → TERMINATED` with `termination_reason` `RELEASE_CLEARED`, running the full
        acceleration-and-forfeiture cascade of §3.4."
        PRD 3.6: "`releasing_team_dead_money_cents` is then the contract's
        `dead_money_current_season_cents`, and the releasing club's
        `dead_money_cents`, cap fields and posture are all recomputed."

        Design: Corner/endpoints/wire_processing_is_refused_before_clearance_and_admitted_at_it
        """
        world = self._unclaimed_wire(league)
        league.set_clock("2026-08-11T14:00:00Z")

        processed = league.process_wire(world["waiver_request_id"])

        assert processed["status"] == "CLEARED", (
            f"an unclaimed wire clears, got {processed['status']}"
        )
        assert processed["processed_at"] == "2026-08-11T14:00:00.000Z", (
            f"the processing instant is the logical clock, got {processed['processed_at']}"
        )
        assert processed["releasing_team_dead_money_cents"] == 3_333_333, (
            "the releasing club keeps this season's unamortised bonus share, got "
            f"{processed['releasing_team_dead_money_cents']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "TERMINATED", (
            f"the contract ends with the clearance, got {contract['status']}"
        )
        assert contract["termination_reason"] == "RELEASE_CLEARED", (
            f"and records why, got {contract['termination_reason']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player leaves the roster entirely, got {player['roster_designation']}"
        )
        assert player["current_team_id"] is None, (
            f"and belongs to nobody, got {player['current_team_id']}"
        )

        club = league.club(world["club"]["id"])
        assert_cap_position(
            club, provisional=3_333_333, final=3_333_333,
            dead_money=3_333_333, cap_space=496_666_667,
        )


class TestOneSweepPerformsSeveralClockDrivenSteps:
    """A single sweep call reaches into two unrelated lifecycles."""

    SWEEP_AT = "2026-08-26T14:00:00Z"

    @staticmethod
    def _stale_draft_and_stale_physical(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"],
            years=3, base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        exam = league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
        )
        league.set_clock(TestOneSweepPerformsSeveralClockDrivenSteps.SWEEP_AT)
        return {
            "club": club, "player": player, "filing": filing,
            "contract_id": filing["contract_id"], "exam": exam,
        }

    def test_one_sweep_voids_the_stale_draft_and_expires_the_stale_physical(
        self, league: League
    ) -> None:
        """Two independent steps land in the same response.

        PRD 3.9: "Step one voids every `DRAFT` filing whose `filing_deadline_at` the
        logical clock has passed, voiding a `SIGNING` filing's `PENDING_APPROVAL`
        contract along with it and recomputing the club's provisional commitment."
        PRD 3.9: "Step five expires every `PASSED` physical whose `expires_at` the
        clock has passed, moving it to `EXPIRED` so that no approval can cite it
        again."

        Design: Corner/endpoints/one_compliance_sweep_voids_a_stale_filing_and_expires_a_stale_physical
        """
        world = self._stale_draft_and_stale_physical(league)

        assert world["filing"]["filing_deadline_at"] == "2026-08-12T14:00:00.000Z", (
            "the deadline was fixed 48 hours after creation, got "
            f"{world['filing']['filing_deadline_at']}"
        )
        assert world["exam"]["expires_at"] == "2026-08-24T14:00:00.000Z", (
            f"a pass expires 14 days after it was performed, got {world['exam']['expires_at']}"
        )

        league.run_sweep(world["club"]["id"])

        filing = league.filing(world["filing"]["id"])
        assert filing["status"] == "VOIDED", (
            f"the never-filed draft should be voided, got {filing['status']}"
        )
        assert filing["filed_at"] is None, (
            f"it was never submitted, got {filing['filed_at']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "VOIDED", (
            "the offered contract is dragged along with its filing, got "
            f"{contract['status']}"
        )

        exam = league.exam(world["exam"]["id"])
        assert exam["status"] == "EXPIRED", (
            f"the stale physical should be expired, got {exam['status']}"
        )
        assert exam["performed_at"] == "2026-08-10T14:00:00.000Z", (
            f"expiry does not rewrite when it was performed, got {exam['performed_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "UNROSTERED", (
            f"the player never joined anybody, got {player['roster_designation']}"
        )
        assert player["medical_status"] == "CLEARED", (
            "an expired physical is not an injury, so the medical status is "
            f"untouched, got {player['medical_status']}"
        )

    def test_the_sweep_row_reports_settled_money_and_a_compliant_posture(
        self, league: League
    ) -> None:
        """Neither leftover is a violation, and the audit row reads the final variant.

        PRD 3.9: "One subtlety deserves emphasis: the sweep row's `cap_space_cents` is
        the club's `salary_cap_limit_cents` less its **final** committed total, because
        the audit view reports settled money — unlike the club record's own
        `cap_space_cents`, which is measured against the *provisional* total."
        PRD 3.9: "There is exactly **one** way out, and it is the same edge from all
        three violation postures: a sweep that finds an empty violation list returns
        the club to `COMPLIANT`, clears `grace_expires_at` to null and resets
        `consecutive_noncompliant_checks` to 0."

        Design: Corner/endpoints/one_compliance_sweep_voids_a_stale_filing_and_expires_a_stale_physical
        """
        world = self._stale_draft_and_stale_physical(league)

        row = league.run_sweep(world["club"]["id"])

        assert row["violation_codes"] == [], (
            f"a stale draft is not a violation, got {row['violation_codes']}"
        )
        assert row["result"] == "COMPLIANT", (
            f"the sweep should pass the club, got {row['result']}"
        )
        assert row["resulting_compliance_status"] == "COMPLIANT", (
            f"and leave it compliant, got {row['resulting_compliance_status']}"
        )
        assert row["checked_at"] == "2026-08-26T14:00:00.000Z", (
            f"the sweep instant is the logical clock, got {row['checked_at']}"
        )
        assert row["final_cap_committed_cents"] == 0, (
            "the voided contract commits nothing, got "
            f"{row['final_cap_committed_cents']}"
        )
        assert row["cap_space_cents"] == 500_000_000, (
            "the audit row measures space against the final total, got "
            f"{row['cap_space_cents']}"
        )
        assert row["active_roster_count"] == 0, (
            f"the club rostered nobody, got {row['active_roster_count']}"
        )

        club = league.club(world["club"]["id"])
        assert club["provisional_cap_committed_cents"] == 0, (
            "voiding the contract released the provisional commitment, got "
            f"{club['provisional_cap_committed_cents']}"
        )
        assert club["compliance_status"] == "COMPLIANT", (
            f"the club's posture is unchanged, got {club['compliance_status']}"
        )
        assert club["consecutive_noncompliant_checks"] == 0, (
            "a violation-free sweep resets the counter, got "
            f"{club['consecutive_noncompliant_checks']}"
        )
