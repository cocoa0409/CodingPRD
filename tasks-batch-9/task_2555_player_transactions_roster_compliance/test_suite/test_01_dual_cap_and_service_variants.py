"""The two dual-variant ledgers: club cap money and player service time."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as fac
from test_helpers.assertions import (
    assert_cap_position,
    assert_service_profile,
)
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"


def _club_with_divergent_cap_variants(league: League) -> Dict[str, Any]:
    """Build one club whose two cap variants must disagree.

    The club ends up holding an ACTIVE contract charging 83,333,333 cents with a
    SCHEDULED performance-likely allocation of 5,000,000 cents and an EARNED
    performance-not-likely allocation of 7,000,000 cents, plus a second contract
    still pending approval and charging 40,000,000 cents.
    """
    league.set_clock(CLOCK)
    club = league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
    )
    signed_player = league.register_player(
        full_name="Ray Alder", position="QB", accrued_active_days=500,
        accrued_reserve_days=100, accrued_ir_days=80, accrued_practice_days=200,
    )
    first_filing = league.open_signing(
        club["id"], signed_player["id"], expected_team_version=club["version"],
        years=3, base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
        start_season_year=2026, performance_ltbe_cents=5_000_000,
        performance_nltbe_cents=7_000_000,
    )
    league.pass_entry_physical(
        club["id"], signed_player["id"], first_filing["id"],
        window_start_at="2026-08-10T13:00:00Z",
        window_end_at="2026-08-10T20:00:00Z",
        performed_at=CLOCK,
    )
    league.submit_filing(first_filing["id"], club["id"])
    league.approve_filing(first_filing["id"])

    allocations = league.allocations(first_filing["contract_id"])
    not_likely_row = allocations[4]
    league.earn_allocation(not_likely_row["id"])

    pending_player = league.register_player(full_name="Milo Vance", position="WR")
    second_filing = league.open_signing(
        club["id"], pending_player["id"], years=1,
        base_salary_cents=40_000_000, start_season_year=2026,
    )
    return {
        "club": club,
        "active_contract_id": first_filing["contract_id"],
        "pending_contract_id": second_filing["contract_id"],
        "allocations": allocations,
        "not_likely_row_id": not_likely_row["id"],
    }


class TestClubCapVariants:
    """One roster, two commitment totals."""

    def test_cap_ledger_reports_provisional_above_final_on_one_roster(
        self, league: League
    ) -> None:
        """The cap-ledger read separates the provisional and final commitments.

        PRD 3.1: "Consider a club holding one `ACTIVE` contract whose
        current-season charge is 83,333,333 cents, carrying a `SCHEDULED`
        `PERFORMANCE_LTBE` allocation of 5,000,000 cents and an `EARNED`
        `PERFORMANCE_NLTBE` allocation of 7,000,000 cents, plus a
        `PENDING_APPROVAL` contract whose current-season charge is 40,000,000
        cents, with no dead money: the provisional total is 128,333,333 cents,
        the final total is 90,333,333 cents, and against the standard cap the
        club's `cap_space_cents` is 371,666,667 cents."

        Design: Difficulty/dual_variant_calc/team_cap_provisional_and_final_diverge_on_identical_roster
        """
        world = _club_with_divergent_cap_variants(league)

        response = league.api.get_cap_ledger(
            world["club"]["id"], League.analyst(world["club"])
        )
        ledger = validate_success(response, 200)

        assert_cap_position(
            ledger, provisional=128_333_333, final=90_333_333,
            dead_money=0, cap_space=371_666_667,
        )
        divergence = (
            ledger["provisional_cap_committed_cents"]
            - ledger["final_cap_committed_cents"]
        )
        assert divergence == 38_000_000, (
            "the pending contract and the earned not-likely bonus should pull "
            f"the two variants 38000000 cents apart, got {divergence}"
        )

    def test_pending_contract_and_earned_not_likely_bonus_drive_the_divergence(
        self, league: League
    ) -> None:
        """Each variant admits exactly the rows the PRD assigns to it.

        PRD 3.1: "The two variants therefore disagree on identical data in two
        specific ways: a not-yet-approved contract raises the provisional total
        while never touching the final total, and an earned not-likely-to-be-earned
        performance bonus raises the final total while never having touched the
        provisional one."

        Design: Difficulty/dual_variant_calc/team_cap_provisional_and_final_diverge_on_identical_roster
        """
        world = _club_with_divergent_cap_variants(league)

        active_contract = league.contract(world["active_contract_id"])
        assert active_contract["status"] == "ACTIVE", (
            "the approved filing's contract should be ACTIVE, got "
            f"{active_contract['status']}"
        )
        assert active_contract["current_season_cap_charge_cents"] == 83_333_333, (
            "the approved contract should charge 83333333 cents this season, got "
            f"{active_contract['current_season_cap_charge_cents']}"
        )

        pending_contract = league.contract(world["pending_contract_id"])
        assert pending_contract["status"] == "PENDING_APPROVAL", (
            "the second filing's contract should still be PENDING_APPROVAL, got "
            f"{pending_contract['status']}"
        )
        assert pending_contract["current_season_cap_charge_cents"] == 40_000_000, (
            "the pending contract should charge 40000000 cents this season, got "
            f"{pending_contract['current_season_cap_charge_cents']}"
        )

        rows = world["allocations"]
        assert rows[4]["bonus_type"] == "PERFORMANCE_NLTBE", (
            "the fifth allocation row should be the not-likely performance bonus "
            "after three proration rows and the likely one, got "
            f"{[row['bonus_type'] for row in rows]}"
        )
        earned_row = league.allocations(world["active_contract_id"])[4]
        assert earned_row["allocation_status"] == "EARNED", (
            f"the earned row should report EARNED, got {earned_row['allocation_status']}"
        )
        assert earned_row["counts_against_provisional"] is False, (
            "a not-likely-to-be-earned bonus never counts against the provisional "
            "variant"
        )


class TestPlayerServiceVariants:
    """One career, two day totals."""

    def test_injured_reserve_days_count_fully_for_pension_and_half_for_roster(
        self, league: League
    ) -> None:
        """The two service totals diverge by half the injured-reserve days.

        PRD 3.2: "**`pension_credit_days`** is the sum of `accrued_active_days`,
        `accrued_reserve_days` and `accrued_ir_days` — injured-reserve days at
        full weight, practice-squad days excluded entirely."
        PRD 3.2: "**`roster_service_days`** is `accrued_active_days` plus
        `accrued_reserve_days` plus the floor of `accrued_ir_days` multiplied by
        one half — injured-reserve days at half weight, practice-squad days again
        excluded."

        Design: Difficulty/dual_variant_calc/player_pension_credit_and_roster_service_diverge_on_ir_days
        """
        league.set_clock(CLOCK)

        response = league.api.create_player(
            fac.player_payload(
                full_name="Ray Alder", position="QB", accrued_active_days=500,
                accrued_reserve_days=100, accrued_ir_days=80,
                accrued_practice_days=200, practice_squad_seasons_used=0,
            ),
            league.officer,
        )
        player = validate_success(response, 201)

        assert player["pension_credit_days"] == 680, (
            "pension credit should count all 80 injured-reserve days, got "
            f"{player['pension_credit_days']}"
        )
        assert player["roster_service_days"] == 640, (
            "roster service should count only 40 of the 80 injured-reserve days, "
            f"got {player['roster_service_days']}"
        )
        divergence = player["pension_credit_days"] - player["roster_service_days"]
        assert divergence == 40, (
            f"the two totals should differ by 40 days, got {divergence}"
        )

    def test_pension_days_drive_the_rights_class_while_practice_days_count_nowhere(
        self, league: League
    ) -> None:
        """Four seasons of pension credit make the player unrestricted.

        PRD 3.2: "Take a player with 500 active days, 100 reserve days, 80
        injured-reserve days and 200 practice-squad days: pension credit is 680
        days, which is 4 service years, so the rights class is `UNRESTRICTED`;
        roster service is 640 days, so the player is not practice-squad eligible."

        Design: Difficulty/dual_variant_calc/player_pension_credit_and_roster_service_diverge_on_ir_days
        """
        league.set_clock(CLOCK)

        player = league.register_player(
            full_name="Ray Alder", position="QB", accrued_active_days=500,
            accrued_reserve_days=100, accrued_ir_days=80,
            accrued_practice_days=200, practice_squad_seasons_used=0,
        )

        assert_service_profile(
            player, pension_credit_days=680, roster_service_days=640,
            service_years=4, contract_rights_class="UNRESTRICTED",
            practice_squad_eligible=False,
        )
        assert player["accrued_practice_days"] == 200, (
            "the practice-squad bucket should still hold its seeded 200 days, got "
            f"{player['accrued_practice_days']}"
        )
        assert player["pension_credit_days"] == 500 + 100 + 80, (
            "practice-squad days must stay out of the pension total"
        )
