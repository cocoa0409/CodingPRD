"""StudioVisit routes (PRD §3.2, §3.3, §3.7, §3.8, §3.9; SCAFFOLD §1.5).

RBAC:
  POST /studio-visits                    Anonymous, StudioStaff, StudioManager
  GET  /studio-visits/{id}               StudioStaff, StudioManager, LoyaltyMember(own)
  GET  /studio-visits                    StudioStaff, StudioManager
  GET  /studio-visits/{id}/points-preview StudioStaff, StudioManager, LoyaltyMember(own)
  POST /studio-visits/{id}/pieces        StudioStaff, StudioManager
  POST /studio-visits/{id}/consume       StudioStaff, StudioManager
  POST /studio-visits/{id}/checkout      StudioStaff, StudioManager
  POST /studio-visits/{id}/void          StudioManager
"""

from flask import Blueprint, request

from db import db, new_id, stamp_common, touch
from errors import (ApiError, invalid_state, ERR_VISIT_NOT_OPEN,
                    ERR_INSUFFICIENT_STOCK, ERR_PIECES_NOT_READY,
                    ERR_MEMBER_SUSPENDED, ERR_INSUFFICIENT_POINTS)
from middleware import get_caller, require_roles
from response import success, list_success, parse_pagination, paginate
from services import serializers, calculations, loyalty, visit_calc
from services.lookup import (get_visit, get_member, get_item, assert_member_owns)
from services.validation import (require_body, require_int, require_str,
                                 optional_int, optional_str, optional_enum)

bp = Blueprint("studio_visits", __name__)

STAFF_MANAGER = {"StudioStaff", "StudioManager"}
STAFF_MANAGER_MEMBER = {"StudioStaff", "StudioManager", "LoyaltyMember"}
FIRING_TEMPS = {"CONE_06", "CONE_6"}
VISIT_TYPES = {"WALK_IN", "PARTY"}


@bp.route("/studio-visits", methods=["POST"])
def open_visit():
    caller = get_caller()
    require_roles(caller, {"Anonymous", "StudioStaff", "StudioManager"})
    payload = require_body(request.get_json(silent=True))

    party_size = require_int(payload, "party_size", minimum=1)
    visit_type = optional_enum(payload, "visit_type", VISIT_TYPES, "WALK_IN")
    member_id = optional_str(payload, "member_id", default=None)
    party_booking_id = optional_str(payload, "party_booking_id", default=None)

    # Existence checks for referenced FKs (PRD §2.8 left-to-right).
    if member_id is not None:
        get_member(member_id)
    if party_booking_id is not None:
        if party_booking_id not in db.party_bookings:
            from errors import not_found
            raise not_found("PartyBooking %s not found" % party_booking_id)

    # studio_fee: party_size * 1000 for WALK_IN; 0 for PARTY (PRD §3.2).
    studio_fee_cents = (party_size * calculations.STUDIO_FEE_PER_PAINTER_CENTS
                        if visit_type == "WALK_IN" else 0)

    record = {
        "id": new_id(),
        "member_id": member_id,
        "party_size": party_size,
        "visit_type": visit_type,
        "party_booking_id": party_booking_id,
        "studio_fee_cents": studio_fee_cents,
        "bisque_subtotal_cents": 0,
        "supplies_subtotal_cents": 0,
        "provisional_total_cents": studio_fee_cents,
        "points_redeemed": 0,
        "discount_cents": 0,
        "settled_total_cents": 0,
        "points_earned": 0,
        "status": "OPEN",
    }
    stamp_common(record)
    db.studio_visits[record["id"]] = record
    return success(serializers.studio_visit(record), status=201)


