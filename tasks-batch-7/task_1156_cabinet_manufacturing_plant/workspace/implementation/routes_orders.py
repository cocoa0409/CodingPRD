"""Orders, order lines, and modification requests (PRD §3.2, §3.3, §3.7)."""
from flask import Blueprint, request

from auth import check_dealer_ownership, require_any_role, require_roles
from domain import (
    LINE_TYPES,
    MOD_CODES,
    REVIEW_DECISIONS,
    approved_mod_total,
    compute_mod_surcharge,
    lines_of_order,
    live_lines,
    mods_of_line,
    price_order_provisional,
    recompute_order_cube,
    reevaluate_order,
    sublots_of_line,
)
from errors import api_error
from serializers import ser_hold, ser_modification, ser_order, ser_order_line
from store import db, new_id, now, stamp, touch
from util import Body, paginate, respond_list, respond_object, sort_records, rhu_int, D

bp = Blueprint("orders", __name__)


def _get_order(order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise api_error("ERR_ORDER_NOT_FOUND", f"Order {order_id} not found")
    return order


def _get_line(line_id):
    line = db.order_lines.get(line_id)
    if line is None:
        raise api_error("ERR_ORDER_LINE_NOT_FOUND", f"OrderLine {line_id} not found")
    return line


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@bp.post("/kcma/orders")
def create_order():
    uid, _ = require_roles({"Dealer"})
    dealer = db.dealers.get(uid)
    if dealer is None:
        # Dealer is entity-backed: X-User-ID must name a persisted Dealer.
        raise api_error("ERR_DEALER_NOT_FOUND", f"Dealer {uid} not found")
    order = {
        "id": new_id(),
        "dealer_id": uid,
        "price_level_snapshot": dealer["price_level"],
        "status": "DRAFT",
        "cube_ft": D("0"),
        "provisional_merchandise_cents": None,
        "provisional_discount_cents": None,
        "provisional_total_cents": None,
        "final_merchandise_cents": None,
        "final_discount_cents": None,
        "freight_cents": None,
        "grand_total_cents": None,
        "delivery_route_id": None,
        "route_stop_seq": None,
        "submitted_at": None,
        "shipped_at": None,
    }
    stamp(order)
    db.orders[order["id"]] = order
    return respond_object(ser_order(order), 201)


@bp.get("/kcma/orders")
def list_orders():
    require_any_role()
    records = list(db.orders.values())
    dealer_id = request.args.get("dealer_id")
    if dealer_id is not None:
        records = [o for o in records if o["dealer_id"] == dealer_id]
    route_id = request.args.get("delivery_route_id")
    if route_id is not None:
        records = [o for o in records if o["delivery_route_id"] == route_id]
    status = request.args.get("status")
    if status is not None:
        records = [o for o in records if o["status"] == status]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_order(o) for o in page], total, limit, offset)


@bp.get("/kcma/orders/<orderId>")
def get_order(orderId):
    require_any_role()
    return respond_object(ser_order(_get_order(orderId)), 200)


