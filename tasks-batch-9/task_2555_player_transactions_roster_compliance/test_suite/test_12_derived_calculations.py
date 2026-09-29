"""Derived figures recomputed from the rows they summarise."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers.api_errors import ERR_CAP_LIMIT_EXCEEDED
from test_helpers.assertions import (
    assert_cap_position,
    assert_designation_counts,
    assert_posture,
    assert_violation_codes,
)
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"


def _club(league: League, cap: int = 500_000_000) -> Dict[str, Any]:
    league.set_clock(CLOCK)
    return league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=cap, waiver_priority_rank=1,
    )


def _two_pending_signings(league: League) -> Dict[str, Any]:
    """One club carrying an 83,333,333 charge and a 32,000,000 charge, undecided."""
    club = _club(league)
    first_player = league.register_player(full_name="Ray Alder", position="QB")
    second_player = league.register_player(full_name="Dov Keller", position="WR")
    first = league.open_signing(
        club["id"], first_player["id"],
        expected_team_version=club["version"], years=3,
        base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
        start_season_year=2026,
    )
    second = league.open_signing(
        club["id"], second_player["id"], years=7,
        base_salary_cents=30_000_000, signing_bonus_cents=10_000_000,
        start_season_year=2026,
    )
    return {
        "club": club,
        "first_player": first_player,
        "first_filing": first,
        "second_filing": second,
    }


class TestContractCurrentSeasonCharge:
    """The stored charge is a base salary plus one season's share."""

    def test_the_current_season_charge_adds_only_this_seasons_share(
        self, league: League
    ) -> None:
        """The remainder cent belongs to the final season, not to this one.

        PRD 3.4: "A contract with an 80,000,000-cent base salary, a
        10,000,000-cent signing bonus, three years and a 2026 start has an elapsed
        season count of zero, a proration share of 3,333,333 cents, and a
        current-season charge of 83,333,333 cents."

        Design: Corner/calculations/contract_cap_charge_sums_base_salary_and_first_year_proration
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"], expected_team_version=club["version"],
            years=3, base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )

        contract = league.contract(filing["contract_id"])

        assert contract["proration_years"] == 3, (
            f"three years spread over three seasons, got {contract['proration_years']}"
        )
        assert contract["annual_proration_cents"] == 3_333_333, (
            f"the annual share should be 3333333, got {contract['annual_proration_cents']}"
        )
        assert contract["final_season_proration_cents"] == 3_333_334, (
            "the final season absorbs the remainder cent, got "
            f"{contract['final_season_proration_cents']}"
        )
        assert contract["current_season_cap_charge_cents"] == 83_333_333, (
            "the first season carries the annual share, not the final one, got "
            f"{contract['current_season_cap_charge_cents']}"
        )
        assert contract["total_value_cents"] == 250_000_000, (
            f"three seasons of base plus the bonus, got {contract['total_value_cents']}"
        )
        assert contract["status"] == "PENDING_APPROVAL", (
            f"a fresh contract awaits approval, got {contract['status']}"
        )
        assert contract["dead_money_current_season_cents"] == 0, (
            "a live contract owes no dead money, got "
            f"{contract['dead_money_current_season_cents']}"
        )


class TestProvisionalTotalIsASetMembershipSum:
    """Voiding a contract removes it from the input set, nothing more."""

    def test_rejecting_one_filing_drops_only_that_contracts_charge(
        self, league: League
    ) -> None:
        """The survivor's charge is untouched and the total is exactly its charge.

        PRD 3.1: "It sums the current-season cap charge of every contract of this
        club whose `status` is either `PENDING_APPROVAL` or `ACTIVE`; adds every
        current-season bonus allocation of those contracts whose
        `counts_against_provisional` flag is true (that is, whose `bonus_type` is
        `ROSTER_BONUS` or `PERFORMANCE_LTBE`), whose `season_year` is the current
        season of 2026, and whose `allocation_status` is either `SCHEDULED` or
        `EARNED`; and finally adds the club's `dead_money_cents`."
        PRD 3.3: "When the rejected filing was a `SIGNING`, its contract moves
        `PENDING_APPROVAL → VOIDED` and the club's provisional commitment and cap
        space are recomputed."

        Design: Corner/calculations/provisional_commitment_drops_only_the_voided_contract_from_the_sum
        """
        world = _two_pending_signings(league)
        analyst = League.analyst(world["club"])

        before = validate_success(
            league.api.get_cap_ledger(world["club"]["id"], analyst), 200
        )
        assert before["provisional_cap_committed_cents"] == 115_333_333, (
            "both undecided charges sit in the provisional total, got "
            f"{before['provisional_cap_committed_cents']}"
        )

        league.submit_filing(world["first_filing"]["id"], world["club"]["id"])
        league.reject_filing(world["first_filing"]["id"], "cap posture")

        after = validate_success(
            league.api.get_cap_ledger(world["club"]["id"], analyst), 200
        )
        assert_cap_position(
            after, provisional=32_000_000, final=0,
            dead_money=0, cap_space=468_000_000,
        )

        voided = league.contract(world["first_filing"]["contract_id"])
        assert voided["status"] == "VOIDED", (
            f"the rejected signing's contract is voided, got {voided['status']}"
        )
        assert voided["current_season_cap_charge_cents"] == 83_333_333, (
            "the row keeps its own value and merely leaves the sum, got "
            f"{voided['current_season_cap_charge_cents']}"
        )

        survivor = league.contract(world["second_filing"]["contract_id"])
        assert survivor["status"] == "PENDING_APPROVAL", (
            f"the other contract is untouched, got {survivor['status']}"
        )
        assert survivor["current_season_cap_charge_cents"] == 32_000_000, (
            "a seven-year deal clamped to five seasons charges 32000000, got "
            f"{survivor['current_season_cap_charge_cents']}"
        )
        assert survivor["annual_proration_cents"] == 2_000_000, (
            f"with an annual share of 2000000, got {survivor['annual_proration_cents']}"
        )
        assert survivor["proration_years"] == 5, (
            f"and a five-season spread, got {survivor['proration_years']}"
        )

        rejected = league.filing(world["first_filing"]["id"])
        assert rejected["status"] == "REJECTED", (
            f"the filing itself is rejected, got {rejected['status']}"
        )
        assert rejected["rejection_reason"] == "cap posture", (
            f"with the stated reason, got {rejected['rejection_reason']}"
        )


class TestRevocableClearanceConstant:
    """A placement made well before the cutoff takes the 24-hour constant."""

    def test_a_revocable_placement_clears_twenty_four_hours_later(
        self, league: League
    ) -> None:
        """The raw deadline already sits in the window, so no snap moves it.

        PRD 3.6: "And `revocability` is evaluated once, at `placed_at`, and frozen:
        a placement made strictly before 2026-08-25T16:00:00Z is `REVOCABLE`, and a
        placement made at or after that instant is `IRREVOCABLE`."
        PRD 3.6: "`clearance_deadline_at` is `placed_at` plus 24 hours for a
        `REVOCABLE` placement or plus 48 hours for an `IRREVOCABLE` one, snapped
        into the daily processing window per §2.5."

        Design: Corner/calculations/waiver_clearance_applies_the_24_hour_revocable_constant
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        release = league.open_release(club["id"], player["id"])
        league.submit_filing(release["id"], club["id"])
        league.approve_filing(release["id"])

        wire = league.place_on_waivers(club["id"], player["id"], release["id"])

        assert wire["revocability"] == "REVOCABLE", (
            "August 10th is well before the irrevocable cutoff, got "
            f"{wire['revocability']}"
        )
        assert wire["placed_at"] == "2026-08-10T14:00:00.000Z", (
            f"the placement instant is the clock, got {wire['placed_at']}"
        )
        assert wire["clearance_deadline_at"] == "2026-08-11T14:00:00.000Z", (
            "24 hours later is still inside the daily window, so nothing snaps, got "
            f"{wire['clearance_deadline_at']}"
        )
        assert wire["status"] == "PENDING", (
            f"a new placement is pending, got {wire['status']}"
        )
        assert wire["contract_id"] == signing["contract_id"], (
            "the active contract rides along on the wire, got "
            f"{wire['contract_id']}"
        )
        assert wire["awarded_to_team_id"] is None, (
            f"nobody has been awarded the player, got {wire['awarded_to_team_id']}"
        )
        assert wire["claim_count"] == 0, (
            f"and nobody has claimed him, got {wire['claim_count']}"
        )

        assert league.player(player["id"])["roster_designation"] == "WAIVED_PENDING", (
            "the player waits on the wire, got "
            f"{league.player(player['id'])['roster_designation']}"
        )


