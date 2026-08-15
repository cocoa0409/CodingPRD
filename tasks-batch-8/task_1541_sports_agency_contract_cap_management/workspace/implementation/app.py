"""Sports Agency Contract & Cap Management API — Flask entry point.

Validation pipeline per PRD 2.7 (an earlier failure masks all later checks):
  1 auth (ERR_UNAUTHENTICATED 401)
  2 role (ERR_FORBIDDEN 403)
  3 existence, path ids left-to-right (ERR_NOT_FOUND 404)
  -- OCC version check (ERR_STALE_VERSION 412) on the two OCC endpoints --
  4 state (ERR_INVALID_STATE 409)
  5 certification (ERR_AGENT_NOT_CERTIFIED 422)
  6 ownership (ERR_OWNERSHIP_VIOLATION 422)
  7 temporal windows (ERR_WINDOW_CLOSED 422)
  8 soft-cap reservation check (ERR_CAP_WOULD_EXCEED 422)
  9 hard-cap acceptance check (ERR_CAP_HARD_LIMIT 422)
 10 resource locks (ERR_RESOURCE_LOCKED 409)
 11 contract uniqueness (ERR_DUPLICATE_ACTIVE_CONTRACT 409)
 12 field constraints (ERR_INVALID_REQUEST 400)
 13 release gates (ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS 409)
 14 open-grievance gate (ERR_OPEN_GRIEVANCE 409)
"""

import os

from flask import Flask, g

import db
import helpers as h
import services as svc
from errors import (
    ApiError, err_invalid_state, err_stale_version, err_agent_not_certified,
    err_ownership_violation, err_window_closed, err_cap_would_exceed,
    err_cap_hard_limit, err_resource_locked, err_duplicate_active_contract,
    err_invalid_request, err_client_has_active_obligations,
    err_open_grievance, err_not_found,
)
from helpers import (
    authenticate, require_role, get_json_body, reject_unknown_fields,
    req_string, opt_string, req_enum, req_int, opt_int, req_number, opt_number,
    opt_bool, req_datetime, new_entity, bump, bump_once, now_stamp,
    parse_pagination, paginate, sorted_by_created,
    resolve_agency, resolve_agent, resolve_client, resolve_team,
    resolve_cap_season, resolve_contract, resolve_proposal,
    resolve_endorsement, resolve_tender_option, resolve_grievance,
    resolve_fee_entry, acting_certified_agent,
)
from response import success_object, success_list, error_response, format_ts

app = Flask(__name__)

ROLES_ALL = h.ALL_ROLES
TENDER_KINDS = {"QUALIFYING_OFFER", "TEAM_OPTION", "PLAYER_OPTION"}
GRIEVANCE_CATEGORIES = {"NON_PAYMENT", "ROSTER_MOVE", "BONUS_DISPUTE", "MEDICAL"}


# ---------------------------------------------------------------------------
# Request lifecycle: one process-wide lock per request; time-driven state
# transitions are evaluated against the logical clock before each request.
# ---------------------------------------------------------------------------

@app.before_request
def _begin_request():
    db.lock.acquire()
    g._locked = True
    svc.sweep_time_transitions()


@app.teardown_request
def _end_request(exc):
    if getattr(g, "_locked", False):
        db.lock.release()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, status = error_response(exc.error_id, exc.message, exc.http_status)
    return body, status


@app.errorhandler(404)
def handle_404(exc):
    body, status = error_response("ERR_NOT_FOUND", "Resource not found", 404)
    return body, status


@app.errorhandler(405)
def handle_405(exc):
    body, status = error_response("ERR_NOT_FOUND", "Resource not found", 404)
    return body, status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unexpected error")
    body, status = error_response("ERR_INTERNAL", "Internal error", 500)
    return body, status


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def view(entity):
    from decimal import Decimal
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        # Decimals ride internally for exact rate math (PRD 2.6); serialize as
        # plain JSON numbers.
        if isinstance(v, Decimal):
            v = int(v) if v == v.to_integral_value() else float(v)
        out[k] = v
    return out


def cap_season_view(cs):
    d = view(cs)
    d["available_hard_cents"] = (
        cs["cap_limit_cents"] - cs["committed_cents"] - cs["reserved_cents"]
    )
    d["available_luxury_cents"] = (
        cs["luxury_threshold_cents"] - cs["committed_cents"] - cs["reserved_cents"]
    )
    return d


def list_response(items, view_fn=view):
    limit, offset = parse_pagination()
    ordered = sorted_by_created(items)
    page, total = paginate(ordered, limit, offset)
    return success_list([view_fn(e) for e in page], limit, offset, total)


def _match(entity, field, raw):
    if raw is None:
        return True
    return str(entity.get(field)) == raw


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    authenticate()
    role = __import__("flask").request.headers.get("X-User-Role")
    require_role(role, ["LeagueOfficer", "AgencyManager"])
    body = get_json_body()
    reject_unknown_fields(body, {"to_iso8601"})
    dt = h.parse_datetime_iso(body.get("to_iso8601"), "to_iso8601") if "to_iso8601" in body else None
    if dt is None:
        raise err_invalid_request("Missing required field: to_iso8601")
    db.set_clock(dt)
    svc.sweep_time_transitions()
    return success_object({"current_utc": format_ts(db.get_clock())})


# ---------------------------------------------------------------------------
# Agency
# ---------------------------------------------------------------------------

@app.post("/agencies")
def create_agency():
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    body = get_json_body()
    reject_unknown_fields(body, {"name", "fee_cap_pct"})
    name = req_string(body, "name")
    fee_cap_pct = req_number(body, "fee_cap_pct")
    agency = new_entity()
    agency.update({
        "name": name,
        "fee_cap_pct": fee_cap_pct,
        "status": "ACTIVE",
    })
    db.agencies[agency["id"]] = agency
    return success_object(view(agency), 201)