@bp.post("/kcma/orders/<orderId>/lines")
def create_order_line(orderId):
    uid, _ = require_roles({"Dealer"})
    order = _get_order(orderId)                                   # priority 4 (path)
    check_dealer_ownership(uid, order["dealer_id"])               # priority 3
    body = Body(request.get_json(silent=True))
    line_type = body.req_enum("line_type", LINE_TYPES)
    door_style_id = body.opt_str("door_style_id")
    finish_id = body.req_str("finish_id")
    width_in = body.req_int("width_in", min_value=1)
    height_in = body.req_int("height_in", min_value=1)
    depth_in = body.req_int("depth_in", min_value=1)
    qty = body.req_int("qty", min_value=1)
    unit_list_price_cents = body.req_int("unit_list_price_cents", min_value=1)
    required_sheen_lot_no = body.opt_str("required_sheen_lot_no")

    # priority 5: body foreign keys exist
    finish = None
    if finish_id is not None:
        finish = db.finish_specs.get(finish_id)
        if finish is None:
            raise api_error("ERR_FINISH_NOT_FOUND", f"FinishSpec {finish_id} not found")
    style = None
    if door_style_id is not None:
        style = db.door_styles.get(door_style_id)
        if style is None:
            raise api_error("ERR_DOOR_STYLE_NOT_FOUND", f"DoorStyle {door_style_id} not found")

    # priority 6: target resource state — line addition requires DRAFT order
    if order["status"] != "DRAFT":
        raise api_error("ERR_ORDER_NOT_SUBMITTABLE", "Lines can only be added to a DRAFT order")

    # priority 8: referenced catalog resources must be active (style, then finish)
    if line_type == "DOOR" and style is not None and not style["active"]:
        raise api_error("ERR_DOOR_STYLE_INACTIVE", f"DoorStyle {style['id']} is inactive")
    if finish is not None and not finish["active"]:
        raise api_error("ERR_FINISH_INACTIVE", f"FinishSpec {finish['id']} is inactive")

    # priority 9: shape/type discipline per line_type
    if line_type == "DOOR":
        if door_style_id is None:
            raise api_error("ERR_WRONG_LINE_TYPE", "DOOR line requires door_style_id")
        if depth_in is not None and depth_in != 1:
            raise api_error("ERR_WRONG_LINE_TYPE", "DOOR line depth_in must equal 1")
    elif line_type == "BOX":
        if door_style_id is not None:
            raise api_error("ERR_WRONG_LINE_TYPE", "BOX line must not carry door_style_id")
        if required_sheen_lot_no is not None:
            raise api_error("ERR_WRONG_LINE_TYPE", "BOX line must not carry required_sheen_lot_no")

    # priority 14: field-level sanity, always last
    body.raise_field_errors()

    line_list_cents = unit_list_price_cents * qty
    finish_upcharge_cents = rhu_int(D(line_list_cents) * D(finish["upcharge_pct"]))
    line = {
        "id": new_id(),
        "order_id": order["id"],
        "line_type": line_type,
        "door_style_id": door_style_id if line_type == "DOOR" else None,
        "finish_id": finish_id,
        "width_in": width_in,
        "height_in": height_in,
        "depth_in": depth_in,
        "qty": qty,
        "unit_list_price_cents": unit_list_price_cents,
        "finish_upcharge_pct_snapshot": finish["upcharge_pct"],
        "line_list_cents": line_list_cents,
        "finish_upcharge_cents": finish_upcharge_cents,
        "mod_surcharge_cents": 0,
        "provisional_net_cents": None,
        "final_net_cents": None,
        "finish_batch_id": None,
        "required_sheen_lot_no": required_sheen_lot_no if line_type == "DOOR" else None,
        "status": "PENDING",
    }
    stamp(line)
    db.order_lines[line["id"]] = line
    recompute_order_cube(order)  # derived field refresh; no version bump
    return respond_object(ser_order_line(line), 201)


@bp.get("/kcma/orders/<orderId>/holds")
def list_order_holds(orderId):
    require_any_role()
    order = _get_order(orderId)
    records = [h for h in db.holds.values() if h["order_id"] == order["id"]]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_hold(h) for h in page], total, limit, offset)


