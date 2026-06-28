"""Follow-up plans and weighted feeds (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_CONSULT_NOT_COMPLETED,
    ERR_PLAN_NOT_OPEN,
    ERR_PLAN_CLOSED,
)
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_full, init_lightweight, touch, serialize, get_body,
    require_str, require_int, paginate,
)
from services.lookups import get_or_404, get_fk_or_404
from services.calculations import weighted_feed_rollup

bp = Blueprint("follow_up_plans", __name__)

READ_ROLES = {"PracticeAdmin", "BillingSpecialist", "Consultant", "FrontDesk", "Client"}


def _recompute_plan(plan):
    """Recompute total/avg/meets_target over all feeds of the plan (PRD §3.8)."""
    feeds = [f for f in db.weighted_feeds.values()
             if f["follow_up_plan_id"] == plan["id"]]
    total, avg, meets = weighted_feed_rollup(feeds, plan["target_daily_transfer_grams"])
    plan["total_transfer_grams"] = total
    plan["avg_transfer_grams"] = avg
    plan["meets_target"] = meets


# ---------------------------------------------------------------------------
# Follow-up plans
# ---------------------------------------------------------------------------
@bp.post("/follow-up-plans")
def create_plan():
    # PRD §3.8 / §4: Consultant only.
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    body = get_body()
    consult_id = require_str(body, "consult_id")
    # FK existence.
    consult = get_fk_or_404(db.consults, consult_id)
    # Well-formedness: target > 0 (PRD §3.8).
    target = require_int(body, "target_daily_transfer_grams", min_value=1)
    # Parent consult must be COMPLETED (PRD §3.8).
    if consult["status"] != "COMPLETED":
        raise err(ERR_CONSULT_NOT_COMPLETED, "Parent consult is not COMPLETED")

    record = {
        "consult_id": consult_id,
        "client_id": consult["client_id"],  # copied from parent consult
        "target_daily_transfer_grams": target,
        "avg_transfer_grams": 0,
        "total_transfer_grams": 0,
        "meets_target": False,
        "status": "OPEN",
    }
    init_full(record)
    db.follow_up_plans[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/follow-up-plans/<rid>")
def get_plan(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.follow_up_plans, rid)
    return object_response(serialize(record), 200)


@bp.get("/follow-up-plans")
def list_plans():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    consult_id = request.args.get("consult_id")
    client_id = request.args.get("client_id")
    records = []
    for r in db.follow_up_plans.values():
        if consult_id is not None and r["consult_id"] != consult_id:
            continue
        if client_id is not None and r["client_id"] != client_id:
            continue
        records.append(r)
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.post("/follow-up-plans/<rid>/close")
def close_plan(rid):
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    plan = get_or_404(db.follow_up_plans, rid)
    # Must be OPEN (PRD §3.8).
    if plan["status"] != "OPEN":
        raise err(ERR_PLAN_NOT_OPEN, "Follow-up plan is not OPEN")
    plan["status"] = "CLOSED"
    touch(plan)
    return object_response(serialize(plan), 200)


# ---------------------------------------------------------------------------
# Weighted feeds
# ---------------------------------------------------------------------------
@bp.post("/weighted-feeds")
def create_weighted_feed():
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    body = get_body()
    plan_id = require_str(body, "follow_up_plan_id")
    # FK existence.
    plan = get_fk_or_404(db.follow_up_plans, plan_id)
    # Well-formedness: pre > 0, post >= pre (PRD §3.8).
    pre = require_int(body, "pre_feed_weight_grams", min_value=1)
    post = require_int(body, "post_feed_weight_grams")
    if post < pre:
        raise err(ERR_INVALID_REQUEST,
                  "post_feed_weight_grams must be >= pre_feed_weight_grams")
    # Plan must be OPEN (PRD §3.8).
    if plan["status"] != "OPEN":
        raise err(ERR_PLAN_CLOSED, "Follow-up plan is CLOSED")

    record = {
        "follow_up_plan_id": plan_id,
        "pre_feed_weight_grams": pre,
        "post_feed_weight_grams": post,
        # transfer_grams = post - pre (PRD §3.8).
        "transfer_grams": post - pre,
    }
    init_lightweight(record)
    db.weighted_feeds[record["id"]] = record

    # Recompute parent plan rollups; this mutates the plan -> version bump.
    _recompute_plan(plan)
    touch(plan)
    return object_response(serialize(record), 201)


@bp.get("/weighted-feeds/<rid>")
def get_weighted_feed(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.weighted_feeds, rid)
    return object_response(serialize(record), 200)


@bp.get("/weighted-feeds")
def list_weighted_feeds():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    plan_id = request.args.get("follow_up_plan_id")
    records = [
        r for r in db.weighted_feeds.values()
        if plan_id is None or r["follow_up_plan_id"] == plan_id
    ]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)
