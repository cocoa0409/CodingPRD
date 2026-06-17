"""Order, TicketLineItem, and badge-issuance/refund endpoints (PRD §3.3, §3.4)."""
from flask import Blueprint, request

import clock
import common
import db
import errors
import util
from middleware import authenticate, authorize
from services import calc, lookup, state
import response

bp = Blueprint("orders", __name__)

WRITE_ROLES = {"Attendee", "RegistrationAgent"}
READ_ROLES = {"ConventionAdmin", "RegistrationAgent", "Attendee"}


def _check_not_banned(role, attendee):
    """ERR_ATTENDEE_BANNED when an entity-backed actor is banned (PRD §2.9 step 4).

    Applies to the purchaser attendee on create/transition operations driven by an
    Attendee. RegistrationAgent acting on behalf is bound by the same ban on the
    target attendee (the acting attendee/exhibitor must not be BANNED).
    """
    if attendee is not None and attendee["status"] == "BANNED":
        raise errors.err(errors.ERR_ATTENDEE_BANNED, "Attendee is banned")


# --------------------------------------------------------------------------- #
# Order create + reads
# --------------------------------------------------------------------------- #
@bp.route("/orders", methods=["POST"])
def create_order():
    user_id, role = authenticate()
    authorize(role, WRITE_ROLES)
    body = common.get_body()

    # Existence: body FKs resolved left-to-right (PRD §2.8).
    convention_id = common.require_str(body, "convention_id")
    purchaser_id = common.require_str(body, "purchaser_attendee_id")
    conv = lookup.convention(convention_id)
    purchaser = lookup.attendee(purchaser_id)

    # Ownership: Attendee may only order for itself (PRD §2.1).
    lookup.require_attendee_owns(role, user_id, purchaser_id)

    # Banned check (PRD §2.9 step 4).
    _check_not_banned(role, purchaser)

    line_items = body.get("line_items")
    if line_items is None or not isinstance(line_items, list) or len(line_items) == 0:
        # Order create with zero line items (PRD §3.3).
        raise errors.err(errors.ERR_EMPTY_ORDER, "Order must have at least one line item")

    # Validate each line and resolve ticket_type FKs (existence).
    parsed_lines = []
    for li in line_items:
        if not isinstance(li, dict):
            raise errors.err(errors.ERR_INVALID_REQUEST, "Each line item must be an object")
        tt_id = li.get("ticket_type_id")
        if tt_id is None or not isinstance(tt_id, str) or tt_id == "":
            raise errors.err(errors.ERR_INVALID_REQUEST, "line item missing ticket_type_id")
        qty = li.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise errors.err(errors.ERR_INVALID_REQUEST, "line item quantity must be an integer >= 1")
        tt = lookup.ticket_type(tt_id)
        parsed_lines.append((tt, qty))

    order_row = common.common_fields()
    order_row.update({
        "convention_id": convention_id,
        "purchaser_attendee_id": purchaser_id,
        "is_group": False,
        "status": "DRAFT",
        "ticket_subtotal_cents": 0,
        "processing_fee_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "refund_amount_cents": 0,
        "provisional_refund_cents": 0,
    })
    db.orders[order_row["id"]] = order_row

    for tt, qty in parsed_lines:
        li_row = common.common_fields()
        li_row.update({
            "order_id": order_row["id"],
            "ticket_type_id": tt["id"],
            "quantity": qty,
            "line_base_cents": 0,
            "line_discounted_cents": 0,
        })
        db.ticket_line_items[li_row["id"]] = li_row

    return response.success(common.serialize(order_row), 201)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = authenticate()
    authorize(role, READ_ROLES)
    order = lookup.order(oid)
    lookup.require_attendee_owns(role, user_id, order["purchaser_attendee_id"])
    return response.success(common.serialize(order), 200)


@bp.route("/orders", methods=["GET"])
def list_orders():
    user_id, role = authenticate()
    authorize(role, READ_ROLES)
    rows = list(db.orders.values())
    purchaser_filter = request.args.get("purchaser_attendee_id")
    conv_filter = request.args.get("convention_id")
    if purchaser_filter is not None:
        rows = [o for o in rows if o["purchaser_attendee_id"] == purchaser_filter]
    if conv_filter is not None:
        rows = [o for o in rows if o["convention_id"] == conv_filter]
    # Attendee sees only own orders (PRD §2.1).
    if role == "Attendee":
        rows = [o for o in rows if o["purchaser_attendee_id"] == user_id]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


def _order_lines(order_id):
    return [li for li in db.ticket_line_items.values() if li["order_id"] == order_id]


