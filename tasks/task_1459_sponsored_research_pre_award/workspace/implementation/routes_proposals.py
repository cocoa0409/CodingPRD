"""Routes: proposals, budget lines, budget finalizations, snapshots."""

from decimal import Decimal

from flask import Blueprint

from db import store, mint, touch
from errors import (ApiError, bad_request, not_found, ERR_FORBIDDEN,
                    ERR_NOT_OWNER, ERR_PI_NOT_ELIGIBLE, ERR_OPPORTUNITY_CLOSED,
                    ERR_ACTIVITY_NOT_ALLOWED, ERR_PI_LIMIT, ERR_PROPOSAL_STATE,
                    ERR_STALE_VERSION, ERR_EMPTY_BUDGET, ERR_NO_RATE,
                    ERR_REQUEST_CAP)
from middleware import authenticate, require_roles
from response import ok_object, ok_list, parse_pagination
from serializers import proposal_out, budget_line_out, snapshot_out
from services import (ACTIVITY_CODES, ACTIVITY_TO_RATE_TYPE,
                      PROPOSAL_TERMINAL_STATES, proposals_of_pi,
                      lines_of_proposal, snapshots_of_proposal,
                      select_rate_agreement, applied_rate, compute_indirect,
                      recompute_cost_share, recompute_mtdc_flags)
from utils import (json_body, req_field, opt_field, as_str, as_int, as_bool,
                   as_number, as_enum, parse_date_value)

bp = Blueprint("proposals", __name__)

BUDGET_CATEGORIES = ["PERSONNEL", "EQUIPMENT", "TRAVEL", "PARTICIPANT_SUPPORT",
                     "MATERIALS", "PUBLICATION", "CONSULTANT", "SUBAWARD",
                     "TUITION", "OTHER_DIRECT"]
FA_BASE_TYPES = ["MTDC", "TDC"]

WITHDRAWABLE_STATES = {"DRAFT", "BUDGET_LOCKED", "ROUTED",
                       "RETURNED_FOR_REVISION", "INSTITUTIONALLY_APPROVED",
                       "SUBMITTED", "JIT_REQUESTED", "NEGOTIATING"}


def _get_proposal_or_404(pid):
    p = store.proposals.get(pid)
    if p is None:
        raise not_found("Proposal not found")
    return p


