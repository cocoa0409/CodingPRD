"""Candidate scope: proposal, scoring, ranking and decisions (PRD 3.2, 3.3)."""
from flask import Blueprint, request

import core
import serialize
from auth import authorize
from core import new_record, recompute_coverage, recompute_ranks, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_asset, get_scope_item, get_test_plan, paginate
from store import store
from validate import body, get_enum, get_int, get_number, get_str

bp = Blueprint("scope", __name__)

DECISIONS = ("APPROVE", "DEFER", "WITHDRAW")
READ_ROLES = ("ProgramManager", "ComplianceOfficer", "PlatformAdmin")
OCCUPYING_STATUSES = ("PROPOSED", "APPROVED")


@bp.post("/scope-items")
def propose_candidate():
    authorize("ProgramManager")
    data = body()
    plan_id = get_str(data, "test_plan_id")
    asset_id = get_str(data, "asset_id")
    justification = get_str(data, "justification", min_len=1, max_len=500)
    hours = get_number(
        data, "requested_engagement_hours", minimum=0, exclusive_min=True, maximum=400
    )
    expected_version = get_int(data, "expected_test_plan_version")
    plan = get_test_plan(plan_id)
    asset = get_asset(asset_id)
    if expected_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT")
    for existing in core.plan_scope_items(plan["id"]):
        if existing["asset_id"] == asset["id"] and existing["status"] in OCCUPYING_STATUSES:
            raise ApiError("ERR_DUPLICATE_SCOPE_ITEM")
    record = new_record(
        test_plan_id=plan["id"],
        asset_id=asset["id"],
        justification=justification,
        requested_engagement_hours=hours,
        priority_score=None,
        priority_rank=None,
        below_threshold_flag=False,
        status="PROPOSED",
        decision_note=None,
        scored_mode=None,
    )
    core.score_scope_item(record, plan)
    store.scope_items[record["id"]] = record
    recompute_ranks(plan["id"])
    touch(plan)
    return object_response(serialize.scope_item(record), 201)


@bp.get("/scope-items/<item_id>")
def read_candidate(item_id):
    authorize(*READ_ROLES)
    return object_response(serialize.scope_item(get_scope_item(item_id)))


@bp.get("/scope-items")
def list_candidates():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.scope_items.values()),
        test_plan_id=request.args.get("test_plan_id"),
        asset_id=request.args.get("asset_id"),
        status=request.args.get("status"),
    )
    return paginate(rows, serialize.scope_item)


@bp.post("/scope-items/<item_id>/decision")
def decide_candidate(item_id):
    authorize("ProgramManager", "ComplianceOfficer")
    item = get_scope_item(item_id)
    data = body()
    decision = get_enum(data, "decision", DECISIONS)
    note = get_str(data, "note", required=False)
    override_note = get_str(data, "override_note", required=False)
    plan = store.test_plans.get(item["test_plan_id"])
    if plan is None or plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT")
    if item["status"] not in ("PROPOSED", "DEFERRED"):
        raise ApiError("ERR_SCOPE_ITEM_NOT_PENDING")
    if decision == "APPROVE":
        if item["below_threshold_flag"]:
            if override_note is None or not override_note.strip():
                raise ApiError("ERR_BELOW_RISK_THRESHOLD")
        item["status"] = "APPROVED"
    elif decision == "DEFER":
        item["status"] = "DEFERRED"
        item["priority_rank"] = None
    else:
        item["status"] = "WITHDRAWN"
        item["priority_rank"] = None
    item["decision_note"] = override_note if override_note is not None else note
    touch(item)
    recompute_ranks(plan["id"])
    recompute_coverage(plan)
    touch(plan)
    return object_response(serialize.scope_item(item))
