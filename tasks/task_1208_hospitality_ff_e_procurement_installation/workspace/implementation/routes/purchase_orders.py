"""PurchaseOrder and POLine endpoints (PRD 3.4, 3.6 reconcile, 3.8 attic)."""
from flask import Blueprint

import db
import services as svc
from errors import ApiError
from middleware import auth, require_role, body, req_str, req_int, req_enum
from response import ok, paginate
from routes.projects import ANY

bp = Blueprint("purchase_orders", __name__)
S = db.STORE

FULFILLMENT_STATUSES = ("ISSUED", "ACKNOWLEDGED", "READY_TO_SHIP", "CONSOLIDATED",
                        "DELIVERED", "CLOSED", "CANCELLED")
INVOICE_STATUSES = ("UNBILLED", "PARTIALLY_INVOICED", "INVOICED", "PAID")

# Per-target role rules on the shared transition endpoint (PRD 2.1):
# only Vendor may move fulfillment to ACKNOWLEDGED/READY_TO_SHIP; the
# PurchasingAgent owns the invoice axis and fulfillment CANCELLED/CLOSED.
PO_TARGETS = {
    "Vendor": {("FULFILLMENT", "ACKNOWLEDGED"), ("FULFILLMENT", "READY_TO_SHIP")},
    "PurchasingAgent": {("INVOICE", "PARTIALLY_INVOICED"), ("INVOICE", "INVOICED"),
                        ("INVOICE", "PAID"), ("FULFILLMENT", "CANCELLED"),
                        ("FULFILLMENT", "CLOSED")},
}


@bp.route("/api/purchase-orders", methods=["POST"])
def create_po():
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    b = body()
    project_id = b.get("project_id")
    if not isinstance(project_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: project_id")
    vendor_name = req_str(b, "vendor_name")
    project = svc.get_project(project_id)
    svc.check_posture_open(project)
    po = db.create("purchase_orders", {
        "project_id": project_id,
        "vendor_name": vendor_name,
        "shipment_id": None,
        "fulfillment_status": "ISSUED",
        "invoice_status": "UNBILLED",
        "total_extended_cents": 0,
        "total_cube_m3": 0,
    })
    return ok(db.pub(po), 201)


@bp.route("/api/purchase-orders/<purchaseOrderId>", methods=["GET"])
def get_po(purchaseOrderId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_po(purchaseOrderId)))