@bp.route("/studio-visits/<visit_id>", methods=["GET"])
def fetch_visit(visit_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    visit = get_visit(visit_id)
    assert_member_owns(caller, visit["member_id"])
    # Recompute live provisional total on read while OPEN (provisional variant).
    if visit["status"] == "OPEN":
        visit_calc.recompute_all(visit)
    return success(serializers.studio_visit(visit))


@bp.route("/studio-visits", methods=["GET"])
def list_visits():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    limit, offset = parse_pagination(request.args)
    records = list(db.studio_visits.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    member_id = request.args.get("member_id")
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    party_booking_id = request.args.get("party_booking_id")
    if party_booking_id is not None:
        records = [r for r in records if r["party_booking_id"] == party_booking_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.studio_visit(r) for r in window], limit, offset, total)


@bp.route("/studio-visits/<visit_id>/points-preview", methods=["GET"])
def points_preview(visit_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    visit = get_visit(visit_id)
    assert_member_owns(caller, visit["member_id"])
    # Estimate variant: use provisional_total_cents (pre-discount) as net spend.
    if visit["status"] == "OPEN":
        visit_calc.recompute_all(visit)
    out = serializers.studio_visit(visit)
    if visit["member_id"] is not None:
        out["points_earned"] = calculations.visit_points_earned(visit["provisional_total_cents"])
    else:
        out["points_earned"] = 0
    return success(out)


@bp.route("/studio-visits/<visit_id>/pieces", methods=["POST"])
def add_piece(visit_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    visit = get_visit(visit_id)
    payload = require_body(request.get_json(silent=True))
    sku = require_str(payload, "sku")
    name = require_str(payload, "name")
    bisque_price_cents = require_int(payload, "bisque_price_cents", minimum=1)
    firing_temp = optional_enum(payload, "firing_temp", FIRING_TEMPS, "CONE_06")

    # A piece may only be added to an OPEN visit (PRD §3.3).
    if visit["status"] != "OPEN":
        raise ApiError(ERR_VISIT_NOT_OPEN, 409, "Visit is not OPEN")

    piece = {
        "id": new_id(),
        "studio_visit_id": visit_id,
        "kiln_batch_id": None,
        "sku": sku,
        "name": name,
        "bisque_price_cents": bisque_price_cents,
        "firing_temp": firing_temp,
        "status": "PAINTED",
        "ready_at": None,
    }
    stamp_common(piece)
    db.bisque_pieces[piece["id"]] = piece

    # Recompute the visit's derived totals (mutation of the owner).
    visit_calc.recompute_all(visit)
    touch(visit)
    return success(serializers.bisque_piece(piece), status=201)


@bp.route("/studio-visits/<visit_id>/consume", methods=["POST"])
def consume_supply(visit_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    visit = get_visit(visit_id)
    payload = require_body(request.get_json(silent=True))
    paint_bar_item_id = require_str(payload, "paint_bar_item_id")
    qty = require_int(payload, "qty", minimum=1)
    item = get_item(paint_bar_item_id)

    # State: visit must be OPEN (PRD §3.7).
    if visit["status"] != "OPEN":
        raise ApiError(ERR_VISIT_NOT_OPEN, 409, "Visit is not OPEN")

    # Item must be ACTIVE and have enough stock (PRD §3.7).
    if item["status"] != "ACTIVE" or item["on_hand_qty"] < qty:
        raise ApiError(ERR_INSUFFICIENT_STOCK, 409,
                       "Item discontinued or insufficient on-hand stock")

    charge = calculations.line_charge_cents(qty, item["unit_price_cents"])
    from clock import clock
    line = {
        "id": new_id(),
        "visit_id": visit_id,
        "paint_bar_item_id": paint_bar_item_id,
        "qty": qty,
        "charge_cents": charge,
        "voided": False,
        "created_at": clock.now_iso(),
        "_seq": db.next_seq(),
    }
    db.supply_lines[line["id"]] = line

    # Decrement stock (PRD §3.7).
    item["on_hand_qty"] -= qty
    item["low_stock"] = item["on_hand_qty"] <= item["reorder_threshold"]
    touch(item)

    visit_calc.recompute_all(visit)
    touch(visit)
    return success(serializers.studio_visit(visit), status=201)


@bp.route("/studio-visits/<visit_id>/checkout", methods=["POST"])
def checkout_visit(visit_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    visit = get_visit(visit_id)
    payload = request.get_json(silent=True) or {}
    points_redeemed = optional_int(payload, "points_redeemed", default=0, minimum=0)

    # State: only an OPEN visit may be checked out (PRD §3.8).
    if visit["status"] != "OPEN":
        raise invalid_state("Visit is not OPEN")

    # Safety gate: every piece must be READY/PICKED_UP/VOIDED (PRD §3.8).
    for p in visit_calc.pieces_on_visit(visit_id):
        if p["status"] not in ("READY", "PICKED_UP", "VOIDED"):
            raise ApiError(ERR_PIECES_NOT_READY, 409,
                           "A piece is still in the kiln pipeline")

    member = None
    if visit["member_id"] is not None:
        member = get_member(visit["member_id"])

    # Redemption validation (PRD §3.8).
    if points_redeemed > 0:
        if member is None:
            # Anonymous visit cannot redeem points.
            raise ApiError(ERR_INSUFFICIENT_POINTS, 422,
                           "Anonymous visit cannot redeem points")
        if member["status"] == "SUSPENDED":
            raise ApiError(ERR_MEMBER_SUSPENDED, 409,
                           "Suspended member may not redeem points")
        if points_redeemed > member["point_balance"]:
            raise ApiError(ERR_INSUFFICIENT_POINTS, 422,
                           "points_redeemed exceeds member point_balance")

    # Recompute base components from current state.
    visit_calc.recompute_bisque_subtotal(visit)
    visit_calc.recompute_supplies_subtotal(visit)

    member_tier = member["tier"] if member else None
    settled, discount, tier_disc, redemption_value, _ = calculations.settle_visit_charge(
        visit["studio_fee_cents"],
        visit["bisque_subtotal_cents"],
        visit["supplies_subtotal_cents"],
        member_tier,
        points_redeemed,
    )

    visit["settled_total_cents"] = settled
    visit["discount_cents"] = discount
    visit["points_redeemed"] = points_redeemed

    # Loyalty earn (member visits only), computed on post-discount net spend.
    points_earned = 0
    if member is not None:
        points_earned = calculations.visit_points_earned(settled)
    visit["points_earned"] = points_earned

    # Commit side effects (PRD §3.8): earn credit, redeem debit, tier recompute.
    if member is not None:
        if points_earned > 0:
            loyalty.credit_earn(member, points_earned, "VISIT", visit_id)
        if points_redeemed > 0:
            loyalty.debit_redeem(member, points_redeemed, "VISIT", visit_id)
        # tier already recomputed by credit_earn; ensure recompute after redeem
        # (redeem does not change lifetime, but recompute is idempotent/safe).
        loyalty.recompute_tier(member)
        touch(member)

    visit["status"] = "SETTLED"
    touch(visit)
    return success(serializers.studio_visit(visit))


@bp.route("/studio-visits/<visit_id>/void", methods=["POST"])
def void_visit(visit_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    visit = get_visit(visit_id)

    # State: only OPEN may be voided (PRD §3.9).
    if visit["status"] != "OPEN":
        raise invalid_state("Visit is not OPEN")

    # Cascade non-terminal pieces -> VOIDED (PRD §3.9).
    for piece in visit_calc.pieces_on_visit(visit_id):
        if piece["status"] in ("PAINTED", "LOADED", "FIRING", "READY"):
            # If the piece was in a kiln, un-load it from its batch.
            if piece["status"] in ("LOADED", "FIRING", "READY") and piece["kiln_batch_id"]:
                batch = db.kiln_batches.get(piece["kiln_batch_id"])
                if batch is not None:
                    batch["occupied_slots"] -= 1
                    touch(batch)  # refresh updated_at + bump version
                piece["kiln_batch_id"] = None
            piece["status"] = "VOIDED"
            piece["ready_at"] = piece.get("ready_at")  # left as-is
            touch(piece)

    # Restore consumed inventory for every supply line on the visit (PRD §3.7/§3.9).
    for line in visit_calc.supply_lines_on_visit(visit_id):
        if not line["voided"]:
            item = db.paint_bar_items.get(line["paint_bar_item_id"])
            if item is not None:
                item["on_hand_qty"] += line["qty"]
                item["low_stock"] = item["on_hand_qty"] <= item["reorder_threshold"]
                touch(item)
            line["voided"] = True

    # settled_total_cents stays 0; recompute derived totals.
    visit_calc.recompute_all(visit)
    visit["settled_total_cents"] = 0
    visit["status"] = "VOIDED"
    touch(visit)
    return success(serializers.studio_visit(visit))