@bp.post("/kcma/orders/<orderId>/submit")
def submit_order(orderId):
    uid, _ = require_roles({"Dealer"})
    order = _get_order(orderId)                                   # priority 4
    check_dealer_ownership(uid, order["dealer_id"])               # priority 3
    if order["status"] != "DRAFT":                                # priority 6
        raise api_error("ERR_ORDER_NOT_SUBMITTABLE", "Submit requires the order in DRAFT")
    lines = live_lines(order)
    if not lines:
        raise api_error("ERR_ORDER_HAS_NO_LINES", "Submit requires at least one line")
    # priority 7: no modification on any of the order's lines may sit inside
    # the review loop.
    for line in lines:
        for mod in mods_of_line(line["id"]):
            if mod["status"] in ("UNDER_REVIEW", "CHANGES_REQUESTED"):
                raise api_error(
                    "ERR_MODS_PENDING_REVIEW",
                    "A modification request on the order is still under review",
                )
    # provisional pricing variant, computed before commit
    merch, discount, total, nets, mods = price_order_provisional(order)
    dealer = db.dealers[order["dealer_id"]]
    if total > dealer["credit_limit_cents"]:                      # priority 13
        raise api_error(
            "ERR_DEALER_CREDIT_EXCEEDED",
            f"provisional_total_cents {total} exceeds dealer credit limit "
            f"{dealer['credit_limit_cents']}",
        )

    for line in lines:
        line["mod_surcharge_cents"] = mods[line["id"]]
        line["provisional_net_cents"] = nets[line["id"]]
        line["status"] = "QUOTED"  # PENDING -> QUOTED
        touch(line)
    order["provisional_merchandise_cents"] = merch
    order["provisional_discount_cents"] = discount
    order["provisional_total_cents"] = total
    order["status"] = "SUBMITTED"
    order["submitted_at"] = now()
    touch(order)
    return respond_object(ser_order(order), 200)


@bp.post("/kcma/orders/<orderId>/cancel")
def cancel_order(orderId):
    uid, _ = require_roles({"Dealer"})
    order = _get_order(orderId)                                   # priority 4
    check_dealer_ownership(uid, order["dealer_id"])               # priority 3
    if order["status"] not in ("DRAFT", "SUBMITTED"):             # priority 6
        raise api_error(
            "ERR_ORDER_NOT_CANCELLABLE",
            "Cancel requires the order in DRAFT or SUBMITTED",
        )
    was_submitted = order["status"] == "SUBMITTED"
    lines = live_lines(order)
    affected_batch_ids = set()
    for line in lines:
        line["status"] = "CANCELLED"
        if line["line_type"] == "DOOR" and line["finish_batch_id"] is not None:
            affected_batch_ids.add(line["finish_batch_id"])
            line["finish_batch_id"] = None
        touch(line)
    # open modification requests are force-rejected
    for line in lines_of_order(order["id"]):
        for mod in mods_of_line(line["id"]):
            if mod["status"] in ("UNDER_REVIEW", "CHANGES_REQUESTED"):
                mod["status"] = "REJECTED"
                mod["reviewer_note"] = "ORDER_CANCELLED"
                touch(mod)
    if was_submitted:
        # SCHEDULED sub-lots covering the order's box lines are cancelled,
        # freeing assembly-line windows and day load.
        for line in lines_of_order(order["id"]):
            for sub in sublots_of_line(line["id"]):
                if sub["status"] == "SCHEDULED":
                    sub["status"] = "CANCELLED"
                    touch(sub)
        for hold in [h for h in db.holds.values() if h["order_id"] == order["id"]]:
            if hold["status"] == "PLACED":
                hold["status"] = "RELEASED"
                touch(hold)
        # route unassignment (reserved cube / count reconcile on read)
        if order["delivery_route_id"] is not None:
            order["delivery_route_id"] = None
            order["route_stop_seq"] = None
    order["status"] = "CANCELLED"
    touch(order)
    return respond_object(ser_order(order), 200)


# ---------------------------------------------------------------------------
# Order lines (flat access)
# ---------------------------------------------------------------------------

@bp.get("/kcma/order-lines")
def list_order_lines():
    require_any_role()
    records = list(db.order_lines.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        records = [l for l in records if l["order_id"] == order_id]
    door_style_id = request.args.get("door_style_id")
    if door_style_id is not None:
        records = [l for l in records if l["door_style_id"] == door_style_id]
    finish_id = request.args.get("finish_id")
    if finish_id is not None:
        records = [l for l in records if l["finish_id"] == finish_id]
    finish_batch_id = request.args.get("finish_batch_id")
    if finish_batch_id is not None:
        records = [l for l in records if l["finish_batch_id"] == finish_batch_id]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_order_line(l) for l in page], total, limit, offset)


@bp.get("/kcma/order-lines/<lineId>")
def get_order_line(lineId):
    require_any_role()
    return respond_object(ser_order_line(_get_line(lineId)), 200)


