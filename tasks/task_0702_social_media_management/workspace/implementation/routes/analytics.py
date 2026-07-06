"""Analytics snapshot routes (PRD §3.7)."""
from flask import Blueprint, request

import db
import response
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_nonneg_int,
)
from services import lookup, listing, calc
from services.budget import count_posts_published_this_cycle
from services.serialize import snapshot_out

bp = Blueprint("analytics", __name__)


@bp.post("/clients/<client_id>/analytics-snapshots")
def create_snapshot(client_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin"})
    body = get_json_body()
    with db.LOCK:
        client = lookup.get_client(client_id)
        total_impressions = require_nonneg_int(body, "total_impressions")
        total_engagements = require_nonneg_int(body, "total_engagements")
        cycle_index = client["current_cycle_index"]
        posts_published = count_posts_published_this_cycle(client)
        boost_spent = sum(
            b["spent_budget_cents"]
            for b in db.boost_campaigns.values()
            if b["client_id"] == client_id and b["status"] in ("RUNNING", "COMPLETED")
        )
        bps = calc.engagement_rate_bps(total_engagements, total_impressions)
        s = {
            "id": db.new_id(),
            "client_id": client_id,
            "cycle_index": cycle_index,
            "posts_published": posts_published,
            "boost_spent_cents": boost_spent,
            "engagement_rate_bps": bps,
            "total_impressions": total_impressions,
            "total_engagements": total_engagements,
        }
        db.stamp_create(s, full=False)
        db.analytics_snapshots[s["id"]] = s
        return response.created(snapshot_out(s))


@bp.get("/analytics-snapshots")
def list_snapshots():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    limit, offset = get_pagination()
    cycle_filter = request.args.get("cycle_index")
    cycle_val = None
    if cycle_filter is not None:
        try:
            cycle_val = int(cycle_filter)
        except (TypeError, ValueError):
            cycle_val = None
    with db.LOCK:
        rows = listing.apply_filters(list(db.analytics_snapshots.values()), {
            "client_id": request.args.get("client_id"),
            "cycle_index": cycle_val,
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([snapshot_out(s) for s in window], limit, offset, total)


@bp.get("/analytics-snapshots/<snapshot_id>")
def get_snapshot(snapshot_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    with db.LOCK:
        s = lookup.get_snapshot(snapshot_id)
        return response.ok(snapshot_out(s))
