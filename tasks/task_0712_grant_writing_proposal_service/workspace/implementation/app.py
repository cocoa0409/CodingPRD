"""Grant-Writing & Proposal Service API (task_0712)."""
import os
from decimal import Decimal

from flask import Flask, request

import auth
import clock
import db
import services as svc
from errors import ApiError
from helpers import (get_json, parse_pagination, paginate, require_enum,
                     require_fields, require_int, serialize, serialize_list)
import response

app = Flask(__name__)

P = "/grant-desk"
ALL_ROLES = {"AccountManager", "GrantWriter", "ClientContact", "ComplianceOfficer", "Ops"}


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return response.error("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)


# ===========================================================================
# Shared lookup helpers (existence -> ERR_NOT_FOUND)
# ===========================================================================
def fetch(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return rec


def ok(rec, status=200):
    return response.success(serialize(rec), status)


# ===========================================================================
# Clock
# ===========================================================================
@app.route(P + "/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth.require_context()
    auth.require_role(role, {"Ops"})
    body = get_json()
    require_fields(body, ["to_iso8601"])
    try:
        target = clock.parse_iso(body["to_iso8601"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601")
    clock.set_now(target)
    _apply_clock_effects()
    return response.success({}, 200)


def _apply_clock_effects():
    now = clock.get_now()
    for opp in db.opportunities.values():
        if opp["status"] == "OPEN":
            deadline = clock.parse_iso(opp["deadline_utc"])
            if now >= deadline:
                opp["status"] = "CLOSED"
                db.touch(opp)
    affected_awards = set()
    for rep in db.compliance_reports.values():
        if rep["status"] == "PENDING":
            due = clock.parse_iso(rep["due_utc"])
            if now >= due:
                rep["status"] = "LATE"
                db.touch(rep)
                affected_awards.add(rep["award_id"])
    for award_id in affected_awards:
        award = db.awards.get(award_id)
        if award:
            svc.recompute_compliance_status(award)
            db.touch(award)


# ===========================================================================
# Client
# ===========================================================================
@app.route(P + "/clients", methods=["POST"])
def create_client():
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    body = get_json()
    require_fields(body, ["org_name", "ein", "mission_areas", "annual_budget_cents", "contact_email"])
    if not isinstance(body["mission_areas"], list):
        raise ApiError("ERR_INVALID_REQUEST", "mission_areas must be an array")
    require_int(body["annual_budget_cents"], "annual_budget_cents", non_negative=True)
    ein = body["ein"]
    for c in db.clients.values():
        if c["ein"] == ein and c["status"] != "ARCHIVED":
            raise ApiError("ERR_INVALID_REQUEST", "EIN already in use")
    rec = {
        "org_name": body["org_name"],
        "ein": ein,
        "mission_areas": body["mission_areas"],
        "annual_budget_cents": body["annual_budget_cents"],
        "contact_email": body["contact_email"],
        "status": "ACTIVE",
        "proposals_submitted_count": 0,
        "proposals_won_count": 0,
        "win_rate_pct": 0.0,
    }
    db.init_common(rec)
    db.clients[rec["id"]] = rec
    return ok(rec, 201)


@app.route(P + "/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    rec = fetch(db.clients, cid)
    svc.recompute_client_counters(rec)
    return ok(rec)


@app.route(P + "/clients", methods=["GET"])
def list_clients():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    recs = list(db.clients.values())
    if status:
        recs = [r for r in recs if r["status"] == status]
    for r in recs:
        svc.recompute_client_counters(r)
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/clients/<cid>/suspend", methods=["POST"])
def suspend_client(cid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    rec = fetch(db.clients, cid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Client not ACTIVE")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return ok(rec)


# ===========================================================================
# FundingOpportunity
# ===========================================================================
@app.route(P + "/opportunities", methods=["POST"])
def create_opportunity():
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    body = get_json()
    require_fields(body, ["funder_name", "title", "focus_areas", "ceiling_amount_cents",
                          "portal_name", "deadline_utc"])
    if not isinstance(body["focus_areas"], list):
        raise ApiError("ERR_INVALID_REQUEST", "focus_areas must be an array")
    require_int(body["ceiling_amount_cents"], "ceiling_amount_cents", non_negative=True)
    floor = body.get("floor_amount_cents", 0)
    require_int(floor, "floor_amount_cents", non_negative=True)
    min_budget = body.get("min_org_budget_cents", 0)
    require_int(min_budget, "min_org_budget_cents", non_negative=True)
    try:
        clock.parse_iso(body["deadline_utc"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "deadline_utc must be ISO 8601")
    rec = {
        "funder_name": body["funder_name"],
        "title": body["title"],
        "focus_areas": body["focus_areas"],
        "ceiling_amount_cents": body["ceiling_amount_cents"],
        "floor_amount_cents": floor,
        "portal_name": body["portal_name"],
        "deadline_utc": body["deadline_utc"],
        "min_org_budget_cents": min_budget,
        "status": "OPEN",
    }
    db.init_common(rec)
    db.opportunities[rec["id"]] = rec
    return ok(rec, 201)


@app.route(P + "/opportunities/<oid>", methods=["GET"])
def get_opportunity(oid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.opportunities, oid))


@app.route(P + "/opportunities", methods=["GET"])
def list_opportunities():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.opportunities.values())
    status = request.args.get("status")
    portal = request.args.get("portal_name")
    if status:
        recs = [r for r in recs if r["status"] == status]
    if portal:
        recs = [r for r in recs if r["portal_name"] == portal]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


# ===========================================================================
# Engagement
# ===========================================================================
@app.route(P + "/engagements", methods=["POST"])
def create_engagement():
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    body = get_json()
    require_fields(body, ["client_id", "fee_model"])
    fetch(db.clients, body["client_id"])
    require_enum(body["fee_model"], {"SUCCESS_FEE", "HOURLY", "RETAINER"}, "fee_model")
    rec = {
        "client_id": body["client_id"],
        "fee_model": body["fee_model"],
        "success_fee_pct": body.get("success_fee_pct", 0),
        "hourly_rate_cents": body.get("hourly_rate_cents", 0),
        "retainer_monthly_cents": body.get("retainer_monthly_cents", 0),
        "retainer_included_hours": body.get("retainer_included_hours", 0),
        "overage_rate_cents": body.get("overage_rate_cents", 0),
        "status": "DRAFT",
        "ytd_billed_cents": 0,
    }
    db.init_common(rec)
    db.engagements[rec["id"]] = rec
    return ok(rec, 201)


@app.route(P + "/engagements/<eid>", methods=["GET"])
def get_engagement(eid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    rec = fetch(db.engagements, eid)
    svc.recompute_ytd_billed(rec)
    return ok(rec)


@app.route(P + "/engagements", methods=["GET"])
def list_engagements():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.engagements.values())
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if client_id:
        recs = [r for r in recs if r["client_id"] == client_id]
    if status:
        recs = [r for r in recs if r["status"] == status]
    for r in recs:
        svc.recompute_ytd_billed(r)
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/engagements/<eid>/activate", methods=["POST"])
def activate_engagement(eid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    eng = fetch(db.engagements, eid)
    if eng["status"] not in ("DRAFT", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", "Engagement cannot be activated")
    client = db.clients.get(eng["client_id"])
    if not client or client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", "Owning client is not ACTIVE")
    if eng["status"] == "DRAFT":
        fm = eng["fee_model"]
        if fm == "SUCCESS_FEE" and not (eng["success_fee_pct"] and eng["success_fee_pct"] > 0):
            raise ApiError("ERR_FEE_MODEL_INCOMPLETE", "success_fee_pct required")
        if fm == "HOURLY" and not (eng["hourly_rate_cents"] and eng["hourly_rate_cents"] > 0):
            raise ApiError("ERR_FEE_MODEL_INCOMPLETE", "hourly_rate_cents required")
        if fm == "RETAINER" and not (eng["retainer_monthly_cents"] and eng["retainer_monthly_cents"] > 0):
            raise ApiError("ERR_FEE_MODEL_INCOMPLETE", "retainer_monthly_cents required")
    eng["status"] = "ACTIVE"
    db.touch(eng)
    return ok(eng)


@app.route(P + "/engagements/<eid>/pause", methods=["POST"])
def pause_engagement(eid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    eng = fetch(db.engagements, eid)
    if eng["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Engagement not ACTIVE")
    eng["status"] = "PAUSED"
    db.touch(eng)
    return ok(eng)


@app.route(P + "/engagements/<eid>/close", methods=["POST"])
def close_engagement(eid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    eng = fetch(db.engagements, eid)
    if eng["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", "Engagement cannot be closed")
    for prop in db.proposals.values():
        if prop["engagement_id"] == eid and prop["status"] in ("DRAFTING", "IN_REVIEW"):
            raise ApiError("ERR_ENGAGEMENT_HAS_OPEN_WORK", "Open proposal work blocks close")
    eng["status"] = "CLOSED"
    db.touch(eng)
    return ok(eng)


# ===========================================================================
# MatchAssessment
# ===========================================================================
@app.route(P + "/matches", methods=["POST"])
def create_match():
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager", "GrantWriter"})
    body = get_json()
    require_fields(body, ["client_id", "opportunity_id"])
    client = fetch(db.clients, body["client_id"])
    opp = fetch(db.opportunities, body["opportunity_id"])
    score, eligible = svc.compute_match(client, opp)
    rec = {
        "client_id": body["client_id"],
        "opportunity_id": body["opportunity_id"],
        "score": score,
        "eligible": eligible,
        "status": "PROPOSED",
    }
    db.init_common(rec)
    db.matches[rec["id"]] = rec
    return ok(rec, 201)


@app.route(P + "/matches/<mid>", methods=["GET"])
def get_match(mid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.matches, mid))


@app.route(P + "/matches", methods=["GET"])
def list_matches():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.matches.values())
    for key in ("client_id", "opportunity_id", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/matches/<mid>/pursue", methods=["POST"])
def pursue_match(mid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager", "GrantWriter"})
    m = fetch(db.matches, mid)
    if m["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Match not PROPOSED")
    client = db.clients.get(m["client_id"])
    if not client or client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", "Client not ACTIVE")
    m["status"] = "PURSUING"
    db.touch(m)
    return ok(m)


@app.route(P + "/matches/<mid>/decline", methods=["POST"])
def decline_match(mid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager", "GrantWriter"})
    m = fetch(db.matches, mid)
    if m["status"] not in ("PROPOSED", "PURSUING"):
        raise ApiError("ERR_INVALID_STATE", "Match cannot be declined")
    if m["status"] == "PURSUING":
        for prop in db.proposals.values():
            if prop["match_id"] == mid and prop["status"] in ("DRAFTING", "IN_REVIEW", "APPROVED"):
                raise ApiError("ERR_INVALID_STATE", "Open proposal under this match")
    m["status"] = "DECLINED"
    db.touch(m)
    return ok(m)


# ===========================================================================
# Proposal
# ===========================================================================
@app.route(P + "/proposals", methods=["POST"])
def create_proposal():
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    body = get_json()
    require_fields(body, ["engagement_id", "match_id", "requested_amount_cents"])
    fetch(db.engagements, body["engagement_id"])
    match = fetch(db.matches, body["match_id"])
    require_int(body["requested_amount_cents"], "requested_amount_cents", positive=True)
    if match["status"] != "PURSUING":
        raise ApiError("ERR_MATCH_NOT_PURSUING", "Match is not PURSUING")
    rec = {
        "engagement_id": body["engagement_id"],
        "match_id": body["match_id"],
        "requested_amount_cents": body["requested_amount_cents"],
        "revision_round": 0,
        "budget_total_cents": 0,
        "status": "DRAFTING",
    }
    db.init_common(rec)
    db.proposals[rec["id"]] = rec
    return ok(rec, 201)


@app.route(P + "/proposals/<pid>", methods=["GET"])
def get_proposal(pid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    rec = fetch(db.proposals, pid)
    svc.recompute_budget_total(rec)
    return ok(rec)


@app.route(P + "/proposals", methods=["GET"])
def list_proposals():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.proposals.values())
    for key in ("engagement_id", "match_id", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    for r in recs:
        svc.recompute_budget_total(r)
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/proposals/<pid>/submit-for-review", methods=["POST"])
def submit_for_review(pid):
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    prop = fetch(db.proposals, pid)
    if prop["status"] != "DRAFTING":
        raise ApiError("ERR_INVALID_STATE", "Proposal not in DRAFTING")
    eng = db.engagements.get(prop["engagement_id"])
    if not eng or eng["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "Engagement not ACTIVE")
    has_narrative = any(
        d["proposal_id"] == pid and d["kind"] == "NARRATIVE"
        for d in db.deliverables.values()
    )
    if not has_narrative:
        raise ApiError("ERR_NO_NARRATIVE", "No NARRATIVE deliverable")
    svc.recompute_budget_total(prop)
    if prop["budget_total_cents"] <= 0:
        raise ApiError("ERR_EMPTY_BUDGET", "Budget total is zero")
    prop["status"] = "IN_REVIEW"
    db.touch(prop)
    return ok(prop)


def _assert_client_owner(user_id, role, client):
    if role == "ClientContact":
        if not client or client["id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner")


@app.route(P + "/proposals/<pid>/request-changes", methods=["POST"])
def request_changes(pid):
    user_id, role = auth.require_context()
    auth.require_role(role, {"ClientContact"})
    prop = fetch(db.proposals, pid)
    _assert_client_owner(user_id, role, svc.client_for_proposal(prop))
    if prop["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Proposal not IN_REVIEW")
    prop["status"] = "DRAFTING"
    prop["revision_round"] += 1
    db.touch(prop)
    for d in db.deliverables.values():
        if d["proposal_id"] == pid and d["approval_status"] == "APPROVED":
            d["approval_status"] = "CHANGES_REQUESTED"
            db.touch(d)
    return ok(prop)


@app.route(P + "/proposals/<pid>/approve", methods=["POST"])
def approve_proposal(pid):
    user_id, role = auth.require_context()
    auth.require_role(role, {"ClientContact"})
    prop = fetch(db.proposals, pid)
    _assert_client_owner(user_id, role, svc.client_for_proposal(prop))
    if prop["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Proposal not IN_REVIEW")
    deliverables = [d for d in db.deliverables.values() if d["proposal_id"] == pid]
    if not all(d["approval_status"] == "APPROVED" for d in deliverables):
        raise ApiError("ERR_DELIVERABLES_NOT_APPROVED", "Deliverables not all approved")
    prop["status"] = "APPROVED"
    db.touch(prop)
    return ok(prop)


@app.route(P + "/proposals/<pid>/withdraw", methods=["POST"])
def withdraw_proposal(pid):
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    prop = fetch(db.proposals, pid)
    if prop["status"] not in ("DRAFTING", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", "Proposal cannot be withdrawn")
    prop["status"] = "WITHDRAWN"
    db.touch(prop)
    return ok(prop)


# ===========================================================================
# BudgetLine
# ===========================================================================
@app.route(P + "/budget-lines", methods=["POST"])
def create_budget_line():
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    body = get_json()
    require_fields(body, ["proposal_id", "category", "label"])
    prop = fetch(db.proposals, body["proposal_id"])
    require_enum(body["category"], {"PERSONNEL", "EQUIPMENT", "TRAVEL", "INDIRECT", "OTHER"}, "category")
    category = body["category"]
    indirect_rate = body.get("indirect_rate_pct", 0)
    if category == "INDIRECT":
        amount = 0
    else:
        amount = body.get("amount_cents")
        require_int(amount, "amount_cents", non_negative=True)
    rec = {
        "proposal_id": body["proposal_id"],
        "category": category,
        "label": body["label"],
        "amount_cents": amount if category != "INDIRECT" else 0,
        "indirect_rate_pct": indirect_rate if category == "INDIRECT" else 0,
    }
    db.init_common(rec)
    db.budget_lines[rec["id"]] = rec
    svc.recompute_budget_total(prop)
    db.touch(prop)
    return ok(rec, 201)


@app.route(P + "/budget-lines/<bid>", methods=["GET"])
def get_budget_line(bid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.budget_lines, bid))


@app.route(P + "/budget-lines", methods=["GET"])
def list_budget_lines():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.budget_lines.values())
    for key in ("proposal_id", "category"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


# ===========================================================================
# Deliverable
# ===========================================================================
@app.route(P + "/deliverables", methods=["POST"])
def create_deliverable():
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    body = get_json()
    require_fields(body, ["proposal_id", "kind", "title"])
    fetch(db.proposals, body["proposal_id"])
    require_enum(body["kind"], {"NARRATIVE", "BUDGET_JUSTIFICATION", "ATTACHMENT"}, "kind")
    body_text = body.get("body", "")
    snippet = None
    import_id = body.get("import_snippet_id")
    if import_id is not None:
        snippet = fetch(db.boilerplate, import_id)
        body_text = snippet["body"]
    rec = {
        "proposal_id": body["proposal_id"],
        "kind": body["kind"],
        "title": body["title"],
        "body": body_text,
        "content_status": "OUTLINE",
        "approval_status": "UNREVIEWED",
        "open_revision_count": 0,
        "_imported_snippet_id": import_id,
    }
    db.init_common(rec)
    db.deliverables[rec["id"]] = rec
    if snippet:
        svc.recompute_usage_count(snippet)
        db.touch(snippet)
    return ok(rec, 201)


@app.route(P + "/deliverables/<did>", methods=["GET"])
def get_deliverable(did):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    rec = fetch(db.deliverables, did)
    svc.recompute_open_revision_count(rec)
    return ok(rec)


@app.route(P + "/deliverables", methods=["GET"])
def list_deliverables():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.deliverables.values())
    for key in ("proposal_id", "kind"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    for r in recs:
        svc.recompute_open_revision_count(r)
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/deliverables/<did>", methods=["PATCH"])
def update_deliverable(did):
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    rec = fetch(db.deliverables, did)
    body = get_json()
    require_fields(body, ["body"])
    rec["body"] = body["body"]
    db.touch(rec)
    return ok(rec)


@app.route(P + "/deliverables/<did>/advance-content", methods=["POST"])
def advance_content(did):
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    rec = fetch(db.deliverables, did)
    cur = rec["content_status"]
    if cur == "OUTLINE":
        if not rec.get("body"):
            raise ApiError("ERR_EMPTY_BODY", "Body is empty")
        rec["content_status"] = "DRAFTED"
    elif cur == "DRAFTED":
        if svc.recompute_open_revision_count(rec) != 0:
            raise ApiError("ERR_OPEN_REVISIONS_BLOCK_FINAL", "Open revisions block FINAL")
        rec["content_status"] = "FINAL"
    else:
        raise ApiError("ERR_INVALID_STATE", "Content already FINAL")
    db.touch(rec)
    return ok(rec)


@app.route(P + "/deliverables/<did>/approve", methods=["POST"])
def approve_deliverable(did):
    user_id, role = auth.require_context()
    auth.require_role(role, {"ClientContact"})
    rec = fetch(db.deliverables, did)
    _assert_client_owner(user_id, role, svc.client_for_deliverable(rec))
    if rec["approval_status"] not in ("UNREVIEWED", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", "Deliverable already APPROVED")
    if rec["approval_status"] == "UNREVIEWED":
        if rec["content_status"] not in ("DRAFTED", "FINAL"):
            raise ApiError("ERR_NOT_REVIEWABLE", "Content still OUTLINE")
    if svc.recompute_open_revision_count(rec) != 0:
        raise ApiError("ERR_OPEN_REVISIONS_BLOCK_APPROVAL", "Open revisions block approval")
    rec["approval_status"] = "APPROVED"
    db.touch(rec)
    return ok(rec)


# ===========================================================================
# RevisionRequest
# ===========================================================================
@app.route(P + "/revision-requests", methods=["POST"])
def create_revision_request():
    user_id, role = auth.require_context()
    auth.require_role(role, {"ClientContact"})
    body = get_json()
    require_fields(body, ["deliverable_id", "note"])
    deliverable = fetch(db.deliverables, body["deliverable_id"])
    supersedes_id = body.get("supersedes_revision_id")
    superseded = None
    if supersedes_id is not None:
        superseded = fetch(db.revision_requests, supersedes_id)
    _assert_client_owner(user_id, role, svc.client_for_deliverable(deliverable))
    if deliverable["content_status"] not in ("DRAFTED", "FINAL"):
        raise ApiError("ERR_NOT_REVIEWABLE", "Cannot review OUTLINE deliverable")
    rec = {
        "deliverable_id": body["deliverable_id"],
        "supersedes_revision_id": supersedes_id,
        "note": body["note"],
        "status": "OPEN",
    }
    db.init_common(rec)
    db.revision_requests[rec["id"]] = rec
    if superseded and superseded["status"] == "OPEN":
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)
    deliverable["approval_status"] = "CHANGES_REQUESTED"
    svc.recompute_open_revision_count(deliverable)
    db.touch(deliverable)
    return ok(rec, 201)


@app.route(P + "/revision-requests/<rid>", methods=["GET"])
def get_revision_request(rid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.revision_requests, rid))


@app.route(P + "/revision-requests", methods=["GET"])
def list_revision_requests():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.revision_requests.values())
    for key in ("deliverable_id", "supersedes_revision_id", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/revision-requests/<rid>/resolve", methods=["POST"])
def resolve_revision_request(rid):
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    rec = fetch(db.revision_requests, rid)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Revision request not OPEN")
    rec["status"] = "RESOLVED"
    db.touch(rec)
    deliverable = db.deliverables.get(rec["deliverable_id"])
    if deliverable:
        svc.recompute_open_revision_count(deliverable)
        db.touch(deliverable)
    return ok(rec)


# ===========================================================================
# Submission
# ===========================================================================
@app.route(P + "/submissions", methods=["POST"])
def create_submission():
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    body = get_json()
    require_fields(body, ["proposal_id", "expected_proposal_version"])
    prop = fetch(db.proposals, body["proposal_id"])
    expected = body["expected_proposal_version"]
    require_int(expected, "expected_proposal_version", non_negative=True)
    if prop["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Proposal not APPROVED")
    opp = svc.opportunity_for_proposal(prop)
    if opp is None:
        raise ApiError("ERR_NOT_FOUND", "Opportunity not found")
    now = clock.get_now()
    deadline = clock.parse_iso(opp["deadline_utc"])
    if opp["status"] != "OPEN" or now >= deadline:
        raise ApiError("ERR_OPPORTUNITY_CLOSED", "Opportunity closed or past deadline")
    if not (opp["floor_amount_cents"] <= prop["requested_amount_cents"] <= opp["ceiling_amount_cents"]):
        raise ApiError("ERR_REQUEST_OUT_OF_RANGE", "Requested amount out of range")
    if expected != prop["version"]:
        raise ApiError("ERR_STALE_PROPOSAL_VERSION", "Proposal version is stale")
    rec = {
        "proposal_id": body["proposal_id"],
        "portal_name": opp["portal_name"],
        "submitted_at_utc": clock.now_iso(),
        "decision_due_utc": body.get("decision_due_utc"),
        "status": "FILED",
    }
    db.init_common(rec)
    db.submissions[rec["id"]] = rec
    prop["status"] = "SUBMITTED"
    db.touch(prop)
    client = svc.client_for_proposal(prop)
    if client:
        svc.recompute_client_counters(client)
        db.touch(client)
    return ok(rec, 201)


@app.route(P + "/submissions/<sid>", methods=["GET"])
def get_submission(sid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.submissions, sid))


@app.route(P + "/submissions", methods=["GET"])
def list_submissions():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.submissions.values())
    for key in ("proposal_id", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/submissions/<sid>/record-decision", methods=["POST"])
def record_decision(sid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    sub = fetch(db.submissions, sid)
    body = get_json()
    require_fields(body, ["decision"])
    require_enum(body["decision"], {"ACCEPTED", "REJECTED"}, "decision")
    if sub["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Submission not FILED")
    if body["decision"] == "ACCEPTED":
        opp = svc.opportunity_for_proposal(db.proposals.get(sub["proposal_id"], {}))
        if opp is None:
            raise ApiError("ERR_NOT_FOUND", "Opportunity not found")
        sub["status"] = "ACCEPTED"
    else:
        sub["status"] = "REJECTED"
    db.touch(sub)
    client = svc.client_for_submission(sub)
    if client:
        svc.recompute_client_counters(client)
        db.touch(client)
    return ok(sub)


@app.route(P + "/submissions/<sid>/withdraw", methods=["POST"])
def withdraw_submission(sid):
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    sub = fetch(db.submissions, sid)
    if sub["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Submission not FILED")
    prop = db.proposals.get(sub["proposal_id"])
    opp = svc.opportunity_for_proposal(prop) if prop else None
    if opp is not None:
        now = clock.get_now()
        deadline = clock.parse_iso(opp["deadline_utc"])
        if now >= deadline:
            raise ApiError("ERR_OPPORTUNITY_CLOSED", "Past deadline")
    sub["status"] = "WITHDRAWN"
    db.touch(sub)
    if prop:
        prop["status"] = "WITHDRAWN"
        db.touch(prop)
    client = svc.client_for_submission(sub)
    if client:
        svc.recompute_client_counters(client)
        db.touch(client)
    return ok(sub)


# ===========================================================================
# TimeEntry
# ===========================================================================
def _valid_yyyymm(s):
    if not isinstance(s, str) or len(s) != 6 or not s.isdigit():
        return False
    month = int(s[4:6])
    return 1 <= month <= 12


@app.route(P + "/time-entries", methods=["POST"])
def create_time_entry():
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter", "AccountManager"})
    body = get_json()
    require_fields(body, ["engagement_id", "minutes", "period_yyyymm"])
    fetch(db.engagements, body["engagement_id"])
    proposal_id = body.get("proposal_id")
    if proposal_id is not None:
        fetch(db.proposals, proposal_id)
    require_int(body["minutes"], "minutes", positive=True)
    if not _valid_yyyymm(body["period_yyyymm"]):
        raise ApiError("ERR_INVALID_REQUEST", "period_yyyymm must be YYYYMM")
    rec = {
        "engagement_id": body["engagement_id"],
        "proposal_id": proposal_id,
        "minutes": body["minutes"],
        "period_yyyymm": body["period_yyyymm"],
        "status": "LOGGED",
    }
    db.init_common(rec)
    db.time_entries[rec["id"]] = rec
    return ok(rec, 201)


@app.route(P + "/time-entries/<tid>", methods=["GET"])
def get_time_entry(tid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.time_entries, tid))


@app.route(P + "/time-entries", methods=["GET"])
def list_time_entries():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.time_entries.values())
    for key in ("engagement_id", "proposal_id", "period_yyyymm", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


# ===========================================================================
# Invoice
# ===========================================================================
@app.route(P + "/invoices", methods=["POST"])
def create_invoice():
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    body = get_json()
    require_fields(body, ["engagement_id"])
    eng = fetch(db.engagements, body["engagement_id"])
    fee_model = eng["fee_model"]
    period_start = body.get("period_start_yyyymm")
    period_end = body.get("period_end_yyyymm")
    award_id = body.get("award_id")
    if award_id is not None:
        fetch(db.awards, award_id)

    # Body well-formedness (priority 5)
    if fee_model in ("HOURLY", "RETAINER"):
        if period_start is None or period_end is None:
            raise ApiError("ERR_INVALID_REQUEST", "period_start_yyyymm/period_end_yyyymm required")
        if not _valid_yyyymm(period_start) or not _valid_yyyymm(period_end):
            raise ApiError("ERR_INVALID_REQUEST", "Invalid period format")
        if svc.yyyymm_index(period_end) < svc.yyyymm_index(period_start):
            raise ApiError("ERR_INVALID_REQUEST", "period_end before period_start")

    # Engagement billable state (priority 11)
    if eng["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "Engagement not ACTIVE")

    if fee_model == "SUCCESS_FEE":
        return _issue_success_fee(eng, award_id)
    elif fee_model == "HOURLY":
        return _issue_hourly(eng, period_start, period_end)
    else:
        return _issue_retainer(eng, period_start, period_end)


def _billing_overlap(engagement_id, start_idx, end_idx):
    for inv in db.invoices.values():
        if inv["engagement_id"] != engagement_id:
            continue
        if inv["status"] != "ISSUED":
            continue
        if inv.get("period_start_yyyymm") is None:
            continue
        a2 = svc.yyyymm_index(inv["period_start_yyyymm"])
        b2 = svc.yyyymm_index(inv["period_end_yyyymm"])
        if svc.closed_intervals_overlap(start_idx, end_idx, a2, b2):
            return True
    return False


def _persist_invoice(rec, eng):
    db.init_common(rec)
    db.invoices[rec["id"]] = rec
    svc.recompute_ytd_billed(eng)
    db.touch(eng)
    return ok(rec, 201)


def _issue_success_fee(eng, award_id):
    if award_id is None:
        raise ApiError("ERR_NO_AWARD_FOR_SUCCESS_FEE", "award_id required for SUCCESS_FEE")
    award = db.awards.get(award_id)
    if not award or award["status"] != "ACTIVE":
        raise ApiError("ERR_NO_AWARD_FOR_SUCCESS_FEE", "No valid won award")
    total = svc.floor_div_decimal(
        Decimal(str(award["awarded_amount_cents"])) * Decimal(str(eng["success_fee_pct"])), 100
    )
    rec = {
        "engagement_id": eng["id"],
        "kind": "SUCCESS_FEE",
        "period_start_yyyymm": None,
        "period_end_yyyymm": None,
        "award_id": award_id,
        "line_count": 0,
        "total_cents": total,
        "status": "ISSUED",
    }
    return _persist_invoice(rec, eng)


def _sweep_entries(eng_id, start_idx, end_idx):
    swept = []
    for te in db.time_entries.values():
        if te["engagement_id"] != eng_id or te["status"] != "LOGGED":
            continue
        idx = svc.yyyymm_index(te["period_yyyymm"])
        if start_idx <= idx <= end_idx:
            swept.append(te)
    return swept


def _issue_hourly(eng, period_start, period_end):
    start_idx = svc.yyyymm_index(period_start)
    end_idx = svc.yyyymm_index(period_end)
    if _billing_overlap(eng["id"], start_idx, end_idx):
        raise ApiError("ERR_BILLING_PERIOD_OVERLAP", "Billing period overlaps existing invoice")
    swept = _sweep_entries(eng["id"], start_idx, end_idx)
    if not swept:
        raise ApiError("ERR_NOTHING_TO_BILL", "No LOGGED time in window")
    total_minutes = sum(te["minutes"] for te in swept)
    total = int((Decimal(total_minutes) / Decimal(60) * Decimal(str(eng["hourly_rate_cents"])))
                .to_integral_value(rounding="ROUND_FLOOR"))
    rec = {
        "engagement_id": eng["id"],
        "kind": "HOURLY",
        "period_start_yyyymm": period_start,
        "period_end_yyyymm": period_end,
        "award_id": None,
        "line_count": len(swept),
        "total_cents": total,
        "status": "ISSUED",
    }
    resp = _persist_invoice(rec, eng)
    for te in swept:
        te["status"] = "BILLED"
        te["_invoice_id"] = rec["id"]
        db.touch(te)
    return resp


def _issue_retainer(eng, period_start, period_end):
    start_idx = svc.yyyymm_index(period_start)
    end_idx = svc.yyyymm_index(period_end)
    if _billing_overlap(eng["id"], start_idx, end_idx):
        raise ApiError("ERR_BILLING_PERIOD_OVERLAP", "Billing period overlaps existing invoice")
    swept = _sweep_entries(eng["id"], start_idx, end_idx)
    billed_minutes = sum(te["minutes"] for te in swept)
    billed_hours = Decimal(billed_minutes) / Decimal(60)
    included = Decimal(str(eng["retainer_included_hours"]))
    overage_hours = billed_hours - included
    if overage_hours < 0:
        overage_hours = Decimal(0)
    overage_cents = int((overage_hours * Decimal(str(eng["overage_rate_cents"])))
                        .to_integral_value(rounding="ROUND_FLOOR"))
    total = eng["retainer_monthly_cents"] + overage_cents
    rec = {
        "engagement_id": eng["id"],
        "kind": "RETAINER",
        "period_start_yyyymm": period_start,
        "period_end_yyyymm": period_end,
        "award_id": None,
        "line_count": 0,
        "total_cents": total,
        "status": "ISSUED",
    }
    resp = _persist_invoice(rec, eng)
    for te in swept:
        te["status"] = "BILLED"
        te["_invoice_id"] = rec["id"]
        db.touch(te)
    return resp


@app.route(P + "/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.invoices, iid))


@app.route(P + "/invoices", methods=["GET"])
def list_invoices():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.invoices.values())
    for key in ("engagement_id", "award_id", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    _, role = auth.require_context()
    auth.require_role(role, {"AccountManager"})
    inv = fetch(db.invoices, iid)
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Invoice not ISSUED")
    inv["status"] = "VOID"
    db.touch(inv)
    for te in db.time_entries.values():
        if te.get("_invoice_id") == iid and te["status"] == "BILLED":
            te["status"] = "LOGGED"
            te["_invoice_id"] = None
            db.touch(te)
    eng = db.engagements.get(inv["engagement_id"])
    if eng:
        svc.recompute_ytd_billed(eng)
        db.touch(eng)
    return ok(inv)


# ===========================================================================
# Award
# ===========================================================================
@app.route(P + "/awards", methods=["POST"])
def create_award():
    _, role = auth.require_context()
    auth.require_role(role, {"ComplianceOfficer", "AccountManager"})
    body = get_json()
    require_fields(body, ["submission_id", "expected_submission_version",
                          "awarded_amount_cents", "period_of_performance_months"])
    sub = fetch(db.submissions, body["submission_id"])
    require_int(body["awarded_amount_cents"], "awarded_amount_cents", non_negative=True)
    require_int(body["period_of_performance_months"], "period_of_performance_months", non_negative=True)
    cadence = body.get("report_cadence_months", 3)
    require_int(cadence, "report_cadence_months", positive=True)
    expected = body["expected_submission_version"]
    require_int(expected, "expected_submission_version", non_negative=True)
    if sub["status"] != "ACCEPTED":
        raise ApiError("ERR_SUBMISSION_NOT_ACCEPTED", "Submission not ACCEPTED")
    if expected != sub["version"]:
        raise ApiError("ERR_STALE_SUBMISSION_VERSION", "Submission version is stale")
    rec = {
        "submission_id": body["submission_id"],
        "awarded_amount_cents": body["awarded_amount_cents"],
        "period_of_performance_months": body["period_of_performance_months"],
        "report_cadence_months": cadence,
        "compliance_status": "GREEN",
        "status": "ACTIVE",
    }
    db.init_common(rec)
    db.awards[rec["id"]] = rec
    sub["version"] += 1
    sub["updated_at"] = clock.now_iso()
    svc.generate_report_schedule(rec)
    svc.recompute_compliance_status(rec)
    return ok(rec, 201)


@app.route(P + "/awards/<aid>", methods=["GET"])
def get_award(aid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    rec = fetch(db.awards, aid)
    svc.recompute_compliance_status(rec)
    return ok(rec)


@app.route(P + "/awards", methods=["GET"])
def list_awards():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.awards.values())
    for key in ("submission_id", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    for r in recs:
        svc.recompute_compliance_status(r)
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/awards/<aid>/close-out", methods=["POST"])
def close_out_award(aid):
    _, role = auth.require_context()
    auth.require_role(role, {"ComplianceOfficer"})
    award = fetch(db.awards, aid)
    if award["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Award not ACTIVE")
    for r in db.compliance_reports.values():
        if r["award_id"] == aid and r["status"] in ("PENDING", "LATE"):
            raise ApiError("ERR_REPORTS_OUTSTANDING", "Outstanding reports")
    award["status"] = "CLOSED_OUT"
    db.touch(award)
    return ok(award)


# ===========================================================================
# ComplianceReport
# ===========================================================================
@app.route(P + "/compliance-reports", methods=["POST"])
def create_compliance_report():
    _, role = auth.require_context()
    auth.require_role(role, {"ComplianceOfficer"})
    body = get_json()
    require_fields(body, ["award_id", "covers_window_start_utc", "due_utc", "sequence_index"])
    award = fetch(db.awards, body["award_id"])
    require_int(body["sequence_index"], "sequence_index", positive=True)
    try:
        start = clock.parse_iso(body["covers_window_start_utc"])
        due = clock.parse_iso(body["due_utc"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid datetime")
    if award["status"] != "ACTIVE":
        raise ApiError("ERR_AWARD_CLOSED", "Award is not ACTIVE")
    # half-open overlap check (priority within business constraints)
    for r in db.compliance_reports.values():
        if r["award_id"] != award["id"]:
            continue
        if r.get("covers_window_start_utc") is None:
            continue
        s2 = clock.parse_iso(r["covers_window_start_utc"])
        e2 = clock.parse_iso(r["due_utc"])
        if svc.half_open_overlap(start, due, s2, e2):
            raise ApiError("ERR_REPORT_WINDOW_OVERLAP", "Report window overlaps")
    rec = {
        "award_id": body["award_id"],
        "due_utc": body["due_utc"],
        "covers_window_start_utc": body["covers_window_start_utc"],
        "report_type": "SUPPLEMENTAL",
        "sequence_index": body["sequence_index"],
        "submitted_at_utc": None,
        "status": "PENDING",
    }
    db.init_common(rec)
    db.compliance_reports[rec["id"]] = rec
    svc.recompute_compliance_status(award)
    db.touch(award)
    return ok(rec, 201)


@app.route(P + "/compliance-reports/<rid>", methods=["GET"])
def get_compliance_report(rid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    return ok(fetch(db.compliance_reports, rid))


@app.route(P + "/compliance-reports", methods=["GET"])
def list_compliance_reports():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.compliance_reports.values())
    for key in ("award_id", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/compliance-reports/<rid>/file", methods=["POST"])
def file_compliance_report(rid):
    _, role = auth.require_context()
    auth.require_role(role, {"ComplianceOfficer"})
    rep = fetch(db.compliance_reports, rid)
    if rep["status"] not in ("PENDING", "LATE"):
        raise ApiError("ERR_INVALID_STATE", "Report not PENDING/LATE")
    award = db.awards.get(rep["award_id"])
    if not award or award["status"] != "ACTIVE":
        raise ApiError("ERR_AWARD_CLOSED", "Award not ACTIVE")
    rep["status"] = "FILED"
    rep["submitted_at_utc"] = clock.now_iso()
    db.touch(rep)
    svc.recompute_compliance_status(award)
    db.touch(award)
    return ok(rep)


# ===========================================================================
# BoilerplateSnippet
# ===========================================================================
@app.route(P + "/boilerplate", methods=["POST"])
def create_boilerplate():
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    body = get_json()
    require_fields(body, ["client_id", "section_key", "body"])
    fetch(db.clients, body["client_id"])
    for s in db.boilerplate.values():
        if (s["client_id"] == body["client_id"] and s["section_key"] == body["section_key"]
                and s["status"] == "ACTIVE"):
            raise ApiError("ERR_INVALID_REQUEST", "section_key already in use")
    rec = {
        "client_id": body["client_id"],
        "section_key": body["section_key"],
        "body": body["body"],
        "usage_count": 0,
        "status": "ACTIVE",
    }
    db.init_common(rec)
    db.boilerplate[rec["id"]] = rec
    return ok(rec, 201)


@app.route(P + "/boilerplate/<bid>", methods=["GET"])
def get_boilerplate(bid):
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    rec = fetch(db.boilerplate, bid)
    svc.recompute_usage_count(rec)
    return ok(rec)


@app.route(P + "/boilerplate", methods=["GET"])
def list_boilerplate():
    _, role = auth.require_context()
    auth.require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    recs = list(db.boilerplate.values())
    for key in ("client_id", "section_key", "status"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r[key] == val]
    for r in recs:
        svc.recompute_usage_count(r)
    page, meta = paginate(recs, limit, offset)
    return response.success(serialize_list(page), 200, meta)


@app.route(P + "/boilerplate/<bid>/retire", methods=["POST"])
def retire_boilerplate(bid):
    _, role = auth.require_context()
    auth.require_role(role, {"GrantWriter"})
    rec = fetch(db.boilerplate, bid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Snippet not ACTIVE")
    rec["status"] = "RETIRED"
    db.touch(rec)
    return ok(rec)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
