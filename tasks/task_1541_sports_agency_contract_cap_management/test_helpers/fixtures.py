"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a state that takes 5-15
API calls to reach (agency + certified manager + certified agent + client +
team + cap season + contract + proposal, often signed). These helpers
encapsulate those chains so tests can focus on assertions.

All helpers use get_success_data() (lenient validator) so setup failures
surface as clear setup errors rather than confusing assertion failures.

Identity threading: AgencyManager/Agent/Team calls that are ownership-gated
always use make_*_headers(entity_id) with the real entity id — never the
shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_agency_payload,
    create_agent_payload,
    create_cap_season_payload,
    create_client_payload,
    create_contract_payload,
    create_endorsement_payload,
    create_grievance_payload,
    create_proposal_payload,
    create_team_payload,
    create_tender_option_payload,
)
from .test_users import TEST_USERS, make_agency_manager_headers, make_agent_headers, make_team_headers

LEAGUE = TEST_USERS["league_officer_headers"]
# Bootstrap identity used only to register the very first manager agent of an
# agency (agent registration is an AgencyManager act with no ownership check,
# so a shared identifier is safe for that single call).
BOOTSTRAP_MANAGER = TEST_USERS["agency_manager_headers"]


# ─── Tier 2: Entity hierarchy ─────────────────────────────────────────

def create_agency(fee_cap_pct=0.03, name="Apex Sports") -> dict:
    """LeagueOfficer founds an agency. Returns the Agency (ACTIVE)."""
    return get_success_data(
        api_client.create_agency(create_agency_payload(name=name, fee_cap_pct=fee_cap_pct),
                                 LEAGUE))


def create_team_with_cap_season(cap_limit_cents=500_000_000,
                                luxury_threshold_cents=600_000_000,
                                season_year=2026):
    """LeagueOfficer creates a Team and one OPEN CapSeason. Returns (team, cap_season)."""
    team = get_success_data(api_client.create_team(create_team_payload(), LEAGUE))
    cap_season = get_success_data(api_client.create_cap_season(
        team["id"],
        create_cap_season_payload(season_year=season_year,
                                  cap_limit_cents=cap_limit_cents,
                                  luxury_threshold_cents=luxury_threshold_cents),
        LEAGUE))
    return team, cap_season


def register_agent(agency_id, is_manager=False, acting_headers=None, **overrides) -> dict:
    """Register an agent under the agency (starts PENDING). Returns the Agent."""
    return get_success_data(api_client.create_agent(
        agency_id, create_agent_payload(is_manager=is_manager, **overrides),
        acting_headers or BOOTSTRAP_MANAGER))


def certify_agent(agency_id, agent_id, manager_id) -> dict:
    """Manager certifies a PENDING agent. Returns the CERTIFIED Agent."""
    return get_success_data(api_client.certify_agent(
        agency_id, agent_id, make_agency_manager_headers(manager_id)))


def register_client(agency_id, primary_agent_id, **overrides) -> dict:
    """A certified agent registers a client (starts ACTIVE). Returns the Client."""
    return get_success_data(api_client.create_client(
        agency_id, create_client_payload(primary_agent_id, **overrides),
        make_agent_headers(primary_agent_id)))


def setup_agency_with_manager_and_agent(fee_cap_pct=0.03, name="Apex Sports") -> dict:
    """Agency + certified manager + one certified (non-manager) agent.

    Returns {"agency", "manager", "agent"}.
    """
    agency = create_agency(fee_cap_pct=fee_cap_pct, name=name)
    manager = register_agent(agency["id"], is_manager=True)
    manager = certify_agent(agency["id"], manager["id"], manager["id"])
    agent = register_agent(agency["id"], acting_headers=make_agency_manager_headers(manager["id"]))
    agent = certify_agent(agency["id"], agent["id"], manager["id"])
    return {"agency": agency, "manager": manager, "agent": agent}


