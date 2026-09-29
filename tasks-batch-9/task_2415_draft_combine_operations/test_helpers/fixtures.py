"""Composite state builders and pytest fixtures.

The API server is restarted with an empty store before every test, so every
fixture here builds the state it needs from scratch through published
endpoints only. Helper functions come first so that a test needing a variant
of a scenario can compose its own chain; the pytest fixtures at the bottom wrap
the most frequently needed compositions.

Canonical two-club / two-round cycle used across the suite::

    HAR  prior_season_win_pct 0.125  lottery_combinations 140  -> pre_lottery_rank 1
    ELM  prior_season_win_pct 0.500  lottery_combinations  75  -> pre_lottery_rank 2

    lottery draw [200, 50] puts ELM in slot one and HAR in slot two, so
    draft_order_index is 1 for ELM and 2 for HAR, and the minted ledger is
    r1p1 ELM 1000.0, r1p2 HAR 940.0, r2p1 ELM 420.0, r2p2 HAR 394.8.
"""

from typing import Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, api_client
from .constants import (
    COMBINE_WEEK_START_AT,
    CYCLE_SETUP_NOW,
    DRAFT_START_AT,
)
from .test_users import (
    make_club_gm_headers,
    make_club_medical_director_headers,
    make_committee_headers,
    make_examiner_headers,
    make_league_admin_headers,
    make_prospect_agent_headers,
    COMMITTEE_DECIDER_USER_ID,
    COMMITTEE_REVIEWER_USER_ID,
)

ADMIN = make_league_admin_headers()
EXAMINER = make_examiner_headers()
COMMITTEE = make_committee_headers()

# Seeding inputs for the canonical clubs.
CLUB_SEEDS: Dict[str, Dict] = {
    "ELM": {
        "market_name": "Elmwood",
        "prior_season_win_pct": 0.500,
        "strength_of_schedule": 0.470,
        "head_to_head_rank": 5,
        "rookie_pool_total_cents": 896721432,
        "lottery_combinations": 75,
    },
    "HAR": {
        "market_name": "Harbor City",
        "prior_season_win_pct": 0.125,
        "strength_of_schedule": 0.520,
        "head_to_head_rank": 1,
        "rookie_pool_total_cents": 500000000,
        "lottery_combinations": 140,
    },
    "BRN": {
        "market_name": "Brenton",
        "prior_season_win_pct": 0.250,
        "strength_of_schedule": 0.480,
        "head_to_head_rank": 2,
        "rookie_pool_total_cents": 500000000,
        "lottery_combinations": 125,
    },
}

# Lottery draw that fills both slots of the canonical two-club pool: 200 falls
# inside ELM's combination block and 50 inside HAR's.
CANONICAL_LOTTERY_SEQUENCE = [200, 50]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Dict:
    """Move the logical clock and return the resulting payload."""
    response = api.set_logical_clock(f.clock_payload(to_iso8601), ADMIN)
    return get_success_data(response)


def create_cycle(api: ApiClient, **overrides) -> Dict:
    response = api.create_draft_cycle(f.draft_cycle_payload(**overrides), ADMIN)
    return get_success_data(response)


def register_club(api: ApiClient, cycle_id: str, club_code: str, **overrides) -> Dict:
    seed = dict(CLUB_SEEDS.get(club_code, {}))
    seed.update(overrides)
    response = api.create_club(
        f.club_payload(cycle_id, club_code, **seed), ADMIN
    )
    return get_success_data(response)


def register_prospect(api: ApiClient, cycle_id: str, **overrides) -> Dict:
    response = api.create_prospect(f.prospect_payload(cycle_id, **overrides), ADMIN)
    return get_success_data(response)


def move_phase(api: ApiClient, cycle_id: str, target_status: str) -> Dict:
    response = api.set_cycle_phase(cycle_id, f.phase_payload(target_status), ADMIN)
    return get_success_data(response)


def read_cycle(api: ApiClient, cycle_id: str) -> Dict:
    return get_success_data(api.get_draft_cycle(cycle_id, ADMIN))


def read_club(api: ApiClient, club_id: str) -> Dict:
    return get_success_data(api.get_club(club_id, ADMIN))


def read_prospect(api: ApiClient, prospect_id: str) -> Dict:
    return get_success_data(api.get_prospect(prospect_id, ADMIN))


