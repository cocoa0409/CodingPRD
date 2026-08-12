"""Lots: sorting, penning, the ring, quarantine and the gate (PRD 3.3-3.9)."""
from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, check_min, enum_field, fields, path_row, reference
from clock import clock, render_instant
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from money import D, q2
from services import invoices as inv_svc
from services.bidding import lot_bids
from services.consignments import maybe_sorted
from services.inspections import (mark_ready_documents, release_documents,
                                  require_documents)
from services.lots import lot_extension
from services.pens import recompute_pens
from store import db, get, insert_versioned, touch

bp = Blueprint("lots", __name__)
ALL = config.ALL_ROLES


def _context(lot):
    consignment = get("consignments", lot["consignment_id"])
    sale_day = get("sale_days", lot["sale_day_id"])
    party = get("parties", consignment["consignor_party_id"]) if consignment else None
    return consignment, sale_day, party


# ----------------------------------------------------------------- create --
@bp.post("/sale-barn/lots")
def create_lot():
    actor(["YardOperator"])
    data = body()
    v = fields(data, required=[
        ("consignment_id", "string"),
        ("head_count", "integer"),
        ("livestock_class", "string"),
        ("bid_basis", "string"),
        ("opening_bid", "number"),
        ("reserve_price", "number"),
    ])
    livestock_class = enum_field(data, "livestock_class", config.LIVESTOCK_CLASSES)
    bid_basis = enum_field(data, "bid_basis", config.BID_BASES)
    check_min(v["head_count"], 1, "head_count")
    check_min(v["opening_bid"], 0, "opening_bid", inclusive=False)
    check_min(v["reserve_price"], 0, "reserve_price")

    consignment = reference("consignments", v["consignment_id"], "Consignment")
    sale_day = get("sale_days", consignment["sale_day_id"])
    party = get("parties", consignment["consignor_party_id"])
    run_gates("lots.create", sale_day=sale_day, party=party)

    if v["head_count"] > consignment["head_unassigned"]:
        fail("ERR_HEAD_COUNT_EXCEEDED")

    row = insert_versioned("lots", {
        "consignment_id": consignment["id"],
        "sale_day_id": consignment["sale_day_id"],
        "pen_id": None,
        "head_count": v["head_count"],
        "livestock_class": livestock_class,
        "bid_basis": bid_basis,
        "opening_bid": D(v["opening_bid"]),
        "reserve_price": D(v["reserve_price"]),
        "destination_state_code": None,
        "ring_order": None,
        "sale_status": "DRAFT",
        "custody_status": "BARN",
        "quarantine_hold": False,
        "rering_count": 0,
        "gross_weight_lb": None,
        "tare_weight_lb": None,
        "net_weight_lb": None,
        "settle_weight_lb": None,
        "avg_weight_lb": None,
        "weight_class": "NONE",
        "hammer_price": None,
        "extended_amount": q2(0),
        "buy_back": False,
        "penned_at": None,
        "released_at": None,
        "_released_dt": None,
    })
    consignment["head_unassigned"] -= v["head_count"]
    touch(consignment)
    maybe_sorted(consignment, touch)
    return ok(serialize.lot(row), 201)


@bp.get("/sale-barn/lots/<lot_id>")
def read_lot(lot_id):
    actor(ALL)
    return ok(serialize.lot(path_row("lots", lot_id, "Lot")))