@bp.route("/orders/<oid>/line-items", methods=["GET"])
def list_order_line_items(oid):
    user_id, role = authenticate()
    authorize(role, READ_ROLES)
    order = lookup.order(oid)
    lookup.require_attendee_owns(role, user_id, order["purchaser_attendee_id"])
    items, limit, offset, total = common.paginate(_order_lines(oid))
    return response.success_list(items, limit, offset, total)


@bp.route("/ticket-line-items", methods=["GET"])
def list_line_items():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rows = list(db.ticket_line_items.values())
    order_filter = request.args.get("order_id")
    tt_filter = request.args.get("ticket_type_id")
    if order_filter is not None:
        rows = [r for r in rows if r["order_id"] == order_filter]
    if tt_filter is not None:
        rows = [r for r in rows if r["ticket_type_id"] == tt_filter]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/ticket-line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    li = lookup.ticket_line_item(lid)
    return response.success(common.serialize(li), 200)


# --------------------------------------------------------------------------- #
# Submit (pricing)
# --------------------------------------------------------------------------- #
@bp.route("/orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    user_id, role = authenticate()
    authorize(role, WRITE_ROLES)
    order = lookup.order(oid)
    lookup.require_attendee_owns(role, user_id, order["purchaser_attendee_id"])

    purchaser = db.attendees.get(order["purchaser_attendee_id"])
    _check_not_banned(role, purchaser)

    if order["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Order is not DRAFT")

    lines = _order_lines(oid)
    if not lines:
        raise errors.err(errors.ERR_EMPTY_ORDER, "Order has no line items")

    conv = db.conventions[order["convention_id"]]
    # Submission permitted only when posture is OPEN (PRD §3.3).
    if conv["posture"] != "OPEN":
        raise errors.err(errors.ERR_POSTURE_BLOCKED, "Convention is not OPEN for submission")

    def base_price_for(line):
        return db.ticket_types[line["ticket_type_id"]]["base_price_cents"]

    per_line, subtotal, fee, total, total_qty, is_group, _pct = calc.price_order(lines, base_price_for)
    for li, computed in zip(lines, per_line):
        li["line_base_cents"] = computed["line_base_cents"]
        li["line_discounted_cents"] = computed["line_discounted_cents"]
        common.touch(li)

    order["ticket_subtotal_cents"] = subtotal
    order["processing_fee_cents"] = fee
    order["total_cents"] = total
    order["is_group"] = is_group
    order["status"] = "PENDING_PAYMENT"
    common.touch(order)
    return response.success(common.serialize(order), 200)


# --------------------------------------------------------------------------- #
# Pay (capacity consume + OCC + cascade A)
# --------------------------------------------------------------------------- #
@bp.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    user_id, role = authenticate()
    authorize(role, WRITE_ROLES)
    order = lookup.order(oid)
    lookup.require_attendee_owns(role, user_id, order["purchaser_attendee_id"])

    purchaser = db.attendees.get(order["purchaser_attendee_id"])
    _check_not_banned(role, purchaser)

    if order["status"] != "PENDING_PAYMENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Order is not PENDING_PAYMENT")

    conv = db.conventions[order["convention_id"]]
    lines = _order_lines(oid)

    # Posture gating (PRD §3.4): OPEN proceeds; SOLD_OUT requires a WON waitlist
    # entry else ERR_LOTTERY_NOT_WON; CLOSED is ERR_POSTURE_BLOCKED.
    if conv["posture"] == "CLOSED":
        raise errors.err(errors.ERR_POSTURE_BLOCKED, "Convention is CLOSED")
    if conv["posture"] == "SOLD_OUT":
        has_won = any(
            e["convention_id"] == conv["id"]
            and e["attendee_id"] == order["purchaser_attendee_id"]
            and e["status"] == "WON"
            for e in db.waitlist_entries.values()
        )
        if not has_won:
            raise errors.err(errors.ERR_LOTTERY_NOT_WON, "No WON waitlist entry under SOLD_OUT posture")

    # Per-tier capacity (PRD §3.4). Aggregate quantities per ticket type.
    qty_by_tt = {}
    for li in lines:
        qty_by_tt[li["ticket_type_id"]] = qty_by_tt.get(li["ticket_type_id"], 0) + li["quantity"]
    for tt_id, qty in qty_by_tt.items():
        tt = db.ticket_types[tt_id]
        if tt["tier_issued_count"] + qty > tt["tier_capacity"]:
            raise errors.err(errors.ERR_TIER_SOLD_OUT, "Ticket tier capacity exceeded")

    # Convention capacity (PRD §3.4).
    total_qty = sum(li["quantity"] for li in lines)
    if conv["badges_issued_count"] + total_qty > conv["total_badge_capacity"]:
        raise errors.err(errors.ERR_CAPACITY_EXCEEDED, "Convention badge capacity exceeded")

    # OCC against Convention.version (PRD §2.7).
    body = common.get_body()
    expected = common.require_int(body, "expected_convention_version")
    if expected != conv["version"]:
        raise errors.err(errors.ERR_STALE_CONVENTION_VERSION, "Stale convention version")

    # --- commit: cascade A ---
    order["amount_paid_cents"] = order["total_cents"]
    order["status"] = "PAID"
    common.touch(order)

    affected_tt = set()
    for li in lines:
        affected_tt.add(li["ticket_type_id"])
        for _ in range(li["quantity"]):
            badge = common.common_fields()
            badge.update({
                "order_id": order["id"],
                "ticket_type_id": li["ticket_type_id"],
                "holder_attendee_id": order["purchaser_attendee_id"],
                "status": "ISSUED",
                "rfid_status": "UNASSIGNED",
                "rfid_uid": None,
                "transfer_count": 0,
            })
            db.badges[badge["id"]] = badge

    # Recompute counters from the authoritative badge set (PRD §3.4).
    for tt_id in affected_tt:
        state.recompute_ticket_type_count(db.ticket_types[tt_id])
    state.recompute_convention_count(conv)

    # Flip posture to SOLD_OUT when capacity reached (PRD §3.4).
    if conv["badges_issued_count"] >= conv["total_badge_capacity"]:
        conv["posture"] = "SOLD_OUT"

    # Pay increments the convention's version by one (PRD §3.4).
    common.touch(conv)
    return response.success(common.serialize(order), 200)