def _paginate(items, serializer):
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, len(ordered))


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals")
def create_proposal():
    user_id, _ = require_roles(["PI"])
    body = json_body()
    opportunity_id = as_str(req_field(body, "opportunity_id"), "opportunity_id")
    pi_id = as_str(req_field(body, "pi_id"), "pi_id")
    title = as_str(req_field(body, "title"), "title")
    activity_code = as_enum(req_field(body, "activity_code"), "activity_code",
                            ACTIVITY_CODES)
    start_raw = as_str(req_field(body, "project_start_on"), "project_start_on")
    end_raw = as_str(req_field(body, "project_end_on"), "project_end_on")
    start = parse_date_value(start_raw, "project_start_on")
    end = parse_date_value(end_raw, "project_end_on")
    if end < start:
        raise bad_request("project_end_on is earlier than project_start_on")
    effort = as_number(req_field(body, "pi_effort_pct"), "pi_effort_pct")
    if effort <= 0 or effort > Decimal("100"):
        raise bad_request("Field 'pi_effort_pct' must be > 0 and <= 100")
    fa_base_type = as_enum(opt_field(body, "fa_base_type", "MTDC"),
                           "fa_base_type", FA_BASE_TYPES)

    if pi_id != user_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "A PI may only create proposals with pi_id equal to "
                       "their own X-User-ID")

    opp = store.funding_opportunities.get(opportunity_id)
    if opp is None:
        raise not_found("Funding opportunity not found")
    pi = store.principal_investigators.get(pi_id)
    if pi is None:
        raise not_found("Principal investigator not found")

    if pi["delinquent_report_count"] != 0:
        raise ApiError(ERR_PI_NOT_ELIGIBLE, 403,
                       "The principal investigator has delinquent prior-award "
                       "reports")
    if opp["status"] != "PUBLISHED":
        raise ApiError(ERR_OPPORTUNITY_CLOSED, 409,
                       "The funding opportunity is not PUBLISHED")
    if activity_code not in opp["activity_codes_allowed"]:
        raise ApiError(ERR_ACTIVITY_NOT_ALLOWED, 422,
                       "The activity code is not allowed by this opportunity")
    cap = opp["max_proposals_per_pi"]
    if cap is not None:
        active = [p for p in proposals_of_pi(pi_id)
                  if p["opportunity_id"] == opportunity_id
                  and p["status"] not in PROPOSAL_TERMINAL_STATES]
        if len(active) >= cap:
            raise ApiError(ERR_PI_LIMIT, 409,
                           "The PI has reached this opportunity's proposal "
                           "limit")

    rec = mint({
        "opportunity_id": opportunity_id,
        "pi_id": pi_id,
        "title": title,
        "activity_code": activity_code,
        "project_start_on": start_raw,
        "project_end_on": end_raw,
        "pi_effort_pct": effort,
        "fa_base_type": fa_base_type,
        "current_snapshot_id": None,
        "pinned_budget_snapshot_id": None,
        "total_direct_cents": 0,
        "total_indirect_cents": 0,
        "total_request_cents": 0,
        "fa_rate_pct_applied": None,
        "applied_rate_source": None,
        "total_approved_cost_share_cents": 0,
        "total_effective_cost_share_cents": 0,
        "is_cost_share_adequate": False,
        "compliance_posture": "CLEAR",
        "routed_by_user_id": None,
        "budget_amended_since_approval": False,
        "revision_count": 0,
        "submitted_at": None,
        "jit_due_at": None,
        "awarded_total_cents": None,
        "status": "DRAFT",
        "_start": start,
        "_end": end,
    })
    store.proposals[rec["id"]] = rec
    return ok_object(proposal_out(rec), 201)


@bp.get("/pre-award/proposals")
def list_proposals():
    authenticate()
    items = list(store.proposals.values())
    for key in ("opportunity_id", "pi_id", "status", "current_snapshot_id",
                "pinned_budget_snapshot_id"):
        raw = request_arg(key)
        if raw is not None:
            items = [p for p in items
                     if (p[key] if p[key] is not None else None) == raw]
    return _paginate(items, proposal_out)


def request_arg(name):
    from flask import request
    return request.args.get(name)


@bp.get("/pre-award/proposals/<pid>")
def get_proposal(pid):
    authenticate()
    return ok_object(proposal_out(_get_proposal_or_404(pid)), 200)


@bp.patch("/pre-award/proposals/<pid>")
def patch_proposal(pid):
    user_id, _ = require_roles(["PI"])
    p = _get_proposal_or_404(pid)
    if p["pi_id"] != user_id:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "A PI may only edit proposals they own")
    body = json_body()
    updates = {}
    if "title" in body and body["title"] is not None:
        updates["title"] = as_str(body["title"], "title")
    new_start = p["_start"]
    new_end = p["_end"]
    if "project_start_on" in body and body["project_start_on"] is not None:
        raw = as_str(body["project_start_on"], "project_start_on")
        new_start = parse_date_value(raw, "project_start_on")
        updates["project_start_on"] = raw
    if "project_end_on" in body and body["project_end_on"] is not None:
        raw = as_str(body["project_end_on"], "project_end_on")
        new_end = parse_date_value(raw, "project_end_on")
        updates["project_end_on"] = raw
    if new_end < new_start:
        raise bad_request("project_end_on is earlier than project_start_on")
    if "pi_effort_pct" in body and body["pi_effort_pct"] is not None:
        effort = as_number(body["pi_effort_pct"], "pi_effort_pct")
        if effort <= 0 or effort > Decimal("100"):
            raise bad_request("Field 'pi_effort_pct' must be > 0 and <= 100")
        updates["pi_effort_pct"] = effort
    if "fa_base_type" in body and body["fa_base_type"] is not None:
        updates["fa_base_type"] = as_enum(body["fa_base_type"], "fa_base_type",
                                          FA_BASE_TYPES)
    if p["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Proposals may only be edited while DRAFT or "
                       "RETURNED_FOR_REVISION")
    for k, v in updates.items():
        p[k] = v
    p["_start"] = new_start
    p["_end"] = new_end
    if p["status"] == "RETURNED_FOR_REVISION":
        p["status"] = "DRAFT"
    touch(p)
    return ok_object(proposal_out(p), 200)