def setup_negotiation_env(fee_cap_pct=0.03,
                          cap_limit_cents=500_000_000,
                          luxury_threshold_cents=600_000_000,
                          season_year=2026,
                          agency_name="Apex Sports") -> dict:
    """Full negotiation environment: agency, certified manager, certified
    agent, one ACTIVE client of that agent, one team, one OPEN cap season.

    Returns {"agency", "manager", "agent", "client", "team", "cap_season"}.
    """
    bundle = setup_agency_with_manager_and_agent(fee_cap_pct=fee_cap_pct, name=agency_name)
    team, cap_season = create_team_with_cap_season(
        cap_limit_cents=cap_limit_cents,
        luxury_threshold_cents=luxury_threshold_cents,
        season_year=season_year)
    client = register_client(bundle["agency"]["id"], bundle["agent"]["id"])
    bundle.update({"team": team, "cap_season": cap_season, "client": client})
    return bundle


def add_certified_agent(env, is_manager=False, **overrides) -> dict:
    """Register + certify another agent inside an existing env's agency."""
    agent = register_agent(env["agency"]["id"], is_manager=is_manager,
                           acting_headers=make_agency_manager_headers(env["manager"]["id"]),
                           **overrides)
    return certify_agent(env["agency"]["id"], agent["id"], env["manager"]["id"])


def add_client(env, primary_agent_id=None, **overrides) -> dict:
    """Register another ACTIVE client inside an existing env's agency."""
    agent_id = primary_agent_id or env["agent"]["id"]
    return register_client(env["agency"]["id"], agent_id, **overrides)


# ─── Tier 3: Contract / proposal lifecycle shortcuts ──────────────────

def create_contract(env, client_id=None, **overrides) -> dict:
    """Agent creates a contract (NEGOTIATING x UNPOSTED; valuation computed)."""
    client_id = client_id or env["client"]["id"]
    return get_success_data(api_client.create_contract(
        env["agency"]["id"], client_id,
        create_contract_payload(env["team"]["id"], env["cap_season"]["id"], **overrides),
        make_agent_headers(env["agent"]["id"])))


def create_draft_proposal(env, contract_id, proposed_aav_cents=None,
                          proposed_guaranteed_cents=None, agent_id=None) -> dict:
    """Agent drafts a proposal (DRAFT, round_index assigned)."""
    agent_id = agent_id or env["agent"]["id"]
    overrides = {}
    if proposed_aav_cents is not None:
        overrides["proposed_aav_cents"] = proposed_aav_cents
    if proposed_guaranteed_cents is not None:
        overrides["proposed_guaranteed_cents"] = proposed_guaranteed_cents
    return get_success_data(api_client.create_proposal(
        env["agency"]["id"], _client_of(env, contract_id), contract_id,
        create_proposal_payload(agent_id, **overrides),
        make_agent_headers(agent_id)))


def _client_of(env, contract_id):
    """Resolve the client owning a contract created inside this env."""
    client_id = env.get("contract_clients", {}).get(contract_id)
    return client_id or env["client"]["id"]


def fresh_cap_season(env) -> dict:
    """Re-read the cap season (fresh version for OCC-carrying writes)."""
    return get_success_data(api_client.get_cap_season(
        env["team"]["id"], env["cap_season"]["id"], LEAGUE))


def submit_proposal(env, contract_id, proposal_id, agent_id=None) -> dict:
    """Submit a DRAFT proposal with a freshly observed cap-season version."""
    agent_id = agent_id or env["agent"]["id"]
    season = fresh_cap_season(env)
    return get_success_data(api_client.submit_proposal(
        env["agency"]["id"], _client_of(env, contract_id), contract_id, proposal_id,
        season["version"], make_agent_headers(agent_id)))


def accept_proposal(env, contract_id, proposal_id) -> dict:
    """Team accepts a SUBMITTED proposal."""
    return get_success_data(api_client.accept_proposal(
        env["agency"]["id"], _client_of(env, contract_id), contract_id, proposal_id,
        make_team_headers(env["team"]["id"])))


def sign_contract(env, contract_id, agent_id=None) -> dict:
    """Sign a NEGOTIATING contract with a freshly observed contract version."""
    agent_id = agent_id or env["agent"]["id"]
    contract = get_success_data(api_client.get_contract(
        env["agency"]["id"], _client_of(env, contract_id), contract_id,
        make_agent_headers(agent_id)))
    return get_success_data(api_client.sign_contract(
        env["agency"]["id"], _client_of(env, contract_id), contract_id,
        contract["version"], make_agent_headers(agent_id)))