# ---------------------------------------------------------------------------
# Modification requests
# ---------------------------------------------------------------------------

@bp.post("/kcma/order-lines/<lineId>/modifications")
def create_modification(lineId):
    uid, _ = require_roles({"Dealer"})
    line = _get_line(lineId)                                      # priority 4
    order = db.orders[line["order_id"]]
    check_dealer_ownership(uid, order["dealer_id"])               # priority 3
    if order["status"] != "DRAFT":                                # priority 6
        raise api_error(
            "ERR_ORDER_NOT_SUBMITTABLE",
            "Modifications can only be requested on lines of a DRAFT order",
        )
    body = Body(request.get_json(silent=True))
    mod_code = body.req_enum("mod_code", MOD_CODES)
    new_dimension_in = body.req_int("new_dimension_in", min_value=1)
    body.raise_field_errors()                                     # priority 14

    mod = {
        "id": new_id(),
        "order_line_id": line["id"],
        "mod_code": mod_code,
        "new_dimension_in": new_dimension_in,
        "surcharge_cents": compute_mod_surcharge(line, mod_code, new_dimension_in),
        "revision": 1,
        "status": "UNDER_REVIEW",
        "reviewer_note": None,
    }
    stamp(mod)
    db.mods[mod["id"]] = mod
    return respond_object(ser_modification(mod), 201)


@bp.get("/kcma/order-lines/<lineId>/modifications")
def list_modifications(lineId):
    require_any_role()
    line = _get_line(lineId)
    page, total, limit, offset = paginate(sort_records(mods_of_line(line["id"])))
    return respond_list([ser_modification(m) for m in page], total, limit, offset)


@bp.post("/kcma/modifications/<modId>/review")
def review_modification(modId):
    require_roles({"Engineer"})
    mod = db.mods.get(modId)
    if mod is None:
        raise api_error("ERR_MODIFICATION_NOT_FOUND", f"ModificationRequest {modId} not found")
    if mod["status"] != "UNDER_REVIEW":                           # priority 6
        raise api_error("ERR_MOD_NOT_REVIEWABLE", "Review requires the mod in UNDER_REVIEW")
    body = Body(request.get_json(silent=True))
    decision = body.req_enum("decision", REVIEW_DECISIONS)
    note = body.opt_str("note")
    body.raise_field_errors()                                     # priority 14

    mod["reviewer_note"] = note
    if decision == "APPROVE":
        mod["status"] = "APPROVED"
        # line's mod_surcharge_cents = sum over APPROVED mods; effective at
        # the order's next pricing event
        line = db.order_lines[mod["order_line_id"]]
        line["mod_surcharge_cents"] = approved_mod_total(line["id"])
    elif decision == "REJECT":
        mod["status"] = "REJECTED"
    else:
        mod["status"] = "CHANGES_REQUESTED"
    touch(mod)
    return respond_object(ser_modification(mod), 200)


@bp.post("/kcma/modifications/<modId>/resubmit")
def resubmit_modification(modId):
    uid, _ = require_roles({"Dealer"})
    mod = db.mods.get(modId)
    if mod is None:
        raise api_error("ERR_MODIFICATION_NOT_FOUND", f"ModificationRequest {modId} not found")
    line = db.order_lines[mod["order_line_id"]]
    order = db.orders[line["order_id"]]
    check_dealer_ownership(uid, order["dealer_id"])               # priority 3
    if mod["status"] != "CHANGES_REQUESTED":                      # priority 6
        raise api_error(
            "ERR_MOD_NOT_RESUBMITTABLE",
            "Resubmit requires the mod in CHANGES_REQUESTED",
        )
    body = Body(request.get_json(silent=True))
    new_dimension_in = body.req_int("new_dimension_in", min_value=1)
    body.raise_field_errors()                                     # priority 14

    mod["new_dimension_in"] = new_dimension_in
    mod["surcharge_cents"] = compute_mod_surcharge(line, mod["mod_code"], new_dimension_in)
    mod["revision"] += 1
    mod["status"] = "UNDER_REVIEW"
    touch(mod)
    return respond_object(ser_modification(mod), 200)