def read_pick(api: ApiClient, pick_id: str) -> Dict:
    return get_success_data(api.get_draft_pick(pick_id, ADMIN))


def read_trade(api: ApiClient, trade_id: str) -> Dict:
    return get_success_data(api.get_pick_trade(trade_id, ADMIN))


def read_contract(api: ApiClient, contract_id: str) -> Dict:
    return get_success_data(api.get_player_contract(contract_id, ADMIN))


def read_evaluation(api: ApiClient, evaluation_id: str) -> Dict:
    return get_success_data(api.get_medical_evaluation(evaluation_id, ADMIN))


def read_share(api: ApiClient, share_id: str) -> Dict:
    return get_success_data(api.get_medical_record_share(share_id, ADMIN))


def read_booking(api: ApiClient, booking_id: str) -> Dict:
    return get_success_data(api.get_combine_booking(booking_id, ADMIN))


def read_claim(api: ApiClient, claim_id: str) -> Dict:
    return get_success_data(api.get_compensatory_claim(claim_id, ADMIN))


# ---------------------------------------------------------------------------
# Prospect dimension helpers
# ---------------------------------------------------------------------------


def declare_prospect(api: ApiClient, prospect: Dict) -> Dict:
    """Declare a prospect, acting as the agent that represents it."""
    response = api.declare_prospect(
        prospect["id"],
        f.declaration_payload("DECLARE"),
        make_prospect_agent_headers(prospect["id"]),
    )
    return get_success_data(response)


def withdraw_prospect(api: ApiClient, prospect: Dict) -> Dict:
    response = api.declare_prospect(
        prospect["id"],
        f.declaration_payload("WITHDRAW"),
        make_prospect_agent_headers(prospect["id"]),
    )
    return get_success_data(response)


def rule_prospect_eligible(api: ApiClient, prospect: Dict) -> Dict:
    response = api.determine_prospect_eligibility(
        prospect["id"],
        f.eligibility_determination_payload("DECLARE_ELIGIBLE"),
        COMMITTEE,
    )
    return get_success_data(response)


def rule_prospect_ineligible(api: ApiClient, prospect: Dict) -> Dict:
    response = api.determine_prospect_eligibility(
        prospect["id"],
        f.eligibility_determination_payload("DECLARE_INELIGIBLE"),
        COMMITTEE,
    )
    return get_success_data(response)


def invite_prospect(api: ApiClient, prospect: Dict) -> Dict:
    response = api.act_on_combine_invitation(
        prospect["id"], f.combine_invitation_payload("INVITE"), ADMIN
    )
    return get_success_data(response)


def accept_invitation(api: ApiClient, prospect: Dict) -> Dict:
    response = api.act_on_combine_invitation(
        prospect["id"],
        f.combine_invitation_payload("ACCEPT"),
        make_prospect_agent_headers(prospect["id"]),
    )
    return get_success_data(response)


def grant_consent(
    api: ApiClient,
    prospect: Dict,
    scope: str = "FULL",
    consent_expires_at: str = "2027-03-15T12:00:00.000Z",
) -> Dict:
    response = api.act_on_prospect_consent(
        prospect["id"],
        f.consent_payload("GRANT", scope, consent_expires_at),
        make_prospect_agent_headers(prospect["id"]),
    )
    return get_success_data(response)


