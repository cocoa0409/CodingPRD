"""Global milestone reads and FK reverse-reachability lists (PRD 4)."""
from flask import Blueprint

import db
from middleware import require_auth, require_role
from response import success
from services import common, derive

bp = Blueprint("milestones", __name__)


@bp.get("/milestones/<mid>")
def get_milestone(mid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    m = common.get_milestone(mid)
    return success(derive.milestone_view(m))


@bp.get("/milestones/<mid>/payouts")
def milestone_payouts(mid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer", "Client"])
    common.get_milestone(mid)
    items = [p for p in db.payouts.values() if p["milestone_id"] == mid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.payout_view(p) for p in page], pagination=meta)


@bp.get("/milestones/<mid>/escrow-transactions")
def milestone_escrow(mid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_milestone(mid)
    items = [e for e in db.escrow_transactions.values() if e["milestone_id"] == mid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.escrow_view(e) for e in page], pagination=meta)


@bp.get("/milestones/<mid>/timelogs")
def milestone_timelogs(mid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_milestone(mid)
    items = [t for t in db.timelogs.values() if t["milestone_id"] == mid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.timelog_view(t) for t in page], pagination=meta)


@bp.get("/milestones/<mid>/disputes")
def milestone_disputes(mid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer", "Arbitrator"])
    common.get_milestone(mid)
    items = [d for d in db.disputes.values() if d["milestone_id"] == mid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.dispute_view(d) for d in page], pagination=meta)