@bp.get("/sale-barn/lots")
def list_lots():
    actor(ALL)
    rows = list(db["lots"].values())
    for key in ("consignment_id", "sale_day_id", "pen_id", "sale_status",
                "custody_status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.lot)


# ------------------------------------------------------------- assign-pen --
@bp.post("/sale-barn/lots/<lot_id>/assign-pen")
def assign_pen(lot_id):
    actor(["YardOperator"])
    lot = path_row("lots", lot_id, "Lot")
    data = body()
    v = fields(data, required=[("pen_id", "string")])
    pen = reference("pens", v["pen_id"], "Pen")
    consignment, sale_day, party = _context(lot)
    run_gates("lots.assign_pen", sale_day=sale_day, lot=lot, party=party)
    if lot["sale_status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    _pen_admission(lot, pen, consignment)
    lot["pen_id"] = pen["id"]
    lot["penned_at"] = render_instant(clock.now())
    lot["sale_status"] = "PENNED"
    touch(lot)
    recompute_pens(pen["id"])
    return ok(serialize.lot(lot))


def _pen_admission(lot, pen, consignment):
    """Rungs 22, 23 and 24, in ladder order."""
    if consignment is not None and pen["species_class"] != consignment["species_class"]:
        fail("ERR_PEN_SPECIES_MISMATCH")
    if pen["status"] == "OUT_OF_SERVICE":
        fail("ERR_INVALID_STATE")
    if pen["current_head"] + lot["head_count"] > pen["head_capacity"]:
        fail("ERR_PEN_CAPACITY_EXCEEDED")


# ------------------------------------------------------------- mark-ready --
@bp.post("/sale-barn/lots/<lot_id>/mark-ready")
def mark_ready(lot_id):
    actor(["YardOperator"])
    lot = path_row("lots", lot_id, "Lot")
    consignment, sale_day, party = _context(lot)
    run_gates("lots.mark_ready", sale_day=sale_day, lot=lot, party=party)
    if lot["sale_status"] != "PENNED":
        fail("ERR_INVALID_STATE")
    if lot.get("settle_weight_lb") is None:
        fail("ERR_SETTLE_WEIGHT_MISSING")
    require_documents(lot, mark_ready_documents(lot))
    lot["sale_status"] = "READY"
    lot["ring_order"] = sale_day["next_ring_order"]
    sale_day["next_ring_order"] = sale_day["next_ring_order"] + config.RING_ORDER_STEP
    touch(sale_day)
    touch(lot)
    return ok(serialize.lot(lot))


# ------------------------------------------------------------- enter-ring --
@bp.post("/sale-barn/lots/<lot_id>/enter-ring")
def enter_ring(lot_id):
    actor(["Auctioneer"])
    lot = path_row("lots", lot_id, "Lot")
    consignment, sale_day, party = _context(lot)
    run_gates("lots.enter_ring", sale_day=sale_day, lot=lot, party=party)
    if lot["sale_status"] != "READY" or sale_day["status"] != "RINGING":
        fail("ERR_INVALID_STATE")
    lot["sale_status"] = "IN_RING"
    touch(lot)
    return ok(serialize.lot(lot))


# ------------------------------------------------------------ hammer-down --
@bp.post("/sale-barn/lots/<lot_id>/hammer-down")
def hammer_down(lot_id):
    actor(["Auctioneer"])
    lot = path_row("lots", lot_id, "Lot")
    data = body()
    v = fields(data,
               required=[("winning_bid_id", "string"),
                         ("expected_lot_version", "integer")],
               optional=[("buy_back", "boolean")])
    bid = reference("bids", v["winning_bid_id"], "Bid")
    consignment, sale_day, party = _context(lot)

    # Rung 8: the named bid's registration and this lot share a sale day.
    reg = get("buyer_registrations", bid["buyer_registration_id"])
    if reg is not None and reg["sale_day_id"] != lot["sale_day_id"]:
        fail("ERR_SALE_DAY_MISMATCH")

    # Rung 10: optimistic concurrency on the lot, BEFORE all five gates.
    if v["expected_lot_version"] != lot["version"]:
        fail("ERR_STALE_VERSION")

    run_gates("lots.hammer_down", sale_day=sale_day, lot=lot, party=party)

    if lot["sale_status"] != "IN_RING" or sale_day["status"] != "RINGING":
        fail("ERR_INVALID_STATE")
    if bid["status"] != "WINNING" or bid["lot_id"] != lot["id"]:
        fail("ERR_INVALID_STATE")

    buyer_party = get("parties", reg["party_id"]) if reg else None
    is_own_consignor = (reg is not None
                        and consignment is not None
                        and reg["party_id"] == consignment["consignor_party_id"])
    buy_back_elected = bool(v["buy_back"])
    if D(bid["unit_price"]) < D(lot["reserve_price"]):
        if not (buy_back_elected and is_own_consignor):
            fail("ERR_RESERVE_NOT_MET")

    lot["hammer_price"] = D(bid["unit_price"])
    lot["extended_amount"] = lot_extension(lot, bid["unit_price"])
    lot["buy_back"] = bool(is_own_consignor)
    if buyer_party is not None:
        lot["destination_state_code"] = buyer_party["origin_state_code"]
    lot["sale_status"] = "SOLD"
    if lot["custody_status"] == "BARN":
        lot["custody_status"] = "BUYER_PEN"
    touch(lot)

    bid["status"] = "HAMMERED"
    touch(bid)

    invoice = inv_svc.find_or_create_invoice(reg, lot["sale_day_id"], insert_versioned)
    purchase = insert_versioned("purchases", {
        "lot_id": lot["id"],
        "buyer_registration_id": reg["id"],
        "winning_bid_id": bid["id"],
        "buyer_invoice_id": invoice["id"],
        "bid_basis": lot["bid_basis"],
        "unit_price": D(bid["unit_price"]),
        "head_count": lot["head_count"],
        "total_weight_lb": lot.get("settle_weight_lb"),
        "extended_amount": lot["extended_amount"],
        "doa_head": 0,
        "doa_credit_amount": q2(0),
        "status": "CONFIRMED",
    })
    inv_svc.recompute_subtotal_only(invoice)
    return ok(serialize.purchase(purchase), 201)


# ---------------------------------------------------------------- no-sale --
@bp.post("/sale-barn/lots/<lot_id>/no-sale")
def no_sale(lot_id):
    actor(["Auctioneer"])
    lot = path_row("lots", lot_id, "Lot")
    consignment, sale_day, party = _context(lot)
    run_gates("lots.no_sale", sale_day=sale_day, lot=lot, party=party)
    if lot["sale_status"] != "IN_RING":
        fail("ERR_INVALID_STATE")
    lot["sale_status"] = "NO_SALE"
    touch(lot)
    for bid in lot_bids(lot["id"]):
        if bid["status"] == "WINNING":
            bid["status"] = "VOIDED"
            touch(bid)
    return ok(serialize.lot(lot))


# ---------------------------------------------------------------- re-ring --
@bp.post("/sale-barn/lots/<lot_id>/re-ring")
def re_ring(lot_id):
    actor(["Auctioneer"])
    lot = path_row("lots", lot_id, "Lot")
    consignment, sale_day, party = _context(lot)
    run_gates("lots.re_ring", sale_day=sale_day, lot=lot, party=party)
    if lot["sale_status"] != "NO_SALE" or sale_day["status"] != "RINGING":
        fail("ERR_INVALID_STATE")
    if lot["rering_count"] >= config.MAX_RERING_COUNT:
        fail("ERR_RERING_LIMIT_EXCEEDED")
    lot["rering_count"] += 1
    lot["sale_status"] = "READY"
    lot["ring_order"] = sale_day["next_ring_order"]
    sale_day["next_ring_order"] = sale_day["next_ring_order"] + config.RING_ORDER_STEP
    touch(sale_day)
    touch(lot)
    return ok(serialize.lot(lot))


# ------------------------------------------------------------- quarantine --
@bp.post("/sale-barn/lots/<lot_id>/quarantine")
def quarantine(lot_id):
    actor(["YardOperator"])
    lot = path_row("lots", lot_id, "Lot")
    data = body()
    v = fields(data, required=[("hold", "boolean")])
    consignment, sale_day, party = _context(lot)
    # Exempt from G2 itself, which is what keeps the lift reachable.
    run_gates("lots.quarantine", sale_day=sale_day, lot=lot, party=party)
    lot["quarantine_hold"] = bool(v["hold"])
    touch(lot)
    return ok(serialize.lot(lot))


# ---------------------------------------------------------------- release --
@bp.post("/sale-barn/lots/<lot_id>/release")
def release(lot_id):
    actor(["YardOperator"])
    lot = path_row("lots", lot_id, "Lot")
    consignment, sale_day, party = _context(lot)
    run_gates("lots.release", sale_day=sale_day, lot=lot, party=party)
    if lot["custody_status"] != "LOADED":
        fail("ERR_INVALID_STATE")

    require_documents(lot, release_documents(lot, sale_day))

    # Rung 41: the lot must sit on a DISPATCHED or DELIVERED manifest.
    assigned = False
    for line in db["load_lines"].values():
        if line["lot_id"] != lot["id"]:
            continue
        manifest = get("load_manifests", line["load_manifest_id"])
        if manifest is not None and manifest["status"] in ("DISPATCHED", "DELIVERED"):
            assigned = True
            break
    if not assigned:
        fail("ERR_LOAD_NOT_ASSIGNED")

    # Rung 42: the buying registration is bonded, or the invoice is PAID.
    if not _funds_cleared(lot):
        fail("ERR_FUNDS_NOT_CLEARED")

    pen_id = lot.get("pen_id")
    lot["custody_status"] = "RELEASED"
    lot["released_at"] = render_instant(clock.now())
    lot["_released_dt"] = clock.now()
    touch(lot)
    recompute_pens(pen_id)
    return ok(serialize.lot(lot))


def _funds_cleared(lot):
    for purchase in sorted(db["purchases"].values(), key=lambda p: p["_seq"]):
        if purchase["lot_id"] != lot["id"] or purchase["status"] == "VOIDED":
            continue
        reg = get("buyer_registrations", purchase["buyer_registration_id"])
        if reg is not None and reg["bond_type"] == "BONDED":
            return True
        invoice = get("buyer_invoices", purchase.get("buyer_invoice_id"))
        if invoice is not None and invoice["status"] == "PAID":
            return True
        return False
    return False