@bp.route("/api/purchase-orders/<id>/lines", methods=["GET"])
def list_po_lines(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_po(id)
    rows = db.sorted_items(r for r in S["po_lines"].values()
                           if r["purchase_order_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/purchase-orders/<id>/lines", methods=["POST"])
def add_po_line(id):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    po = svc.get_po(id)
    b = body()
    spec_item_id = b.get("spec_item_id")
    if not isinstance(spec_item_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: spec_item_id")
    quantity_ordered = req_int(b, "quantity_ordered", 1)
    declared_cube = req_int(b, "declared_cube_m3", 1)
    spec = svc.get_spec(spec_item_id)
    project = svc.get_project(po["project_id"])
    # stage 5: posture gate
    svc.check_posture_open(project)
    # stage 7: brand-standard gate
    if spec["status"] != "BRAND_APPROVED":
        raise ApiError("ERR_SPEC_NOT_BRAND_APPROVED",
                       "A PO line may only be added for a BRAND_APPROVED spec")
    # stage 8: an AWARDED/ORDERED bid must exist for (spec, PO vendor_name)
    matches = [x for x in S["bids"].values()
               if x["spec_item_id"] == spec_item_id
               and x["vendor_name"] == po["vendor_name"]
               and x["status"] in ("AWARDED", "ORDERED")]
    if not matches:
        raise ApiError("ERR_NO_AWARDED_BID",
                       "No AWARDED or ORDERED bid exists for (spec_item_id, PO vendor_name)")
    matches = db.sorted_items(matches)
    awarded = next((x for x in matches if x["status"] == "AWARDED"), matches[0])
    # spec must belong to the PO's project
    if spec["project_id"] != po["project_id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                       "Spec item belongs to a different project than the purchase order")
    # stage 9: at most one non-CANCELLED line per spec across all POs
    if any(l["spec_item_id"] == spec_item_id and l["status"] != "CANCELLED"
           for l in S["po_lines"].values()):
        raise ApiError("ERR_SPEC_ALREADY_ORDERED",
                       "A non-CANCELLED PO line already exists for this spec item")
    unit_price = awarded["unit_price_cents"]
    extended = quantity_ordered * unit_price
    # stage 11 (fiscal, last): committed + extended must stay <= budgeted
    bl = next((x for x in S["budget_lines"].values()
               if x["project_id"] == po["project_id"] and x["category"] == spec["category"]),
              None)
    if bl is None:
        raise ApiError("ERR_BUDGET_LINE_NOT_FOUND",
                       "No budget line for the spec's category in this project")
    svc.recompute_budget_line(bl)
    if bl["committed_cents"] + extended > bl["budgeted_cents"]:
        raise ApiError("ERR_BUDGET_LINE_EXCEEDED",
                       "New line would push category committed above budgeted_cents")
    line = db.create("po_lines", {
        "purchase_order_id": po["id"],
        "spec_item_id": spec_item_id,
        "quantity_ordered": quantity_ordered,
        "declared_cube_m3": declared_cube,
        "unit_price_cents": unit_price,
        "extended_cents": extended,
        "qty_received": 0,
        "qty_damaged_unresolved": 0,
        "qty_damaged_credited": 0,
        "qty_short": 0,
        "qty_installable": 0,
        "qty_installed": 0,
        "qty_attic": 0,
        "freight_alloc_provisional_cents": 0,
        "freight_alloc_final_cents": None,
        "damage_credit_cents": 0,
        "actual_landed_cents": 0,
        "status": "OPEN",
    })
    if awarded["status"] == "AWARDED":
        awarded["status"] = "ORDERED"
        db.touch(awarded)
    svc.recompute_po_totals(po)
    db.touch(po)  # side effect: purchase_order.version += 1
    # if the PO is attached to a shipment, its cube participates in the shipment
    if po["shipment_id"]:
        svc.recompute_shipment_cube(S["shipments"][po["shipment_id"]])
    svc.recompute_attic_target(spec)
    svc.recompute_project_financials(po["project_id"])
    return ok(db.pub(line), 201)


@bp.route("/api/purchase-orders/<id>/transitions", methods=["POST"])
def po_transition(id):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent", "Vendor"))
    b = body()
    axis = b.get("axis")
    to_status = b.get("to_status")
    # per-target role authorization (stage 2) requires the discriminators
    if isinstance(axis, str) and axis in ("FULFILLMENT", "INVOICE"):
        axis_enums = {"FULFILLMENT": FULFILLMENT_STATUSES, "INVOICE": INVOICE_STATUSES}
        if isinstance(to_status, str) and to_status in axis_enums[axis]:
            if (axis, to_status) not in PO_TARGETS.get(role, set()):
                raise ApiError("ERR_UNAUTHORIZED_ROLE",
                               f"Role {role} may not move {axis} to {to_status}")
    po = svc.get_po(id)
    if not isinstance(axis, str) or axis not in ("FULFILLMENT", "INVOICE"):
        raise ApiError("ERR_INVALID_REQUEST", "axis must be FULFILLMENT or INVOICE")
    axis_enums = {"FULFILLMENT": FULFILLMENT_STATUSES, "INVOICE": INVOICE_STATUSES}
    if not isinstance(to_status, str) or to_status not in axis_enums[axis]:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"to_status must be one of {sorted(axis_enums[axis])}")

    if axis == "FULFILLMENT":
        _fulfillment_transition(po, to_status)
    else:
        _invoice_transition(po, to_status)
    db.touch(po)
    return ok(db.pub(po))


def _fulfillment_transition(po, to_status):
    cur = po["fulfillment_status"]
    if to_status == "ACKNOWLEDGED":
        if cur != "ISSUED":
            raise ApiError("ERR_INVALID_PO_TRANSITION",
                           "ACKNOWLEDGED requires fulfillment ISSUED")
        po["fulfillment_status"] = "ACKNOWLEDGED"
    elif to_status == "READY_TO_SHIP":
        if cur != "ACKNOWLEDGED":
            raise ApiError("ERR_INVALID_PO_TRANSITION",
                           "READY_TO_SHIP requires fulfillment ACKNOWLEDGED")
        if not svc.lines_of_po(po["id"]):
            raise ApiError("ERR_PO_HAS_NO_LINES",
                           "READY_TO_SHIP requires at least one non-CANCELLED line")
        po["fulfillment_status"] = "READY_TO_SHIP"
    elif to_status == "CANCELLED":
        if cur not in ("ISSUED", "ACKNOWLEDGED"):
            raise ApiError("ERR_INVALID_PO_TRANSITION",
                           "CANCELLED requires fulfillment ISSUED or ACKNOWLEDGED")
        po["fulfillment_status"] = "CANCELLED"
        for line in svc.lines_of_po(po["id"]):
            line["status"] = "CANCELLED"
            db.touch(line)
        svc.recompute_po_totals(po)
        svc.recompute_project_financials(po["project_id"])
    elif to_status == "CLOSED":
        if cur != "DELIVERED":
            raise ApiError("ERR_INVALID_PO_TRANSITION",
                           "CLOSED requires fulfillment DELIVERED")
        if po["invoice_status"] != "PAID":
            raise ApiError("ERR_INVOICE_NOT_PAID",
                           "CLOSED requires invoice_status PAID")
        lines = svc.lines_of_po(po["id"], include_cancelled=True)
        if any(l["status"] not in ("RECONCILED", "CANCELLED") for l in lines):
            raise ApiError("ERR_LINES_NOT_RECONCILED",
                           "CLOSED requires all lines RECONCILED or CANCELLED")
        po["fulfillment_status"] = "CLOSED"
    else:
        # ISSUED / CONSOLIDATED / DELIVERED are system-driven targets
        raise ApiError("ERR_INVALID_PO_TRANSITION",
                       f"{cur} -> {to_status} is not a legal fulfillment transition")


def _invoice_transition(po, to_status):
    cur = po["invoice_status"]
    if to_status == "PARTIALLY_INVOICED":
        if cur != "UNBILLED":
            raise ApiError("ERR_INVALID_PO_TRANSITION",
                           "PARTIALLY_INVOICED requires invoice UNBILLED")
        po["invoice_status"] = "PARTIALLY_INVOICED"
    elif to_status == "INVOICED":
        if cur not in ("UNBILLED", "PARTIALLY_INVOICED"):
            raise ApiError("ERR_INVALID_PO_TRANSITION",
                           "INVOICED requires invoice UNBILLED or PARTIALLY_INVOICED")
        po["invoice_status"] = "INVOICED"
    elif to_status == "PAID":
        if cur != "INVOICED":
            raise ApiError("ERR_INVALID_PO_TRANSITION",
                           "PAID requires invoice INVOICED")
        if po["fulfillment_status"] not in ("DELIVERED", "CLOSED"):
            raise ApiError("ERR_INVOICE_BEFORE_DELIVERY",
                           "PAID requires fulfillment DELIVERED or CLOSED")
        po["invoice_status"] = "PAID"
    else:
        raise ApiError("ERR_INVALID_PO_TRANSITION",
                       f"{cur} -> {to_status} is not a legal invoice transition")


# --- POLine reads and actions -------------------------------------------------

@bp.route("/api/po-lines/<poLineId>", methods=["GET"])
def get_po_line(poLineId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_line(poLineId)))


@bp.route("/api/po-lines/<id>/reconcile", methods=["POST"])
def reconcile_line(id):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    line = svc.get_line(id)
    if line["status"] not in ("FULLY_RECEIVED", "PARTIALLY_RECEIVED"):
        raise ApiError("ERR_LINE_NOT_RECEIVED",
                       "reconcile requires the line FULLY_RECEIVED or PARTIALLY_RECEIVED")
    if line["status"] == "PARTIALLY_RECEIVED":
        po = svc.po_of_line(line)
        shipment = S["shipments"].get(po["shipment_id"]) if po["shipment_id"] else None
        if shipment is None or shipment["status"] != "RECEIVED":
            raise ApiError("ERR_LINE_SHORTFALL_OPEN",
                           "A PARTIALLY_RECEIVED line reconciles only once its shipment is RECEIVED")
    if any(c["po_line_id"] == line["id"] and c["status"] in svc.NON_TERMINAL_CLAIM_STATES
           for c in S["damage_claims"].values()):
        raise ApiError("ERR_CLAIMS_OPEN",
                       "Claims in OPEN, SUBMITTED, or DISPUTED remain on the line")
    line["status"] = "RECONCILED"
    db.touch(line)
    return ok(db.pub(line))


@bp.route("/api/po-lines/<id>/attic-transfers", methods=["POST"])
def attic_transfer(id):
    user_id, role = auth()
    require_role(role, ("WarehouseReceiver",))
    line = svc.get_line(id)
    b = body()
    direction = req_enum(b, "direction", ("IN", "OUT", "WRITE_OFF"))
    quantity = req_int(b, "quantity", 1)
    expected = b.get("expected_po_line_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_po_line_version is required")
    # stage 6 OCC, before any pool or cap check (PRD 3.8)
    if expected != line["version"]:
        raise ApiError("ERR_STALE_PO_LINE_VERSION",
                       "expected_po_line_version does not match the line's current version")
    # stage 9, pinned order: pool sufficiency BEFORE the attic target cap
    if direction == "IN":
        if quantity > line["qty_installable"]:
            raise ApiError("ERR_INSUFFICIENT_INSTALLABLE",
                           "Transfer IN quantity exceeds qty_installable")
        spec = svc.spec_of_line(line)
        if line["qty_attic"] + quantity > spec["attic_target_qty"]:
            raise ApiError("ERR_ATTIC_TARGET_EXCEEDED",
                           "Transfer IN would raise qty_attic above the attic target")
        line["qty_installable"] -= quantity
        line["qty_attic"] += quantity
    elif direction == "OUT":
        if quantity > line["qty_attic"]:
            raise ApiError("ERR_INSUFFICIENT_ATTIC",
                           "Transfer OUT quantity exceeds qty_attic")
        line["qty_attic"] -= quantity
        line["qty_installable"] += quantity
    else:  # WRITE_OFF
        if quantity > line["qty_attic"]:
            raise ApiError("ERR_INSUFFICIENT_ATTIC",
                           "WRITE_OFF quantity exceeds qty_attic")
        line["qty_attic"] -= quantity
    db.touch(line)
    movement = db.create_event({
        "po_line_id": line["id"],
        "direction": direction,
        "quantity": quantity,
        "resulting_installable": line["qty_installable"],
        "resulting_attic": line["qty_attic"],
    })
    return ok(db.pub(movement), 201)


@bp.route("/api/po-lines/<id>/attic-movements", methods=["GET"])
def attic_movements(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_line(id)
    rows = db.sorted_items(r for r in S["attic_movements"].values()
                           if r["po_line_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/po-lines/<id>/damage-claims", methods=["GET"])
def line_damage_claims(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_line(id)
    rows = db.sorted_items(r for r in S["damage_claims"].values()
                           if r["po_line_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/po-lines/<id>/installation-tasks", methods=["GET"])
def line_installation_tasks(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_line(id)
    rows = db.sorted_items(r for r in S["installation_tasks"].values()
                           if r["po_line_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)
