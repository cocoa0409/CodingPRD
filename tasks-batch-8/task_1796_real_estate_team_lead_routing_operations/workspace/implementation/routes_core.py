"""Routes: clock, teams, agents, routing policies, lead sources."""
from datetime import timedelta

from flask import Blueprint

import store
import services as svc
import views
from util import (
    ApiError, ok_object, ok_list, parse_dt, parse_pagination, paginate,
    auth_context, require_role, get_body, check_allowed, req_field, opt_field,
    as_str, as_int, as_bool, as_enum, err_invalid_request, err_not_found, new_id, iso,
    month_key,
)

bp = Blueprint("core", __name__)

ANY_ROLE = ("TeamAdmin", "TeamLeader", "Agent", "ReferralPartner")
AGENT_ROLES = ("MEMBER", "LEADER")
POLICY_MODES = ("ROUND_ROBIN", "PERFORMANCE_WEIGHTED")
SOURCE_TYPES = ("PORTAL", "IDX_WEBSITE", "PAID_AD", "REFERRAL_PARTNER", "SPHERE", "SIGN_CALL")
TIERS = ("BRONZE", "SILVER", "GOLD", "PLATINUM")


def resolve_leader(uid, team_id):
    """Priority 5: TeamLeader callers resolve to a LEADER agent on the team."""
    agent = store.agents.get(uid)
    if agent is None or agent["team_id"] != team_id or agent["role_on_team"] != "LEADER":
        raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                       "TeamLeader caller does not resolve to a LEADER agent on the team")
    return agent


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"to_iso8601"})
    to = parse_dt(req_field(body, "to_iso8601"), "to_iso8601")
    store.clock["now"] = to
    ctx = svc.run_sweep()
    return ok_object({
        "now_utc": iso(store.now()),
        "expired_assignment_count": ctx["expired_assignment_count"],
        "auto_paused_agent_count": ctx["auto_paused_agent_count"],
        "expired_agreement_count": ctx["expired_agreement_count"],
        "advanced_enrollment_count": ctx["advanced_enrollment_count"],
    })


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

