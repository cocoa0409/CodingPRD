"""Sale lots, weight tickets, finalize (sell) and withdraw."""
from flask import Blueprint, request

import errors
from db import db
from clock import clock
from middleware import authenticate, require_role
from response import object_response, array_response
from util import (get_json_body, as_str, as_enum, as_number, as_int,
                  round_half_up, parse_pagination, paginate)
from services.common import base_record, get_or_404, touch
from services import serializers as S
from services import domain

bp = Blueprint("sales", __name__)

CHANNELS = {"AUCTION", "PRIVATE_TREATY"}

PRICE_LIGHT = 520.00
PRICE_MEDIUM = 480.00
PRICE_HEAVY = 440.00
TIER_LIGHT_MAX = 250
TIER_MEDIUM_MAX = 400


# ---------------------------------------------------------------- sale lots
@bp.route("/sale-lots", methods=["POST"])
def create_sale_lot():
    role = authenticate()
    require_role(role, {"SaleClerk"})
    body = get_json_body()

    herd_id = as_str(body, "herd_id")
    get_or_404(db.herds, herd_id)
    channel = as_enum(body, "channel", CHANNELS)
    pencil_shrink = as_number(body, "pencil_shrink_pct", required=False, default=0,
                              ge=0, le=0.10)
    commission = as_number(body, "commission_pct", required=False, default=0,
                           ge=0, le=0.20)

    # PRIVATE_TREATY must have commission_pct == 0 (priority 13)
    if channel == "PRIVATE_TREATY" and commission != 0:
        raise errors.ApiError(errors.ERR_COMMISSION_NOT_ALLOWED, 422,
                              "PRIVATE_TREATY lots may not carry commission")

    rec = base_record()
    rec.update({
        "herd_id": herd_id,
        "channel": channel,
        "pencil_shrink_pct": pencil_shrink,
        "commission_pct": commission,
        "head_count": 0,
        "gross_sale_amount": 0.0,
        "commission_amount": 0.0,
        "net_proceeds": 0.0,
        "status": "OPEN",
    })
    db.sale_lots[rec["id"]] = rec
    return object_response(S.sale_lot_out(rec), 201)


@bp.route("/sale-lots/<sid>", methods=["GET"])
def get_sale_lot(sid):
    role = authenticate()
    require_role(role, {"SaleClerk", "HerdManager", "Auditor"})
    s = get_or_404(db.sale_lots, sid)
    return object_response(S.sale_lot_out(s), 200)


@bp.route("/sale-lots", methods=["GET"])
def list_sale_lots():
    role = authenticate()
    require_role(role, {"SaleClerk", "HerdManager", "Auditor"})
    limit, offset = parse_pagination()
    herd_id = request.args.get("herd_id")
    items = list(db.sale_lots.values())
    if herd_id is not None:
        items = [s for s in items if s["herd_id"] == herd_id]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.sale_lot_out(s) for s in window], limit, offset, total)


def _tickets_of_lot(lot_id):
    return [t for t in db.weight_tickets.values() if t["sale_lot_id"] == lot_id]


# ---------------------------------------------------------------- tickets
@bp.route("/sale-lots/<sid>/tickets", methods=["POST"])
def add_ticket(sid):
    role = authenticate()
    require_role(role, {"SaleClerk"})
    lot = get_or_404(db.sale_lots, sid)
    body = get_json_body()

    # FK existence: animal
    animal_id = as_str(body, "animal_id")
    animal = get_or_404(db.animals, animal_id)
    # shape
    gross_weight = as_number(body, "gross_weight_kg", gt=0)
    expected_version = as_int(body, "expected_sale_lot_version", required=True)

    # state (priority 5): lot must be OPEN
    if lot["status"] != "OPEN":
        raise errors.invalid_state("lot must be OPEN to attach tickets")

    # residue safety (priority 8): WITHHELD blocks
    if animal["meat_clearance_status"] == "WITHHELD":
        raise errors.ApiError(errors.ERR_WITHDRAWAL_NOT_CLEARED, 409,
                              "animal is under meat withdrawal")
    # animal must be ACTIVE
    if animal["life_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_ANIMAL_NOT_ACTIVE, 409,
                              "animal must be ACTIVE to be ticketed")

    # already on another OPEN lot (priority 10)
    for t in db.weight_tickets.values():
        if t["animal_id"] != animal_id:
            continue
        other_lot = db.sale_lots.get(t["sale_lot_id"])
        if other_lot is not None and other_lot["status"] == "OPEN":
            raise errors.ApiError(errors.ERR_ANIMAL_ALREADY_LISTED, 409,
                                  "animal is already on an OPEN sale lot")

    # OCC (priority 16)
    if expected_version != lot["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "sale lot version is stale")

    # herd match (priority 17)
    if animal["herd_id"] != lot["herd_id"]:
        raise errors.ApiError(errors.ERR_HERD_MISMATCH, 409,
                              "animal's herd differs from the lot's herd")

    # pricing at ticket creation
    net_weight = round_half_up(gross_weight * (1 - lot["pencil_shrink_pct"]), 3)
    if net_weight < TIER_LIGHT_MAX:
        price = PRICE_LIGHT
    elif net_weight < TIER_MEDIUM_MAX:
        price = PRICE_MEDIUM
    else:
        price = PRICE_HEAVY
    gross_line = round_half_up(net_weight / 100 * price, 2)

    rec = base_record()
    rec.update({
        "sale_lot_id": sid,
        "animal_id": animal_id,
        "gross_weight_kg": gross_weight,
        "price_per_100kg": round_half_up(price, 2),
        "net_weight_kg": net_weight,
        "gross_line_amount": gross_line,
    })
    db.weight_tickets[rec["id"]] = rec

    # increment head_count and version
    lot["head_count"] += 1
    touch(lot)  # bumps version by 1

    return object_response(S.weight_ticket_out(rec), 201)


@bp.route("/sale-lots/<sid>/tickets", methods=["GET"])
def list_lot_tickets(sid):
    role = authenticate()
    require_role(role, {"SaleClerk", "HerdManager", "Auditor"})
    get_or_404(db.sale_lots, sid)
    limit, offset = parse_pagination()
    items = _tickets_of_lot(sid)
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.weight_ticket_out(t) for t in window], limit, offset, total)


# ---------------------------------------------------------------- sell / withdraw
@bp.route("/sale-lots/<sid>/sell", methods=["POST"])
def sell_lot(sid):
    role = authenticate()
    require_role(role, {"SaleClerk"})
    lot = get_or_404(db.sale_lots, sid)

    if lot["status"] != "OPEN":
        raise errors.invalid_state("only OPEN lots may be sold")

    tickets = _tickets_of_lot(sid)
    if lot["head_count"] == 0 or len(tickets) == 0:
        raise errors.ApiError(errors.ERR_EMPTY_LOT, 409, "cannot sell an empty lot")

    # every linked animal must be ACTIVE + CLEAR (check all before committing)
    for t in tickets:
        animal = db.animals.get(t["animal_id"])
        if animal is None:
            raise errors.not_found("ticketed animal not found")
        if animal["meat_clearance_status"] == "WITHHELD":
            raise errors.ApiError(errors.ERR_WITHDRAWAL_NOT_CLEARED, 409,
                                  "a linked animal is under meat withdrawal")
        if animal["life_status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_ANIMAL_NOT_ACTIVE, 409,
                                  "a linked animal is not ACTIVE")

    # lot totals — sum-then-commission
    gross_sale = round_half_up(sum(t["gross_line_amount"] for t in tickets), 2)
    commission = round_half_up(gross_sale * lot["commission_pct"], 2)
    net = round_half_up(gross_sale - commission, 2)
    lot["gross_sale_amount"] = gross_sale
    lot["commission_amount"] = commission
    lot["net_proceeds"] = net
    lot["status"] = "SOLD"
    touch(lot)

    # cascade: each linked Animal ACTIVE -> SOLD
    affected_herds = set()
    affected_pastures = set()
    for t in tickets:
        animal = db.animals[t["animal_id"]]
        old_pasture = animal.get("current_pasture_id")
        animal["life_status"] = "SOLD"
        touch(animal)
        affected_herds.add(animal["herd_id"])
        if old_pasture:
            affected_pastures.add(old_pasture)
        domain.append_trace(animal["id"], "SALE", "WeightTicket", t["id"], clock.today(),
                            {"sale_lot_id": sid, "gross_line_amount": t["gross_line_amount"]})

    for hid in affected_herds:
        h = db.herds[hid]
        domain.recompute_herd_loads(h)
        touch(h)
    for pid in affected_pastures:
        domain.recompute_pasture_by_id(pid)

    return object_response(S.sale_lot_out(lot), 200)


@bp.route("/sale-lots/<sid>/withdraw", methods=["POST"])
def withdraw_lot(sid):
    role = authenticate()
    require_role(role, {"SaleClerk"})
    lot = get_or_404(db.sale_lots, sid)
    if lot["status"] != "OPEN":
        raise errors.invalid_state("only OPEN lots may be withdrawn")
    lot["status"] = "WITHDRAWN"
    touch(lot)
    return object_response(S.sale_lot_out(lot), 200)


# ---------------------------------------------------------------- weight tickets (top-level)
@bp.route("/weight-tickets/<tid>", methods=["GET"])
def get_weight_ticket(tid):
    role = authenticate()
    require_role(role, {"SaleClerk", "HerdManager", "Auditor"})
    t = get_or_404(db.weight_tickets, tid)
    return object_response(S.weight_ticket_out(t), 200)


@bp.route("/weight-tickets", methods=["GET"])
def list_weight_tickets():
    role = authenticate()
    require_role(role, {"SaleClerk", "HerdManager", "Auditor"})
    limit, offset = parse_pagination()
    animal_id = request.args.get("animal_id")
    sale_lot_id = request.args.get("sale_lot_id")
    items = list(db.weight_tickets.values())
    if animal_id is not None:
        items = [t for t in items if t["animal_id"] == animal_id]
    if sale_lot_id is not None:
        items = [t for t in items if t["sale_lot_id"] == sale_lot_id]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.weight_ticket_out(t) for t in window], limit, offset, total)
