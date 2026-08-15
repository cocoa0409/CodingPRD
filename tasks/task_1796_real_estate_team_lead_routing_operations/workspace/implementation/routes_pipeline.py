"""Routes: leads and assignments."""
from datetime import timedelta

from flask import Blueprint

import store
import services as svc
import views
from util import (
    ApiError, ok_object, ok_list, parse_dt, parse_pagination, paginate,
    auth_context, require_role, get_body, check_allowed, req_field, opt_field,
    as_str, as_int, as_enum, err_invalid_request, err_not_found, new_id, month_key,
)
from routes_core import resolve_leader, request_arg, _sorted, ANY_ROLE

bp = Blueprint("pipeline", __name__)

LEAD_STATUSES = ("NEW", "OFFERED", "CLAIMED", "WORKING", "UNDER_CONTRACT",
                 "CLOSED_WON", "CLOSED_LOST")


def _get_lead_or_404(leadId):
    lead = store.leads.get(leadId)
    if lead is None:
        raise err_not_found("lead not found")
    return lead


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

@bp.post("/crm/leads")
def create_lead():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin", "TeamLeader", "ReferralPartner"))
    body = get_body()
    check_allowed(body, {"team_id", "source_id", "contact_name", "contact_phone",
                         "contact_email", "expected_close_price_cents", "referral_partner_id"})
    team_id = as_str(req_field(body, "team_id"), "team_id")
    source_id = as_str(req_field(body, "source_id"), "source_id")
    contact_name = as_str(req_field(body, "contact_name"), "contact_name")
    contact_phone = as_str(req_field(body, "contact_phone"), "contact_phone")
    contact_email = as_str(req_field(body, "contact_email"), "contact_email")
    price = as_int(req_field(body, "expected_close_price_cents"), "expected_close_price_cents")
    if price <= 0:
        raise err_invalid_request("expected_close_price_cents must be > 0")
    partner_id = opt_field(body, "referral_partner_id", None)
    if partner_id is not None:
        as_str(partner_id, "referral_partner_id")

    # priority 4: existence, left-to-right
    team = store.teams.get(team_id)
    if team is None:
        raise err_not_found("team not found")
    src = store.sources.get(source_id)
    if src is None:
        raise err_not_found("lead source not found")
    if partner_id is not None and store.partners.get(partner_id) is None:
        raise err_not_found("referral partner not found")

    # priority 5: entity-backed identity
    if role == "ReferralPartner":
        if partner_id != uid:
            raise ApiError("ERR_PARTNER_IDENTITY_MISMATCH", 403,
                           "ReferralPartner caller id must equal referral_partner_id")
    elif role == "TeamLeader":
        resolve_leader(uid, team_id)

    # priority 6: source state
    if src["status"] != "ACTIVE":
        raise ApiError("ERR_SOURCE_NOT_ACTIVE", 409, "Lead intake from a PAUSED source")

    # priority 8: referral partner presence
    if src["type"] == "REFERRAL_PARTNER" and partner_id is None:
        raise ApiError("ERR_REFERRAL_PARTNER_REQUIRED", 422,
                       "referral_partner_id is required for REFERRAL_PARTNER sources")
    if src["type"] != "REFERRAL_PARTNER" and partner_id is not None:
        raise ApiError("ERR_REFERRAL_PARTNER_REQUIRED", 422,
                       "referral_partner_id is forbidden for non-referral source types")

    # priority 9: duplicate open phone within the team
    for l in store.leads.values():
        if l["team_id"] == team_id and l["contact_phone"] == contact_phone \
                and l["status"] not in ("CLOSED_WON", "CLOSED_LOST"):
            raise ApiError("ERR_DUPLICATE_OPEN_LEAD", 409,
                           "contact_phone already used by a non-terminal lead on this team")

    # priority 10: monthly budget (equality allowed)
    mk = month_key(store.now(), team["timezone"])
    month_count = sum(1 for l in store.leads.values()
                      if l["source_id"] == src["id"]
                      and month_key(l["created_at"], team["timezone"]) == mk)
    spent = month_count * src["cost_per_lead_cents"]
    if spent + src["cost_per_lead_cents"] > src["monthly_budget_cents"]:
        raise ApiError("ERR_SOURCE_BUDGET_EXHAUSTED", 409,
                       "Intake would exceed the source monthly budget")

    now = store.now()
    lead = {"id": new_id(), "team_id": team_id, "source_id": source_id,
            "assigned_agent_id": None, "referral_partner_id": partner_id,
            "contact_name": contact_name, "contact_phone": contact_phone,
            "contact_email": contact_email, "expected_close_price_cents": price,
            "status": "NEW", "temperature": "COLD",
            "first_response_at": None, "within_speed_sla": None,
            "speed_deadline_at": None, "claim_deadline_at": None,
            "current_assignment_id": None, "close_reason": None,
            "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.leads[lead["id"]] = lead

    if src["auto_route"]:
        svc.route_lead(lead)  # silent on no-policy / empty pool — lead stays NEW

    return ok_object(views.lead_view(lead), status=201)


@bp.get("/crm/leads/<leadId>")
def get_lead(leadId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    lead = _get_lead_or_404(leadId)
    svc.refresh_lead_temperature(lead)
    return ok_object(views.lead_view(lead))


@bp.get("/crm/leads")
def list_leads():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.leads.values())
    for fname, field in (("team_id", "team_id"), ("source_id", "source_id"),
                         ("assigned_agent_id", "assigned_agent_id"),
                         ("referral_partner_id", "referral_partner_id"),
                         ("status", "status"), ("temperature", "temperature")):
        fv = request_arg(fname)
        if fv is not None:
            items = [l for l in items if l[field] == fv]
    page, total = paginate(items, limit, offset)
    return ok_list([views.lead_view(l) for l in page], limit, offset, total)


@bp.post("/crm/leads/<leadId>/route")
def route_lead_manual(leadId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin", "TeamLeader"))
    body = get_body()
    check_allowed(body, set())
    lead = _get_lead_or_404(leadId)
    if role == "TeamLeader":
        resolve_leader(uid, lead["team_id"])
    if lead["status"] != "NEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a NEW lead can be routed")
    asg, err = svc.route_lead(lead)
    if err == "no_policy":
        raise ApiError("ERR_NO_ACTIVE_POLICY", 409, "The team has no ACTIVE routing policy")
    if err == "empty_pool":
        raise ApiError("ERR_NO_ELIGIBLE_AGENT", 409, "No eligible agent for routing")
    return ok_object(views.assignment_view(asg), status=201)


@bp.post("/crm/leads/<leadId>/claim")
def claim_lead(leadId):
    uid, role = auth_context()
    require_role(role, ("Agent",))
    body = get_body()
    check_allowed(body, set())
    lead = _get_lead_or_404(leadId)

    # priority 5: identity — NOT_OFFERED when caller is an ACTIVE agent but not
    # the offered one; IDENTITY_MISMATCH when the caller is not an ACTIVE agent.
    cur = store.assignments.get(lead["current_assignment_id"] or "")
    caller_agent = store.agents.get(uid)
    if cur is not None and cur["status"] == "OFFERED":
        if caller_agent is None or caller_agent["status"] != "ACTIVE":
            raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                           "Caller does not resolve to an ACTIVE agent")
        if cur["agent_id"] != uid:
            raise ApiError("ERR_NOT_OFFERED_TO_AGENT", 403,
                           "Lead is not currently offered to this agent")

    if lead["status"] != "OFFERED" or cur is None or cur["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an OFFERED lead can be claimed")

    now = store.now()
    cur["status"] = "CLAIMED"
    cur["_claimed_at"] = now
    store.touch(cur)
    lead["status"] = "CLAIMED"
    lead["claim_deadline_at"] = None
    store.touch(lead)
    agent = store.agents.get(cur["agent_id"])
    if agent is not None:
        agent["consecutive_missed_claims"] = 0
        store.touch(agent)
    return ok_object(views.lead_view(lead))


