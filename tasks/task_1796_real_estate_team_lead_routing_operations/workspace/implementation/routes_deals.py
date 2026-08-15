"""Routes: nurture campaigns/enrollments, referral partners, split agreements, deals."""
from datetime import timedelta

from flask import Blueprint

import store
import services as svc
import views
from util import (
    ApiError, ok_object, ok_list, parse_dt, parse_pagination, paginate,
    auth_context, require_role, get_body, check_allowed, req_field, opt_field,
    as_str, as_int, as_enum, err_invalid_request, err_not_found, new_id,
)
from routes_core import resolve_leader, request_arg, _sorted, ANY_ROLE

bp = Blueprint("deals", __name__)

TEMPERATURES = ("COLD", "WARM", "HOT")


# ---------------------------------------------------------------------------
# Nurture campaigns
# ---------------------------------------------------------------------------

@bp.post("/crm/nurture-campaigns")
def create_campaign():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"team_id", "name", "temperature_target", "steps"})
    team_id = as_str(req_field(body, "team_id"), "team_id")
    name = as_str(req_field(body, "name"), "name")
    target = as_enum(req_field(body, "temperature_target"), "temperature_target", TEMPERATURES)
    steps = req_field(body, "steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise err_invalid_request("steps must be a non-empty array")
    norm_steps = []
    prev = None
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            raise err_invalid_request(f"steps[{i}] must be an object")
        for k in s:
            if k not in ("offset_days", "channel"):
                raise err_invalid_request(f"steps[{i}] has undeclared field: {k}")
        if "offset_days" not in s or "channel" not in s:
            raise err_invalid_request(f"steps[{i}] requires offset_days and channel")
        off = as_int(s["offset_days"], f"steps[{i}].offset_days")
        if off < 0:
            raise err_invalid_request(f"steps[{i}].offset_days must be >= 0")
        chan = as_str(s["channel"], f"steps[{i}].channel")
        if prev is not None and off <= prev:
            raise err_invalid_request("steps offset_days must be strictly increasing")
        prev = off
        norm_steps.append({"offset_days": off, "channel": chan})
    team = store.teams.get(team_id)
    if team is None:
        raise err_not_found("team not found")
    now = store.now()
    camp = {"id": new_id(), "team_id": team_id, "name": name, "temperature_target": target,
            "steps": norm_steps, "status": "DRAFT",
            "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.campaigns[camp["id"]] = camp
    return ok_object(views.campaign_view(camp), status=201)


@bp.get("/crm/nurture-campaigns/<campaignId>")
def get_campaign(campaignId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    camp = store.campaigns.get(campaignId)
    if camp is None:
        raise err_not_found("nurture campaign not found")
    return ok_object(views.campaign_view(camp))


@bp.get("/crm/nurture-campaigns")
def list_campaigns():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.campaigns.values())
    team_id = request_arg("team_id")
    status = request_arg("status")
    if team_id is not None:
        items = [c for c in items if c["team_id"] == team_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([views.campaign_view(c) for c in page], limit, offset, total)


@bp.post("/crm/nurture-campaigns/<campaignId>/activate")
def activate_campaign(campaignId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, set())
    camp = store.campaigns.get(campaignId)
    if camp is None:
        raise err_not_found("nurture campaign not found")
    if camp["status"] not in ("DRAFT", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT or PAUSED campaign can be activated")
    resuming = camp["status"] == "PAUSED"
    camp["status"] = "ACTIVE"
    store.touch(camp)
    if resuming:
        for e in store.enrollments.values():
            if e["campaign_id"] == camp["id"] and e["status"] == "PAUSED":
                e["status"] = "ENROLLED"
                store.touch(e)
    return ok_object(views.campaign_view(camp))


@bp.post("/crm/nurture-campaigns/<campaignId>/pause")
def pause_campaign(campaignId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, set())
    camp = store.campaigns.get(campaignId)
    if camp is None:
        raise err_not_found("nurture campaign not found")
    if camp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE campaign can be paused")
    camp["status"] = "PAUSED"
    store.touch(camp)
    for e in store.enrollments.values():
        if e["campaign_id"] == camp["id"] and e["status"] == "ENROLLED":
            e["status"] = "PAUSED"
            store.touch(e)
    return ok_object(views.campaign_view(camp))


# ---------------------------------------------------------------------------
# Nurture enrollments
# ---------------------------------------------------------------------------

@bp.post("/crm/nurture-enrollments")
def create_enrollment():
    uid, role = auth_context()
    require_role(role, ("TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, {"campaign_id", "lead_id"})
    campaign_id = as_str(req_field(body, "campaign_id"), "campaign_id")
    lead_id = as_str(req_field(body, "lead_id"), "lead_id")
    camp = store.campaigns.get(campaign_id)
    if camp is None:
        raise err_not_found("nurture campaign not found")
    lead = store.leads.get(lead_id)
    if lead is None:
        raise err_not_found("lead not found")
    if role == "TeamLeader":
        resolve_leader(uid, camp["team_id"])
    if camp["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE", 409,
                       "Enrollment requires an ACTIVE campaign")
    if lead["status"] not in ("CLAIMED", "WORKING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CLAIMED or WORKING lead can be enrolled")
    svc.refresh_lead_temperature(lead)
    if lead["temperature"] != camp["temperature_target"]:
        raise ApiError("ERR_TEMPERATURE_MISMATCH", 409,
                       "Lead temperature does not equal the campaign temperature_target")
    for e in store.enrollments.values():
        if e["lead_id"] == lead["id"] and e["status"] in ("ENROLLED", "PAUSED"):
            raise ApiError("ERR_LEAD_ALREADY_ENROLLED", 409,
                           "Lead already has an ENROLLED or PAUSED enrollment")
    now = store.now()
    enr = {"id": new_id(), "campaign_id": camp["id"], "lead_id": lead["id"],
           "status": "ENROLLED", "entered_temperature": lead["temperature"],
           "current_step_index": 0,
           "next_send_at": now + timedelta(days=camp["steps"][0]["offset_days"]),
           "exit_reason": None,
           "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.enrollments[enr["id"]] = enr
    return ok_object(views.enrollment_view(enr), status=201)


@bp.get("/crm/nurture-enrollments/<enrollmentId>")
def get_enrollment(enrollmentId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    enr = store.enrollments.get(enrollmentId)
    if enr is None:
        raise err_not_found("nurture enrollment not found")
    return ok_object(views.enrollment_view(enr))


@bp.get("/crm/nurture-enrollments")
def list_enrollments():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.enrollments.values())
    for fname in ("campaign_id", "lead_id", "status"):
        fv = request_arg(fname)
        if fv is not None:
            items = [e for e in items if e[fname] == fv]
    page, total = paginate(items, limit, offset)
    return ok_list([views.enrollment_view(e) for e in page], limit, offset, total)


@bp.post("/crm/nurture-enrollments/<enrollmentId>/exit")
def exit_enrollment(enrollmentId):
    uid, role = auth_context()
    require_role(role, ("TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, set())
    enr = store.enrollments.get(enrollmentId)
    if enr is None:
        raise err_not_found("nurture enrollment not found")
    camp = store.campaigns.get(enr["campaign_id"])
    if role == "TeamLeader" and camp is not None:
        resolve_leader(uid, camp["team_id"])
    if enr["status"] not in ("ENROLLED", "PAUSED"):
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409,
                       "Only an ENROLLED or PAUSED enrollment can be exited")
    enr["status"] = "EXITED"
    enr["exit_reason"] = "MANUAL"
    store.touch(enr)
    return ok_object(views.enrollment_view(enr))


# ---------------------------------------------------------------------------
# Referral partners
# ---------------------------------------------------------------------------

@bp.post("/crm/referral-partners")
def create_partner():
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"team_id", "name", "fee_bps"})
    team_id = as_str(req_field(body, "team_id"), "team_id")
    name = as_str(req_field(body, "name"), "name")
    fee_bps = as_int(req_field(body, "fee_bps"), "fee_bps")
    if fee_bps < 0 or fee_bps > 5000:
        raise err_invalid_request("fee_bps must be between 0 and 5000")
    team = store.teams.get(team_id)
    if team is None:
        raise err_not_found("team not found")
    now = store.now()
    p = {"id": new_id(), "team_id": team_id, "name": name, "fee_bps": fee_bps,
         "status": "ACTIVE",
         "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.partners[p["id"]] = p
    return ok_object(views.partner_view(p), status=201)


@bp.get("/crm/referral-partners/<partnerId>")
def get_partner(partnerId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    p = store.partners.get(partnerId)
    if p is None:
        raise err_not_found("referral partner not found")
    return ok_object(views.partner_view(p))


@bp.get("/crm/referral-partners")
def list_partners():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.partners.values())
    team_id = request_arg("team_id")
    status = request_arg("status")
    if team_id is not None:
        items = [p for p in items if p["team_id"] == team_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([views.partner_view(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Split agreements
# ---------------------------------------------------------------------------

def _agreement_overlaps(a_from, a_until, b_from, b_until):
    """Half-open interval intersection; adjacency allowed; None until = infinite."""
    a_end = a_until if a_until is not None else None
    b_end = b_until if b_until is not None else None
    if a_end is not None and b_from >= a_end:
        return False
    if b_end is not None and a_from >= b_end:
        return False
    return True


@bp.post("/crm/split-agreements")
def create_agreement():
    uid, role = auth_context()
    require_role(role, ("TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, {"team_id", "agent_a_id", "agent_b_id", "a_share_bps",
                         "b_share_bps", "effective_from", "effective_until"})
    team_id = as_str(req_field(body, "team_id"), "team_id")
    agent_a_id = as_str(req_field(body, "agent_a_id"), "agent_a_id")
    agent_b_id = as_str(req_field(body, "agent_b_id"), "agent_b_id")
    a_share = as_int(req_field(body, "a_share_bps"), "a_share_bps")
    b_share = as_int(req_field(body, "b_share_bps"), "b_share_bps")
    eff_from = parse_dt(req_field(body, "effective_from"), "effective_from")
    eff_until = opt_field(body, "effective_until", None)
    if eff_until is not None:
        eff_until = parse_dt(eff_until, "effective_until")

    team = store.teams.get(team_id)
    if team is None:
        raise err_not_found("team not found")
    agent_a = store.agents.get(agent_a_id)
    if agent_a is None:
        raise err_not_found("agent_a not found")
    agent_b = store.agents.get(agent_b_id)
    if agent_b is None:
        raise err_not_found("agent_b not found")

    if role == "TeamLeader":
        resolve_leader(uid, team_id)

    # priority 7: temporal overlap against ACTIVE agreements of the same pair
    pair = {agent_a_id, agent_b_id}
    for ag in store.agreements.values():
        if ag["status"] != "ACTIVE":
            continue
        if {ag["agent_a_id"], ag["agent_b_id"]} != pair:
            continue
        if _agreement_overlaps(eff_from, eff_until, ag["effective_from"], ag["effective_until"]):
            raise ApiError("ERR_SPLIT_WINDOW_OVERLAP", 409,
                           "Window overlaps an ACTIVE agreement for this agent pair")

    # priority 8: structural cross-field rules
    if a_share + b_share != 10000:
        raise ApiError("ERR_SPLIT_SHARE_SUM_INVALID", 422,
                       "a_share_bps + b_share_bps must equal 10000")
    if (agent_a_id == agent_b_id
            or agent_a["team_id"] != agent_b["team_id"]
            or agent_a["team_id"] != team_id
            or agent_a["status"] != "ACTIVE" or agent_b["status"] != "ACTIVE"):
        raise ApiError("ERR_SPLIT_AGENT_PAIR_INVALID", 422,
                       "Split agents must be two distinct ACTIVE agents of the same team")

    now = store.now()
    ag = {"id": new_id(), "team_id": team_id, "agent_a_id": agent_a_id,
          "agent_b_id": agent_b_id, "a_share_bps": a_share, "b_share_bps": b_share,
          "effective_from": eff_from, "effective_until": eff_until, "status": "ACTIVE",
          "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.agreements[ag["id"]] = ag
    return ok_object(views.agreement_view(ag), status=201)


@bp.get("/crm/split-agreements/<agreementId>")
def get_agreement(agreementId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    ag = store.agreements.get(agreementId)
    if ag is None:
        raise err_not_found("split agreement not found")
    return ok_object(views.agreement_view(ag))


@bp.get("/crm/split-agreements")
def list_agreements():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.agreements.values())
    team_id = request_arg("team_id")
    agent_a_id = request_arg("agent_a_id")
    agent_b_id = request_arg("agent_b_id")
    agent_id = request_arg("agent_id")
    status = request_arg("status")
    if team_id is not None:
        items = [a for a in items if a["team_id"] == team_id]
    if agent_a_id is not None:
        items = [a for a in items if a["agent_a_id"] == agent_a_id]
    if agent_b_id is not None:
        items = [a for a in items if a["agent_b_id"] == agent_b_id]
    if agent_id is not None:
        items = [a for a in items if agent_id in (a["agent_a_id"], a["agent_b_id"])]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([views.agreement_view(a) for a in page], limit, offset, total)


@bp.post("/crm/split-agreements/<agreementId>/terminate")
def terminate_agreement(agreementId):
    uid, role = auth_context()
    require_role(role, ("TeamLeader", "TeamAdmin"))
    body = get_body()
    check_allowed(body, set())
    ag = store.agreements.get(agreementId)
    if ag is None:
        raise err_not_found("split agreement not found")
    if role == "TeamLeader":
        resolve_leader(uid, ag["team_id"])
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE agreement can be terminated")
    ag["status"] = "TERMINATED"
    store.touch(ag)
    return ok_object(views.agreement_view(ag))


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------

@bp.post("/crm/deals")
def create_deal():
    uid, role = auth_context()
    require_role(role, ("Agent", "TeamLeader"))
    body = get_body()
    check_allowed(body, {"lead_id", "gross_commission_cents"})
    lead_id = as_str(req_field(body, "lead_id"), "lead_id")
    gross = as_int(req_field(body, "gross_commission_cents"), "gross_commission_cents")
    if gross <= 0:
        raise err_invalid_request("gross_commission_cents must be > 0")
    lead = store.leads.get(lead_id)
    if lead is None:
        raise err_not_found("lead not found")
    if role == "Agent":
        if lead["assigned_agent_id"] is None or lead["assigned_agent_id"] != uid:
            raise ApiError("ERR_AGENT_IDENTITY_MISMATCH", 403,
                           "Agent callers may only create deals on their own leads")
    elif role == "TeamLeader":
        resolve_leader(uid, lead["team_id"])
    if lead["status"] != "WORKING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A deal can only be created for a WORKING lead")

    now = store.now()
    deal = {"id": new_id(), "team_id": lead["team_id"], "lead_id": lead["id"],
            "agent_id": lead["assigned_agent_id"],
            "gross_commission_cents": gross, "actual_gross_commission_cents": None,
            "status": "PENDING", "split_basis_type": "ESTIMATED",
            "split_basis_cents": 0,
            "referral_partner_id": lead["referral_partner_id"],
            "effective_fee_bps": 0, "referral_fee_cents": 0, "house_share_cents": 0,
            "agent_pool_cents": 0, "agent_shares": [], "split_agreement_id": None,
            "approved_at": None, "dispute_reason": None,
            "created_at": now, "updated_at": now, "version": 1, "_seq": store.next_seq()}
    store.deals[deal["id"]] = deal
    svc.apply_waterfall(deal, gross, now, snapshot_agreement=True)

    lead["status"] = "UNDER_CONTRACT"
    store.touch(lead)
    return ok_object(views.deal_view(deal), status=201)


@bp.get("/crm/deals/<dealId>")
def get_deal(dealId):
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    deal = store.deals.get(dealId)
    if deal is None:
        raise err_not_found("deal not found")
    return ok_object(views.deal_view(deal))


@bp.get("/crm/deals")
def list_deals():
    uid, role = auth_context()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = _sorted(store.deals.values())
    for fname in ("team_id", "lead_id", "agent_id", "status"):
        fv = request_arg(fname)
        if fv is not None:
            items = [d for d in items if d[fname] == fv]
    page, total = paginate(items, limit, offset)
    return ok_list([views.deal_view(d) for d in page], limit, offset, total)


@bp.post("/crm/deals/<dealId>/approve")
def approve_deal(dealId):
    uid, role = auth_context()
    require_role(role, ("TeamLeader",))
    body = get_body()
    check_allowed(body, {"actual_gross_commission_cents"})
    actual = opt_field(body, "actual_gross_commission_cents", None)
    if actual is not None:
        actual = as_int(actual, "actual_gross_commission_cents")
        if actual <= 0:
            raise err_invalid_request("actual_gross_commission_cents must be > 0")
    deal = store.deals.get(dealId)
    if deal is None:
        raise err_not_found("deal not found")
    resolve_leader(uid, deal["team_id"])
    if deal["status"] not in ("PENDING", "DISPUTED"):
        raise ApiError("ERR_DEAL_NOT_APPROVABLE", 409,
                       "Only a PENDING or DISPUTED deal can be approved")

    now = store.now()
    if actual is not None:
        deal["actual_gross_commission_cents"] = actual
        deal["split_basis_type"] = "ACTUAL"
        basis = actual
    else:
        basis = deal["gross_commission_cents"]
    svc.apply_waterfall(deal, basis, now, snapshot_agreement=True)
    deal["status"] = "APPROVED"
    deal["approved_at"] = now
    deal["dispute_reason"] = None
    store.touch(deal)

    lead = store.leads.get(deal["lead_id"])
    if lead is not None and lead["status"] != "CLOSED_WON":
        lead["status"] = "CLOSED_WON"
        lead["current_assignment_id"] = None
        lead["claim_deadline_at"] = None
        store.touch(lead)
        for e in store.enrollments.values():
            if e["lead_id"] == lead["id"] and e["status"] in ("ENROLLED", "PAUSED"):
                e["status"] = "EXITED"
                e["exit_reason"] = "CONVERTED"
                store.touch(e)
    return ok_object(views.deal_view(deal))


@bp.post("/crm/deals/<dealId>/dispute")
def dispute_deal(dealId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, {"reason"})
    reason = as_str(req_field(body, "reason"), "reason")
    deal = store.deals.get(dealId)
    if deal is None:
        raise err_not_found("deal not found")
    if deal["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED deal can be disputed")
    deal["status"] = "DISPUTED"
    deal["dispute_reason"] = reason
    store.touch(deal)
    return ok_object(views.deal_view(deal))


@bp.post("/crm/deals/<dealId>/mark-paid")
def mark_paid_deal(dealId):
    uid, role = auth_context()
    require_role(role, ("TeamAdmin",))
    body = get_body()
    check_allowed(body, set())
    deal = store.deals.get(dealId)
    if deal is None:
        raise err_not_found("deal not found")
    if deal["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED deal can be marked paid")
    deal["status"] = "PAID_OUT"
    store.touch(deal)
    return ok_object(views.deal_view(deal))
