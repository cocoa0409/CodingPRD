"""Shipment and ReceivingEvent endpoints (PRD 3.5)."""
from flask import Blueprint

import db
import services as svc
from errors import ApiError
from middleware import auth, require_role, body, req_str, req_int, req_enum
from response import ok, paginate
from routes.projects import ANY

bp = Blueprint("shipments", __name__)
S = db.STORE

SHIPMENT_STATUSES = ("PLANNED", "CONSOLIDATING", "SEALED", "IN_TRANSIT",
                     "RECEIVED", "CANCELLED")


@bp.route("/api/shipments", methods=["POST"])
def create_shipment():
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    b = body()
    project_id = b.get("project_id")
    if not isinstance(project_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: project_id")
    carrier_name = req_str(b, "carrier_name")
    svc.get_project(project_id)
    sh = db.create("shipments", {
        "project_id": project_id,
        "carrier_name": carrier_name,
        "total_cube_m3": 0,
        "freight_mode": None,
        "freight_total_cents": None,
        "status": "PLANNED",
    })
    return ok(db.pub(sh), 201)


@bp.route("/api/shipments/<shipmentId>", methods=["GET"])
def get_shipment(shipmentId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_shipment(shipmentId)))


@bp.route("/api/shipments/<id>/purchase-orders", methods=["GET"])
def shipment_pos(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_shipment(id)
    rows = db.sorted_items(r for r in S["purchase_orders"].values()
                           if r["shipment_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/shipments/<id>/receiving-events", methods=["GET"])
def shipment_events(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_shipment(id)
    rows = db.sorted_items(r for r in S["receiving_events"].values()
                           if r["shipment_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/shipments/<id>/purchase-orders", methods=["POST"])
def attach_po(id):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    shipment = svc.get_shipment(id)
    b = body()
    po_id = b.get("purchase_order_id")
    if not isinstance(po_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: purchase_order_id")
    po = svc.get_po(po_id)
    # stage 5, pinned order: shipment state before PO state
    if shipment["status"] != "CONSOLIDATING":
        raise ApiError("ERR_SHIPMENT_NOT_CONSOLIDATING",
                       "Attaching a PO requires the shipment CONSOLIDATING")
    if po["fulfillment_status"] != "READY_TO_SHIP":
        raise ApiError("ERR_PO_NOT_READY_TO_SHIP",
                       "Attaching requires the PO fulfillment READY_TO_SHIP")
    # stage 8: same project
    if po["project_id"] != shipment["project_id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                       "The PO belongs to a different project than the shipment")
    po["fulfillment_status"] = "CONSOLIDATED"
    po["shipment_id"] = shipment["id"]
    db.touch(po)
    svc.recompute_shipment_cube(shipment)
    return ok(db.pub(po))


@bp.route("/api/shipments/<id>/transitions", methods=["POST"])
def shipment_transition(id):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    shipment = svc.get_shipment(id)
    b = body()
    to_status = req_enum(b, "to_status", SHIPMENT_STATUSES)
    cur = shipment["status"]
    if to_status == "CONSOLIDATING":
        if cur != "PLANNED":
            raise ApiError("ERR_INVALID_SHIPMENT_TRANSITION",
                           "CONSOLIDATING requires the shipment PLANNED")
        shipment["status"] = "CONSOLIDATING"
    elif to_status == "SEALED":
        if cur != "CONSOLIDATING":
            raise ApiError("ERR_INVALID_SHIPMENT_TRANSITION",
                           "SEALED requires the shipment CONSOLIDATING")
        if not svc.shipment_pos(shipment):
            raise ApiError("ERR_SHIPMENT_EMPTY",
                           "Seal requires at least one attached PO")
        svc.recompute_shipment_cube(shipment)
        svc.seal_freight(shipment)
        shipment["status"] = "SEALED"
        svc.recompute_project_financials(shipment["project_id"])
    elif to_status == "IN_TRANSIT":
        if cur != "SEALED":
            raise ApiError("ERR_INVALID_SHIPMENT_TRANSITION",
                           "IN_TRANSIT requires the shipment SEALED")
        shipment["status"] = "IN_TRANSIT"
    elif to_status == "RECEIVED":
        if cur != "IN_TRANSIT":
            raise ApiError("ERR_INVALID_SHIPMENT_TRANSITION",
                           "RECEIVED requires the shipment IN_TRANSIT")
        events = [e for e in S["receiving_events"].values() if e["shipment_id"] == id]
        if not any(e["status"] == "POSTED" for e in events):
            raise ApiError("ERR_NO_RECEIPTS_POSTED",
                           "RECEIVED requires at least one POSTED receiving event")
        if any(e["status"] == "DRAFT" for e in events):
            raise ApiError("ERR_DRAFT_EVENTS_OUTSTANDING",
                           "RECEIVED is blocked while a DRAFT receiving event exists")
        _receive_cascade(shipment)
        shipment["status"] = "RECEIVED"
    elif to_status == "CANCELLED":
        if cur not in ("PLANNED", "CONSOLIDATING"):
            raise ApiError("ERR_INVALID_SHIPMENT_TRANSITION",
                           "CANCELLED requires the shipment PLANNED or CONSOLIDATING")
        for po in svc.shipment_pos(shipment):
            if po["fulfillment_status"] == "CONSOLIDATED":
                po["fulfillment_status"] = "READY_TO_SHIP"
                po["shipment_id"] = None
                db.touch(po)
        shipment["total_cube_m3"] = 0
        shipment["status"] = "CANCELLED"
        svc.recompute_project_financials(shipment["project_id"])
    else:  # PLANNED is never a legal target
        raise ApiError("ERR_INVALID_SHIPMENT_TRANSITION",
                       f"{cur} -> {to_status} is not a legal shipment transition")
    db.touch(shipment)
    return ok(db.pub(shipment))


def _receive_cascade(shipment):
    """Five-link receipt cascade (PRD 3.5), all visible in the same response."""
    # Link 1: attached CONSOLIDATED POs -> DELIVERED
    delivered = []
    for po in svc.shipment_pos(shipment):
        if po["fulfillment_status"] == "CONSOLIDATED":
            po["fulfillment_status"] = "DELIVERED"
            db.touch(po)
            delivered.append(po)
    # Link 2: each delivered PO finalizes its lines' qty_short and status
    for po in delivered:
        for line in svc.lines_of_po(po["id"]):
            line["qty_short"] = line["quantity_ordered"] - line["qty_received"]
            line["status"] = ("FULLY_RECEIVED" if line["qty_short"] == 0
                              else "PARTIALLY_RECEIVED")
            db.touch(line)
    # Link 3: final freight allocation on the received-units basis
    svc.final_freight(shipment)
    # Links 4+5: landed costs, budget actuals/variances, project rollup/posture
    svc.recompute_project_financials(shipment["project_id"])


# --- ReceivingEvent -----------------------------------------------------------

EVENT_STATUSES = ("DRAFT", "POSTED", "REVERSED")


def _parse_event_lines(b):
    lines = b.get("lines")
    if not isinstance(lines, list):
        raise ApiError("ERR_INVALID_REQUEST", "lines must be an array")
    parsed = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each lines entry must be an object")
        po_line_id = entry.get("po_line_id")
        if not isinstance(po_line_id, str):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Missing or invalid field: po_line_id")
        qty_received = entry.get("qty_received")
        if not isinstance(qty_received, int) or isinstance(qty_received, bool) or qty_received < 1:
            raise ApiError("ERR_INVALID_REQUEST", "qty_received must be >= 1")
        qty_damaged = entry.get("qty_damaged")
        if not isinstance(qty_damaged, int) or isinstance(qty_damaged, bool) or qty_damaged < 0:
            raise ApiError("ERR_INVALID_REQUEST", "qty_damaged must be >= 0")
        parsed.append({"po_line_id": po_line_id,
                       "qty_received": qty_received,
                       "qty_damaged": qty_damaged})
    return parsed


@bp.route("/api/receiving-events", methods=["POST"])
def create_event():
    auth_user, role = auth()
    require_role(role, ("WarehouseReceiver",))
    b = body()
    shipment_id = b.get("shipment_id")
    if not isinstance(shipment_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: shipment_id")
    entries = _parse_event_lines(b)
    shipment = svc.get_shipment(shipment_id)
    lines = [svc.get_line(e["po_line_id"]) for e in entries]
    # stage 5: shipment must be IN_TRANSIT at creation
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_NOT_IN_TRANSIT",
                       "Receiving events require the shipment IN_TRANSIT")
    # stage 8: every entry's line must belong to a PO attached to this shipment
    for line in lines:
        po = svc.po_of_line(line)
        if po["shipment_id"] != shipment["id"]:
            raise ApiError("ERR_LINE_NOT_ON_SHIPMENT",
                           "An entry names a line whose PO is not attached to this shipment")
    event = db.create("receiving_events", {
        "shipment_id": shipment_id,
        "lines": entries,
        "status": "DRAFT",
    })
    return ok(db.pub(event), 201)


@bp.route("/api/receiving-events/<receivingEventId>", methods=["GET"])
def get_event(receivingEventId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_event(receivingEventId)))


@bp.route("/api/receiving-events/<receivingEventId>/transitions", methods=["POST"])
def event_transition(receivingEventId):
    auth_user, role = auth()
    require_role(role, ("WarehouseReceiver",))
    event = svc.get_event(receivingEventId)
    b = body()
    to_status = req_enum(b, "to_status", EVENT_STATUSES)
    if to_status == "POSTED":
        _post_event(event)
    elif to_status == "REVERSED":
        _reverse_event(event)
    else:
        raise ApiError("ERR_INVALID_EVENT_TRANSITION",
                       f"{event['status']} -> {to_status} is not a legal event transition")
    db.touch(event)
    return ok(db.pub(event))


def _post_event(event):
    if event["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_EVENT_TRANSITION",
                       "POSTED requires the event DRAFT")
    shipment = svc.get_shipment(event["shipment_id"])
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_NOT_IN_TRANSIT",
                       "Posting requires the shipment IN_TRANSIT")
    # per-entry guards: cumulative over-receipt per line, damage bound per entry
    totals = {}
    for e in event["lines"]:
        totals[e["po_line_id"]] = (
            totals.get(e["po_line_id"], (0, 0))[0] + e["qty_received"],
            totals.get(e["po_line_id"], (0, 0))[1] + e["qty_damaged"],
        )
    for line_id, (rec, _dmg) in totals.items():
        line = svc.get_line(line_id)
        if line["qty_received"] + rec > line["quantity_ordered"]:
            raise ApiError("ERR_OVER_RECEIPT",
                           "Cumulative received would exceed quantity_ordered")
    for e in event["lines"]:
        if e["qty_damaged"] > e["qty_received"]:
            raise ApiError("ERR_DAMAGE_EXCEEDS_RECEIPT",
                           "qty_damaged exceeds qty_received within an entry")
    # apply per line (aggregated so duplicate entries in one event behave)
    affected_projects = set()
    for line_id, (rec, dmg) in totals.items():
        line = svc.get_line(line_id)
        line["qty_received"] += rec
        line["qty_damaged_unresolved"] += dmg
        line["qty_installable"] += rec - dmg
        db.touch(line)
        svc.recompute_line_status_from_receipts(line)
        svc.recompute_landed(line)
        affected_projects.add(svc.po_of_line(line)["project_id"])
    event["status"] = "POSTED"
    for pid in affected_projects:
        svc.recompute_project_financials(pid)


def _reverse_event(event):
    if event["status"] != "POSTED":
        raise ApiError("ERR_INVALID_EVENT_TRANSITION",
                       "REVERSED requires the event POSTED")
    shipment = svc.get_shipment(event["shipment_id"])
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_NOT_IN_TRANSIT",
                       "Reversal requires the shipment still IN_TRANSIT")
    covered = {e["po_line_id"] for e in event["lines"]}
    # claims guard: non-OPEN claims block; OPEN claims are voided instead
    blocking = ("SUBMITTED", "DISPUTED", "RESOLVED_CREDIT",
                "RESOLVED_REPLACEMENT", "DENIED")
    for c in S["damage_claims"].values():
        if c["po_line_id"] in covered and c["status"] in blocking:
            raise ApiError("ERR_CLAIMS_BLOCK_REVERSAL",
                           "A claim on a covered line blocks the reversal")
    # pool guard: installable must survive each entry's net subtraction
    for e in event["lines"]:
        line = svc.get_line(e["po_line_id"])
        if line["qty_installable"] - (e["qty_received"] - e["qty_damaged"]) < 0:
            raise ApiError("ERR_REVERSAL_POOL_SHORTFALL",
                           "Reversal would drive a line pool negative")
    affected_projects = set()
    for e in event["lines"]:
        line = svc.get_line(e["po_line_id"])
        line["qty_received"] -= e["qty_received"]
        line["qty_damaged_unresolved"] -= e["qty_damaged"]
        line["qty_installable"] -= e["qty_received"] - e["qty_damaged"]
        db.touch(line)
        svc.recompute_line_status_from_receipts(line)
        svc.recompute_landed(line)
        affected_projects.add(svc.po_of_line(line)["project_id"])
    for c in db.sorted_items(S["damage_claims"].values()):
        if c["po_line_id"] in covered and c["status"] == "OPEN":
            c["status"] = "VOID"
            db.touch(c)
    event["status"] = "REVERSED"
    for pid in affected_projects:
        svc.recompute_project_financials(pid)
