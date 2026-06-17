"""Estimate authoring (forward-looking) and the revision loop."""
from flask import Blueprint, request

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles
from helpers import (base_record, get_body, require_int, get_work_order_or_404,
                     get_resource_or_404, parse_pagination, paginate, touch,
                     serialize, serialize_list)
from response import ok_object, ok_array
import calculations as calc
from services import (order_line_items, fabric_price_lookup, foam_price_lookup,
                      recompute_line_item_subtotal, reconcile_balance_due)

bp = Blueprint("estimates", __name__)


@bp.post("/work-orders/<wid>/estimates")
def author_estimate(wid):
    _, role = get_identity()
    require_roles(role, {"Estimator"})
    wo = get_work_order_or_404(wid)
    body = get_body()
    expected_version = require_int(body, "expected_work_order_version")
    supersedes_id = body.get("supersedes_estimate_id")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        raise err(errors.ERR_INVALID_REQUEST, "supersedes_estimate_id must be a string")

    # State (priority 20): must be ESTIMATING or REVISION_REQUESTED, >=1 line item.
    if wo["status"] not in ("ESTIMATING", "REVISION_REQUESTED"):
        raise err(errors.ERR_INVALID_STATE,
                  "Estimate authoring requires ESTIMATING or REVISION_REQUESTED")
    line_items = order_line_items(wid)
    if not line_items:
        raise err(errors.ERR_INVALID_STATE, "At least one line item is required")

    # OCC (priority 21).
    if expected_version != wo["version"]:
        raise err(errors.ERR_STALE_WORK_ORDER_VERSION,
                  "expected_work_order_version does not match")

    # supersedes_estimate_id semantics: null on first; else must name current ACTIVE.
    active = _active_estimate(wid)
    if active is None:
        if supersedes_id is not None:
            raise err(errors.ERR_INVALID_REQUEST,
                      "supersedes_estimate_id must be null for the first estimate")
    else:
        if supersedes_id != active["id"]:
            raise err(errors.ERR_INVALID_REQUEST,
                      "supersedes_estimate_id must name the current ACTIVE estimate")

    # Recompute subtotals at authoring time (catalog prices).
    service_type = wo["service_type"]
    for li in line_items:
        recompute_line_item_subtotal(li, service_type)
        touch(li)

    labor_total, materials_total, rush_surcharge, total = calc.estimate_totals(
        line_items=line_items,
        service_type=service_type,
        rush_requested=wo["rush_requested"],
        fabric_price_lookup=fabric_price_lookup,
        foam_price_lookup=foam_price_lookup,
    )

    # Supersede prior ACTIVE.
    if active is not None:
        active["status"] = "SUPERSEDED"
        touch(active)

    prior_max = max(
        (e["version_no"] for e in db.estimates.values() if e["work_order_id"] == wid),
        default=0,
    )
    rec = base_record(common=True)
    rec.update({
        "work_order_id": wid,
        "supersedes_estimate_id": supersedes_id,
        "version_no": prior_max + 1,
        "labor_total_cents": labor_total,
        "materials_total_cents": materials_total,
        "rush_surcharge_cents": rush_surcharge,
        "total_cents": total,
        "status": "ACTIVE",
    })
    db.estimates[rec["id"]] = rec

    # Reconcile work order.
    wo["active_estimate_id"] = rec["id"]
    wo["estimate_total_cents"] = total
    reconcile_balance_due(wo)
    wo["status"] = "AWAITING_APPROVAL"
    touch(wo)  # increments WorkOrder.version by 1

    return ok_object(serialize(rec), 201)


def _active_estimate(wid):
    for e in db.estimates.values():
        if e["work_order_id"] == wid and e["status"] == "ACTIVE":
            return e
    return None


@bp.get("/estimates/<eid>")
def get_estimate(eid):
    _, role = get_identity()
    require_roles(role, {"Estimator", "ShopManager", "Customer", "IntakeClerk"})
    rec = get_resource_or_404(db.estimates, eid)
    return ok_object(serialize(rec), 200)


@bp.get("/work-orders/<wid>/estimates")
def list_work_order_estimates(wid):
    _, role = get_identity()
    require_roles(role, {"Estimator", "ShopManager", "Customer", "IntakeClerk"})
    limit, offset = parse_pagination()
    get_work_order_or_404(wid)
    matches = [e for e in db.estimates.values() if e["work_order_id"] == wid]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/estimates")
def list_estimates():
    _, role = get_identity()
    require_roles(role, {"Estimator", "ShopManager"})
    limit, offset = parse_pagination()
    supersedes_id = request.args.get("supersedes_estimate_id")
    work_order_id = request.args.get("work_order_id")
    matches = list(db.estimates.values())
    if supersedes_id is not None:
        matches = [e for e in matches if e.get("supersedes_estimate_id") == supersedes_id]
    if work_order_id is not None:
        matches = [e for e in matches if e["work_order_id"] == work_order_id]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
