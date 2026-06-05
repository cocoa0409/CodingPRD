"""LiquidationEvent + WaterfallDistribution routes. PRD §3.12."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_int,
    require_string, stamp_common_fields, stamp_immutable, touch,
)
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles
from response import created, success, list_response
from services import core
from services.calc import compute_waterfall

bp = Blueprint("liquidation", __name__)


@bp.post("/liquidation-events")
@require_roles("Administrator")
def create_event():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)
    total_proceeds_cents = require_int(body, "total_proceeds_cents", min_value=0)
    now = db.now_utc()
    ev = {
        "cap_table_id": cap_table_id,
        "total_proceeds_cents": total_proceeds_cents,
        "status": "DRAFT",
    }
    stamp_common_fields(ev, now)
    db.liquidation_events[ev["id"]] = ev
    return created(core.serialize(ev))


@bp.get("/liquidation-events/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor")
def get_event(cid):
    return success(core.serialize(core.get_liquidation_event(cid)))


@bp.get("/liquidation-events")
@require_roles("Administrator", "BoardApprover", "Auditor")
def list_events():
    limit, offset = pagination_params()
    items = list(db.liquidation_events.values())
    cap_table_id = request.args.get("cap_table_id")
    if cap_table_id is not None:
        items = [e for e in items if e["cap_table_id"] == cap_table_id]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(e) for e in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/liquidation-events/<cid>/compute")
@require_roles("BoardApprover")
def compute_event(cid):
    ev = core.get_liquidation_event(cid)
    if ev["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Event must be DRAFT to compute.", 409)
    classes = core.classes_of(ev["cap_table_id"])
    if not classes:
        raise APIError(ERR_INVALID_STATE, "Cap table has no security classes.", 409)

    now = db.now_utc()
    rows = compute_waterfall(ev, classes, now)
    for row in rows:
        dist = {
            "cap_table_id": ev["cap_table_id"],
            "liquidation_event_id": ev["id"],
            "security_class_id": row["security_class_id"],
            "preference_paid_cents": row["preference_paid_cents"],
            "participation_paid_cents": row["participation_paid_cents"],
            "total_paid_cents": row["total_paid_cents"],
        }
        stamp_immutable(dist, now)
        db.waterfall_distributions[dist["id"]] = dist

    ev["status"] = "COMPUTED"
    touch(ev, now)
    return success(core.serialize(ev))


@bp.post("/liquidation-events/<cid>/recompute")
@require_roles("BoardApprover")
def recompute_event(cid):
    ev = core.get_liquidation_event(cid)
    if ev["status"] != "COMPUTED":
        raise APIError(ERR_INVALID_STATE, "Event must be COMPUTED to recompute.", 409)
    now = db.now_utc()
    to_delete = [d["id"] for d in db.waterfall_distributions.values() if d["liquidation_event_id"] == ev["id"]]
    for did in to_delete:
        db.waterfall_distributions.pop(did, None)
    ev["status"] = "DRAFT"
    touch(ev, now)
    return success(core.serialize(ev))


@bp.post("/liquidation-events/<cid>/finalize")
@require_roles("BoardApprover")
def finalize_event(cid):
    ev = core.get_liquidation_event(cid)
    if ev["status"] != "COMPUTED":
        raise APIError(ERR_INVALID_STATE, "Event must be COMPUTED to finalize.", 409)
    now = db.now_utc()
    ev["status"] = "FINALIZED"
    touch(ev, now)
    return success(core.serialize(ev))


@bp.get("/liquidation-events/<cid>/distributions")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def list_event_distributions(cid):
    ev = core.get_liquidation_event(cid)
    limit, offset = pagination_params()
    items = [d for d in db.waterfall_distributions.values() if d["liquidation_event_id"] == ev["id"]]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(d) for d in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.get("/waterfall-distributions/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_distribution(cid):
    return success(core.serialize(core.get_waterfall_distribution(cid)))


@bp.get("/waterfall-distributions")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def list_distributions():
    limit, offset = pagination_params()
    items = list(db.waterfall_distributions.values())
    for key in ("cap_table_id", "liquidation_event_id", "security_class_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )
