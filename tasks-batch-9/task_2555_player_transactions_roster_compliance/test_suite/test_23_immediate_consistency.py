"""Nothing settles late: one approval, and every derived field is already there."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_cap_position, assert_designation_counts
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"

TERMS = {
    "years": 3,
    "base_salary_cents": 80_000_000,
    "signing_bonus_cents": 10_000_000,
    "start_season_year": 2026,
}


class TestAnApprovalPublishesEveryDerivedFieldAtOnce:
    """The largest cascade in the system, observed with no delay in between.

    PRD 2.9: "Every write in this system is applied **immediately and completely** —
    there is no deferred settlement."
    """

    @staticmethod
    def _a_filed_signing_awaiting_the_league(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"],
            expected_team_version=club["version"], **TERMS
        )
        league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
        )
        league.submit_filing(filing["id"], club["id"])
        return {
            "club": club, "player": player,
            "filing_id": filing["id"], "contract_id": filing["contract_id"],
        }

    def test_the_decide_response_already_carries_the_effective_stamp(
        self, league: League
    ) -> None:
        """Before the decision only provisional money moved; the response closes it.

        PRD 3.1: "Both variants are recomputed by every write that creates, terminates,
        transfers or re-values a contract or a bonus allocation, and they are also
        available as a computed read: the cap-ledger view recomputes both totals from the
        club's live contract and allocation rows and returns them side by side with
        `dead_money_cents` and `cap_space_cents`."

        PRD 3.3: "Once those hold, the approval writes: `status` becomes `APPROVED`;
        `decided_at` and `effective_at` are both set to the logical clock;
        `decided_by_user_id` records the deciding officer; and `prior_designation`
        snapshots the player's `roster_designation` as observed immediately *before* the
        designation side effects below run."

        Design: Corner/consistency_model/an_approval_publishes_every_derived_field_in_the_same_response
        """
        world = self._a_filed_signing_awaiting_the_league(league)

        before = validate_success(
            league.api.get_cap_ledger(
                world["club"]["id"], League.analyst(world["club"])
            ),
            200,
        )
        assert_cap_position(
            before, provisional=83_333_333, final=0,
            dead_money=0, cap_space=416_666_667,
        )
        assert_designation_counts(
            before, active=0, reserve=0, injured_reserve=0, practice_squad=0,
        )

        approved = league.approve_filing(world["filing_id"])
        assert approved["status"] == "APPROVED", (
            f"the decision is the league's answer, got {approved['status']}"
        )
        assert approved["decided_at"] == "2026-08-10T14:00:00.000Z", (
            f"stamped on the logical clock, got {approved['decided_at']}"
        )
        assert approved["effective_at"] == "2026-08-10T14:00:00.000Z", (
            "and effective at that same instant, got "
            f"{approved['effective_at']}"
        )
        assert approved["prior_designation"] == "UNROSTERED", (
            "the snapshot is the designation held before the cascade, got "
            f"{approved['prior_designation']}"
        )

    def test_the_very_next_reads_show_everything_already_settled(
        self, league: League
    ) -> None:
        """No intervening write, no delay, and a repeat read that adds nothing.

        PRD 2.9: "When an operation touches more than one record, all of the
        consequences described in §3 land within the same request: the primary state
        change, the derived recomputations on the affected clubs (their four designation
        headcounts, both cap totals, dead money and cap space), the re-evaluation of the
        affected clubs' compliance posture, and the `updated_at` and `version` bumps on
        each mutated record."

        PRD 3.3: "- **`SIGNING`**: the linked contract moves `PENDING_APPROVAL →
        ACTIVE`; its bonus allocation rows are created; `option_status` becomes `PENDING`
        when the contract carries an option and stays `NOT_APPLICABLE` otherwise; the
        player's designation becomes `PRACTICE_SQUAD` for a practice-squad contract and
        `ACTIVE` otherwise; and `current_team_id` becomes the filing club."

        Design: Corner/consistency_model/an_approval_publishes_every_derived_field_in_the_same_response
        """
        world = self._a_filed_signing_awaiting_the_league(league)
        league.approve_filing(world["filing_id"])

        headers = League.analyst(world["club"])
        after = validate_success(
            league.api.get_cap_ledger(world["club"]["id"], headers), 200
        )
        assert_cap_position(
            after, provisional=83_333_333, final=83_333_333,
            dead_money=0, cap_space=416_666_667,
        )
        assert_designation_counts(
            after, active=1, reserve=0, injured_reserve=0, practice_squad=0,
        )
        assert after["compliance_status"] == "COMPLIANT", (
            "the posture was re-evaluated in the same request, got "
            f"{after['compliance_status']}"
        )

        subject = league.player(world["player"]["id"])
        assert subject["roster_designation"] == "ACTIVE", (
            f"the player is on the active roster, got "
            f"{subject['roster_designation']}"
        )
        assert subject["current_team_id"] == world["club"]["id"], (
            f"owned by the filing club, got {subject['current_team_id']}"
        )
        assert subject["medical_status"] == "CLEARED", (
            f"and medically cleared by his passed entry physical, got "
            f"{subject['medical_status']}"
        )

        again = validate_success(
            league.api.get_cap_ledger(world["club"]["id"], headers), 200
        )
        assert again["final_cap_committed_cents"] == 83_333_333, (
            "the repeated read settles nothing new, got "
            f"{again['final_cap_committed_cents']}"
        )
        assert again["active_roster_count"] == 1, (
            f"nor does it move the headcount, got {again['active_roster_count']}"
        )
        assert again["version"] == after["version"], (
            "a purely computed read leaves the club's version alone, got "
            f"{again['version']} against {after['version']}"
        )

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the offered contract is now live, got {contract['status']}"
        )
        assert contract["option_status"] == "NOT_APPLICABLE", (
            "an option-free contract keeps that dimension parked, got "
            f"{contract['option_status']}"
        )