@bp.post("/pre-award/proposals/<pid>/withdraw")
def withdraw_proposal(pid):
    user_id, role = require_roles(["PI", "OSPDirector"])
    p = _get_proposal_or_404(pid)
    if role == "PI" and p["pi_id"] != user_id:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "A PI may only withdraw proposals they own")
    if p["status"] not in WITHDRAWABLE_STATES:
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "This proposal status cannot be withdrawn")
    from services import terminal_cleanup
    terminal_cleanup(p)
    p["status"] = "WITHDRAWN"
    touch(p)
    return ok_object(proposal_out(p), 200)


# ---------------------------------------------------------------------------
# Budget lines
# ---------------------------------------------------------------------------

def _supersede_current_snapshot(p):
    sid = p["current_snapshot_id"]
    if sid is not None:
        snap = store.budget_snapshots.get(sid)
        if snap is not None and snap["status"] == "CURRENT":
            snap["status"] = "SUPERSEDED"
            touch(snap)
    p["current_snapshot_id"] = None


def _line_mutation_side_effects(p):
    """Snapshot supersede rules shared by budget-line add and delete."""
    if p["status"] == "BUDGET_LOCKED":
        _supersede_current_snapshot(p)
        p["status"] = "DRAFT"
    elif p["status"] == "JIT_REQUESTED":
        _supersede_current_snapshot(p)
        p["budget_amended_since_approval"] = True
    recompute_mtdc_flags(p)
    touch(p)


@bp.post("/pre-award/proposals/<pid>/budget-lines")
def add_budget_line(pid):
    require_roles(["PreAwardAnalyst"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    category = as_enum(req_field(body, "category"), "category",
                       BUDGET_CATEGORIES)
    description = as_str(req_field(body, "description"), "description")
    fiscal_year = as_int(req_field(body, "fiscal_year"), "fiscal_year")
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    if amount <= 0:
        raise bad_request("Field 'amount_cents' must be > 0")
    is_cost_share = as_bool(opt_field(body, "is_cost_share", False),
                            "is_cost_share")
    commitment_id = opt_field(body, "subrecipient_commitment_id", None)
    if commitment_id is not None:
        commitment_id = as_str(commitment_id, "subrecipient_commitment_id")
    if category == "SUBAWARD" and commitment_id is None:
        raise bad_request("A SUBAWARD line requires a "
                          "subrecipient_commitment_id")
    if commitment_id is not None and \
            commitment_id not in store.subrecipient_commitments:
        raise not_found("Subrecipient commitment not found")
    if p["status"] not in ("DRAFT", "BUDGET_LOCKED", "JIT_REQUESTED"):
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Budget lines may only change while the proposal is "
                       "DRAFT, BUDGET_LOCKED, or JIT_REQUESTED")
    rec = mint({
        "proposal_id": pid,
        "category": category,
        "description": description,
        "fiscal_year": fiscal_year,
        "amount_cents": amount,
        "is_cost_share": is_cost_share,
        "subrecipient_commitment_id": commitment_id,
        "counts_toward_mtdc": True,
    })
    store.budget_lines[rec["id"]] = rec
    _line_mutation_side_effects(p)
    return ok_object(budget_line_out(rec), 201)


@bp.get("/pre-award/proposals/<pid>/budget-lines")
def list_budget_lines(pid):
    authenticate()
    _get_proposal_or_404(pid)
    return _paginate(lines_of_proposal(pid), budget_line_out)


@bp.get("/pre-award/budget-lines/<lid>")
def get_budget_line(lid):
    authenticate()
    rec = store.budget_lines.get(lid)
    if rec is None:
        raise not_found("Budget line not found")
    return ok_object(budget_line_out(rec), 200)


@bp.get("/pre-award/budget-lines")
def list_all_budget_lines():
    authenticate()
    items = list(store.budget_lines.values())
    for key in ("proposal_id", "subrecipient_commitment_id", "category"):
        raw = request_arg(key)
        if raw is not None:
            items = [l for l in items if l[key] == raw]
    return _paginate(items, budget_line_out)


@bp.delete("/pre-award/budget-lines/<lid>")
def delete_budget_line(lid):
    require_roles(["PreAwardAnalyst"])
    rec = store.budget_lines.get(lid)
    if rec is None:
        raise not_found("Budget line not found")
    p = store.proposals.get(rec["proposal_id"])
    if p is None:
        raise not_found("Proposal not found")
    if p["status"] not in ("DRAFT", "BUDGET_LOCKED", "JIT_REQUESTED"):
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Budget lines may only change while the proposal is "
                       "DRAFT, BUDGET_LOCKED, or JIT_REQUESTED")
    del store.budget_lines[lid]
    _line_mutation_side_effects(p)
    return "", 204


