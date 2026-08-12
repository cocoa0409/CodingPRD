"""Shipment endpoints: scheduling (delivery window + posture gate), get/list,
mark-delivered (no-substitution, quantity discipline, line state machine,
notice resolution, replacement report resolution)."""
from flask import Blueprint, request

from db import new_record, public, store, touch
from errors import (
    ERR_DELIVERY_EXCEEDS_ORDERED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_OUTSIDE_DELIVERY_WINDOW,
    ERR_PO_AT_RISK_BLOCKS_SCHEDULING,
    ERR_SUBSTITUTION_NOT_ALLOWED,
    raise_err,
)
from middleware import ALL_ROLES, authenticate, require_roles
from response import success
from services.cascade import award_of_po, open_notice_of_line, po_of_line, recompute_po
from validation import (
    body,
    get_or_404,
    opt_enum,
    paginate,
    parse_pagination,
    pdate,
    req_date,
    req_list,
    req_str,
)

bp = Blueprint("shipments", __name__)

SHIPPABLE_LINE_STATES = ("ORDERED", "PARTIALLY_DELIVERED", "BACKORDERED")


def _validate_shipment_lines(data):
    """Shape-check the lines array; returns a list of {po_line_id, qty} entries."""
    lines = req_list(data, "lines")
    if len(lines) == 0:
        raise_err(ERR_INVALID_REQUEST, "Field 'lines' must contain at least one entry")
    entries = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "Each lines entry must be an object")
        po_line_id = entry.get("po_line_id")
        if not isinstance(po_line_id, str):
            raise_err(ERR_INVALID_REQUEST, "Each lines entry requires a string po_line_id")
        qty = entry.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_err(ERR_INVALID_REQUEST, "Each lines entry requires integer qty >= 1")
        entries.append({"po_line_id": po_line_id, "qty": qty})
    return entries


def _maybe_advance_po(po):
    """First shipment on an ACCEPTED PO moves it to IN_FULFILLMENT."""
    if po is not None and po["status"] == "ACCEPTED":
        po["status"] = "IN_FULFILLMENT"
        touch(po)


@bp.route("/v1/shipments", methods=["POST"])
def create_shipment():
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    data = body()

    purchase_order_id = data.get("purchase_order_id")
    school_site_id = data.get("school_site_id")

    # priority 4: body FK existence in canonical order
    po = None
    if isinstance(purchase_order_id, str):
        po = get_or_404(store.purchase_orders, purchase_order_id, "purchase order")
    site = None
    if isinstance(school_site_id, str):
        site = get_or_404(store.school_sites, school_site_id, "school site")
    raw_lines = data.get("lines")
    if isinstance(raw_lines, list):
        for entry in raw_lines:
            if isinstance(entry, dict) and isinstance(entry.get("po_line_id"), str):
                get_or_404(store.po_lines, entry["po_line_id"], "PO line")

    # priority 5: shape
    purchase_order_id = req_str(data, "purchase_order_id")
    school_site_id = req_str(data, "school_site_id")
    scheduled_date = req_date(data, "scheduled_date")
    entries = _validate_shipment_lines(data)
    kind = opt_enum(data, "kind", ("STANDARD", "REPLACEMENT"), default="STANDARD")
    # each referenced line must belong to this PO
    for entry in entries:
        line = store.po_lines[entry["po_line_id"]]
        if line["purchase_order_id"] != purchase_order_id:
            raise_err(ERR_INVALID_REQUEST, "Each shipment line must belong to the referenced purchase order")

    # priority 6: every referenced line must be shippable
    for entry in entries:
        line = store.po_lines[entry["po_line_id"]]
        if line["status"] not in SHIPPABLE_LINE_STATES:
            raise_err(ERR_INVALID_STATE, f"PO line {line['id']} in status {line['status']} cannot be shipped")

    # priority 8: scheduled date must lie within the bid spec's delivery window (inclusive)
    award = award_of_po(po)
    spec = store.bid_specs.get(award["bid_spec_id"])
    sd = pdate(scheduled_date)
    if sd < pdate(spec["delivery_window_start"]) or sd > pdate(spec["delivery_window_end"]):
        raise_err(ERR_OUTSIDE_DELIVERY_WINDOW, "scheduled_date is outside the delivery window")

    # priority 16: backorder posture gate (remediation shipments are exempt)
    if po["posture"] == "AT_RISK" and kind != "REPLACEMENT":
        has_backordered = any(
            store.po_lines[e["po_line_id"]]["status"] == "BACKORDERED" for e in entries
        )
        if not has_backordered:
            raise_err(ERR_PO_AT_RISK_BLOCKS_SCHEDULING, "PO posture is AT_RISK; only remediation shipments may be scheduled")

    rec = new_record({
        "purchase_order_id": purchase_order_id,
        "school_site_id": school_site_id,
        "kind": kind,
        "damage_report_id": None,
        "scheduled_date": scheduled_date,
        "lines": entries,
        "status": "SCHEDULED",
    })
    store.shipments[rec["id"]] = rec
    _maybe_advance_po(po)
    return success(public(rec), code=201)


@bp.route("/v1/shipments/<rid>", methods=["GET"])
def get_shipment(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.shipments, rid, "shipment")
    return success(public(rec), code=200)


