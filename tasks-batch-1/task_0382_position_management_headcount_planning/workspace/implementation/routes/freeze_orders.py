"""FreezeOrder endpoints: create (nested under cost center), lift, get, list
(PRD §3.5)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize, calc
from services.common import (
    get_body, require_string, fetch, paginate, base_common_fields, bump,
)
from services.cascade import reconcile_posture
from util import parse_datetime

bp = Blueprint("freeze_orders", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


@bp.post("/cost-centers/<cost_center_id>/freeze-orders")
def create_freeze_order(cost_center_id):
    require_auth(["FinanceController"])
    cc = fetch(db.cost_centers, cost_center_id)
    body = get_body()
    reason = require_string(body, "reason")
    from_raw = body.get("effective_from")
    to_raw = body.get("effective_to")
    if from_raw is None or to_raw is None:
        raise err("ERR_INVALID_REQUEST", "effective_from and effective_to are required")
    from_dt = parse_datetime(from_raw)
    to_dt = parse_datetime(to_raw)
    if from_dt is None or to_dt is None:
        raise err("ERR_INVALID_REQUEST", "effective_from/effective_to are malformed")

    # Window well-formed: from strictly before to (priority 11).
    if not (from_dt < to_dt):
        raise err("ERR_FREEZE_WINDOW_OVERLAP", "effective_from must be before effective_to")

    # Must not overlap another ACTIVE freeze order on the same cost center;
    # half-open [from, to), touching boundaries allowed (priority 11).
    for f in db.freeze_orders.values():
        if f["cost_center_id"] != cost_center_id or f["status"] != "ACTIVE":
            continue
        if from_dt < f["_to_dt"] and f["_from_dt"] < to_dt:
            raise err("ERR_FREEZE_WINDOW_OVERLAP", "window overlaps another ACTIVE freeze order")

    prev_posture = calc.cost_center_posture(cost_center_id)

    rec = base_common_fields()
    rec.update({
        "cost_center_id": cost_center_id,
        "effective_from": from_raw,
        "effective_to": to_raw,
        "_from_dt": from_dt,
        "_to_dt": to_dt,
        "reason": reason,
        "status": "ACTIVE",
    })
    db.freeze_orders[rec["id"]] = rec

    # Recompute posture and cascade if it just flipped to FROZEN (PRD §3.5).
    reconcile_posture(cost_center_id, prev_posture)
    return success(serialize.freeze_order_out(rec), status=201)


@bp.get("/cost-centers/<cost_center_id>/freeze-orders")
def list_cc_freeze_orders(cost_center_id):
    require_auth(ALL_ROLES)
    fetch(db.cost_centers, cost_center_id)
    records = [f for f in db.freeze_orders.values() if f["cost_center_id"] == cost_center_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.freeze_order_out(r) for r in page], limit, offset, total)


@bp.get("/freeze-orders/<freeze_order_id>")
def get_freeze_order(freeze_order_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.freeze_orders, freeze_order_id)
    return success(serialize.freeze_order_out(rec))


@bp.get("/freeze-orders")
def list_freeze_orders():
    require_auth(ALL_ROLES)
    records = list(db.freeze_orders.values())
    for field in ("cost_center_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.freeze_order_out(r) for r in page], limit, offset, total)


@bp.post("/freeze-orders/<freeze_order_id>/lift")
def lift_freeze_order(freeze_order_id):
    require_auth(["FinanceController"])
    f = fetch(db.freeze_orders, freeze_order_id)
    # State (priority 6).
    if f["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "freeze order must be ACTIVE to lift")

    cc_id = f["cost_center_id"]
    prev_posture = calc.cost_center_posture(cc_id)
    f["status"] = "LIFTED"
    bump(f)
    # Recompute posture; if it flips to OPEN, un-freeze cascade fires (PRD §3.5).
    reconcile_posture(cc_id, prev_posture)
    return success(serialize.freeze_order_out(f))