# ---------------------------------------------------------------------------
# Budget finalization (snapshots)
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/budget-finalizations")
def finalize_budget(pid):
    require_roles(["PreAwardAnalyst"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    expected = as_int(req_field(body, "expected_proposal_version"),
                      "expected_proposal_version")
    if expected != p["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_proposal_version does not match the "
                       "proposal's current version")
    if p["status"] not in ("DRAFT", "BUDGET_LOCKED", "JIT_REQUESTED"):
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Budget finalization is allowed only from DRAFT, "
                       "BUDGET_LOCKED, or JIT_REQUESTED")
    non_cs_lines = [l for l in lines_of_proposal(pid) if not l["is_cost_share"]]
    if not non_cs_lines:
        raise ApiError(ERR_EMPTY_BUDGET, 422,
                       "At least one non-cost-share budget line is required")
    opp = store.funding_opportunities[p["opportunity_id"]]
    rate_type = ACTIVITY_TO_RATE_TYPE[p["activity_code"]]
    agreement, rate_source = select_rate_agreement(rate_type, p["_start"],
                                                   "PROVISIONAL_BASIS")
    if agreement is None:
        raise ApiError(ERR_NO_RATE, 422,
                       "No F&A rate agreement covers project_start_on")
    applied = applied_rate(agreement["rate_pct"], opp)
    per_line, total_direct, total_indirect, base_total = compute_indirect(
        p, applied)
    total_request = total_direct + total_indirect
    if opp["max_request_cents"] is not None and \
            total_request > opp["max_request_cents"]:
        raise ApiError(ERR_REQUEST_CAP, 422,
                       "total_request_cents exceeds the opportunity's "
                       "max_request_cents")

    _supersede_current_snapshot(p)
    snap = mint({
        "proposal_id": pid,
        "snapshot_index": len(snapshots_of_proposal(pid)) + 1,
        "fa_base_type": p["fa_base_type"],
        "rate_type": rate_type,
        "selected_rate_pct": agreement["rate_pct"],
        "applied_rate_pct": applied,
        "rate_source": rate_source,
        "mtdc_base_cents": base_total,
        "total_direct_cents": total_direct,
        "total_indirect_cents": total_indirect,
        "total_request_cents": total_request,
        "per_line_indirect": per_line,
        "status": "CURRENT",
    })
    store.budget_snapshots[snap["id"]] = snap

    p["current_snapshot_id"] = snap["id"]
    p["total_direct_cents"] = total_direct
    p["total_indirect_cents"] = total_indirect
    p["total_request_cents"] = total_request
    p["fa_rate_pct_applied"] = applied
    p["applied_rate_source"] = rate_source
    if p["status"] == "DRAFT":
        p["status"] = "BUDGET_LOCKED"
    recompute_cost_share(p)
    touch(p)
    return ok_object(snapshot_out(snap), 201)


@bp.get("/pre-award/proposals/<pid>/budget-snapshots")
def list_snapshots(pid):
    authenticate()
    _get_proposal_or_404(pid)
    return _paginate(snapshots_of_proposal(pid), snapshot_out)
