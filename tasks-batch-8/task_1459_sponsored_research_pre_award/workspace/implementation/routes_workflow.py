"""Routes: routing/approval/submission/JIT workflow and cost-share commitments."""

from datetime import timedelta

from flask import Blueprint

from db import store, mint, touch
from errors import (ApiError, bad_request, not_found, ERR_PROPOSAL_STATE,
                    ERR_SELF_APPROVAL, ERR_OPPORTUNITY_CLOSED,
                    ERR_DEADLINE_PASSED, ERR_PI_EFFORT,
                    ERR_COST_SHARE_INADEQUATE, ERR_COMMITMENT_STATE,
                    ERR_COST_SHARE_SELF_APPROVAL)
from middleware import authenticate, require_roles
from response import ok_object, ok_list, parse_pagination
from serializers import proposal_out, package_out, cost_share_out
from services import (effort_capacity_ok, return_for_revision_effects,
                      recompute_cost_share, cost_shares_of_proposal)
from utils import (json_body, req_field, opt_field, as_str, as_int, as_enum,
                   fmt_dt)

bp = Blueprint("workflow", __name__)

COST_SHARE_SOURCES = ["DEPARTMENT", "COLLEGE", "CENTRAL_OFFICE",
                      "THIRD_PARTY_IN_KIND"]

COST_SHARE_APPROVABLE_PROPOSAL_STATES = {
    "DRAFT", "BUDGET_LOCKED", "ROUTED", "INSTITUTIONALLY_APPROVED",
    "SUBMITTED", "JIT_REQUESTED", "NEGOTIATING", "AWARDED",
}


def _get_proposal_or_404(pid):
    p = store.proposals.get(pid)
    if p is None:
        raise not_found("Proposal not found")
    return p


def _get_cost_share_or_404(cid):
    c = store.cost_share_commitments.get(cid)
    if c is None:
        raise not_found("Cost-share commitment not found")
    return c


def _paginate(items, serializer):
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, len(ordered))


# ---------------------------------------------------------------------------
# Routing and institutional approval
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/route")
def route_proposal(pid):
    user_id, _ = require_roles(["PreAwardAnalyst"])
    p = _get_proposal_or_404(pid)
    if p["status"] != "BUDGET_LOCKED":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Only a BUDGET_LOCKED proposal can be routed")
    if not effort_capacity_ok(p):
        raise ApiError(ERR_PI_EFFORT, 422,
                       "The PI's committed effort across overlapping project "
                       "windows would exceed 100.00")
    opp = store.funding_opportunities[p["opportunity_id"]]
    if opp["requires_cost_share"] and not p["is_cost_share_adequate"]:
        raise ApiError(ERR_COST_SHARE_INADEQUATE, 422,
                       "Approved cost share does not meet the required "
                       "minimum")
    p["routed_by_user_id"] = user_id
    p["status"] = "ROUTED"
    touch(p)
    return ok_object(proposal_out(p), 200)


@bp.post("/pre-award/proposals/<pid>/approve-institutional")
def approve_institutional(pid):
    user_id, _ = require_roles(["OSPDirector"])
    p = _get_proposal_or_404(pid)
    opp = store.funding_opportunities[p["opportunity_id"]]
    if p["status"] == "ROUTED":
        if user_id == p["routed_by_user_id"]:
            raise ApiError(ERR_SELF_APPROVAL, 403,
                           "The institutional approver must differ from the "
                           "analyst who routed the proposal")
        if opp["status"] != "PUBLISHED":
            raise ApiError(ERR_OPPORTUNITY_CLOSED, 409,
                           "The funding opportunity is not PUBLISHED")
        p["pinned_budget_snapshot_id"] = p["current_snapshot_id"]
        p["status"] = "INSTITUTIONALLY_APPROVED"
    elif p["status"] == "JIT_REQUESTED":
        if not p["budget_amended_since_approval"]:
            raise ApiError(ERR_PROPOSAL_STATE, 409,
                           "Re-approval from JIT_REQUESTED requires a budget "
                           "amendment since approval")
        if opp["status"] != "PUBLISHED":
            raise ApiError(ERR_OPPORTUNITY_CLOSED, 409,
                           "The funding opportunity is not PUBLISHED")
        p["pinned_budget_snapshot_id"] = p["current_snapshot_id"]
        p["budget_amended_since_approval"] = False
    elif p["status"] == "AWARDED":
        if not p["budget_amended_since_approval"]:
            raise ApiError(ERR_PROPOSAL_STATE, 409,
                           "Re-approval from AWARDED requires a budget "
                           "amendment since approval")
        p["pinned_budget_snapshot_id"] = p["current_snapshot_id"]
        p["budget_amended_since_approval"] = False
    else:
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Institutional approval is not available from this "
                       "status")
    touch(p)
    return ok_object(proposal_out(p), 200)