class TestHeadcountsAreRecomputedNotIncremented:
    """A move and its reversal leave both buckets exactly as they started."""

    def test_a_designation_move_and_its_reversal_leave_no_residue(
        self, league: League
    ) -> None:
        """Counting from the player rows makes the reversal exact.

        PRD 3.1: "Each is recomputed, never asserted, as the number of players
        whose owning club is this club and whose `roster_designation` is
        respectively `ACTIVE`, `RESERVE`, `INJURED_RESERVE` and `PRACTICE_SQUAD`."

        Design: Corner/calculations/designation_counts_recompute_after_a_move_and_its_reversal
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )

        onto_reserve = league.open_designation_change(
            club["id"], player["id"], "RESERVE"
        )
        league.submit_filing(onto_reserve["id"], club["id"])
        league.approve_filing(onto_reserve["id"])

        midpoint = league.club(club["id"])
        assert_designation_counts(
            midpoint, active=0, reserve=1, injured_reserve=0, practice_squad=0
        )

        back_to_active = league.open_designation_change(
            club["id"], player["id"], "ACTIVE"
        )
        league.submit_filing(back_to_active["id"], club["id"])
        reversed_move = league.approve_filing(back_to_active["id"])

        assert reversed_move["prior_designation"] == "RESERVE", (
            "the reversal snapshots the reserve bucket it came from, got "
            f"{reversed_move['prior_designation']}"
        )

        after = league.club(club["id"])
        assert_designation_counts(
            after, active=1, reserve=0, injured_reserve=0, practice_squad=0
        )
        assert_cap_position(
            after, provisional=83_333_333, final=83_333_333,
            dead_money=0, cap_space=416_666_667,
        )

        restored = league.player(player["id"])
        assert restored["roster_designation"] == "ACTIVE", (
            f"the player is back where he started, got {restored['roster_designation']}"
        )
        assert restored["current_team_id"] == club["id"], (
            f"and still belongs to the club, got {restored['current_team_id']}"
        )


class TestFinalVariantCatchesUpOnApproval:
    """The provisional total already knew; the final total finds out late."""

    def test_approving_one_of_two_pending_deals_moves_only_the_final_total(
        self, league: League
    ) -> None:
        """The forward-looking variant needs no re-entry when a pending deal confirms.

        PRD 3.1: "The two variants therefore disagree on identical data in two
        specific ways: a not-yet-approved contract raises the provisional total
        while never touching the final total, and an earned not-likely-to-be-earned
        performance bonus raises the final total while never having touched the
        provisional one."
        PRD 3.1: "**`final_cap_committed_cents`** — the *final* variant, used for
        compliance reporting and for the season-settlement view — sums the
        current-season cap charge of only those contracts whose `status` is
        `ACTIVE`; adds only those current-season bonus allocations of those
        contracts whose `allocation_status` is `EARNED`, and here the eligible kinds
        are `ROSTER_BONUS`, `PERFORMANCE_LTBE` **and** `PERFORMANCE_NLTBE`; and
        again adds `dead_money_cents`."

        Design: Corner/calculations/provisional_counts_pending_contracts_and_final_catches_up_on_approval
        """
        world = _two_pending_signings(league)
        club_id = world["club"]["id"]
        analyst = League.analyst(world["club"])

        before = validate_success(league.api.get_cap_ledger(club_id, analyst), 200)
        assert before["provisional_cap_committed_cents"] == 115_333_333, (
            "both pending charges are already counted, got "
            f"{before['provisional_cap_committed_cents']}"
        )
        assert before["final_cap_committed_cents"] == 0, (
            "while the final total knows of no active contract, got "
            f"{before['final_cap_committed_cents']}"
        )

        league.pass_entry_physical(
            club_id, world["first_player"]["id"], world["first_filing"]["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
        )
        league.submit_filing(world["first_filing"]["id"], club_id)
        league.approve_filing(world["first_filing"]["id"])

        after = validate_success(league.api.get_cap_ledger(club_id, analyst), 200)
        assert_cap_position(
            after, provisional=115_333_333, final=83_333_333,
            dead_money=0, cap_space=384_666_667,
        )

        activated = league.contract(world["first_filing"]["contract_id"])
        assert activated["status"] == "ACTIVE", (
            f"the approved contract is active, got {activated['status']}"
        )
        still_pending = league.contract(world["second_filing"]["contract_id"])
        assert still_pending["status"] == "PENDING_APPROVAL", (
            f"the undecided one is not, got {still_pending['status']}"
        )

        rows = league.allocations(world["first_filing"]["contract_id"])
        assert len(rows) == 3, (
            f"a three-season bonus makes three rows, got {len(rows)}"
        )
        assert all(row["bonus_type"] == "SIGNING_PRORATION" for row in rows), (
            "with no performance money there are only proration rows, got "
            f"{[row['bonus_type'] for row in rows]}"
        )
        assert all(row["allocation_status"] == "SCHEDULED" for row in rows), (
            "every row is born scheduled, got "
            f"{[row['allocation_status'] for row in rows]}"
        )
        assert all(row["counts_against_provisional"] is False for row in rows), (
            "and no proration row enters either cap variant, got "
            f"{[row['counts_against_provisional'] for row in rows]}"
        )


class TestAdmissionGateReadsTheProvisionalVariant:
    """The gate compares the provisional total, even when the final one is zero."""

    def test_a_second_filing_is_refused_on_a_total_the_final_variant_cannot_see(
        self, league: League
    ) -> None:
        """One undecided deal is enough to close the club's cap room.

        PRD 3.1: "**`provisional_cap_committed_cents`** — the *provisional* variant
        — is what every admission gate compares against `salary_cap_limit_cents`."
        PRD 2.8: "The club's provisional cap commitment stays within
        `salary_cap_limit_cents` after the write — otherwise
        `ERR_CAP_LIMIT_EXCEEDED` (409)."

        Design: Corner/calculations/provisional_variant_gates_admission_while_final_is_still_zero
        """
        club = _club(league, cap=100_000_000)
        first_player = league.register_player(full_name="Ray Alder", position="QB")
        second_player = league.register_player(full_name="Dov Keller", position="WR")
        first = league.open_signing(
            club["id"], first_player["id"],
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )

        gate = league.club(club["id"])
        assert gate["provisional_cap_committed_cents"] == 83_333_333, (
            "the undecided deal already commits the room, got "
            f"{gate['provisional_cap_committed_cents']}"
        )
        assert gate["final_cap_committed_cents"] == 0, (
            "the final total is still empty, got "
            f"{gate['final_cap_committed_cents']}"
        )

        response = league.api.create_transaction(
            fac.signing_payload(
                club["id"], second_player["id"], gate["version"],
                years=3, base_salary_cents=80_000_000,
                signing_bonus_cents=10_000_000, start_season_year=2026,
            ),
            League.analyst(club),
        )
        validate_error(response, ERR_CAP_LIMIT_EXCEEDED, 409)

        contracts, meta = validate_paginated(
            league.api.list_contracts(league.officer)
        )
        assert meta["total_count"] == 1, (
            f"the refused filing minted no second contract, got {meta['total_count']}"
        )
        assert contracts[0]["id"] == first["contract_id"], (
            "only the first contract exists, got "
            f"{[contract['id'] for contract in contracts]}"
        )

        unchanged = league.club(club["id"])
        assert unchanged["provisional_cap_committed_cents"] == 83_333_333, (
            "the refused write commits nothing, got "
            f"{unchanged['provisional_cap_committed_cents']}"
        )
        assert unchanged["cap_space_cents"] == 16_666_667, (
            f"so the room left is unchanged, got {unchanged['cap_space_cents']}"
        )
        assert unchanged["version"] == gate["version"], (
            f"and the club's version does not move, got {unchanged['version']}"
        )


class TestViolationCatalogueOrder:
    """Two independent violations come back in the catalogue's own order."""

    def test_two_violations_are_listed_in_the_fixed_catalogue_order(
        self, league: League
    ) -> None:
        """The cap code precedes the paperwork code whatever arose first.

        PRD 3.9: "Evaluating a club produces an ordered list of `violation_codes`,
        appended in exactly this fixed order so that the first code is always
        deterministic:"
        PRD 3.9: "`UNFILED_INJURY_PAPERWORK`, when any injury designation of this
        club is still in `PENDING_PAPERWORK` and the logical clock has reached or
        passed that designation's `created_at` plus a 24-hour paperwork grace
        period."
        PRD 3.9: "One subtlety deserves emphasis: the sweep row's `cap_space_cents`
        is the club's `salary_cap_limit_cents` less its **final** committed total,
        because the audit view reports settled money — unlike the club record's own
        `cap_space_cents`, which is measured against the *provisional* total."
        PRD 3.9: "A sweep that finds violations while the club is in `GRACE` and the
        logical clock is still strictly before `grace_expires_at` leaves the club in
        `GRACE`, with `grace_expires_at` and `consecutive_noncompliant_checks` both
        unchanged."

        Design: Corner/calculations/compliance_sweep_lists_violation_codes_in_the_fixed_catalogue_order
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=club["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        designation = league.open_injury_designation(
            club["id"], player["id"], "INJURED_RESERVE"
        )

        league.set_clock("2026-08-11T14:00:00Z")
        cut = league.adjust_limits(club["id"], salary_cap_limit_cents=10_000_000)
        assert cut["cap_space_cents"] == -73_333_333, (
            "cap space is reported negative rather than clamped, got "
            f"{cut['cap_space_cents']}"
        )

        check = league.run_sweep(club["id"])

        assert_violation_codes(check, ["CAP_OVER_LIMIT", "UNFILED_INJURY_PAPERWORK"])
        assert check["checked_at"] == "2026-08-11T14:00:00.000Z", (
            f"the sweep records when it looked, got {check['checked_at']}"
        )
        assert check["result"] == "GRACE", (
            "the club was already inside its grace window, got "
            f"{check['result']}"
        )
        assert check["resulting_compliance_status"] == "GRACE", (
            "and stays there, got "
            f"{check['resulting_compliance_status']}"
        )
        assert check["final_cap_committed_cents"] == 83_333_333, (
            "the audit row reports the settled total, got "
            f"{check['final_cap_committed_cents']}"
        )
        assert check["cap_space_cents"] == -73_333_333, (
            "measured against that final total, got "
            f"{check['cap_space_cents']}"
        )
        assert check["active_roster_count"] == 1, (
            f"the observed active headcount is 1, got {check['active_roster_count']}"
        )
        assert check["injured_reserve_count"] == 0, (
            "an unfiled designation moves no bucket, got "
            f"{check['injured_reserve_count']}"
        )

        swept = league.club(club["id"])
        assert_posture(
            swept, compliance_status="GRACE",
            consecutive_noncompliant_checks=1,
            grace_expires_at="2026-08-12T14:00:00.000Z",
        )

        history = league.sweep_history(club["id"])
        assert len(history) == 1, (
            f"exactly one sweep has been recorded, got {len(history)}"
        )

        stale = league.designation(designation["id"])
        assert stale["status"] == "PENDING_PAPERWORK", (
            "the sweep reports the gap rather than closing it, got "
            f"{stale['status']}"
        )
        assert league.contract(signing["contract_id"])["status"] == "ACTIVE", (
            "the contract is untouched by the sweep, got "
            f"{league.contract(signing['contract_id'])['status']}"
        )
        assert league.player(player["id"])["roster_designation"] == "ACTIVE", (
            "and so is the player, got "
            f"{league.player(player['id'])['roster_designation']}"
        )
