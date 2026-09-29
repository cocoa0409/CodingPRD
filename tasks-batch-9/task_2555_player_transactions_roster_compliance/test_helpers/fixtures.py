"""Shared setup.

``League`` is a thin scripting layer over the API: every method is one or a few
real requests, so all state is built the way a client would build it. The pytest
fixtures below stack those methods into the five reusable postures the test suite
keeps needing - a bare pair of records, a filing part-way through its cycle, a
completed signing, a club pushed up against one of its limits, and a club or wire
already parked in a terminal state.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import instant, shift
from . import factories as fac
from .test_users import (
    LEAGUE_OFFICER_HEADERS,
    SECOND_LEAGUE_OFFICER_HEADERS,
    make_agent_headers,
    make_cap_analyst_headers,
    make_league_officer_headers,
    make_medical_officer_headers,
)
from .types import Headers, Payload

# A working date whose in-window hours are used by every canned posture.
BASE_DATE = (2026, 8, 10)
BASE_INSTANT = instant(*BASE_DATE, 14)
EXAM_WINDOW_START = instant(*BASE_DATE, 14)
EXAM_WINDOW_END = instant(*BASE_DATE, 18)
EXAM_PERFORMED_AT = instant(*BASE_DATE, 15)
WORKING_INSTANT = instant(*BASE_DATE, 15)


class League:
    """Scripts the API the way a front office would drive it."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.officer: Headers = LEAGUE_OFFICER_HEADERS
        self.second_officer: Headers = SECOND_LEAGUE_OFFICER_HEADERS

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, moment: str) -> None:
        """Move the logical league clock to an explicit instant."""
        response = self.api.set_clock(moment, self.officer)
        get_success_data(response)

    # ------------------------------------------------------------------
    # Identity shortcuts
    # ------------------------------------------------------------------
    @staticmethod
    def analyst(team: Dict[str, Any]) -> Headers:
        return make_cap_analyst_headers(team["id"])

    @staticmethod
    def medic(team: Dict[str, Any]) -> Headers:
        return make_medical_officer_headers(team["id"])

    @staticmethod
    def agent(player: Dict[str, Any]) -> Headers:
        return make_agent_headers(player["id"])

    def other_officer(self, user_id: str) -> Headers:
        return make_league_officer_headers(user_id)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def club(self, team_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_team(team_id, self.officer))

    def player(self, player_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_player(player_id, self.officer))

    def contract(self, contract_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_contract(contract_id, self.officer))

    def filing(self, transaction_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_transaction(transaction_id, self.officer)
        )

    def wire(self, waiver_request_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_waiver_request(waiver_request_id, self.officer)
        )

    def claim(self, waiver_claim_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_waiver_claim(waiver_claim_id, self.officer)
        )

    def trade(self, trade_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_trade(trade_id, self.officer))

    def tender(self, tender_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_tender(tender_id, self.officer))

    def designation(self, designation_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_injury_designation(designation_id, self.officer)
        )

    def exam(self, exam_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_physical_exam(exam_id, self.officer))

    def allocations(self, contract_id: str,
                    limit: int = 100) -> List[Dict[str, Any]]:
        response = self.api.list_bonus_allocations(
            contract_id, self.officer, params={"limit": limit}
        )
        return get_success_data(response)

    def trade_assets(self, trade_id: str,
                     limit: int = 100) -> List[Dict[str, Any]]:
        response = self.api.list_trade_assets(
            trade_id, self.officer, params={"limit": limit}
        )
        return get_success_data(response)

    def sweep_history(self, team_id: str,
                      limit: int = 100) -> List[Dict[str, Any]]:
        response = self.api.list_team_compliance_checks(
            team_id, self.officer, params={"limit": limit}
        )
        return get_success_data(response)

    def version_of(self, team_id: str) -> int:
        return self.club(team_id)["version"]

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_club(self, **overrides: Any) -> Dict[str, Any]:
        """Register one club and return its record."""
        response = self.api.create_team(fac.team_payload(**overrides), self.officer)
        return get_success_data(response, 201)

    def register_player(self, **overrides: Any) -> Dict[str, Any]:
        """Register one player and return its record."""
        response = self.api.create_player(
            fac.player_payload(**overrides), self.officer
        )
        return get_success_data(response, 201)

    def adjust_limits(self, team_id: str, **limits: Any) -> Dict[str, Any]:
        """Adjust one club's roster or cap limits."""
        response = self.api.patch_team_limits(
            team_id, fac.team_limits_payload(**limits), self.officer
        )
        return get_success_data(response)

    # ------------------------------------------------------------------
    # Filing cycle
    # ------------------------------------------------------------------
    def open_filing(self, payload: Payload, team_id: str) -> Dict[str, Any]:
        """Open a filing on behalf of the club that owns it."""
        response = self.api.create_transaction(
            payload, make_cap_analyst_headers(team_id)
        )
        return get_success_data(response, 201)

    def open_signing(self, team_id: str, player_id: str,
                     expected_team_version: Optional[int] = None,
                     **terms: Any) -> Dict[str, Any]:
        """Open a signing filing, reading the club's live version if not given."""
        version = (
            expected_team_version
            if expected_team_version is not None
            else self.version_of(team_id)
        )
        payload = fac.signing_payload(team_id, player_id, version, **terms)
        return self.open_filing(payload, team_id)

    def open_release(self, team_id: str, player_id: str,
                     expected_team_version: Optional[int] = None,
                     **overrides: Any) -> Dict[str, Any]:
        """Open a release filing for a rostered player."""
        version = (
            expected_team_version
            if expected_team_version is not None
            else self.version_of(team_id)
        )
        payload = fac.release_payload(team_id, player_id, version, **overrides)
        return self.open_filing(payload, team_id)

    def open_designation_change(self, team_id: str, player_id: str,
                                target_designation: str,
                                expected_team_version: Optional[int] = None,
                                **overrides: Any) -> Dict[str, Any]:
        """Open a designation-change filing."""
        version = (
            expected_team_version
            if expected_team_version is not None
            else self.version_of(team_id)
        )
        payload = fac.designation_change_payload(
            team_id, player_id, version, target_designation, **overrides
        )
        return self.open_filing(payload, team_id)

    def open_ir_placement(self, team_id: str, player_id: str,
                          injury_designation_id: str,
                          expected_team_version: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
        """Open an injured-reserve placement filing."""
        version = (
            expected_team_version
            if expected_team_version is not None
            else self.version_of(team_id)
        )
        payload = fac.ir_placement_payload(
            team_id, player_id, version, injury_designation_id, **overrides
        )
        return self.open_filing(payload, team_id)

    def open_ir_activation(self, team_id: str, player_id: str,
                           injury_designation_id: str,
                           expected_team_version: Optional[int] = None,
                           **overrides: Any) -> Dict[str, Any]:
        """Open an injured-reserve activation filing."""
        version = (
            expected_team_version
            if expected_team_version is not None
            else self.version_of(team_id)
        )
        payload = fac.ir_activation_payload(
            team_id, player_id, version, injury_designation_id, **overrides
        )
        return self.open_filing(payload, team_id)

    def submit_filing(self, transaction_id: str, team_id: str) -> Dict[str, Any]:
        """Submit a draft filing to the league office."""
        response = self.api.file_transaction(
            transaction_id, make_cap_analyst_headers(team_id)
        )
        return get_success_data(response)

    def approve_filing(self, transaction_id: str,
                       headers: Optional[Headers] = None) -> Dict[str, Any]:
        """Approve a submitted filing from the league office."""
        response = self.api.decide_transaction(
            transaction_id, fac.approve_payload(), headers or self.officer
        )
        return get_success_data(response)

    def reject_filing(self, transaction_id: str,
                      rejection_reason: str = "Cap room insufficient",
                      headers: Optional[Headers] = None) -> Dict[str, Any]:
        """Reject a submitted filing with a stated reason."""
        response = self.api.decide_transaction(
            transaction_id,
            fac.reject_payload(rejection_reason),
            headers or self.officer,
        )
        return get_success_data(response)

    def revise_filing(self, transaction_id: str, team_id: str,
                      **overrides: Any) -> Dict[str, Any]:
        """Send a rejected filing back to draft."""
        response = self.api.revise_transaction(
            transaction_id,
            fac.revise_payload(**overrides),
            make_cap_analyst_headers(team_id),
        )
        return get_success_data(response)

    # ------------------------------------------------------------------
    # Medical dimension
    # ------------------------------------------------------------------
    def schedule_exam(self, team_id: str, player_id: str, exam_type: str,
                      window_start_at: str, window_end_at: str,
                      **overrides: Any) -> Dict[str, Any]:
        """Book an examination window for a player."""
        payload = fac.physical_exam_payload(
            player_id, team_id, exam_type, window_start_at, window_end_at,
            **overrides,
        )
        response = self.api.create_physical_exam(
            payload, make_medical_officer_headers(team_id)
        )
        return get_success_data(response, 201)

    def record_exam(self, exam_id: str, team_id: str, result: str,
                    performed_at: str) -> Dict[str, Any]:
        """Record the outcome of a booked examination."""
        response = self.api.record_exam_result(
            exam_id,
            fac.exam_result_payload(result, performed_at),
            make_medical_officer_headers(team_id),
        )
        return get_success_data(response)

    def pass_entry_physical(self, team_id: str, player_id: str,
                            transaction_id: str,
                            window_start_at: str = EXAM_WINDOW_START,
                            window_end_at: str = EXAM_WINDOW_END,
                            performed_at: str = EXAM_PERFORMED_AT
                            ) -> Dict[str, Any]:
        """Book and pass the entry physical a signing filing requires."""
        exam = self.schedule_exam(
            team_id, player_id, "ENTRY_PHYSICAL", window_start_at, window_end_at,
            transaction_id=transaction_id,
        )
        return self.record_exam(exam["id"], team_id, "PASSED", performed_at)

    def open_injury_designation(self, team_id: str, player_id: str,
                                designation_type: str = "INJURED_RESERVE",
                                **overrides: Any) -> Dict[str, Any]:
        """Open an injury designation for a rostered player."""
        payload = fac.injury_designation_payload(
            player_id, team_id, designation_type, **overrides
        )
        response = self.api.create_injury_designation(
            payload, make_medical_officer_headers(team_id)
        )
        return get_success_data(response, 201)

    def file_paperwork(self, designation_id: str, team_id: str,
                       paperwork_reference: str = "LEAGUE-IR-0001"
                       ) -> Dict[str, Any]:
        """File the league paperwork that backs an injury designation."""
        response = self.api.file_injury_paperwork(
            designation_id,
            fac.paperwork_payload(paperwork_reference),
            make_medical_officer_headers(team_id),
        )
        return get_success_data(response)

    # ------------------------------------------------------------------
    # Waiver wire
    # ------------------------------------------------------------------
    def place_on_waivers(self, team_id: str, player_id: str,
                         transaction_id: str) -> Dict[str, Any]:
        """Place a released player onto the waiver wire."""
        payload = fac.waiver_request_payload(player_id, team_id, transaction_id)
        response = self.api.create_waiver_request(
            payload, make_cap_analyst_headers(team_id)
        )
        return get_success_data(response, 201)

    def submit_claim(self, waiver_request_id: str, claiming_team_id: str,
                     expected_team_version: Optional[int] = None
                     ) -> Dict[str, Any]:
        """Submit one club's claim on a pending wire."""
        version = (
            expected_team_version
            if expected_team_version is not None
            else self.version_of(claiming_team_id)
        )
        payload = fac.waiver_claim_payload(claiming_team_id, version)
        response = self.api.submit_waiver_claim(
            waiver_request_id, payload, make_cap_analyst_headers(claiming_team_id)
        )
        return get_success_data(response, 201)

    def withdraw_wire(self, waiver_request_id: str,
                      team_id: str) -> Dict[str, Any]:
        """Pull a revocable wire back before it clears."""
        response = self.api.withdraw_waiver_request(
            waiver_request_id, make_cap_analyst_headers(team_id)
        )
        return get_success_data(response)

    def process_wire(self, waiver_request_id: str) -> Dict[str, Any]:
        """Resolve a wire from the league office."""
        response = self.api.process_waiver_request(
            waiver_request_id, self.officer
        )
        return get_success_data(response)

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------
    def build_trade(self, initiating_team_id: str, counterparty_team_id: str,
                    conditional_clause_type: str = "NONE",
                    **overrides: Any) -> Dict[str, Any]:
        """Construct a trade between two clubs."""
        payload = fac.trade_payload(
            initiating_team_id, counterparty_team_id, conditional_clause_type,
            **overrides,
        )
        response = self.api.create_trade(
            payload, make_cap_analyst_headers(initiating_team_id)
        )
        return get_success_data(response, 201)

    def offer_contract(self, trade_id: str, sending_team_id: str,
                       contract_id: str, direction: str,
                       expected_trade_version: Optional[int] = None
                       ) -> Dict[str, Any]:
        """Put one contract on the table from the sending club's side."""
        version = (
            expected_trade_version
            if expected_trade_version is not None
            else self.trade(trade_id)["version"]
        )
        payload = fac.contract_asset_payload(contract_id, direction, version)
        response = self.api.add_trade_asset(
            trade_id, payload, make_cap_analyst_headers(sending_team_id)
        )
        return get_success_data(response, 201)

    def offer_draft_pick(self, trade_id: str, sending_team_id: str,
                         direction: str,
                         expected_trade_version: Optional[int] = None,
                         **overrides: Any) -> Dict[str, Any]:
        """Put one future draft pick on the table."""
        version = (
            expected_trade_version
            if expected_trade_version is not None
            else self.trade(trade_id)["version"]
        )
        payload = fac.draft_pick_asset_payload(direction, version, **overrides)
        response = self.api.add_trade_asset(
            trade_id, payload, make_cap_analyst_headers(sending_team_id)
        )
        return get_success_data(response, 201)

    def counter(self, trade_id: str, acting_team_id: str,
                expected_trade_version: Optional[int] = None
                ) -> Dict[str, Any]:
        """Answer the trade from whichever side owes the response."""
        version = (
            expected_trade_version
            if expected_trade_version is not None
            else self.trade(trade_id)["version"]
        )
        response = self.api.counter_trade(
            trade_id, fac.counter_payload(version),
            make_cap_analyst_headers(acting_team_id),
        )
        return get_success_data(response)

    def accept_trade(self, trade_id: str, acting_team_id: str) -> Dict[str, Any]:
        """Accept the trade from whichever side owes the response."""
        response = self.api.accept_trade(
            trade_id, make_cap_analyst_headers(acting_team_id)
        )
        return get_success_data(response)

    def execute_trade(self, trade_id: str) -> Dict[str, Any]:
        """Execute an accepted trade from the league office."""
        response = self.api.execute_trade(trade_id, self.officer)
        return get_success_data(response)

    # ------------------------------------------------------------------
    # Tenders and options
    # ------------------------------------------------------------------
    def issue_tender(self, team_id: str, player_id: str, offer_type: str,
                     tender_level: str, prior_base_salary_cents: int,
                     **overrides: Any) -> Dict[str, Any]:
        """Issue a tender from a club to an unrostered player."""
        payload = fac.tender_payload(
            player_id, team_id, offer_type, tender_level,
            prior_base_salary_cents, **overrides,
        )
        response = self.api.create_tender(
            payload, make_cap_analyst_headers(team_id)
        )
        return get_success_data(response, 201)

    def respond_to_tender(self, tender_id: str, player_id: str,
                          response_value: str) -> Dict[str, Any]:
        """Answer a tender as the player's own agent."""
        response = self.api.respond_to_tender(
            tender_id, fac.tender_response_payload(response_value),
            make_agent_headers(player_id),
        )
        return get_success_data(response)

    def decide_option(self, contract_id: str, decision: str, headers: Headers,
                      expected_contract_version: Optional[int] = None
                      ) -> Dict[str, Any]:
        """Exercise or decline a contract option."""
        version = (
            expected_contract_version
            if expected_contract_version is not None
            else self.contract(contract_id)["version"]
        )
        response = self.api.decide_option(
            contract_id, fac.option_decision_payload(decision, version), headers
        )
        return get_success_data(response)

    def earn_allocation(self, allocation_id: str) -> Dict[str, Any]:
        """Mark one bonus allocation earned from the league office."""
        response = self.api.earn_bonus_allocation(allocation_id, self.officer)
        return get_success_data(response)

    # ------------------------------------------------------------------
    # Compliance sweep
    # ------------------------------------------------------------------
    def run_sweep(self, team_id: str) -> Dict[str, Any]:
        """Run the daily sweep for one club and return the recorded row."""
        response = self.api.run_compliance_check(
            fac.compliance_check_payload(team_id), self.officer
        )
        return get_success_data(response, 201)

    # ------------------------------------------------------------------
    # Composite lifecycles
    # ------------------------------------------------------------------
    def sign_onto_roster(self, team_id: str, player_id: str,
                         window_start_at: str = EXAM_WINDOW_START,
                         window_end_at: str = EXAM_WINDOW_END,
                         performed_at: str = EXAM_PERFORMED_AT,
                         **terms: Any) -> Dict[str, Any]:
        """Drive one player all the way onto a club's roster.

        Opens the signing filing, books and passes the entry physical, submits the
        filing and has the league office approve it. Returns the ids and the
        records the caller usually wants next.
        """
        filing = self.open_signing(team_id, player_id, **terms)
        self.pass_entry_physical(
            team_id, player_id, filing["id"],
            window_start_at=window_start_at,
            window_end_at=window_end_at,
            performed_at=performed_at,
        )
        self.submit_filing(filing["id"], team_id)
        approved = self.approve_filing(filing["id"])
        return {
            "transaction_id": approved["id"],
            "transaction": approved,
            "contract_id": approved["contract_id"],
            "contract": self.contract(approved["contract_id"]),
            "player": self.player(player_id),
            "team": self.club(team_id),
        }

    def release_onto_wire(self, team_id: str, player_id: str) -> Dict[str, Any]:
        """Release a rostered player and place him on the waiver wire."""
        filing = self.open_release(team_id, player_id)
        self.submit_filing(filing["id"], team_id)
        approved = self.approve_filing(filing["id"])
        wire = self.place_on_waivers(team_id, player_id, approved["id"])
        return {
            "release_transaction_id": approved["id"],
            "release_transaction": approved,
            "waiver_request_id": wire["id"],
            "waiver_request": wire,
        }

    def place_on_injured_reserve(self, team_id: str, player_id: str,
                                 designation_type: str = "INJURED_RESERVE"
                                 ) -> Dict[str, Any]:
        """Open a designation, file its paperwork and approve the placement."""
        designation = self.open_injury_designation(
            team_id, player_id, designation_type
        )
        self.file_paperwork(designation["id"], team_id)
        filing = self.open_ir_placement(team_id, player_id, designation["id"])
        self.submit_filing(filing["id"], team_id)
        approved = self.approve_filing(filing["id"])
        return {
            "designation_id": designation["id"],
            "designation": self.designation(designation["id"]),
            "transaction_id": approved["id"],
            "transaction": approved,
        }

    def freeze_club(self, team_id: str, first_sweep_at: str,
                    ) -> Dict[str, Any]:
        """Walk a club's posture up the ladder until its transactions freeze.

        Requires the club to already carry a violation. Runs the sweep once to
        arm the grace period, advances the clock past the armed expiry, then runs
        the sweep twice more.
        """
        self.set_clock(first_sweep_at)
        self.run_sweep(team_id)
        self.set_clock(shift(first_sweep_at, hours=25))
        self.run_sweep(team_id)
        final_row = self.run_sweep(team_id)
        return {"final_check": final_row, "team": self.club(team_id)}


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the running API."""
    return ApiClient()


@pytest.fixture
def officer() -> Headers:
    """The league transactions office identity."""
    return LEAGUE_OFFICER_HEADERS


@pytest.fixture
def league(api: ApiClient) -> League:
    """The scripting layer, with the clock parked inside the daily window."""
    helper = League(api)
    helper.set_clock(WORKING_INSTANT)
    return helper


# ---------------------------------------------------------------------------
# Tier 1 - entity hierarchy: the bare records other postures build on
# ---------------------------------------------------------------------------
@pytest.fixture
def club(league: League) -> Dict[str, Any]:
    """One freshly registered club holding the standard cap."""
    return league.register_club(name="Harbor Kings", market_code="HRB",
                               waiver_priority_rank=1)


@pytest.fixture
def second_club(league: League) -> Dict[str, Any]:
    """A second club, so peer-club and two-sided cases have a counterparty."""
    return league.register_club(name="Summit Rangers", market_code="SMT",
                                waiver_priority_rank=2)


@pytest.fixture
def free_agent(league: League) -> Dict[str, Any]:
    """One unrostered player with no accrued service."""
    return league.register_player(full_name="Dell Marek", position="QB")


@pytest.fixture
def club_and_free_agent(club: Dict[str, Any],
                        free_agent: Dict[str, Any]) -> Tuple[Dict, Dict]:
    """A club and an unrostered player, the starting point of a signing."""
    return club, free_agent


# ---------------------------------------------------------------------------
# Tier 2 - state progression: a filing paused at each stage of its cycle
# ---------------------------------------------------------------------------
@pytest.fixture
def draft_signing(league: League, club: Dict[str, Any],
                  free_agent: Dict[str, Any]) -> Dict[str, Any]:
    """A signing filing sitting in draft, with its contract pending approval."""
    filing = league.open_signing(
        club["id"], free_agent["id"], years=1, base_salary_cents=10_000_000,
        signing_bonus_cents=0,
    )
    return {
        "club": club,
        "player": free_agent,
        "filing": filing,
        "contract_id": filing["contract_id"],
    }


@pytest.fixture
def filed_signing(league: League, draft_signing: Dict[str, Any]) -> Dict[str, Any]:
    """A signing filing already submitted, with its entry physical passed."""
    club = draft_signing["club"]
    player = draft_signing["player"]
    league.pass_entry_physical(club["id"], player["id"],
                               draft_signing["filing"]["id"])
    filed = league.submit_filing(draft_signing["filing"]["id"], club["id"])
    return {**draft_signing, "filing": filed}


@pytest.fixture
def rejected_signing(league: League, filed_signing: Dict[str, Any]
                     ) -> Dict[str, Any]:
    """A signing filing the league office sent back with a reason."""
    rejected = league.reject_filing(filed_signing["filing"]["id"],
                                    "Terms exceed the club's cap plan")
    return {**filed_signing, "filing": rejected}


# ---------------------------------------------------------------------------
# Tier 3 - full-lifecycle shortcuts
# ---------------------------------------------------------------------------
@pytest.fixture
def rostered_player(league: League, club: Dict[str, Any],
                    free_agent: Dict[str, Any]) -> Dict[str, Any]:
    """A player signed, cleared and approved onto a club's active roster."""
    outcome = league.sign_onto_roster(
        club["id"], free_agent["id"], years=1,
        base_salary_cents=10_000_000, signing_bonus_cents=0,
    )
    return {"club": outcome["team"], "player": outcome["player"], **outcome}


@pytest.fixture
def pending_wire(league: League, rostered_player: Dict[str, Any]
                 ) -> Dict[str, Any]:
    """A released player parked on a pending, revocable waiver wire."""
    club = rostered_player["club"]
    player = rostered_player["player"]
    wire = league.release_onto_wire(club["id"], player["id"])
    return {**rostered_player, **wire}


@pytest.fixture
def active_ir_designation(league: League, rostered_player: Dict[str, Any]
                          ) -> Dict[str, Any]:
    """A rostered player moved onto injured reserve with his window computed."""
    club = rostered_player["club"]
    player = rostered_player["player"]
    placement = league.place_on_injured_reserve(club["id"], player["id"])
    return {**rostered_player, **placement}


@pytest.fixture
def proposed_trade(league: League, club: Dict[str, Any],
                   second_club: Dict[str, Any]) -> Dict[str, Any]:
    """A plain trade between two clubs, still on the table."""
    trade = league.build_trade(club["id"], second_club["id"])
    return {"initiator": club, "counterparty": second_club, "trade": trade}


# ---------------------------------------------------------------------------
# Tier 4 - accumulation and threshold targeting
# ---------------------------------------------------------------------------
@pytest.fixture
def club_at_active_roster_limit(league: League, club: Dict[str, Any],
                                free_agent: Dict[str, Any]) -> Dict[str, Any]:
    """A club whose active roster limit of one is already filled."""
    league.adjust_limits(club["id"], active_roster_limit=1)
    outcome = league.sign_onto_roster(
        club["id"], free_agent["id"], years=1,
        base_salary_cents=10_000_000, signing_bonus_cents=0,
    )
    return {"club": league.club(club["id"]), "player": outcome["player"],
            **outcome}


@pytest.fixture
def club_over_active_roster_limit(league: League, club: Dict[str, Any],
                                  free_agent: Dict[str, Any]) -> Dict[str, Any]:
    """A club carrying one more active player than its limit allows."""
    outcome = league.sign_onto_roster(
        club["id"], free_agent["id"], years=1,
        base_salary_cents=10_000_000, signing_bonus_cents=0,
    )
    league.adjust_limits(club["id"], active_roster_limit=0)
    return {"club": league.club(club["id"]), "player": outcome["player"],
            **outcome}


# ---------------------------------------------------------------------------
# Tier 5 - finalization and terminal states
# ---------------------------------------------------------------------------
@pytest.fixture
def frozen_club(league: League,
                club_over_active_roster_limit: Dict[str, Any]) -> Dict[str, Any]:
    """A club whose posture has climbed the ladder to a transaction freeze."""
    club_record = club_over_active_roster_limit["club"]
    league.freeze_club(club_record["id"], WORKING_INSTANT)
    league.set_clock(WORKING_INSTANT)
    return {**club_over_active_roster_limit,
            "club": league.club(club_record["id"])}


@pytest.fixture
def voided_at_revision_limit(league: League, filed_signing: Dict[str, Any]
                             ) -> Dict[str, Any]:
    """A filing rejected and revised to the limit, then voided by one more try."""
    club = filed_signing["club"]
    transaction_id = filed_signing["filing"]["id"]
    for _ in range(2):
        league.reject_filing(transaction_id, "Terms still exceed the cap plan")
        league.revise_filing(transaction_id, club["id"])
        league.submit_filing(transaction_id, club["id"])
    league.reject_filing(transaction_id, "Terms still exceed the cap plan")
    voided = league.revise_filing(transaction_id, club["id"])
    return {**filed_signing, "filing": voided}