@bp.post("/pre-award/proposals/<pid>/return-for-revision")
def return_for_revision(pid):
    require_roles(["OSPDirector"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    as_str(req_field(body, "reason"), "reason")
    if p["status"] != "ROUTED":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Only a ROUTED proposal can be returned for revision")
    p["status"] = "RETURNED_FOR_REVISION"
    p["revision_count"] += 1
    return_for_revision_effects(p)
    touch(p)
    return ok_object(proposal_out(p), 200)


# ---------------------------------------------------------------------------
# Submission portal
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/submit")
def submit_proposal(pid):
    require_roles(["OSPDirector"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    key = as_str(req_field(body, "idempotency_key"), "idempotency_key")
    for pkg in store.submission_packages.values():
        if pkg["proposal_id"] == pid and pkg["idempotency_key"] == key:
            return ok_object(package_out(pkg), 201)
    if p["status"] != "INSTITUTIONALLY_APPROVED":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Only an INSTITUTIONALLY_APPROVED proposal can be "
                       "submitted")
    opp = store.funding_opportunities[p["opportunity_id"]]
    if opp["status"] != "PUBLISHED":
        raise ApiError(ERR_OPPORTUNITY_CLOSED, 409,
                       "The funding opportunity is not PUBLISHED")
    if store.clock > opp["_internal_deadline_dt"]:
        raise ApiError(ERR_DEADLINE_PASSED, 422,
                       "The internal deadline for this opportunity has passed")
    import uuid
    submitted = fmt_dt(store.clock)
    pkg = mint({
        "proposal_id": pid,
        "idempotency_key": key,
        "portal_confirmation_code": "PC-" + uuid.uuid4().hex[:12].upper(),
        "submitted_at": submitted,
        "status": "ACCEPTED_BY_PORTAL",
    }, versioned=False)
    store.submission_packages[pkg["id"]] = pkg
    p["submitted_at"] = submitted
    p["status"] = "SUBMITTED"
    touch(p)
    return ok_object(package_out(pkg), 201)


@bp.get("/pre-award/proposals/<pid>/submission-packages")
def list_submission_packages(pid):
    authenticate()
    _get_proposal_or_404(pid)
    items = [x for x in store.submission_packages.values()
             if x["proposal_id"] == pid]
    return _paginate(items, package_out)


# ---------------------------------------------------------------------------
# Just-in-time notices and responses
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/jit-notices")
def jit_notice(pid):
    require_roles(["OSPDirector"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    as_str(req_field(body, "sponsor_reference"), "sponsor_reference")
    due_in_days = as_int(opt_field(body, "due_in_days", 14), "due_in_days")
    if due_in_days < 0:
        raise bad_request("Field 'due_in_days' must be >= 0")
    if p["status"] != "SUBMITTED":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Only a SUBMITTED proposal can receive a JIT notice")
    p["jit_due_at"] = fmt_dt(store.clock + timedelta(days=due_in_days))
    p["status"] = "JIT_REQUESTED"
    touch(p)
    return ok_object(proposal_out(p), 200)


@bp.post("/pre-award/proposals/<pid>/jit-responses")
def jit_response(pid):
    require_roles(["OSPDirector"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    as_str(req_field(body, "sponsor_reference"), "sponsor_reference")
    if p["status"] != "JIT_REQUESTED":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Only a JIT_REQUESTED proposal can record a JIT "
                       "response")
    p["status"] = "SUBMITTED"
    touch(p)
    return ok_object(proposal_out(p), 200)


# ---------------------------------------------------------------------------
# Cost-share commitments
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/cost-share-commitments")
def create_cost_share(pid):
    user_id, _ = require_roles(["PreAwardAnalyst"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    source_type = as_enum(req_field(body, "source_type"), "source_type",
                          COST_SHARE_SOURCES)
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    if amount <= 0:
        raise bad_request("Field 'amount_cents' must be > 0")
    rec = mint({
        "proposal_id": pid,
        "source_type": source_type,
        "amount_cents": amount,
        "committed_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "PLEDGED",
    })
    store.cost_share_commitments[rec["id"]] = rec
    recompute_cost_share(p)
    return ok_object(cost_share_out(rec), 201)


@bp.get("/pre-award/proposals/<pid>/cost-share-commitments")
def list_cost_shares(pid):
    authenticate()
    _get_proposal_or_404(pid)
    return _paginate(cost_shares_of_proposal(pid), cost_share_out)


@bp.post("/pre-award/cost-share-commitments/<cid>/approve")
def approve_cost_share(cid):
    user_id, _ = require_roles(["DepartmentChair"])
    c = _get_cost_share_or_404(cid)
    p = store.proposals.get(c["proposal_id"])
    if c["status"] != "PLEDGED":
        raise ApiError(ERR_COMMITMENT_STATE, 409,
                       "Only a PLEDGED commitment can be approved")
    if p is None or p["status"] not in COST_SHARE_APPROVABLE_PROPOSAL_STATES:
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "The parent proposal's status does not allow cost-share "
                       "approval")
    if user_id == c["committed_by_user_id"]:
        raise ApiError(ERR_COST_SHARE_SELF_APPROVAL, 403,
                       "The approver must differ from the commitment's "
                       "creator")
    c["approved_by_user_id"] = user_id
    c["status"] = "APPROVED"
    touch(c)
    recompute_cost_share(p)
    touch(p)
    return ok_object(cost_share_out(c), 200)


@bp.post("/pre-award/cost-share-commitments/<cid>/release")
def release_cost_share(cid):
    require_roles(["DepartmentChair"])
    c = _get_cost_share_or_404(cid)
    p = store.proposals.get(c["proposal_id"])
    if c["status"] != "APPROVED":
        raise ApiError(ERR_COMMITMENT_STATE, 409,
                       "Only an APPROVED commitment can be released")
    c["status"] = "RELEASED"
    touch(c)
    if p is not None:
        recompute_cost_share(p)
        touch(p)
    return ok_object(cost_share_out(c), 200)


@bp.post("/pre-award/cost-share-commitments/<cid>/withdraw")
def withdraw_cost_share(cid):
    require_roles(["PreAwardAnalyst"])
    c = _get_cost_share_or_404(cid)
    if c["status"] != "PLEDGED":
        raise ApiError(ERR_COMMITMENT_STATE, 409,
                       "Only a PLEDGED commitment can be withdrawn")
    c["status"] = "WITHDRAWN"
    touch(c)
    p = store.proposals.get(c["proposal_id"])
    if p is not None:
        recompute_cost_share(p)
    return ok_object(cost_share_out(c), 200)
