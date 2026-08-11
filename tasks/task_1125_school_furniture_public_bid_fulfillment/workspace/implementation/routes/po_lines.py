"""POLine endpoints: creation with tiered/flat pricing gates, get/list,
declare-backorder (cascade head), cancel (drawdown compensation),
backorder-notice supersede-create (OCC-guarded)."""
from flask import Blueprint, request

from db import clock_date, new_record, now_ts, public, store, touch
from errors import (
    ERR_AWARD_QTY_EXCEEDED,
    ERR_ETA_NOT_FORWARD,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ORDER_WINDOW_CLOSED,
    ERR_SPEC_VERSION_STALE,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import ALL_ROLES, authenticate, require_roles, scope_district
from response import success
from services.cascade import (
    award_of_po,
    district_id_of_line,
    open_notice_of_line,
    po_of_line,
    recompute_po,
    recompute_spec_line,
    resolve_open_notice,
    spec_of_line,
)
from services.pricing import coop_tiered_price
from validation import (
    body,
    get_or_404,
    opt_str,
    paginate,
    parse_pagination,
    pdate,
    req_date,
    req_int,
    req_str,
)

bp = Blueprint("po_lines", __name__)


@bp.route("/v1/po-lines", methods=["POST"])
def create_po_line():
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    data = body()

    purchase_order_id = data.get("purchase_order_id")
    spec_line_id = data.get("spec_line_id")

    po = store.purchase_orders.get(purchase_order_id) if isinstance(purchase_order_id, str) else None
    # priority 3: ownership scope via the PO's district chain
    if po is not None:
        award = award_of_po(po)
        scope_district(caller, award["district_id"] if award else None)

    # priority 4: body FK existence in canonical order (purchase_order_id -> spec_line_id)
    if isinstance(purchase_order_id, str):
        get_or_404(store.purchase_orders, purchase_order_id, "purchase order")
    spec_line = None
    if isinstance(spec_line_id, str):
        spec_line = get_or_404(store.spec_lines, spec_line_id, "spec line")

    # priority 5: shape (client-supplied computed fields are ignored)
    purchase_order_id = req_str(data, "purchase_order_id")
    spec_line_id = req_str(data, "spec_line_id")
    ordered_qty = req_int(data, "ordered_qty", minimum=1)

    award = award_of_po(po)
    spec = store.bid_specs.get(spec_line["bid_spec_id"])

    # priority 6: lines are added only while the PO is RECEIVED
    if po["status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE, f"Cannot add lines to a purchase order in status {po['status']}")

    # priority 8: creation date must fall on or before award.order_by_date
    if clock_date() > pdate(award["order_by_date"]):
        raise_err(ERR_ORDER_WINDOW_CLOSED, "POLine creation is after the award's order_by_date")

    # priority 9: specification version pin
    if spec["spec_version"] != award["awarded_spec_version"]:
        raise_err(ERR_SPEC_VERSION_STALE, "The spec has advanced beyond the award's pinned spec version")

    # priority 13: spec-line drawdown
    if ordered_qty > spec_line["remaining_qty"]:
        raise_err(ERR_AWARD_QTY_EXCEEDED, "ordered_qty exceeds the spec line's remaining_qty")

    # pricing per variant, then the max-unit-price ceiling (ERR_INVALID_REQUEST)
    unit_price, line_total = coop_tiered_price(award, po, spec_line, ordered_qty)
    if unit_price > spec_line["max_unit_price_cents"]:
        raise_err(ERR_INVALID_REQUEST, "Computed unit price breaches the spec line's max_unit_price_cents ceiling")

    rec = new_record({
        "purchase_order_id": purchase_order_id,
        "spec_line_id": spec_line_id,
        "coop_agreement_id": award.get("coop_agreement_id"),
        "ordered_qty": ordered_qty,
        "computed_unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "delivered_qty": 0,
        "installed_at": None,
        "status": "PENDING",
        "_installed_qty": None,
    })
    store.po_lines[rec["id"]] = rec

    recompute_spec_line(spec_line)  # drawdown: remaining_qty -= ordered_qty
    recompute_po(po)  # total_cents recompute
    return success(public(rec), code=201)


@bp.route("/v1/po-lines/<rid>", methods=["GET"])
def get_po_line(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.po_lines, rid, "PO line")
    return success(public(rec), code=200)


@bp.route("/v1/po-lines", methods=["GET"])
def list_po_lines():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.po_lines.values())
    purchase_order_id = request.args.get("purchase_order_id")
    spec_line_id = request.args.get("spec_line_id")
    coop_agreement_id = request.args.get("coop_agreement_id")
    status = request.args.get("status")
    if purchase_order_id is not None:
        records = [r for r in records if r["purchase_order_id"] == purchase_order_id]
    if spec_line_id is not None:
        records = [r for r in records if r["spec_line_id"] == spec_line_id]
    if coop_agreement_id is not None:
        records = [r for r in records if r.get("coop_agreement_id") == coop_agreement_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


@bp.route("/v1/po-lines/<rid>/declare-backorder", methods=["POST"])
def declare_backorder(rid):
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    line = get_or_404(store.po_lines, rid, "PO line")
    data = body()
    initial_eta = req_date(data, "initial_eta_date")

    # priority 6: line must be ORDERED or PARTIALLY_DELIVERED with an undelivered remainder
    if line["status"] not in ("ORDERED", "PARTIALLY_DELIVERED"):
        raise_err(ERR_INVALID_STATE, f"Cannot declare a backorder on a line in status {line['status']}")
    if line["ordered_qty"] - line["delivered_qty"] <= 0:
        raise_err(ERR_INVALID_STATE, "No undelivered remainder exists on this line")

    # priority 8: the ETA must move strictly forward of the clock's current date
    if pdate(initial_eta) <= clock_date():
        raise_err(ERR_ETA_NOT_FORWARD, "initial_eta_date must be strictly later than the current clock date")

    # cascade link 1: the line itself
    line["status"] = "BACKORDERED"
    touch(line)

    # cascade link 2: the district backorder notice
    notice = new_record({
        "po_line_id": line["id"],
        "status": "OPEN",
        "current_eta_date": initial_eta,
        "revision_count": 0,
        "communicated_at": now_ts(),
    })
    store.backorder_notices[notice["id"]] = notice

    # cascade link 3: PO open_backorder_count + posture recompute
    po = po_of_line(line)
    if po is not None:
        recompute_po(po)
    return success(public(line), code=200)


@bp.route("/v1/po-lines/<rid>/cancel", methods=["POST"])
def cancel_po_line(rid):
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    line = store.po_lines.get(rid)
    if line is not None:
        scope_district(caller, district_id_of_line(line))  # priority 3
    line = get_or_404(store.po_lines, rid, "PO line")  # priority 4
    body()

    if line["status"] == "PENDING":
        pass
    elif line["status"] in ("ORDERED", "BACKORDERED") and line["delivered_qty"] == 0:
        pass
    else:
        raise_err(ERR_INVALID_STATE, f"Cannot cancel a line in status {line['status']} with delivered_qty {line['delivered_qty']}")

    was_backordered = line["status"] == "BACKORDERED"
    line["status"] = "CANCELLED"
    touch(line)

    sl = store.spec_lines.get(line["spec_line_id"])
    if sl is not None:
        recompute_spec_line(sl)  # compensating release of the drawdown
    if was_backordered:
        resolve_open_notice(line)  # notice RESOLVED; count/posture recomputed
    po = po_of_line(line)
    if po is not None:
        recompute_po(po)  # total_cents recompute
    return success(public(line), code=200)


@bp.route("/v1/po-lines/<rid>/backorder-notices", methods=["POST"])
def supersede_backorder_notice(rid):
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    line = get_or_404(store.po_lines, rid, "PO line")
    data = body()
    initial_eta = req_date(data, "initial_eta_date")
    expected = req_int(data, "expected_po_line_version")
    opt_str(data, "note", default=None)

    # priority 6: terminal lockdown, and a current open notice must exist to supersede
    if line["status"] in ("CANCELLED", "VERIFIED"):
        raise_err(ERR_INVALID_STATE, f"Cannot create a backorder notice for a line in status {line['status']}")
    prior = open_notice_of_line(line["id"])
    if prior is None:
        raise_err(ERR_INVALID_STATE, "The line has no open backorder notice to supersede")

    # priority 8: the revised ETA must move strictly forward of the clock date
    if pdate(initial_eta) <= clock_date():
        raise_err(ERR_ETA_NOT_FORWARD, "initial_eta_date must be strictly later than the current clock date")

    # priority 17: optimistic concurrency, deliberately last
    if expected != line["version"]:
        raise_err(ERR_STALE_VERSION, "expected_po_line_version does not match the line's current version")

    prior["status"] = "SUPERSEDED"
    touch(prior)

    notice = new_record({
        "po_line_id": line["id"],
        "status": "OPEN",
        "current_eta_date": initial_eta,
        "revision_count": 0,
        "communicated_at": now_ts(),
    })
    store.backorder_notices[notice["id"]] = notice
    touch(line)  # increments POLine.version by 1
    return success(public(notice), code=201)