@bp.route("/v1/shipments", methods=["GET"])
def list_shipments():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.shipments.values())
    purchase_order_id = request.args.get("purchase_order_id")
    school_site_id = request.args.get("school_site_id")
    damage_report_id = request.args.get("damage_report_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if purchase_order_id is not None:
        records = [r for r in records if r["purchase_order_id"] == purchase_order_id]
    if school_site_id is not None:
        records = [r for r in records if r["school_site_id"] == school_site_id]
    if damage_report_id is not None:
        records = [r for r in records if r.get("damage_report_id") == damage_report_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


@bp.route("/v1/shipments/<rid>/mark-delivered", methods=["POST"])
def mark_delivered(rid):
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    shipment = get_or_404(store.shipments, rid, "shipment")
    data = body()

    raw_lines = data.get("lines")
    # priority 4: entry FK existence
    if isinstance(raw_lines, list):
        for entry in raw_lines:
            if isinstance(entry, dict) and isinstance(entry.get("po_line_id"), str):
                get_or_404(store.po_lines, entry["po_line_id"], "PO line")

    # priority 5: shape
    lines = req_list(data, "lines")
    if len(lines) == 0:
        raise_err(ERR_INVALID_REQUEST, "Field 'lines' must contain at least one entry")
    entries = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "Each lines entry must be an object")
        po_line_id = entry.get("po_line_id")
        delivered_qty = entry.get("delivered_qty")
        manufacturer = entry.get("manufacturer")
        model = entry.get("model")
        if not isinstance(po_line_id, str):
            raise_err(ERR_INVALID_REQUEST, "Each delivery entry requires a string po_line_id")
        if isinstance(delivered_qty, bool) or not isinstance(delivered_qty, int) or delivered_qty < 1:
            raise_err(ERR_INVALID_REQUEST, "Each delivery entry requires integer delivered_qty >= 1")
        if not isinstance(manufacturer, str) or not isinstance(model, str):
            raise_err(ERR_INVALID_REQUEST, "Each delivery entry requires manufacturer and model strings")
        entries.append({
            "po_line_id": po_line_id,
            "delivered_qty": delivered_qty,
            "manufacturer": manufacturer,
            "model": model,
        })
    scheduled_ids = {l["po_line_id"] for l in shipment["lines"]}
    for entry in entries:
        if entry["po_line_id"] not in scheduled_ids:
            raise_err(ERR_INVALID_REQUEST, "Delivery entries must reference lines scheduled on this shipment")

    # priority 6: valid only while SCHEDULED
    if shipment["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, f"Cannot mark a shipment in status {shipment['status']} as delivered")

    # priority 10: no-substitution compliance
    for entry in entries:
        line = store.po_lines[entry["po_line_id"]]
        spec_line = store.spec_lines.get(line["spec_line_id"])
        if entry["manufacturer"] != spec_line["manufacturer"] or entry["model"] != spec_line["model"]:
            raise_err(ERR_SUBSTITUTION_NOT_ALLOWED, "Delivered manufacturer/model must exactly equal the pinned spec line values")

    # priority 14: quantity discipline
    for entry in entries:
        line = store.po_lines[entry["po_line_id"]]
        if shipment["kind"] == "REPLACEMENT":
            scheduled_qty = sum(l["qty"] for l in shipment["lines"] if l["po_line_id"] == entry["po_line_id"])
            if entry["delivered_qty"] > scheduled_qty:
                raise_err(ERR_DELIVERY_EXCEEDS_ORDERED, "Delivery entry exceeds the replacement shipment's scheduled quantity")
        else:
            remaining = line["ordered_qty"] - line["delivered_qty"]
            if entry["delivered_qty"] > remaining:
                raise_err(ERR_DELIVERY_EXCEEDS_ORDERED, "Delivery entry exceeds the line's remaining undelivered quantity")

    # ---- side effects ----
    shipment["status"] = "DELIVERED"
    touch(shipment)

    affected_pos = set()
    for entry in entries:
        line = store.po_lines[entry["po_line_id"]]
        line["delivered_qty"] += entry["delivered_qty"]
        if line["status"] in SHIPPABLE_LINE_STATES:
            if line["delivered_qty"] >= line["ordered_qty"]:
                line["status"] = "DELIVERED"
            else:
                line["status"] = "PARTIALLY_DELIVERED"
            # completing a line resolves its open backorder notice
            if line["status"] == "DELIVERED" and open_notice_of_line(line["id"]) is not None:
                notice = open_notice_of_line(line["id"])
                notice["status"] = "RESOLVED"
                touch(notice)
        touch(line)
        affected_pos.add(line["purchase_order_id"])

    for po_id in affected_pos:
        po = store.purchase_orders.get(po_id)
        if po is not None:
            recompute_po(po)

    # replacement cascade resolution: delivery completes the report's damaged_qty
    if shipment.get("damage_report_id"):
        report = store.damage_reports.get(shipment["damage_report_id"])
        if report is not None and report["status"] == "REPLACEMENT_ORDERED":
            delivered_for_line = sum(
                e["delivered_qty"] for e in entries if e["po_line_id"] == report["po_line_id"]
            )
            if delivered_for_line >= report["damaged_qty"]:
                report["status"] = "RESOLVED"
                touch(report)

    return success(public(shipment), code=200)