@bp.post("/crm/leads/<leadId>/release")
def release_lead(leadId):
    uid, role = auth_context()
    require_role(role, ("Agent", "TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, {"reason"})
    if "reason" in body and body["reason"] is not None:
        as_str(body["reason"], "reason")
    lead = _get_lead_or_404(leadId)
    if role == "Agent":
        if lead["assigned_agent_id"] is not None and lead["assigned_agent_id"] != uid:
            raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                           "Agent callers may only release their own leads")
    elif role == "TeamLeader":
        resolve_leader(uid, lead["team_id"])
    if lead["status"] not in ("CLAIMED", "WORKING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CLAIMED or WORKING lead can be released")

    cur = store.assignments.get(lead["current_assignment_id"] or "")
    if cur is not None and cur["status"] in ("OFFERED", "CLAIMED"):
        cur["status"] = "RELEASED"
        cur["outcome_reason"] = "RELEASED"
        store.touch(cur)
    lead["status"] = "NEW"
    lead["assigned_agent_id"] = None
    lead["current_assignment_id"] = None
    lead["claim_deadline_at"] = None
    store.touch(lead)
    return ok_object(views.lead_view(lead))


@bp.post("/crm/leads/<leadId>/log-response")
def log_response(leadId):
    uid, role = auth_context()
    require_role(role, ("Agent",))
    body = get_body()
    check_allowed(body, set())
    lead = _get_lead_or_404(leadId)
    if lead["assigned_agent_id"] is not None and lead["assigned_agent_id"] != uid:
        raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                       "Only the assigned agent may log the first response")
    if lead["assigned_agent_id"] is None:
        raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                       "Only the assigned agent may log the first response")
    if lead["status"] != "CLAIMED" or lead["first_response_at"] is not None:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "First response requires a CLAIMED lead with no prior response")

    now = store.now()
    lead["first_response_at"] = now
    lead["within_speed_sla"] = (lead["speed_deadline_at"] is not None
                                and now <= lead["speed_deadline_at"])
    lead["status"] = "WORKING"
    store.touch(lead)
    cur = store.assignments.get(lead["current_assignment_id"] or "")
    if cur is not None:
        cur["responded_at"] = now
        store.touch(cur)
    return ok_object(views.lead_view(lead))