@app.get("/agencies/<agencyId>")
def get_agency(agencyId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    agency = resolve_agency(agencyId)
    return success_object(view(agency))


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

@app.post("/agencies/<agencyId>/agents")
def create_agent(agencyId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    agency = resolve_agency(agencyId)
    body = get_json_body()
    reject_unknown_fields(body, {"full_name", "email", "cert_number", "is_manager"})
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    cert_number = req_string(body, "cert_number")
    is_manager = opt_bool(body, "is_manager", False)
    for a in db.agents.values():
        if a["agency_id"] == agencyId and a["email"] == email:
            raise err_invalid_request("email must be unique within the agency")
    agent = new_entity()
    agent.update({
        "agency_id": agencyId,
        "full_name": full_name,
        "email": email,
        "cert_number": cert_number,
        "cert_status": "PENDING",
        "certified_at": None,
        "is_manager": is_manager,
    })
    db.agents[agent["id"]] = agent
    return success_object(view(agent), 201)


@app.get("/agencies/<agencyId>/agents")
def list_agents(agencyId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent"])
    resolve_agency(agencyId)
    from flask import request
    items = [a for a in db.agents.values() if a["agency_id"] == agencyId]
    cs = request.args.get("cert_status")
    if cs is not None:
        items = [a for a in items if a["cert_status"] == cs]
    return list_response(items)


@app.get("/agencies/<agencyId>/agents/<agentId>")
def get_agent(agencyId, agentId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent"])
    resolve_agency(agencyId)
    agent = resolve_agent(agencyId, agentId)
    return success_object(view(agent))


@app.post("/agencies/<agencyId>/agents/<agentId>/certify")
def certify_agent(agencyId, agentId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    agency = resolve_agency(agencyId)
    agent = resolve_agent(agencyId, agentId)
    if agent["cert_status"] != "PENDING":
        raise err_invalid_state("Agent cert_status must be PENDING to certify")
    if agency["status"] != "ACTIVE":
        raise err_resource_locked("Agency is not ACTIVE")
    agent["cert_status"] = "CERTIFIED"
    agent["certified_at"] = now_stamp()
    bump(agent)
    return success_object(view(agent))


@app.post("/agencies/<agencyId>/agents/<agentId>/suspend")
def suspend_agent(agencyId, agentId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    resolve_agency(agencyId)
    agent = resolve_agent(agencyId, agentId)
    if agent["cert_status"] != "CERTIFIED":
        raise err_invalid_state("Agent cert_status must be CERTIFIED to suspend")
    agent["cert_status"] = "SUSPENDED"
    bump(agent)
    svc.withdraw_agent_inflight_proposals(agent["id"])
    return success_object(view(agent))


@app.post("/agencies/<agencyId>/agents/<agentId>/reinstate")
def reinstate_agent(agencyId, agentId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    resolve_agency(agencyId)
    agent = resolve_agent(agencyId, agentId)
    if agent["cert_status"] != "SUSPENDED":
        raise err_invalid_state("Agent cert_status must be SUSPENDED to reinstate")
    agent["cert_status"] = "CERTIFIED"
    bump(agent)
    return success_object(view(agent))


@app.post("/agencies/<agencyId>/agents/<agentId>/revoke")
def revoke_agent(agencyId, agentId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    resolve_agency(agencyId)
    agent = resolve_agent(agencyId, agentId)
    if agent["cert_status"] not in ("CERTIFIED", "SUSPENDED"):
        raise err_invalid_state("Agent cert_status must be CERTIFIED or SUSPENDED to revoke")
    was_certified = agent["cert_status"] == "CERTIFIED"
    agent["cert_status"] = "REVOKED"
    bump(agent)
    if was_certified:
        svc.withdraw_agent_inflight_proposals(agent["id"])
    for c in db.clients.values():
        if c["agency_id"] == agencyId and c["primary_agent_id"] == agent["id"] and c["status"] == "ACTIVE":
            c["status"] = "TRANSITIONING"
            c["transition_to_agent_id"] = None
            bump(c)
    return success_object(view(agent))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

@app.post("/agencies/<agencyId>/clients")
def create_client(agencyId):
    user_id, role = authenticate()
    require_role(role, ["Agent", "AgencyManager"])
    resolve_agency(agencyId)
    body = get_json_body()
    reject_unknown_fields(body, {"primary_agent_id", "full_name", "position"})
    primary_agent_id = req_string(body, "primary_agent_id")
    full_name = req_string(body, "full_name")
    position = req_string(body, "position")
    agent = resolve_agent(agencyId, primary_agent_id)
    if agent["cert_status"] != "CERTIFIED":
        raise err_agent_not_certified("primary_agent_id must reference a CERTIFIED agent")
    client = new_entity()
    client.update({
        "agency_id": agencyId,
        "primary_agent_id": primary_agent_id,
        "full_name": full_name,
        "position": position,
        "status": "ACTIVE",
        "transition_to_agent_id": None,
    })
    db.clients[client["id"]] = client
    return success_object(view(client), 201)


@app.get("/agencies/<agencyId>/clients")
def list_clients(agencyId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    resolve_agency(agencyId)
    from flask import request
    items = [c for c in db.clients.values() if c["agency_id"] == agencyId]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    pa = request.args.get("primary_agent_id")
    if pa is not None:
        items = [c for c in items if c["primary_agent_id"] == pa]
    return list_response(items)


@app.get("/agencies/<agencyId>/clients/<clientId>")
def get_client(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    resolve_agency(agencyId)
    client = resolve_client(agencyId, clientId)
    return success_object(view(client))


@app.post("/agencies/<agencyId>/clients/<clientId>/initiate_transition")
def initiate_transition(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    resolve_agency(agencyId)
    client = resolve_client(agencyId, clientId)
    if client["status"] != "ACTIVE":
        raise err_invalid_state("Client must be ACTIVE to initiate a transition")
    body = get_json_body()
    reject_unknown_fields(body, {"target_agent_id"})
    target_agent_id = req_string(body, "target_agent_id")
    target = resolve_agent(agencyId, target_agent_id)
    if target["cert_status"] != "CERTIFIED":
        raise err_agent_not_certified("target_agent_id must reference a CERTIFIED agent")
    client["status"] = "TRANSITIONING"
    client["transition_to_agent_id"] = target_agent_id
    bump(client)
    return success_object(view(client))


@app.post("/agencies/<agencyId>/clients/<clientId>/complete_transition")
def complete_transition(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    agency = resolve_agency(agencyId)
    client = resolve_client(agencyId, clientId)
    if client["status"] != "TRANSITIONING":
        raise err_invalid_state("Client must be TRANSITIONING to complete a transition")
    new_agent_id = client["transition_to_agent_id"]
    new_agent = db.agents.get(new_agent_id) if new_agent_id else None
    if new_agent is None or new_agent["cert_status"] != "CERTIFIED":
        raise err_agent_not_certified("transition_to_agent_id must be a CERTIFIED agent")
    old_agent_id = client["primary_agent_id"]
    client["primary_agent_id"] = new_agent_id
    client["transition_to_agent_id"] = None
    client["status"] = "ACTIVE"
    bump(client)
    current_year = db.get_clock().year
    for contract in db.contracts.values():
        if contract["client_id"] == clientId and contract["signing_status"] == "SIGNED":
            _, old_amount, new_amount = svc.transition_split_amounts(
                contract, agency["fee_cap_pct"], current_year
            )
            svc.emit_fee_entry(
                agencyId, contract["id"], None, old_agent_id,
                0.25, old_amount, "TRANSITION_ADJUSTMENT",
            )
            svc.emit_fee_entry(
                agencyId, contract["id"], None, new_agent_id,
                0.75, new_amount, "TRANSITION_ADJUSTMENT",
            )
    return success_object(view(client))


@app.post("/agencies/<agencyId>/clients/<clientId>/release")
def release_client(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    resolve_agency(agencyId)
    client = resolve_client(agencyId, clientId)
    if client["status"] not in ("ACTIVE", "TRANSITIONING"):
        raise err_invalid_state("Client must be ACTIVE or TRANSITIONING to release")
    has_active_endorsement = any(
        d["client_id"] == clientId and d["status"] == "ACTIVE"
        for d in db.endorsements.values()
    )
    if client["status"] == "ACTIVE":
        blocked = any(
            c["client_id"] == clientId and c["signing_status"] in ("NEGOTIATING", "SIGNED")
            for c in db.contracts.values()
        ) or has_active_endorsement
    else:
        blocked = any(
            c["client_id"] == clientId and c["signing_status"] == "SIGNED"
            for c in db.contracts.values()
        ) or has_active_endorsement
    if blocked:
        raise err_client_has_active_obligations()
    client["status"] = "RELEASED"
    bump(client)
    return success_object(view(client))


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

@app.post("/teams")
def create_team():
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    body = get_json_body()
    reject_unknown_fields(body, {"name", "league_code"})
    name = req_string(body, "name")
    league_code = req_string(body, "league_code")
    team = new_entity()
    team.update({"name": name, "league_code": league_code})
    db.teams[team["id"]] = team
    return success_object(view(team), 201)


@app.get("/teams/<teamId>")
def get_team(teamId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player", "Team"])
    team = resolve_team(teamId)
    return success_object(view(team))


# ---------------------------------------------------------------------------
# CapSeason
# ---------------------------------------------------------------------------

@app.post("/teams/<teamId>/cap_seasons")
def create_cap_season(teamId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    resolve_team(teamId)
    body = get_json_body()
    reject_unknown_fields(body, {"season_year", "cap_limit_cents", "luxury_threshold_cents"})
    season_year = req_int(body, "season_year")
    cap_limit_cents = req_int(body, "cap_limit_cents")
    luxury_threshold_cents = req_int(body, "luxury_threshold_cents")
    if luxury_threshold_cents <= cap_limit_cents:
        raise err_invalid_request("luxury_threshold_cents must exceed cap_limit_cents")
    season = new_entity()
    season.update({
        "team_id": teamId,
        "season_year": season_year,
        "cap_limit_cents": cap_limit_cents,
        "luxury_threshold_cents": luxury_threshold_cents,
        "committed_cents": 0,
        "reserved_cents": 0,
        "status": "OPEN",
    })
    db.cap_seasons[season["id"]] = season
    return success_object(cap_season_view(season), 201)


def _list_cap_seasons_filtered(items):
    from flask import request
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    sy = request.args.get("season_year")
    if sy is not None:
        try:
            sy_int = int(sy)
            items = [s for s in items if s["season_year"] == sy_int]
        except ValueError:
            items = []
    return items


@app.get("/teams/<teamId>/cap_seasons")
def list_cap_seasons(teamId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Team"])
    resolve_team(teamId)
    items = [s for s in db.cap_seasons.values() if s["team_id"] == teamId]
    return list_response(_list_cap_seasons_filtered(items), cap_season_view)


@app.get("/teams/<teamId>/cap_seasons/<capSeasonId>")
def get_cap_season(teamId, capSeasonId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Team"])
    resolve_team(teamId)
    season = resolve_cap_season(teamId, capSeasonId)
    return success_object(cap_season_view(season))


@app.post("/teams/<teamId>/cap_seasons/<capSeasonId>/lock")
def lock_cap_season(teamId, capSeasonId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    resolve_team(teamId)
    season = resolve_cap_season(teamId, capSeasonId)
    if season["status"] != "OPEN":
        raise err_invalid_state("CapSeason must be OPEN to lock")
    season["status"] = "LOCKED"
    bump(season)
    svc.lock_season_cascade(season)
    return success_object(cap_season_view(season))


@app.post("/teams/<teamId>/cap_seasons/<capSeasonId>/unlock")
def unlock_cap_season(teamId, capSeasonId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    resolve_team(teamId)
    season = resolve_cap_season(teamId, capSeasonId)
    if season["status"] != "LOCKED":
        raise err_invalid_state("CapSeason must be LOCKED to unlock")
    season["status"] = "OPEN"
    bump(season)
    return success_object(cap_season_view(season))


@app.post("/teams/<teamId>/cap_seasons/<capSeasonId>/close")
def close_cap_season(teamId, capSeasonId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    resolve_team(teamId)
    season = resolve_cap_season(teamId, capSeasonId)
    if season["status"] not in ("OPEN", "LOCKED"):
        raise err_invalid_state("CapSeason must be OPEN or LOCKED to close")
    if season["reserved_cents"] != 0:
        raise err_invalid_state("CapSeason reserved_cents must be zero to close")
    season["status"] = "CLOSED"
    bump(season)
    return success_object(cap_season_view(season))


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

def _chain_contract(agencyId, clientId, contractId):
    agency = resolve_agency(agencyId)
    client = resolve_client(agencyId, clientId)
    contract = resolve_contract(clientId, contractId)
    return agency, client, contract


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts")
def create_contract(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    resolve_agency(agencyId)
    resolve_client(agencyId, clientId)
    body = get_json_body()
    allowed = {"team_id", "cap_season_id", "start_season_year", "years",
               "base_salary_cents", "guaranteed_cents", "signing_bonus_cents",
               "incentive_cents", "escalator_pct"}
    reject_unknown_fields(body, allowed)
    team_id = req_string(body, "team_id")
    cap_season_id = req_string(body, "cap_season_id")
    start_season_year = req_int(body, "start_season_year")
    years = req_int(body, "years")
    base_salary_cents = req_int(body, "base_salary_cents")
    guaranteed_cents = req_int(body, "guaranteed_cents")
    signing_bonus_cents = opt_int(body, "signing_bonus_cents", 0)
    incentive_cents = opt_int(body, "incentive_cents", 0)
    escalator_pct = opt_number(body, "escalator_pct", 0)
    # Body FK existence (priority 3): team resolves, cap season resolves in team scope.
    resolve_team(team_id)
    resolve_cap_season(team_id, cap_season_id)
    # Uniqueness (priority 11): one NEGOTIATING/SIGNED contract per (client, team).
    for c in db.contracts.values():
        if (c["client_id"] == clientId and c["team_id"] == team_id
                and c["signing_status"] in ("NEGOTIATING", "SIGNED")):
            raise err_duplicate_active_contract()
    # Field constraints (priority 12).
    if years < 1 or years > 5:
        raise err_invalid_request("years must be between 1 and 5")
    if guaranteed_cents > base_salary_cents * years:
        raise err_invalid_request("guaranteed_cents must not exceed base_salary_cents * years")
    if svc.D(escalator_pct) < 0 or svc.D(escalator_pct) > svc.D("0.15"):
        raise err_invalid_request("escalator_pct must lie in [0, 0.15]")
    aav_cents, total_value_cents = svc.contract_valuation(
        base_salary_cents, years, signing_bonus_cents, incentive_cents, escalator_pct
    )
    contract = new_entity()
    contract.update({
        "client_id": clientId,
        "team_id": team_id,
        "cap_season_id": cap_season_id,
        "start_season_year": start_season_year,
        "years": years,
        "base_salary_cents": base_salary_cents,
        "guaranteed_cents": guaranteed_cents,
        "signing_bonus_cents": signing_bonus_cents,
        "incentive_cents": incentive_cents,
        "escalator_pct": escalator_pct,
        "aav_cents": aav_cents,
        "total_value_cents": total_value_cents,
        "signing_status": "NEGOTIATING",
        "cap_posting_status": "UNPOSTED",
    })
    db.contracts[contract["id"]] = contract
    return success_object(view(contract), 201)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts")
def list_contracts(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    resolve_agency(agencyId)
    resolve_client(agencyId, clientId)
    from flask import request
    items = [c for c in db.contracts.values() if c["client_id"] == clientId]
    ss = request.args.get("signing_status")
    if ss is not None:
        items = [c for c in items if c["signing_status"] == ss]
    tid = request.args.get("team_id")
    if tid is not None:
        items = [c for c in items if c["team_id"] == tid]
    return list_response(items)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>")
def get_contract(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player", "Team"])
    _chain_contract(agencyId, clientId, contractId)
    return success_object(view(db.contracts[contractId]))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/sign")
def sign_contract(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    agency, client, contract = _chain_contract(agencyId, clientId, contractId)
    body = get_json_body()
    reject_unknown_fields(body, {"expected_contract_version"})
    expected = req_int(body, "expected_contract_version")
    if expected != contract["version"]:
        raise err_stale_version()
    # State (priority 4)
    if contract["signing_status"] != "NEGOTIATING":
        raise err_invalid_state("Contract must be NEGOTIATING to sign")
    accepted = [p for p in db.proposals.values()
                if p["contract_id"] == contractId and p["status"] == "ACCEPTED"]
    if not accepted:
        raise err_invalid_state("Signing requires an ACCEPTED proposal")
    if client["status"] != "ACTIVE":
        raise err_invalid_state("Client must be ACTIVE to sign")
    # Certification (5) then ownership (6)
    acting_certified_agent(user_id)
    if user_id != client["primary_agent_id"]:
        raise err_ownership_violation("Signer must be the client's primary agent")
    # Side effects
    contract["signing_status"] = "SIGNED"
    contract["cap_posting_status"] = "POSTED"
    bump(contract)
    season = db.cap_seasons[contract["cap_season_id"]]
    season["committed_cents"] += contract["aav_cents"]
    bump_once(season)
    gross_fee = svc.playing_contract_fee(contract["aav_cents"], agency["fee_cap_pct"])
    svc.emit_fee_entry(
        agencyId, contractId, None, client["primary_agent_id"],
        1.0, gross_fee, "PLAYING_CONTRACT",
    )
    svc.withdraw_open_proposals(contract)
    return success_object(view(contract))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/void")
def void_contract(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    agency, client, contract = _chain_contract(agencyId, clientId, contractId)
    if contract["signing_status"] not in ("NEGOTIATING", "SIGNED"):
        raise err_invalid_state("Contract must be NEGOTIATING or SIGNED to void")
    if contract["signing_status"] == "SIGNED":
        open_grievance = any(
            gr["contract_id"] == contractId
            and gr["status"] in ("FILED", "UNDER_REVIEW", "ARBITRATION")
            for gr in db.grievances.values()
        )
        if open_grievance:
            raise err_open_grievance()
    was_signed = contract["signing_status"] == "SIGNED"
    contract["signing_status"] = "VOIDED"
    contract["cap_posting_status"] = "REVERSED"
    bump(contract)
    if was_signed:
        season = db.cap_seasons[contract["cap_season_id"]]
        season["committed_cents"] -= contract["aav_cents"]
        bump_once(season)
        svc.void_accrued_entries_for_contract(contractId)
    else:
        svc.withdraw_open_proposals(contract)
    return success_object(view(contract))


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------

def _chain_proposal(agencyId, clientId, contractId, proposalId):
    agency, client, contract = _chain_contract(agencyId, clientId, contractId)
    proposal = resolve_proposal(contractId, proposalId)
    return agency, client, contract, proposal


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals")
def create_proposal(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    _chain_contract(agencyId, clientId, contractId)
    body = get_json_body()
    reject_unknown_fields(body, {"proposed_by_agent_id", "proposed_aav_cents",
                                 "proposed_guaranteed_cents"})
    proposed_by_agent_id = req_string(body, "proposed_by_agent_id")
    proposed_aav_cents = req_int(body, "proposed_aav_cents")
    proposed_guaranteed_cents = req_int(body, "proposed_guaranteed_cents")
    resolve_agent(agencyId, proposed_by_agent_id)
    round_index = 1 + max(
        [p["round_index"] for p in db.proposals.values() if p["contract_id"] == contractId],
        default=0,
    )
    proposal = new_entity()
    proposal.update({
        "contract_id": contractId,
        "proposed_by_agent_id": proposed_by_agent_id,
        "round_index": round_index,
        "proposed_aav_cents": proposed_aav_cents,
        "proposed_guaranteed_cents": proposed_guaranteed_cents,
        "status": "DRAFT",
    })
    db.proposals[proposal["id"]] = proposal
    return success_object(view(proposal), 201)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals")
def list_proposals(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Team"])
    _chain_contract(agencyId, clientId, contractId)
    from flask import request
    items = [p for p in db.proposals.values() if p["contract_id"] == contractId]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    return list_response(items)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals/<proposalId>")
def get_proposal(agencyId, clientId, contractId, proposalId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Team"])
    _chain_proposal(agencyId, clientId, contractId, proposalId)
    return success_object(view(db.proposals[proposalId]))


def _submit_core(agencyId, contract, proposal, user_id, check_occ, new_aav=None):
    """Shared submit/resubmit logic. Returns the cap season on success."""
    season = db.cap_seasons[contract["cap_season_id"]]
    if check_occ is not None:
        if check_occ != season["version"]:
            raise err_stale_version()
    # State (priority 4)
    expected_from = "DRAFT" if new_aav is None else "COUNTERED"
    if proposal["status"] != expected_from:
        raise err_invalid_state(f"Proposal must be {expected_from}")
    if contract["signing_status"] != "NEGOTIATING":
        raise err_invalid_state("Contract must be NEGOTIATING")
    # Certification (5) then ownership (6)
    acting_certified_agent(user_id)
    if user_id != proposal["proposed_by_agent_id"]:
        raise err_ownership_violation("Acting agent must be the proposal's author")
    aav = proposal["proposed_aav_cents"] if new_aav is None else new_aav
    # Soft cap (priority 8) outranks resource lock (priority 10) — PRD 2.7.
    if season["committed_cents"] + season["reserved_cents"] + aav > season["luxury_threshold_cents"]:
        raise err_cap_would_exceed()
    if season["status"] != "OPEN":
        raise err_resource_locked("CapSeason is not OPEN")
    # Side effects
    if new_aav is not None:
        season["reserved_cents"] -= proposal["proposed_aav_cents"]
        proposal["proposed_aav_cents"] = new_aav
    season["reserved_cents"] += proposal["proposed_aav_cents"]
    bump_once(season)
    proposal["status"] = "SUBMITTED"
    bump(proposal)
    return season


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals/<proposalId>/submit")
def submit_proposal(agencyId, clientId, contractId, proposalId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    agency, client, contract, proposal = _chain_proposal(agencyId, clientId, contractId, proposalId)
    body = get_json_body()
    reject_unknown_fields(body, {"expected_cap_season_version"})
    expected = req_int(body, "expected_cap_season_version")
    _submit_core(agencyId, contract, proposal, user_id, expected)
    return success_object(view(proposal))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals/<proposalId>/counter")
def counter_proposal(agencyId, clientId, contractId, proposalId):
    user_id, role = authenticate()
    require_role(role, ["Team"])
    agency, client, contract, proposal = _chain_proposal(agencyId, clientId, contractId, proposalId)
    body = get_json_body()
    reject_unknown_fields(body, {"counter_aav_cents"})
    counter_aav_cents = req_int(body, "counter_aav_cents")
    if proposal["status"] != "SUBMITTED":
        raise err_invalid_state("Proposal must be SUBMITTED to counter")
    season = db.cap_seasons[contract["cap_season_id"]]
    season["reserved_cents"] -= proposal["proposed_aav_cents"]
    season["reserved_cents"] += counter_aav_cents
    bump_once(season)
    proposal["proposed_aav_cents"] = counter_aav_cents
    proposal["status"] = "COUNTERED"
    bump(proposal)
    return success_object(view(proposal))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals/<proposalId>/resubmit")
def resubmit_proposal(agencyId, clientId, contractId, proposalId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    agency, client, contract, proposal = _chain_proposal(agencyId, clientId, contractId, proposalId)
    body = get_json_body()
    reject_unknown_fields(body, {"proposed_aav_cents"})
    new_aav = req_int(body, "proposed_aav_cents")
    _submit_core(agencyId, contract, proposal, user_id, None, new_aav=new_aav)
    return success_object(view(proposal))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals/<proposalId>/accept")
def accept_proposal(agencyId, clientId, contractId, proposalId):
    user_id, role = authenticate()
    require_role(role, ["Team"])
    agency, client, contract, proposal = _chain_proposal(agencyId, clientId, contractId, proposalId)
    if proposal["status"] != "SUBMITTED":
        raise err_invalid_state("Proposal must be SUBMITTED to accept")
    season = db.cap_seasons[contract["cap_season_id"]]
    # Hard cap (priority 9) outranks resource lock (priority 10) — PRD 2.7.
    if season["committed_cents"] + proposal["proposed_aav_cents"] > season["cap_limit_cents"]:
        raise err_cap_hard_limit()
    if season["status"] != "OPEN":
        raise err_resource_locked("CapSeason is not OPEN")
    season["reserved_cents"] -= proposal["proposed_aav_cents"]
    bump_once(season)
    proposal["status"] = "ACCEPTED"
    bump(proposal)
    # Acceptance rewrites the contract's proposal set (scaffold 1.2.1): the
    # contract version advances so stale signers are caught by OCC.
    bump(contract)
    svc.withdraw_open_proposals(contract)
    return success_object(view(proposal))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals/<proposalId>/reject")
def reject_proposal(agencyId, clientId, contractId, proposalId):
    user_id, role = authenticate()
    require_role(role, ["Team"])
    agency, client, contract, proposal = _chain_proposal(agencyId, clientId, contractId, proposalId)
    if proposal["status"] != "SUBMITTED":
        raise err_invalid_state("Proposal must be SUBMITTED to reject")
    season = db.cap_seasons[contract["cap_season_id"]]
    season["reserved_cents"] -= proposal["proposed_aav_cents"]
    bump_once(season)
    proposal["status"] = "REJECTED"
    bump(proposal)
    return success_object(view(proposal))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/proposals/<proposalId>/withdraw")
def withdraw_proposal(agencyId, clientId, contractId, proposalId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    agency, client, contract, proposal = _chain_proposal(agencyId, clientId, contractId, proposalId)
    if proposal["status"] not in ("DRAFT", "SUBMITTED", "COUNTERED"):
        raise err_invalid_state("Proposal must be DRAFT, SUBMITTED, or COUNTERED to withdraw")
    if user_id != proposal["proposed_by_agent_id"]:
        raise err_ownership_violation("Acting agent must be the proposal's author")
    svc.withdraw_proposal(proposal, contract)
    return success_object(view(proposal))


# ---------------------------------------------------------------------------
# EndorsementDeal
# ---------------------------------------------------------------------------

@app.post("/agencies/<agencyId>/clients/<clientId>/endorsements")
def create_endorsement(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    resolve_agency(agencyId)
    resolve_client(agencyId, clientId)
    body = get_json_body()
    reject_unknown_fields(body, {"brand_name", "deal_value_cents", "start_date", "end_date"})
    brand_name = req_string(body, "brand_name")
    deal_value_cents = req_int(body, "deal_value_cents")
    start_raw = req_string(body, "start_date")
    end_raw = req_string(body, "end_date")
    start_dt = h.parse_datetime_iso(start_raw, "start_date")
    end_dt = h.parse_datetime_iso(end_raw, "end_date")
    if end_dt <= start_dt:
        raise err_window_closed("end_date must be after start_date")
    deal = new_entity()
    deal.update({
        "client_id": clientId,
        "brand_name": brand_name,
        "deal_value_cents": deal_value_cents,
        "start_date": start_raw,
        "end_date": end_raw,
        "agent_fee_cents": None,
        "status": "PENDING_APPROVAL",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.endorsements[deal["id"]] = deal
    return success_object(view(deal), 201)


@app.get("/agencies/<agencyId>/clients/<clientId>/endorsements")
def list_endorsements(agencyId, clientId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    resolve_agency(agencyId)
    resolve_client(agencyId, clientId)
    from flask import request
    items = [d for d in db.endorsements.values() if d["client_id"] == clientId]
    st = request.args.get("status")
    if st is not None:
        items = [d for d in items if d["status"] == st]
    return list_response(items)


@app.get("/agencies/<agencyId>/clients/<clientId>/endorsements/<dealId>")
def get_endorsement(agencyId, clientId, dealId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    resolve_agency(agencyId)
    resolve_client(agencyId, clientId)
    deal = resolve_endorsement(clientId, dealId)
    return success_object(view(deal))


@app.post("/agencies/<agencyId>/clients/<clientId>/endorsements/<dealId>/approve")
def approve_endorsement(agencyId, clientId, dealId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    agency = resolve_agency(agencyId)
    client = resolve_client(agencyId, clientId)
    deal = resolve_endorsement(clientId, dealId)
    if deal["status"] != "PENDING_APPROVAL":
        raise err_invalid_state("Deal must be PENDING_APPROVAL to approve")
    if client["status"] != "ACTIVE":
        raise err_invalid_state("Client must be ACTIVE to approve a deal")
    if agency["status"] != "ACTIVE":
        raise err_resource_locked("Agency is not ACTIVE")
    fee = svc.endorsement_agent_fee(deal["deal_value_cents"], agency["fee_cap_pct"])
    deal["agent_fee_cents"] = fee
    deal["status"] = "ACTIVE"
    bump(deal)
    svc.emit_fee_entry(
        agencyId, None, dealId, client["primary_agent_id"],
        1.0, fee, "ENDORSEMENT",
    )
    return success_object(view(deal))


@app.post("/agencies/<agencyId>/clients/<clientId>/endorsements/<dealId>/terminate")
def terminate_endorsement(agencyId, clientId, dealId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    resolve_agency(agencyId)
    resolve_client(agencyId, clientId)
    deal = resolve_endorsement(clientId, dealId)
    if deal["status"] != "ACTIVE":
        raise err_invalid_state("Deal must be ACTIVE to terminate")
    deal["status"] = "TERMINATED"
    bump(deal)
    svc.void_accrued_entries_for_deal(dealId)
    return success_object(view(deal))


# ---------------------------------------------------------------------------
# TenderOption
# ---------------------------------------------------------------------------

@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/tender_options")
def create_tender_option(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["Agent", "Team"])
    _chain_contract(agencyId, clientId, contractId)
    body = get_json_body()
    reject_unknown_fields(body, {"kind", "window_open_at", "window_close_at"})
    kind = req_enum(body, "kind", TENDER_KINDS)
    open_raw = req_string(body, "window_open_at")
    close_raw = req_string(body, "window_close_at")
    open_dt = h.parse_datetime_iso(open_raw, "window_open_at")
    close_dt = h.parse_datetime_iso(close_raw, "window_close_at")
    if close_dt <= open_dt:
        raise err_window_closed("window_close_at must be after window_open_at")
    tender = new_entity()
    tender.update({
        "contract_id": contractId,
        "kind": kind,
        "window_open_at": open_raw,
        "window_close_at": close_raw,
        "exercised_at": None,
        "status": "PENDING",
        "_open_dt": open_dt,
        "_close_dt": close_dt,
    })
    db.tender_options[tender["id"]] = tender
    return success_object(view(tender), 201)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/tender_options")
def list_tender_options(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Team", "Player"])
    _chain_contract(agencyId, clientId, contractId)
    from flask import request
    items = [t for t in db.tender_options.values() if t["contract_id"] == contractId]
    st = request.args.get("status")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    kd = request.args.get("kind")
    if kd is not None:
        items = [t for t in items if t["kind"] == kd]
    return list_response(items)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/tender_options/<tenderId>")
def get_tender_option(agencyId, clientId, contractId, tenderId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Team", "Player"])
    _chain_contract(agencyId, clientId, contractId)
    tender = resolve_tender_option(contractId, tenderId)
    return success_object(view(tender))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/tender_options/<tenderId>/exercise")
def exercise_tender_option(agencyId, clientId, contractId, tenderId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    agency, client, contract = _chain_contract(agencyId, clientId, contractId)
    tender = resolve_tender_option(contractId, tenderId)
    # State (priority 4)
    if tender["status"] != "PENDING":
        raise err_invalid_state("TenderOption must be PENDING to exercise")
    if contract["signing_status"] != "SIGNED":
        raise err_invalid_state("Contract must be SIGNED to exercise an option")
    # Certification (5) then ownership (6)
    acting_certified_agent(user_id)
    if user_id != client["primary_agent_id"]:
        raise err_ownership_violation("Exerciser must be the client's primary agent")
    # Temporal window (7): [window_open_at, window_close_at)
    now = db.get_clock()
    if now < tender["_open_dt"] or now >= tender["_close_dt"]:
        raise err_window_closed("Outside the exercise window")
    tender["status"] = "EXERCISED"
    tender["exercised_at"] = now_stamp()
    bump(tender)
    return success_object(view(tender))


# ---------------------------------------------------------------------------
# Grievance
# ---------------------------------------------------------------------------

def _chain_grievance(agencyId, clientId, contractId, grievanceId):
    agency, client, contract = _chain_contract(agencyId, clientId, contractId)
    grievance = resolve_grievance(contractId, grievanceId)
    return agency, client, contract, grievance


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances")
def create_grievance(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    _chain_contract(agencyId, clientId, contractId)
    body = get_json_body()
    reject_unknown_fields(body, {"filed_by_agent_id", "category", "description",
                                 "claimed_amount_cents"})
    filed_by_agent_id = req_string(body, "filed_by_agent_id")
    category = req_enum(body, "category", GRIEVANCE_CATEGORIES)
    description = req_string(body, "description")
    claimed_amount_cents = req_int(body, "claimed_amount_cents")
    resolve_agent(agencyId, filed_by_agent_id)
    grievance = new_entity()
    grievance.update({
        "contract_id": contractId,
        "filed_by_agent_id": filed_by_agent_id,
        "category": category,
        "description": description,
        "claimed_amount_cents": claimed_amount_cents,
        "status": "FILED",
    })
    db.grievances[grievance["id"]] = grievance
    return success_object(view(grievance), 201)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances")
def list_grievances(agencyId, clientId, contractId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    _chain_contract(agencyId, clientId, contractId)
    from flask import request
    items = [gr for gr in db.grievances.values() if gr["contract_id"] == contractId]
    st = request.args.get("status")
    if st is not None:
        items = [gr for gr in items if gr["status"] == st]
    cat = request.args.get("category")
    if cat is not None:
        items = [gr for gr in items if gr["category"] == cat]
    return list_response(items)


@app.get("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances/<grievanceId>")
def get_grievance(agencyId, clientId, contractId, grievanceId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent", "Player"])
    _chain_grievance(agencyId, clientId, contractId, grievanceId)
    return success_object(view(db.grievances[grievanceId]))


def _grievance_transition(agencyId, clientId, contractId, grievanceId,
                          from_state, to_state):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    _chain_grievance(agencyId, clientId, contractId, grievanceId)
    grievance = db.grievances[grievanceId]
    if grievance["status"] != from_state:
        raise err_invalid_state(f"Grievance must be {from_state}")
    grievance["status"] = to_state
    bump(grievance)
    return grievance


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances/<grievanceId>/start_review")
def start_review_grievance(agencyId, clientId, contractId, grievanceId):
    grievance = _grievance_transition(
        agencyId, clientId, contractId, grievanceId, "FILED", "UNDER_REVIEW")
    return success_object(view(grievance))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances/<grievanceId>/return_for_cure")
def return_for_cure_grievance(agencyId, clientId, contractId, grievanceId):
    grievance = _grievance_transition(
        agencyId, clientId, contractId, grievanceId, "UNDER_REVIEW", "FILED")
    return success_object(view(grievance))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances/<grievanceId>/escalate")
def escalate_grievance(agencyId, clientId, contractId, grievanceId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    agency, client, contract, grievance = _chain_grievance(
        agencyId, clientId, contractId, grievanceId)
    if grievance["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Grievance must be UNDER_REVIEW to escalate")
    if contract["signing_status"] != "SIGNED":
        raise err_invalid_state("Contract must be SIGNED to escalate to arbitration")
    grievance["status"] = "ARBITRATION"
    bump(grievance)
    return success_object(view(grievance))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances/<grievanceId>/resolve")
def resolve_grievance_route(agencyId, clientId, contractId, grievanceId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    agency, client, contract, grievance = _chain_grievance(
        agencyId, clientId, contractId, grievanceId)
    body = get_json_body()
    reject_unknown_fields(body, {"resolution_outcome"})
    resolution_outcome = req_string(body, "resolution_outcome")
    if grievance["status"] != "ARBITRATION":
        raise err_invalid_state("Grievance must be in ARBITRATION to resolve")
    grievance["status"] = "RESOLVED"
    bump(grievance)
    if resolution_outcome == "UPHELD":
        amount = svc.round_cents(
            svc.D(grievance["claimed_amount_cents"]) * svc.D(agency["fee_cap_pct"])
        )
        svc.emit_fee_entry(
            agencyId, contractId, None, grievance["filed_by_agent_id"],
            1.0, amount, "TRANSITION_ADJUSTMENT",
        )
    return success_object(view(grievance))


@app.post("/agencies/<agencyId>/clients/<clientId>/contracts/<contractId>/grievances/<grievanceId>/withdraw")
def withdraw_grievance(agencyId, clientId, contractId, grievanceId):
    user_id, role = authenticate()
    require_role(role, ["Agent"])
    agency, client, contract, grievance = _chain_grievance(
        agencyId, clientId, contractId, grievanceId)
    if grievance["status"] not in ("FILED", "UNDER_REVIEW"):
        raise err_invalid_state("Grievance must be FILED or UNDER_REVIEW to withdraw")
    if user_id != grievance["filed_by_agent_id"]:
        raise err_ownership_violation("Only the filing agent may withdraw the grievance")
    grievance["status"] = "WITHDRAWN"
    bump(grievance)
    return success_object(view(grievance))


# ---------------------------------------------------------------------------
# FeeLedgerEntry (agency-scoped)
# ---------------------------------------------------------------------------

def _filter_entries(items):
    from flask import request
    for field in ("agent_id", "contract_id", "endorsement_deal_id", "kind", "status"):
        raw = request.args.get(field)
        if raw is not None:
            items = [e for e in items if str(e.get(field)) == raw]
    return items


@app.get("/agencies/<agencyId>/fee_ledger_entries")
def list_fee_ledger_entries(agencyId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent"])
    resolve_agency(agencyId)
    items = [e for e in db.fee_ledger_entries.values() if e["agency_id"] == agencyId]
    return list_response(_filter_entries(items))


@app.get("/agencies/<agencyId>/fee_ledger_entries/<entryId>")
def get_fee_ledger_entry(agencyId, entryId):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer", "AgencyManager", "Agent"])
    resolve_agency(agencyId)
    entry = resolve_fee_entry(agencyId, entryId)
    return success_object(view(entry))


@app.post("/agencies/<agencyId>/fee_ledger_entries/<entryId>/mark_paid")
def mark_fee_entry_paid(agencyId, entryId):
    user_id, role = authenticate()
    require_role(role, ["AgencyManager"])
    resolve_agency(agencyId)
    entry = resolve_fee_entry(agencyId, entryId)
    if entry["status"] != "ACCRUED":
        raise err_invalid_state("FeeLedgerEntry must be ACCRUED to mark paid")
    entry["status"] = "PAID"
    bump(entry)
    return success_object(view(entry))


# ---------------------------------------------------------------------------
# Flat reverse-reachability reads (LeagueOfficer only)
# ---------------------------------------------------------------------------

def _flat_list(store, filters, view_fn=view):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    from flask import request
    items = list(store.values())
    for field in filters:
        raw = request.args.get(field)
        if raw is not None:
            if field == "season_year":
                try:
                    items = [e for e in items if e.get(field) == int(raw)]
                except ValueError:
                    items = []
            else:
                items = [e for e in items if str(e.get(field)) == raw]
    return list_response(items, view_fn)


def _flat_get(store, rid, view_fn=view):
    user_id, role = authenticate()
    require_role(role, ["LeagueOfficer"])
    ent = store.get(rid)
    if ent is None:
        raise err_not_found()
    return success_object(view_fn(ent))


@app.get("/agents")
def flat_list_agents():
    return _flat_list(db.agents, ["agency_id", "cert_status"])


@app.get("/agents/<agentId>")
def flat_get_agent(agentId):
    return _flat_get(db.agents, agentId)


@app.get("/clients")
def flat_list_clients():
    return _flat_list(db.clients, ["agency_id", "primary_agent_id",
                                   "transition_to_agent_id", "status"])


@app.get("/clients/<clientId>")
def flat_get_client(clientId):
    return _flat_get(db.clients, clientId)


@app.get("/cap_seasons")
def flat_list_cap_seasons():
    return _flat_list(db.cap_seasons, ["team_id", "status", "season_year"], cap_season_view)


@app.get("/cap_seasons/<capSeasonId>")
def flat_get_cap_season(capSeasonId):
    return _flat_get(db.cap_seasons, capSeasonId, cap_season_view)


@app.get("/contracts")
def flat_list_contracts():
    return _flat_list(db.contracts, ["client_id", "team_id", "cap_season_id",
                                     "signing_status"])


@app.get("/contracts/<contractId>")
def flat_get_contract(contractId):
    return _flat_get(db.contracts, contractId)


@app.get("/proposals")
def flat_list_proposals():
    return _flat_list(db.proposals, ["contract_id", "proposed_by_agent_id", "status"])


@app.get("/proposals/<proposalId>")
def flat_get_proposal(proposalId):
    return _flat_get(db.proposals, proposalId)


@app.get("/endorsements")
def flat_list_endorsements():
    return _flat_list(db.endorsements, ["client_id", "status"])


@app.get("/endorsements/<dealId>")
def flat_get_endorsement(dealId):
    return _flat_get(db.endorsements, dealId)


@app.get("/tender_options")
def flat_list_tender_options():
    return _flat_list(db.tender_options, ["contract_id", "status", "kind"])


@app.get("/tender_options/<tenderId>")
def flat_get_tender_option(tenderId):
    return _flat_get(db.tender_options, tenderId)


@app.get("/grievances")
def flat_list_grievances():
    return _flat_list(db.grievances, ["contract_id", "filed_by_agent_id",
                                      "status", "category"])


@app.get("/grievances/<grievanceId>")
def flat_get_grievance(grievanceId):
    return _flat_get(db.grievances, grievanceId)


@app.get("/fee_ledger_entries")
def flat_list_fee_ledger_entries():
    return _flat_list(db.fee_ledger_entries, ["agency_id", "agent_id", "contract_id",
                                              "endorsement_deal_id", "kind", "status"])


@app.get("/fee_ledger_entries/<entryId>")
def flat_get_fee_ledger_entry(entryId):
    return _flat_get(db.fee_ledger_entries, entryId)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