# --------------------------------------------------------------------------- #
# Refund quote (PROVISIONAL)
# --------------------------------------------------------------------------- #
@bp.route("/orders/<oid>/refund-quote", methods=["GET"])
def refund_quote(oid):
    user_id, role = authenticate()
    authorize(role, READ_ROLES)
    order = lookup.order(oid)
    lookup.require_attendee_owns(role, user_id, order["purchaser_attendee_id"])

    conv = db.conventions[order["convention_id"]]
    event_start = util.parse_iso(conv["event_start_utc"])
    provisional = calc.refund_amount(order["ticket_subtotal_cents"], event_start, clock.now())
    order["provisional_refund_cents"] = provisional
    common.touch(order)
    return response.success(common.serialize(order), 200)


# --------------------------------------------------------------------------- #
# Cancel (DRAFT / PENDING_PAYMENT)
# --------------------------------------------------------------------------- #
@bp.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = authenticate()
    authorize(role, WRITE_ROLES)
    order = lookup.order(oid)
    lookup.require_attendee_owns(role, user_id, order["purchaser_attendee_id"])

    purchaser = db.attendees.get(order["purchaser_attendee_id"])
    _check_not_banned(role, purchaser)

    if order["status"] not in {"DRAFT", "PENDING_PAYMENT"}:
        raise errors.err(errors.ERR_INVALID_STATE, "Order cannot be cancelled from its current state")

    order["refund_amount_cents"] = 0
    order["status"] = "CANCELLED"
    common.touch(order)
    return response.success(common.serialize(order), 200)


# --------------------------------------------------------------------------- #
# Refund (PAID -> REFUNDED, cascade B)
# --------------------------------------------------------------------------- #
@bp.route("/orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    _, role = authenticate()
    authorize(role, {"RegistrationAgent", "ConventionAdmin"})
    order = lookup.order(oid)

    if order["status"] != "PAID":
        raise errors.err(errors.ERR_INVALID_STATE, "Order is not PAID")

    conv = db.conventions[order["convention_id"]]
    event_end = util.parse_iso(conv["event_end_utc"])
    # Refund window: strictly before event_end_utc (PRD §3.4).
    if clock.now() >= event_end:
        raise errors.err(errors.ERR_REFUND_WINDOW_CLOSED, "Refund window closed")

    # FINAL refund (PRD §3.4).
    event_start = util.parse_iso(conv["event_start_utc"])
    order["refund_amount_cents"] = calc.refund_amount(
        order["ticket_subtotal_cents"], event_start, clock.now()
    )
    order["status"] = "REFUNDED"
    common.touch(order)

    # --- cascade B ---
    affected_tt = set()
    order_badges = [b for b in db.badges.values() if b["order_id"] == order["id"] and b["status"] != "VOID"]
    order_badges.sort(key=lambda b: b["_seq"])
    for badge in order_badges:
        affected_tt.add(badge["ticket_type_id"])
        state.void_badge(badge)

    for tt_id in affected_tt:
        state.recompute_ticket_type_count(db.ticket_types[tt_id])
    state.recompute_convention_count(conv)

    # Posture returns to OPEN when it was SOLD_OUT and is now below capacity (PRD §3.4).
    if conv["posture"] == "SOLD_OUT" and conv["badges_issued_count"] < conv["total_badge_capacity"]:
        conv["posture"] = "OPEN"

    common.touch(conv)
    return response.success(common.serialize(order), 200)
