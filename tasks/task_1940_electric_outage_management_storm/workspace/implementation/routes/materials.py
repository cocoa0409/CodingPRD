"""MaterialStock and MaterialRequisition endpoints."""
from flask import Blueprint, request

from db import db, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_STATE_TRANSITION, ERR_DUPLICATE_STOCK,
    ERR_INSUFFICIENT_MATERIAL,
)
from services.core import (
    get_body, req_string, req_int, paginate, new_common, bump,
    get_stock, get_requisition, get_work_order, get_outage, get_event,
    serialize_stock, serialize_requisition, sort_created_asc,
    post_ledger_entry, check_event_not_closed, stock_reserved,
    CAPITAL_WORK_TYPES,
)

bp = Blueprint("materials", __name__)


# ---------------------------------------------------------------------------
# MaterialStock
# ---------------------------------------------------------------------------
@bp.route("/om/material-stocks", methods=["POST"])
def create_stock():
    require_roles(["MaterialsManager"])
    body = get_body()
    warehouse = req_string(body, "warehouse_code")
    sku = req_string(body, "material_sku")
    on_hand = req_int(body, "quantity_on_hand", minimum=0)
    unit_cost = req_int(body, "unit_cost_cents", minimum=0)
    for s in db.material_stocks.values():
        if s["warehouse_code"] == warehouse and s["material_sku"] == sku:
            raise_err(ERR_DUPLICATE_STOCK,
                      "(warehouse_code, material_sku) already exists")
    s = new_common()
    s.update({
        "warehouse_code": warehouse,
        "material_sku": sku,
        "quantity_on_hand": on_hand,
        "unit_cost_cents": unit_cost,
    })
    db.material_stocks[s["id"]] = s
    return success_object(serialize_stock(s), status=201)


@bp.route("/om/material-stocks/<sid>", methods=["GET"])
def get_one_stock(sid):
    require_roles(ALL_ROLES)
    s = get_stock(sid)
    return success_object(serialize_stock(s))