def sign_contract_via_proposal(env, contract_id, proposal_id, agent_id=None) -> dict:
    """Full signing chain: submit -> accept -> sign. Returns the SIGNED contract."""
    submit_proposal(env, contract_id, proposal_id, agent_id=agent_id)
    accept_proposal(env, contract_id, proposal_id)
    return sign_contract(env, contract_id, agent_id=agent_id)


def setup_signed_contract(fee_cap_pct=0.03,
                          cap_limit_cents=500_000_000,
                          luxury_threshold_cents=600_000_000,
                          base_salary_cents=10_000_000,
                          years=1,
                          proposed_aav_cents=None,
                          **contract_overrides) -> dict:
    """Full env plus one SIGNED contract.

    Returns env dict with extra keys "contract" and "proposal".
    """
    env = setup_negotiation_env(fee_cap_pct=fee_cap_pct,
                                cap_limit_cents=cap_limit_cents,
                                luxury_threshold_cents=luxury_threshold_cents)
    contract = create_contract(env, base_salary_cents=base_salary_cents, years=years,
                               guaranteed_cents=contract_overrides.pop(
                                   "guaranteed_cents", base_salary_cents * years),
                               **contract_overrides)
    env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
    proposal = create_draft_proposal(
        env, contract["id"],
        proposed_aav_cents=proposed_aav_cents or contract["aav_cents"],
        proposed_guaranteed_cents=contract["guaranteed_cents"])
    contract = sign_contract_via_proposal(env, contract["id"], proposal["id"])
    env.update({"contract": contract, "proposal": proposal})
    return env


# ─── Tier 2/3 helpers for endorsements, tenders, grievances ───────────

def create_endorsement(env, client_id=None, agent_id=None, **overrides) -> dict:
    """Agent records an endorsement deal (PENDING_APPROVAL)."""
    client_id = client_id or env["client"]["id"]
    agent_id = agent_id or env["agent"]["id"]
    return get_success_data(api_client.create_endorsement(
        env["agency"]["id"], client_id, create_endorsement_payload(**overrides),
        make_agent_headers(agent_id)))


def approve_endorsement(env, deal_id, client_id=None) -> dict:
    """Manager approves a PENDING_APPROVAL deal (computes fee, emits ledger)."""
    client_id = client_id or env["client"]["id"]
    return get_success_data(api_client.approve_endorsement(
        env["agency"]["id"], client_id, deal_id,
        make_agency_manager_headers(env["manager"]["id"])))


def create_tender_option(env, contract_id, client_id=None, agent_id=None,
                         **overrides) -> dict:
    """Agent places a tender/option on a contract (PENDING)."""
    client_id = client_id or env["client"]["id"]
    agent_id = agent_id or env["agent"]["id"]
    return get_success_data(api_client.create_tender_option(
        env["agency"]["id"], client_id, contract_id,
        create_tender_option_payload(**overrides), make_agent_headers(agent_id)))


def create_grievance(env, contract_id, filed_by_agent_id=None, client_id=None,
                     **overrides) -> dict:
    """Agent files a grievance (FILED)."""
    client_id = client_id or env["client"]["id"]
    filed_by_agent_id = filed_by_agent_id or env["agent"]["id"]
    return get_success_data(api_client.create_grievance(
        env["agency"]["id"], client_id, contract_id,
        create_grievance_payload(filed_by_agent_id, **overrides),
        make_agent_headers(filed_by_agent_id)))


# ─── Ledger read helpers ───────────────────────────────────────────────

def list_fee_entries(agency_id, **filters) -> list:
    """List fee ledger entries for an agency with exact-match filters."""
    data, _meta = validate_paginated(
        api_client.list_fee_ledger_entries(agency_id, LEAGUE, params=filters))
    return data


def fee_entries_for_contract(agency_id, contract_id, kind=None) -> list:
    filters = {"contract_id": contract_id}
    if kind is not None:
        filters["kind"] = kind
    return list_fee_entries(agency_id, **filters)