@bp.post("/crm/leads/<leadId>/engagement-events")
def create_event(leadId):
    uid, role = auth_context()
    require_role(role, ("Agent", "TeamAdmin"))
    body = get_body()
    check_allowed(body, {"type", "occurred_at"})
    etype = as_enum(req_field(body, "type"), "type", tuple(svc.EVENT_POINTS.keys()))
    occurred_at = parse_dt(req_field(body, "occurred_at"), "occurred_at")
    lead = _get_lead_or_404(leadId)
    if role == "Agent" and lead["assigned_agent_id"] != uid:
        raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                       "Agent callers may only log events on their own leads")

    now = store.now()
    ev = {"id": new_id(), "lead_id": lead["id"], "type": etype,
          "occurred_at": occurred_at, "points": svc.EVENT_POINTS[etype],
          "created_at": now, "_seq": store.next_seq()}
    store.events[ev["id"]] = ev
    svc.refresh_lead_temperature(lead)
    store.touch(lead)
    return ok_object(views.event_view(ev), status=201)


@bp.get("/crm/leads/<leadId>/engagement-events")
def list_events(leadId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    lead = _get_lead_or_404(leadId)
    limit, offset = parse_pagination()
    items = _sorted([e for e in store.events.values() if e["lead_id"] == lead["id"]])
    page, total = paginate(items, limit, offset)
    return ok_list([views.event_view(e) for e in page], limit, offset, total)


@bp.post("/crm/leads/<leadId>/close-lost")
def close_lost(leadId):
    uid, role = auth_context()
    require_role(role, ("Agent", "TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, {"reason"})
    reason = as_str(req_field(body, "reason"), "reason")
    lead = _get_lead_or_404(leadId)
    if role == "Agent":
        if lead["assigned_agent_id"] is not None and lead["assigned_agent_id"] != uid:
            raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                           "Agent callers may only close their own leads")
    elif role == "TeamLeader":
        resolve_leader(uid, lead["team_id"])
    if lead["status"] not in ("CLAIMED", "WORKING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CLAIMED or WORKING lead can be closed lost")

    # The CLAIMED assignment is retained as the historical record.
    lead["status"] = "CLOSED_LOST"
    lead["close_reason"] = reason
    lead["assigned_agent_id"] = None
    lead["current_assignment_id"] = None
    lead["claim_deadline_at"] = None
    store.touch(lead)
    return ok_object(views.lead_view(lead))


@bp.post("/crm/leads/<leadId>/recycle")
def recycle_lead(leadId):
    uid, role = auth_context()
    require_role(role, ("TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, set())
    lead = _get_lead_or_404(leadId)
    if role == "TeamLeader":
        resolve_leader(uid, lead["team_id"])
    if lead["status"] != "CLOSED_LOST":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a CLOSED_LOST lead can be recycled")
    lead["status"] = "NEW"
    store.touch(lead)
    return ok_object(views.lead_view(lead))


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

@bp.get("/crm/assignments/<assignmentId>")
def get_assignment(assignmentId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    asg = store.assignments.get(assignmentId)
    if asg is None:
        raise err_not_found("assignment not found")
    return ok_object(views.assignment_view(asg))


@bp.get("/crm/assignments")
def list_assignments():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.assignments.values())
    for fname in ("lead_id", "agent_id", "policy_id", "supersedes_assignment_id", "status"):
        fv = request_arg(fname)
        if fv is not None:
            items = [a for a in items if a[fname] == fv]
    page, total = paginate(items, limit, offset)
    return ok_list([views.assignment_view(a) for a in page], limit, offset, total)


@bp.post("/crm/assignments/<assignmentId>/reassign")
def reassign_assignment(assignmentId):
    uid, role = auth_context()
    require_role(role, ("TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, {"agent_id"})
    target_id = opt_field(body, "agent_id", None)
    if target_id is not None:
        as_str(target_id, "agent_id")
    asg = store.assignments.get(assignmentId)
    if asg is None:
        raise err_not_found("assignment not found")
    lead = store.leads.get(asg["lead_id"])
    if lead is None:
        raise err_not_found("lead not found")
    if target_id is not None and store.agents.get(target_id) is None:
        raise err_not_found("agent not found")
    if role == "TeamLeader":
        resolve_leader(uid, lead["team_id"])
    if asg["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OFFERED assignment can be reassigned")

    team = store.teams.get(lead["team_id"])
    policy = svc.active_policy(lead["team_id"])
    if policy is None:
        raise ApiError("ERR_NO_ACTIVE_POLICY", 409, "The team has no ACTIVE routing policy")

    now = store.now()
    if target_id is not None:
        # Explicit leader override: capacity may be exceeded, but the target must
        # be ACTIVE and not on time off.
        target = store.agents[target_id]
        if target["status"] != "ACTIVE" or svc._on_time_off(target_id, now):
            raise ApiError("ERR_NO_ELIGIBLE_AGENT", 409,
                           "Explicit reassign target must be ACTIVE and not on time off")
        explicit = target
    else:
        # Selector path: choose first so an empty pool fails atomically before
        # the current assignment is touched.
        explicit, _mode = svc.select_agent(lead, team, policy, {asg["agent_id"]})
        if explicit is None:
            raise ApiError("ERR_NO_ELIGIBLE_AGENT", 409,
                           "No eligible agent for reassignment")

    asg["status"] = "REASSIGNED"
    asg["outcome_reason"] = "MANUAL"
    store.touch(asg)

    new_asg, err = svc.route_lead(lead, excluded_ids={asg["agent_id"]},
                                  supersedes=asg["id"], explicit_agent=explicit)
    if err is not None or new_asg is None:
        raise ApiError("ERR_NO_ELIGIBLE_AGENT", 409, "No eligible agent for reassignment")
    return ok_object(views.assignment_view(new_asg), status=201)