# ---------------------------------------------------------------------------
# MaterialRequisition
# ---------------------------------------------------------------------------
@bp.route("/om/material-requisitions", methods=["POST"])
def create_requisition():
    require_roles(["MaterialsManager"])
    body = get_body()
    wo_id = req_string(body, "work_order_id")
    stock_id = req_string(body, "material_stock_id")
    qty = req_int(body, "quantity", minimum=1)
    wo = get_work_order(wo_id)
    get_stock(stock_id)
    if wo["execution_status"] not in ("READY", "DISPATCHED", "IN_PROGRESS"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Requisition requires the work order READY, DISPATCHED, or IN_PROGRESS")
    outage = get_outage(wo["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)

    r = new_common()
    r.update({
        "work_order_id": wo_id,
        "material_stock_id": stock_id,
        "quantity": qty,
        "requisition_status": "REQUESTED",
        "_issue_entry_id": None,
    })
    db.material_requisitions[r["id"]] = r
    return success_object(serialize_requisition(r), status=201)


@bp.route("/om/material-requisitions/<rid>", methods=["GET"])
def get_one_requisition(rid):
    require_roles(ALL_ROLES)
    r = get_requisition(rid)
    return success_object(serialize_requisition(r))


@bp.route("/om/material-requisitions", methods=["GET"])
def list_requisitions():
    require_roles(ALL_ROLES)
    items = list(db.material_requisitions.values())
    for param in ("work_order_id", "material_stock_id", "requisition_status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_requisition(r) for r in page], limit, offset, total)


def _event_for_requisition(r):
    wo = db.work_orders.get(r["work_order_id"])
    outage = db.outages.get(wo["outage_id"]) if wo else None
    event = db.storm_events.get(outage["storm_event_id"]) if outage else None
    return wo, outage, event


@bp.route("/om/material-requisitions/<rid>/stage", methods=["POST"])
def stage(rid):
    require_roles(["MaterialsManager"])
    r = get_requisition(rid)
    if r["requisition_status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Requisition in {r['requisition_status']} cannot be staged")
    _, _, event = _event_for_requisition(r)
    if event is not None:
        check_event_not_closed(event)
    stock = get_stock(r["material_stock_id"])
    available = stock["quantity_on_hand"] - stock_reserved(stock["id"])
    if available < r["quantity"]:
        raise_err(ERR_INSUFFICIENT_MATERIAL, "Staged quantity exceeds available stock")
    r["requisition_status"] = "STAGED"
    bump(r)
    bump(stock)  # quantity_reserved derived from STAGED rows
    return success_object(serialize_requisition(r))


@bp.route("/om/material-requisitions/<rid>/issue", methods=["POST"])
def issue(rid):
    require_roles(["MaterialsManager"])
    r = get_requisition(rid)
    if r["requisition_status"] != "STAGED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Requisition in {r['requisition_status']} cannot be issued")
    wo, outage, event = _event_for_requisition(r)
    if event is not None:
        check_event_not_closed(event)
    stock = get_stock(r["material_stock_id"])
    r["requisition_status"] = "ISSUED"
    bump(r)
    stock["quantity_on_hand"] -= r["quantity"]
    bump(stock)
    # MATERIAL ledger entry: quantity * unit_cost; county from outage's feeder;
    # class per work_type.
    feeder = db.feeders.get(outage["feeder_id"]) if outage else None
    county = feeder["county_code"] if feeder else ""
    cost_class = "CAPITAL" if (wo and wo["work_type"] in CAPITAL_WORK_TYPES) else "O_AND_M"
    amount = r["quantity"] * stock["unit_cost_cents"]
    entry = post_ledger_entry(
        storm_event_id=outage["storm_event_id"] if outage else None,
        work_order_id=r["work_order_id"],
        entry_type="MATERIAL", cost_class=cost_class,
        county_code=county, amount_cents=amount,
    )
    r["_issue_entry_id"] = entry["id"]
    return success_object(serialize_requisition(r))


@bp.route("/om/material-requisitions/<rid>/return", methods=["POST"])
def return_material(rid):
    require_roles(["MaterialsManager"])
    r = get_requisition(rid)
    if r["requisition_status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Requisition in {r['requisition_status']} cannot be returned")
    wo, outage, event = _event_for_requisition(r)
    if event is not None:
        check_event_not_closed(event)
    stock = get_stock(r["material_stock_id"])
    r["requisition_status"] = "RETURNED"
    bump(r)
    stock["quantity_on_hand"] += r["quantity"]
    bump(stock)
    # Reversal entry: negation of the original issue amount.
    issue_entry = db.cost_ledger_entries.get(r.get("_issue_entry_id") or "")
    original_amount = issue_entry["amount_cents"] if issue_entry else r["quantity"] * stock["unit_cost_cents"]
    feeder = db.feeders.get(outage["feeder_id"]) if outage else None
    county = feeder["county_code"] if feeder else ""
    cost_class = "CAPITAL" if (wo and wo["work_type"] in CAPITAL_WORK_TYPES) else "O_AND_M"
    post_ledger_entry(
        storm_event_id=outage["storm_event_id"] if outage else None,
        work_order_id=r["work_order_id"],
        entry_type="MATERIAL", cost_class=cost_class,
        county_code=county, amount_cents=-original_amount,
        reversed_entry_id=issue_entry["id"] if issue_entry else None,
    )
    return success_object(serialize_requisition(r))


@bp.route("/om/material-requisitions/<rid>/consume", methods=["POST"])
def consume(rid):
    require_roles(["MaterialsManager"])
    r = get_requisition(rid)
    if r["requisition_status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Requisition in {r['requisition_status']} cannot be consumed")
    r["requisition_status"] = "CONSUMED"
    bump(r)
    return success_object(serialize_requisition(r))


@bp.route("/om/material-requisitions/<rid>/cancel", methods=["POST"])
def cancel(rid):
    require_roles(["MaterialsManager"])
    r = get_requisition(rid)
    if r["requisition_status"] not in ("REQUESTED", "STAGED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Requisition in {r['requisition_status']} cannot be cancelled")
    was_staged = r["requisition_status"] == "STAGED"
    r["requisition_status"] = "CANCELLED"
    bump(r)
    if was_staged:
        stock = db.material_stocks.get(r["material_stock_id"])
        if stock is not None:
            bump(stock)  # derived quantity_reserved releases automatically
    return success_object(serialize_requisition(r))