def revoke_consent(api: ApiClient, prospect: Dict) -> Dict:
    response = api.act_on_prospect_consent(
        prospect["id"],
        f.consent_payload("REVOKE", scope=None, consent_expires_at=None),
        make_prospect_agent_headers(prospect["id"]),
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Cycle state progression
# ---------------------------------------------------------------------------


def build_cycle_with_clubs(
    api: ApiClient,
    club_codes: List[str] = ("ELM", "HAR"),
    now: str = CYCLE_SETUP_NOW,
    **cycle_overrides,
) -> Dict:
    """Clock, cycle and registered clubs, still at SETUP."""
    set_clock(api, now)
    overrides = {"rounds_count": 2}
    overrides.update(cycle_overrides)
    cycle = create_cycle(api, **overrides)
    clubs = {code: register_club(api, cycle["id"], code) for code in club_codes}
    return {"cycle": cycle, "clubs": clubs}


def open_declarations(api: ApiClient, state: Dict) -> Dict:
    state["cycle"] = move_phase(api, state["cycle"]["id"], "DECLARATION_OPEN")
    return state


def build_declaration_open(api: ApiClient, **kwargs) -> Dict:
    return open_declarations(api, build_cycle_with_clubs(api, **kwargs))


def build_combine_week(api: ApiClient, **kwargs) -> Dict:
    """DECLARATION_OPEN advanced to COMBINE_WEEK behind one declared prospect."""
    state = build_declaration_open(api, **kwargs)
    prospect = register_prospect(api, state["cycle"]["id"])
    state["prospect"] = declare_prospect(api, prospect)
    state["cycle"] = move_phase(api, state["cycle"]["id"], "COMBINE_WEEK")
    return state


def build_order_pending(api: ApiClient, **kwargs) -> Dict:
    state = build_combine_week(api, **kwargs)
    state["prospect"] = rule_prospect_eligible(api, state["prospect"])
    state["cycle"] = move_phase(api, state["cycle"]["id"], "ORDER_PENDING")
    return state


def run_lottery(
    api: ApiClient,
    cycle_id: str,
    sequence: Optional[List[int]] = None,
) -> Dict:
    response = api.run_lottery(
        cycle_id,
        f.lottery_payload(
            list(sequence if sequence is not None else CANONICAL_LOTTERY_SEQUENCE)
        ),
        ADMIN,
    )
    return get_success_data(response)


def finalize_order(api: ApiClient, cycle_id: str) -> Dict:
    return get_success_data(api.finalize_draft_order(cycle_id, None, ADMIN))


def list_picks(api: ApiClient, cycle_id: str, limit: int = 100) -> List[Dict]:
    response = api.list_draft_picks(
        ADMIN, {"draft_cycle_id": cycle_id, "limit": limit}
    )
    return get_success_data(response)


def pick_index(picks: List[Dict]) -> Dict[str, Dict]:
    """Index a minted ledger by a readable ``r<round>p<slot>`` key."""
    return {
        f"r{p['round_number']}p{p['pick_in_round']}": p
        for p in picks
        if not p.get("is_compensatory")
    }


def build_order_final(api: ApiClient, **kwargs) -> Dict:
    """Lottery run, order minted, cycle at ORDER_FINAL, picks indexed."""
    state = build_order_pending(api, **kwargs)
    state["cycle"] = run_lottery(api, state["cycle"]["id"])
    state["finalize"] = finalize_order(api, state["cycle"]["id"])
    state["picks"] = list_picks(api, state["cycle"]["id"])
    state["pick"] = pick_index(state["picks"])
    state["cycle"] = read_cycle(api, state["cycle"]["id"])
    return state


def build_draft_live(api: ApiClient, at: str = DRAFT_START_AT, **kwargs) -> Dict:
    """ORDER_FINAL taken to DRAFT_LIVE with the clock at ``at``."""
    state = build_order_final(api, **kwargs)
    set_clock(api, at)
    state["cycle"] = move_phase(api, state["cycle"]["id"], "DRAFT_LIVE")
    return state


def advance_clock(api: ApiClient, cycle_id: str) -> Dict:
    return get_success_data(api.advance_selection_clock(cycle_id, None, ADMIN))


def build_draft_live_on_clock(api: ApiClient, **kwargs) -> Dict:
    """DRAFT_LIVE with overall pick one on the clock."""
    state = build_draft_live(api, **kwargs)
    state["advance"] = advance_clock(api, state["cycle"]["id"])
    state["cycle"] = read_cycle(api, state["cycle"]["id"])
    return state


# ---------------------------------------------------------------------------
# Selections, contracts and the UDFA window
# ---------------------------------------------------------------------------


def make_selection(
    api: ApiClient, pick: Dict, prospect: Dict, club: Dict, **overrides
) -> Dict:
    response = api.create_selection(
        pick["id"],
        f.selection_payload(prospect["id"], **overrides),
        make_club_gm_headers(club["id"]),
    )
    return get_success_data(response)


def build_first_selection(api: ApiClient, **kwargs) -> Dict:
    """Overall pick one used by ELM on the declared, eligible prospect."""
    state = build_draft_live_on_clock(api, **kwargs)
    elm = state["clubs"]["ELM"]
    state["used_pick"] = make_selection(
        api, state["pick"]["r1p1"], state["prospect"], elm
    )
    state["prospect"] = read_prospect(api, state["prospect"]["id"])
    return state


def offer_drafted_contract(
    api: ApiClient, prospect: Dict, club: Dict, pick: Dict
) -> Dict:
    fresh = read_prospect(api, prospect["id"])
    response = api.create_player_contract(
        f.player_contract_payload(
            prospect["id"],
            club["id"],
            "DRAFTED",
            fresh["version"],
            draft_pick_id=pick["id"],
        ),
        make_club_gm_headers(club["id"]),
    )
    return get_success_data(response)


def sign_contract(api: ApiClient, contract: Dict) -> Dict:
    response = api.set_contract_status(
        contract["id"],
        f.contract_status_payload("SIGN"),
        make_prospect_agent_headers(contract["prospect_id"]),
    )
    return get_success_data(response)


def build_signed_drafted_contract(api: ApiClient, **kwargs) -> Dict:
    """Selection made, contract offered by the drafting club and signed."""
    state = build_first_selection(api, **kwargs)
    elm = state["clubs"]["ELM"]
    contract = offer_drafted_contract(
        api, state["prospect"], elm, state["used_pick"]
    )
    state["contract"] = sign_contract(api, contract)
    return state


def complete_the_draft(api: ApiClient, state: Dict) -> Dict:
    """Advance the clock past every remaining window so the draft completes."""
    cycle_id = state["cycle"]["id"]
    set_clock(api, "2027-04-24T00:00:00.000Z")
    state["final_advance"] = advance_clock(api, cycle_id)
    state["cycle"] = read_cycle(api, cycle_id)
    return state


def build_udfa_window(api: ApiClient, **kwargs) -> Dict:
    """Draft driven to DRAFT_COMPLETE and then opened for undrafted signings."""
    state = build_draft_live_on_clock(api, **kwargs)
    state = complete_the_draft(api, state)
    state["cycle"] = move_phase(api, state["cycle"]["id"], "UDFA_WINDOW")
    return state


# ---------------------------------------------------------------------------
# Combine facilities, bookings and medical records
# ---------------------------------------------------------------------------


def create_station(
    api: ApiClient,
    station_code: str = "ST-ORTHO-1",
    exam_type: str = "ORTHO",
    **overrides,
) -> Dict:
    response = api.create_medical_station(
        f.medical_station_payload(station_code, exam_type, **overrides), ADMIN
    )
    return get_success_data(response)


def create_room(api: ApiClient, room_code: str = "IR-1", **overrides) -> Dict:
    response = api.create_interview_room(
        f.interview_room_payload(room_code, **overrides), ADMIN
    )
    return get_success_data(response)


def book(
    api: ApiClient,
    prospect: Dict,
    booking_type: str,
    starts_at: str,
    ends_at: str,
    **overrides,
) -> Dict:
    response = api.create_combine_booking(
        f.combine_booking_payload(
            prospect["id"], booking_type, starts_at, ends_at, **overrides
        ),
        ADMIN,
    )
    return get_success_data(response)


def set_booking(api: ApiClient, booking: Dict, action: str) -> Dict:
    response = api.set_booking_status(
        booking["id"], f.booking_status_payload(action), ADMIN
    )
    return get_success_data(response)


def build_combine_week_with_station(api: ApiClient, **kwargs) -> Dict:
    """COMBINE_WEEK with an invited prospect and one ORTHO station registered."""
    state = build_combine_week(api, **kwargs)
    state["prospect"] = invite_prospect(api, state["prospect"])
    state["prospect"] = accept_invitation(api, state["prospect"])
    state["station"] = create_station(api)
    return state


def build_completed_medical_exam(api: ApiClient, **kwargs) -> Dict:
    """A medical exam booking taken all the way to COMPLETED."""
    state = build_combine_week_with_station(api, **kwargs)
    booking = book(
        api,
        state["prospect"],
        "MEDICAL_EXAM",
        "2027-02-22T09:00:00.000Z",
        "2027-02-22T09:45:00.000Z",
        medical_station_id=state["station"]["id"],
    )
    set_clock(api, "2027-02-22T08:45:00.000Z")
    booking = set_booking(api, booking, "CHECK_IN")
    state["booking"] = set_booking(api, booking, "COMPLETE")
    return state


def file_evaluation(
    api: ApiClient,
    booking: Dict,
    prospect: Dict,
    findings_code: str = "ORTHO-CLEAR-01",
    medical_grade: str = "PASS",
) -> Dict:
    response = api.create_medical_evaluation(
        f.medical_evaluation_payload(
            booking["id"],
            prospect["id"],
            findings_code=findings_code,
            medical_grade=medical_grade,
        ),
        EXAMINER,
    )
    return get_success_data(response)


def build_medical_evaluation(
    api: ApiClient,
    findings_code: str = "ORTHO-CLEAR-01",
    medical_grade: str = "PASS",
    **kwargs,
) -> Dict:
    """Completed exam plus the filed evaluation documenting it."""
    state = build_completed_medical_exam(api, **kwargs)
    state["evaluation"] = file_evaluation(
        api,
        state["booking"],
        state["prospect"],
        findings_code=findings_code,
        medical_grade=medical_grade,
    )
    state["prospect"] = read_prospect(api, state["prospect"]["id"])
    return state


def request_share(
    api: ApiClient,
    evaluation: Dict,
    club: Dict,
    scope: str = "FULL",
    as_medical_director: bool = False,
    expected_version: Optional[int] = None,
) -> Dict:
    fresh = read_evaluation(api, evaluation["id"])
    headers = (
        make_club_medical_director_headers(club["id"])
        if as_medical_director
        else make_club_gm_headers(club["id"])
    )
    response = api.create_medical_record_share(
        f.medical_record_share_payload(
            evaluation["id"],
            club["id"],
            expected_version if expected_version is not None else fresh["version"],
            scope=scope,
        ),
        headers,
    )
    return get_success_data(response)


def decide_share(api: ApiClient, share: Dict, action: str, **overrides) -> Dict:
    response = api.decide_medical_record_share(
        share["id"], f.share_decision_payload(action, **overrides), ADMIN
    )
    return get_success_data(response)


def build_granted_share(
    api: ApiClient, scope: str = "FULL", consent_scope: str = "FULL", **kwargs
) -> Dict:
    """Evaluation filed, consent granted by the agent and the share granted."""
    state = build_medical_evaluation(api, **kwargs)
    state["prospect"] = grant_consent(api, state["prospect"], scope=consent_scope)
    share = request_share(
        api, state["evaluation"], state["clubs"]["ELM"], scope=scope
    )
    state["share"] = decide_share(api, share, "GRANT")
    state["evaluation"] = read_evaluation(api, state["evaluation"]["id"])
    return state


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------


def file_waiver(
    api: ApiClient, prospect: Dict, waiver_type: str = "LATE_DECLARATION", **overrides
) -> Dict:
    response = api.create_eligibility_waiver(
        prospect["id"],
        f.eligibility_waiver_payload(waiver_type, **overrides),
        make_prospect_agent_headers(prospect["id"]),
    )
    return get_success_data(response)


def review_waiver(
    api: ApiClient,
    waiver: Dict,
    action: str,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict:
    response = api.review_eligibility_waiver(
        waiver["id"],
        f.waiver_review_payload(action, **overrides),
        headers if headers is not None else COMMITTEE,
    )
    return get_success_data(response)


def build_waiver_under_review(
    api: ApiClient, waiver_type: str = "LATE_DECLARATION", **kwargs
) -> Dict:
    """A filed waiver opened for review by a committee member."""
    state = build_declaration_open(api, **kwargs)
    prospect = register_prospect(api, state["cycle"]["id"])
    state["prospect"] = prospect
    waiver = file_waiver(api, prospect, waiver_type)
    state["waiver"] = review_waiver(
        api,
        waiver,
        "OPEN_REVIEW",
        make_committee_headers(COMMITTEE_REVIEWER_USER_ID),
    )
    state["reviewer_headers"] = make_committee_headers(COMMITTEE_REVIEWER_USER_ID)
    state["decider_headers"] = make_committee_headers(COMMITTEE_DECIDER_USER_ID)
    return state


# ---------------------------------------------------------------------------
# Trades and compensatory claims
# ---------------------------------------------------------------------------


def propose_trade(
    api: ApiClient,
    cycle: Dict,
    proposing: Dict,
    receiving: Dict,
    offered: List[Dict],
    requested: List[Dict],
    **overrides,
) -> Dict:
    response = api.create_pick_trade(
        f.pick_trade_payload(
            cycle["id"],
            proposing["id"],
            receiving["id"],
            [p["id"] for p in offered],
            [p["id"] for p in requested],
            **overrides,
        ),
        make_club_gm_headers(proposing["id"]),
    )
    return get_success_data(response)


def counter_trade(
    api: ApiClient,
    trade: Dict,
    acting_club: Dict,
    offered: List[Dict],
    requested: List[Dict],
) -> Dict:
    response = api.counter_pick_trade(
        trade["id"],
        f.trade_counter_payload(
            [p["id"] for p in offered], [p["id"] for p in requested]
        ),
        make_club_gm_headers(acting_club["id"]),
    )
    return get_success_data(response)


def accept_trade(api: ApiClient, trade: Dict, acting_club: Dict) -> Dict:
    response = api.accept_pick_trade(
        trade["id"], None, make_club_gm_headers(acting_club["id"])
    )
    return get_success_data(response)


def file_claim(api: ApiClient, cycle: Dict, club: Dict, **overrides) -> Dict:
    response = api.create_compensatory_claim(
        f.compensatory_claim_payload(cycle["id"], club["id"], **overrides),
        make_club_gm_headers(club["id"]),
    )
    return get_success_data(response)


def verify_claim(api: ApiClient, claim: Dict, action: str = "VERIFY") -> Dict:
    response = api.verify_compensatory_claim(
        claim["id"], f.claim_verify_payload(action), ADMIN
    )
    return get_success_data(response)


def build_seven_round_order_final(api: ApiClient, **kwargs) -> Dict:
    """The canonical two-club cycle minted over all seven rounds."""
    return build_order_final(api, rounds_count=7, **kwargs)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers() -> Dict:
    return make_league_admin_headers()


@pytest.fixture
def examiner_headers() -> Dict:
    return make_examiner_headers()


@pytest.fixture
def committee_headers() -> Dict:
    return make_committee_headers()


@pytest.fixture
def cycle_setup(api: ApiClient) -> Dict:
    """Clock parked in the cycle year with one two-round cycle at SETUP."""
    set_clock(api, CYCLE_SETUP_NOW)
    return create_cycle(api, rounds_count=2)


@pytest.fixture
def cycle_with_two_clubs(api: ApiClient) -> Dict:
    return build_cycle_with_clubs(api)


@pytest.fixture
def declaration_open(api: ApiClient) -> Dict:
    return build_declaration_open(api)


@pytest.fixture
def combine_week(api: ApiClient) -> Dict:
    return build_combine_week(api)


@pytest.fixture
def combine_week_with_station(api: ApiClient) -> Dict:
    return build_combine_week_with_station(api)


@pytest.fixture
def completed_medical_exam(api: ApiClient) -> Dict:
    return build_completed_medical_exam(api)


@pytest.fixture
def medical_evaluation(api: ApiClient) -> Dict:
    return build_medical_evaluation(api)


@pytest.fixture
def granted_share(api: ApiClient) -> Dict:
    return build_granted_share(api)


@pytest.fixture
def waiver_under_review(api: ApiClient) -> Dict:
    return build_waiver_under_review(api)


@pytest.fixture
def order_pending(api: ApiClient) -> Dict:
    return build_order_pending(api)


@pytest.fixture
def order_final(api: ApiClient) -> Dict:
    return build_order_final(api)


@pytest.fixture
def seven_round_order_final(api: ApiClient) -> Dict:
    return build_seven_round_order_final(api)


@pytest.fixture
def draft_live(api: ApiClient) -> Dict:
    return build_draft_live(api)


@pytest.fixture
def draft_live_on_clock(api: ApiClient) -> Dict:
    return build_draft_live_on_clock(api)


@pytest.fixture
def first_selection(api: ApiClient) -> Dict:
    return build_first_selection(api)


@pytest.fixture
def signed_drafted_contract(api: ApiClient) -> Dict:
    return build_signed_drafted_contract(api)


@pytest.fixture
def udfa_window(api: ApiClient) -> Dict:
    return build_udfa_window(api)


@pytest.fixture
def combine_week_start() -> str:
    return COMBINE_WEEK_START_AT