@bp.post("/crm/teams")
def create_team():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"name", "market", "timezone", "speed_to_lead_window_seconds",
                         "claim_window_seconds"})
    name = as_str(req_field(body, "name"), "name")
    market = as_str(req_field(body, "market"), "market")
    tz = as_str(req_field(body, "timezone"), "timezone")
    speed = opt_field(body, "speed_to_lead_window_seconds", 900)
    claim = opt_field(body, "claim_window_seconds", 7200)
    speed = as_int(speed, "speed_to_lead_window_seconds")
    claim = as_int(claim, "claim_window_seconds")
    now = store.now()
    team = {"id": new_id(), "name": name, "market": market, "timezone": tz,
            "speed_to_lead_window_seconds": speed, "claim_window_seconds": claim,
            "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.teams[team["id"]] = team
    return ok_object(views.team_view(team), status=201)


@bp.get("/crm/teams/<teamId>")
def get_team(teamId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    team = store.teams.get(teamId)
    if team is None:
        raise err_not_found("team not found")
    return ok_object(views.team_view(team))


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@bp.post("/crm/agents")
def create_agent():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"team_id", "display_name", "license_number", "role_on_team",
                         "max_active_leads"})
    team_id = as_str(req_field(body, "team_id"), "team_id")
    display_name = as_str(req_field(body, "display_name"), "display_name")
    license_number = as_str(req_field(body, "license_number"), "license_number")
    role_on_team = as_enum(opt_field(body, "role_on_team", "MEMBER"), "role_on_team", AGENT_ROLES)
    max_active = as_int(req_field(body, "max_active_leads"), "max_active_leads")
    if max_active < 1:
        raise err_invalid_request("max_active_leads must be >= 1")
    team = store.teams.get(team_id)
    if team is None:
        raise err_not_found("team not found")
    for a in store.agents.values():
        if a["team_id"] == team_id and a["license_number"] == license_number:
            raise ApiError("ERR_DUPLICATE_LICENSE_NUMBER", 409,
                           "license_number already used by another agent on the same team")
    now = store.now()
    agent = {"id": new_id(), "team_id": team_id, "display_name": display_name,
             "license_number": license_number, "role_on_team": role_on_team,
             "max_active_leads": max_active, "status": "ONBOARDING",
             "consecutive_missed_claims": 0, "last_assigned_at": None, "onboarded_at": None,
             "stat_adj": {"conversions": 0, "claimed": 0, "offered": 0},
             "imported_avg_response": None,
             "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.agents[agent["id"]] = agent
    return ok_object(views.agent_view(agent), status=201)


@bp.get("/crm/agents/<agentId>")
def get_agent(agentId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    agent = store.agents.get(agentId)
    if agent is None:
        raise err_not_found("agent not found")
    return ok_object(views.agent_view(agent))


@bp.get("/crm/agents")
def list_agents():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.agents.values())
    team_id = request_arg("team_id")
    status = request_arg("status")
    rot = request_arg("role_on_team")
    if team_id is not None:
        items = [a for a in items if a["team_id"] == team_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if rot is not None:
        items = [a for a in items if a["role_on_team"] == rot]
    page, total = paginate(items, limit, offset)
    return ok_list([views.agent_view(a) for a in page], limit, offset, total)


def request_arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None


def _get_agent_or_404(agentId):
    agent = store.agents.get(agentId)
    if agent is None:
        raise err_not_found("agent not found")
    return agent


@bp.post("/crm/agents/<agentId>/activate")
def activate_agent(agentId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, set())
    agent = _get_agent_or_404(agentId)
    if agent["status"] != "ONBOARDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ONBOARDING agent can be activated")
    agent["status"] = "ACTIVE"
    agent["onboarded_at"] = store.now()
    store.touch(agent)
    return ok_object(views.agent_view(agent))


@bp.post("/crm/agents/<agentId>/pause")
def pause_agent(agentId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin", "TeamLeader"))
    body = get_body()
    check_allowed(body, set())
    agent = _get_agent_or_404(agentId)
    if role == "TeamLeader":
        resolve_leader(uid, agent["team_id"])
    if agent["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE agent can be paused")
    svc.pause_agent_cascade(agent)
    return ok_object(views.agent_view(agent))


@bp.post("/crm/agents/<agentId>/resume")
def resume_agent(agentId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin", "TeamLeader"))
    body = get_body()
    check_allowed(body, set())
    agent = _get_agent_or_404(agentId)
    if role == "TeamLeader":
        resolve_leader(uid, agent["team_id"])
    if agent["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PAUSED agent can be resumed")
    agent["status"] = "ACTIVE"
    agent["consecutive_missed_claims"] = 0
    store.touch(agent)
    return ok_object(views.agent_view(agent))


@bp.post("/crm/agents/<agentId>/offboard")
def offboard_agent(agentId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, set())
    agent = _get_agent_or_404(agentId)
    if agent["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE or PAUSED agent can be offboarded")
    svc.offboard_agent_cascade(agent)
    return ok_object(views.agent_view(agent))


@bp.get("/crm/agents/<agentId>/scorecard")
def agent_scorecard(agentId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    agent = _get_agent_or_404(agentId)
    team = store.teams.get(agent["team_id"])
    policy = svc.active_policy(agent["team_id"])
    window = svc.effective_speed_window(team, policy) if team else 900

    claimed = svc.agent_claimed(agent)
    offered = svc.agent_offered(agent)
    conversions = svc.agent_conversions(agent)
    avg = svc.agent_avg_response(agent)

    claim_rate_bps = (claimed * 10000) // max(1, offered)
    if avg is None:
        speed_score_bps = 0
    elif avg <= window:
        speed_score_bps = 10000
    else:
        speed_score_bps = (10000 * window) // avg
    conversion_rate_bps = (conversions * 10000) // max(1, claimed)
    accountability = svc_round_score(5 * claim_rate_bps + 3 * speed_score_bps
                                     + 2 * conversion_rate_bps)
    return ok_object({
        "agent_id": agent["id"],
        "performance_tier": svc.agent_tier(agent),
        "active_lead_count": svc.derived_active_lead_count(agent["id"]),
        "trailing_90d_conversions": conversions,
        "trailing_90d_claimed": claimed,
        "trailing_90d_offered": offered,
        "avg_first_response_seconds": avg,
        "claim_rate_bps": claim_rate_bps,
        "speed_score_bps": speed_score_bps,
        "conversion_rate_bps": conversion_rate_bps,
        "accountability_score_bps": accountability,
    })


def svc_round_score(weighted_sum):
    from util import rhu
    return rhu(weighted_sum, 10)


@bp.post("/crm/agents/<agentId>/import-production-stats")
def import_stats(agentId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    allowed = {"trailing_90d_conversions", "trailing_90d_claimed", "trailing_90d_offered",
               "avg_first_response_seconds", "consecutive_missed_claims"}
    check_allowed(body, allowed)
    vals = {}
    for f in ("trailing_90d_conversions", "trailing_90d_claimed", "trailing_90d_offered",
              "consecutive_missed_claims"):
        if f in body:
            v = as_int(body[f], f)
            if v < 0:
                raise err_invalid_request(f"{f} must be >= 0")
            vals[f] = v
    if "avg_first_response_seconds" in body:
        v = body["avg_first_response_seconds"]
        if v is not None:
            v = as_int(v, "avg_first_response_seconds")
            if v < 0:
                raise err_invalid_request("avg_first_response_seconds must be >= 0")
        vals["avg_first_response_seconds"] = v
    agent = _get_agent_or_404(agentId)
    if "trailing_90d_conversions" in vals:
        agent["stat_adj"]["conversions"] = vals["trailing_90d_conversions"] - svc.derived_conversions(agent["id"])
    if "trailing_90d_claimed" in vals:
        agent["stat_adj"]["claimed"] = vals["trailing_90d_claimed"] - svc.derived_claimed(agent["id"])
    if "trailing_90d_offered" in vals:
        agent["stat_adj"]["offered"] = vals["trailing_90d_offered"] - svc.derived_offered(agent["id"])
    if "avg_first_response_seconds" in vals:
        agent["imported_avg_response"] = vals["avg_first_response_seconds"]
    if "consecutive_missed_claims" in vals:
        agent["consecutive_missed_claims"] = vals["consecutive_missed_claims"]
    store.touch(agent)
    return ok_object(views.agent_view(agent))


@bp.post("/crm/agents/<agentId>/time-offs")
def create_timeoff(agentId):
    uid, role = auth_context()
    require_role(role, ("Agent", "TeamAdmin"))
    body = get_body()
    check_allowed(body, {"starts_at", "ends_at", "reason"})
    starts_at = parse_dt(req_field(body, "starts_at"), "starts_at")
    ends_at = parse_dt(req_field(body, "ends_at"), "ends_at")
    reason = as_str(req_field(body, "reason"), "reason")
    if not ends_at > starts_at:
        raise err_invalid_request("ends_at must be strictly after starts_at")
    agent = _get_agent_or_404(agentId)
    if role == "Agent" and uid != agent["id"]:
        raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                       "Agent callers may only manage their own time off")
    for t in store.timeoffs.values():
        if t["agent_id"] != agent["id"]:
            continue
        if starts_at <= t["ends_at"] and ends_at >= t["starts_at"]:
            raise ApiError("ERR_TIME_OFF_OVERLAP", 409,
                           "Time-off block intersects an existing block (closed interval)")
    now = store.now()
    rec = {"id": new_id(), "agent_id": agent["id"], "starts_at": starts_at,
           "ends_at": ends_at, "reason": reason,
           "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.timeoffs[rec["id"]] = rec
    return ok_object(views.timeoff_view(rec), status=201)


@bp.get("/crm/agents/<agentId>/time-offs")
def list_timeoffs(agentId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    agent = _get_agent_or_404(agentId)
    limit, offset = parse_pagination()
    items = _sorted([t for t in store.timeoffs.values() if t["agent_id"] == agent["id"]])
    page, total = paginate(items, limit, offset)
    return ok_list([views.timeoff_view(t) for t in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Routing policies
# ---------------------------------------------------------------------------

@bp.post("/crm/routing-policies")
def create_policy():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"team_id", "mode", "tier_weight_bps", "source_mode_overrides",
                         "claim_window_seconds", "speed_to_lead_window_seconds"})
    team_id = as_str(req_field(body, "team_id"), "team_id")
    mode = as_enum(req_field(body, "mode"), "mode", POLICY_MODES)

    weights = dict(svc.DEFAULT_TIER_WEIGHT_BPS)
    if "tier_weight_bps" in body and body["tier_weight_bps"] is not None:
        tw = body["tier_weight_bps"]
        if not isinstance(tw, dict):
            raise err_invalid_request("tier_weight_bps must be an object")
        for k, v in tw.items():
            if k not in TIERS:
                raise err_invalid_request(f"tier_weight_bps key must be one of {sorted(TIERS)}")
            weights[k] = as_int(v, f"tier_weight_bps.{k}")

    overrides = {}
    if "source_mode_overrides" in body and body["source_mode_overrides"] is not None:
        smo = body["source_mode_overrides"]
        if not isinstance(smo, dict):
            raise err_invalid_request("source_mode_overrides must be an object")
        for k, v in smo.items():
            if k not in SOURCE_TYPES:
                raise err_invalid_request(f"source_mode_overrides key must be one of {sorted(SOURCE_TYPES)}")
            overrides[k] = as_enum(v, f"source_mode_overrides.{k}", POLICY_MODES)

    claim_win = opt_field(body, "claim_window_seconds", None)
    if claim_win is not None:
        claim_win = as_int(claim_win, "claim_window_seconds")
    speed_win = opt_field(body, "speed_to_lead_window_seconds", None)
    if speed_win is not None:
        speed_win = as_int(speed_win, "speed_to_lead_window_seconds")

    team = store.teams.get(team_id)
    if team is None:
        raise err_not_found("team not found")
    version_no = sum(1 for p in store.policies.values() if p["team_id"] == team_id) + 1
    now = store.now()
    policy = {"id": new_id(), "team_id": team_id, "version_no": version_no, "mode": mode,
              "tier_weight_bps": weights, "source_mode_overrides": overrides,
              "claim_window_seconds": claim_win, "speed_to_lead_window_seconds": speed_win,
              "status": "DRAFT", "activated_at": None,
              "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.policies[policy["id"]] = policy
    return ok_object(views.policy_view(policy), status=201)


@bp.get("/crm/routing-policies/<policyId>")
def get_policy(policyId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    policy = store.policies.get(policyId)
    if policy is None:
        raise err_not_found("routing policy not found")
    return ok_object(views.policy_view(policy))


@bp.get("/crm/routing-policies")
def list_policies():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.policies.values())
    team_id = request_arg("team_id")
    status = request_arg("status")
    if team_id is not None:
        items = [p for p in items if p["team_id"] == team_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([views.policy_view(p) for p in page], limit, offset, total)


@bp.post("/crm/routing-policies/<policyId>/activate")
def activate_policy(policyId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"expected_team_version"})
    expected = as_int(req_field(body, "expected_team_version"), "expected_team_version")
    policy = store.policies.get(policyId)
    if policy is None:
        raise err_not_found("routing policy not found")
    team = store.teams.get(policy["team_id"])
    if team is None:
        raise err_not_found("team not found")
    if policy["status"] != "DRAFT":
        raise ApiError("ERR_POLICY_NOT_ACTIVATABLE", 409,
                       "Only a DRAFT policy can be activated")
    if expected != team["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_team_version does not match the team's current version")
    for p in store.policies.values():
        if p["team_id"] == team["id"] and p["status"] == "ACTIVE":
            p["status"] = "SUPERSEDED"
            store.touch(p)
    policy["status"] = "ACTIVE"
    policy["activated_at"] = store.now()
    store.touch(policy)
    store.touch(team)
    return ok_object(views.policy_view(policy))


# ---------------------------------------------------------------------------
# Lead sources
# ---------------------------------------------------------------------------

@bp.post("/crm/lead-sources")
def create_source():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"team_id", "name", "type", "cost_per_lead_cents",
                         "monthly_budget_cents", "priority_weight", "auto_route"})
    team_id = as_str(req_field(body, "team_id"), "team_id")
    name = as_str(req_field(body, "name"), "name")
    stype = as_enum(req_field(body, "type"), "type", SOURCE_TYPES)
    cost = as_int(req_field(body, "cost_per_lead_cents"), "cost_per_lead_cents")
    if cost < 0:
        raise err_invalid_request("cost_per_lead_cents must be >= 0")
    budget = as_int(req_field(body, "monthly_budget_cents"), "monthly_budget_cents")
    if budget < 0:
        raise err_invalid_request("monthly_budget_cents must be >= 0")
    priority = as_int(opt_field(body, "priority_weight", 50), "priority_weight")
    if priority < 1 or priority > 100:
        raise err_invalid_request("priority_weight must be between 1 and 100")
    auto_route = as_bool(opt_field(body, "auto_route", True), "auto_route")
    team = store.teams.get(team_id)
    if team is None:
        raise err_not_found("team not found")
    now = store.now()
    src = {"id": new_id(), "team_id": team_id, "name": name, "type": stype,
           "cost_per_lead_cents": cost, "monthly_budget_cents": budget,
           "priority_weight": priority, "auto_route": auto_route, "status": "ACTIVE",
           "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.sources[src["id"]] = src
    return ok_object(views.source_view(src), status=201)


@bp.get("/crm/lead-sources/<sourceId>")
def get_source(sourceId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    src = store.sources.get(sourceId)
    if src is None:
        raise err_not_found("lead source not found")
    return ok_object(views.source_view(src))


@bp.get("/crm/lead-sources")
def list_sources():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.sources.values())
    team_id = request_arg("team_id")
    status = request_arg("status")
    stype = request_arg("type")
    if team_id is not None:
        items = [s for s in items if s["team_id"] == team_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if stype is not None:
        items = [s for s in items if s["type"] == stype]
    page, total = paginate(items, limit, offset)
    return ok_list([views.source_view(s) for s in page], limit, offset, total)


@bp.post("/crm/lead-sources/<sourceId>/pause")
def pause_source(sourceId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, set())
    src = store.sources.get(sourceId)
    if src is None:
        raise err_not_found("lead source not found")
    if src["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE source can be paused")
    src["status"] = "PAUSED"
    store.touch(src)
    return ok_object(views.source_view(src))


@bp.post("/crm/lead-sources/<sourceId>/resume")
def resume_source(sourceId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, set())
    src = store.sources.get(sourceId)
    if src is None:
        raise err_not_found("lead source not found")
    if src["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PAUSED source can be resumed")
    src["status"] = "ACTIVE"
    store.touch(src)
    return ok_object(views.source_view(src))


@bp.get("/crm/lead-sources/<sourceId>/roi")
def source_roi(sourceId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    src = store.sources.get(sourceId)
    if src is None:
        raise err_not_found("lead source not found")

    basis = request_arg("basis") or "REALIZED"
    if basis not in ("REALIZED", "PROJECTED"):
        raise err_invalid_request("basis must be REALIZED or PROJECTED")
    raw_window = request_arg("window_days")
    if raw_window is None:
        window_days = 90
    else:
        try:
            window_days = int(raw_window)
        except (TypeError, ValueError):
            raise err_invalid_request("window_days must be an integer")
        if window_days < 1:
            raise err_invalid_request("window_days must be >= 1")

    now = store.now()
    window_start = now - timedelta(days=window_days)
    cohort = [l for l in store.leads.values()
              if l["source_id"] == src["id"] and window_start <= l["created_at"] <= now]
    leads_count = len(cohort)
    spend = leads_count * src["cost_per_lead_cents"]
    cohort_ids = {l["id"] for l in cohort}

    realized = 0
    conversions_count = 0
    for d in store.deals.values():
        if d["lead_id"] in cohort_ids and d["status"] in ("APPROVED", "PAID_OUT"):
            realized += d["split_basis_cents"]
            conversions_count += 1

    attributed = realized
    if basis == "PROJECTED":
        for l in cohort:
            if l["status"] in svc.OPEN_PIPELINE_STATUSES:
                prob = svc.TEMP_PROBABILITY_BPS[l["temperature"]]
                attributed += svc_rhu(l["expected_close_price_cents"]
                                      * svc.EST_COMMISSION_BPS * prob, 10000 * 10000)

    if spend == 0:
        roi_bps = None
    else:
        roi_bps = ((attributed - spend) * 10000) // spend

    return ok_object({
        "source_id": src["id"],
        "window_days": window_days,
        "basis": basis,
        "leads_count": leads_count,
        "conversions_count": conversions_count,
        "spend_cents": spend,
        "attributed_commission_cents": attributed,
        "roi_bps": roi_bps,
    })


def svc_rhu(numer, denom):
    from util import rhu
    return rhu(numer, denom)
