"""Shared business logic: constants, calculations, and cross-entity cascades.

Implements SCAFFOLD 1.3 (calculation rules) exactly:
- bucket_available:           available_count = standing_count - reserved_count
- inventory_book_vs_survey:   re-baseline on survey post (+ shrink delta)
- order_invoice:              tier discount from the rounded subtotal, half-up
- crew_ticket_pay:            per-line half-up products, then max with floor
- load_unit_tally:            per-class unit weights, capacity cap
- consignment_settlement:     provisional (worst-case returns) and final
- allocation_waterfall:       oldest-cohort-first filling of the eligible pool
- over_reservation_sweep:     youngest-first whole-allocation releases
- buyer_exposure:             sum of invoice totals over SUBMITTED/ALLOCATED
- run_ops_sweeps:             tag expiry, draft-order expiry, backfill, index
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store
from helpers import new_record, touch

# --- Declared enum domains (SCAFFOLD 1.1) -----------------------------------
HEIGHT_CLASSES = ["H_4_5", "H_5_6", "H_6_7", "H_7_8", "H_8_9", "H_9_PLUS"]
SPECIES = ["NOBLE_FIR", "DOUGLAS_FIR", "GRAND_FIR", "NORDMANN_FIR"]
POSTURES = ["PLANNING", "BOOKING", "HARVEST", "SHIPPING", "SETTLEMENT", "CLOSED"]
CULL_REASONS = ["DISEASE", "DAMAGE", "GRADING", "OTHER"]
BUYER_STANDINGS = ["GOOD_STANDING", "CREDIT_HOLD", "CLOSED"]

# --- Declared constants (SCAFFOLD 1.3) --------------------------------------
PIECE_RATE_CENTS = {
    "H_4_5": 180, "H_5_6": 220, "H_6_7": 260,
    "H_7_8": 310, "H_8_9": 380, "H_9_PLUS": 460,
}
MIN_HOURLY_CENTS_PER_WORKER = 1500
LOAD_UNIT_WEIGHT = {
    "H_4_5": 1, "H_5_6": 2, "H_6_7": 3,
    "H_7_8": 5, "H_8_9": 7, "H_9_PLUS": 9,
}
TAG_TTL_HOURS = 48

TIER_1_QTY, TIER_1_PCT = 100, Decimal("0.03")
TIER_2_QTY, TIER_2_PCT = 200, Decimal("0.05")
TIER_3_QTY, TIER_3_PCT = 500, Decimal("0.08")


def round_half_up(value):
    """Round a Decimal/int to whole cents (integer), half-up (PRD 2.9)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Relational helpers
# ---------------------------------------------------------------------------

def lot_of_bucket(bucket):
    return store.crop_lots[bucket["crop_lot_id"]]


def block_of_lot(lot):
    return store.blocks[lot["block_id"]]


def season_of_block(block):
    return store.seasons[block["season_id"]]


def season_of_lot(lot):
    return season_of_block(block_of_lot(lot))


def season_of_bucket(bucket):
    return season_of_lot(lot_of_bucket(bucket))


def buckets_of_lot(lot_id):
    """The lot's six buckets in declared height-class order (PRD 2.3)."""
    out = [b for b in store.stand_buckets.values() if b["crop_lot_id"] == lot_id]
    out.sort(key=lambda b: HEIGHT_CLASSES.index(b["height_class"]))
    return out


def allocations_of_order(order_id):
    out = [a for a in store.allocations.values() if a["order_id"] == order_id]
    out.sort(key=lambda a: a["_seq"])
    return out


def buyer_exposure_cents(buyer_id):
    """Sum of invoice_total_cents over the buyer's SUBMITTED/ALLOCATED orders
    (DRAFT/CLOSED/CANCELLED/EXPIRED excluded) — SCAFFOLD buyer_exposure."""
    total = 0
    for o in store.orders.values():
        if o["buyer_account_id"] == buyer_id and o["status"] in ("SUBMITTED", "ALLOCATED"):
            total += o["invoice_total_cents"] or 0
    return total


# ---------------------------------------------------------------------------
# Order status bookkeeping
# ---------------------------------------------------------------------------

def recompute_order_status(order):
    """Drive the automatic WholesaleOrder transitions after allocation changes.

    SUBMITTED -> ALLOCATED when allocated_qty reaches quantity;
    ALLOCATED -> SUBMITTED when a release/sweep drops it below quantity.
    """
    if order["status"] == "SUBMITTED" and order["allocated_qty"] == order["quantity"]:
        order["status"] = "ALLOCATED"
    elif order["status"] == "ALLOCATED" and order["allocated_qty"] < order["quantity"]:
        order["status"] = "SUBMITTED"


def maybe_close_order(order):
    """ALLOCATED -> CLOSED when fully allocated and every non-RELEASED
    allocation is LOADED (triggered by load line-adds)."""
    if order["status"] != "ALLOCATED":
        return
    if order["allocated_qty"] != order["quantity"]:
        return
    open_allocs = [a for a in allocations_of_order(order["id"]) if a["status"] != "RELEASED"]
    if open_allocs and all(a["status"] == "LOADED" for a in open_allocs):
        order["status"] = "CLOSED"
        touch(order)


# ---------------------------------------------------------------------------
# CropLot auto-depletion (SCAFFOLD CropLot state machine)
# ---------------------------------------------------------------------------

def check_lot_depleted(lot):
    """ACTIVE -> DEPLETED once every bucket has zero standing, zero reserved,
    and zero active tags. Fires after any consumption event."""
    if lot["status"] != "ACTIVE":
        return
    for b in buckets_of_lot(lot["id"]):
        if (b["standing_count"] != 0 or b["reserved_count"] != 0
                or b["tagged_active_count"] != 0):
            return
    lot["status"] = "DEPLETED"
    touch(lot)


# ---------------------------------------------------------------------------
# Allocation waterfall + over-reservation sweep
# ---------------------------------------------------------------------------

def eligible_buckets(order):
    """Buckets of the order's season matching species+height_class on ACTIVE
    lots with availability, ranked oldest cohort first (planted_year ASC,
    lot created_at ASC, bucket created_at ASC)."""
    out = []
    for b in store.stand_buckets.values():
        lot = store.crop_lots[b["crop_lot_id"]]
        block = store.blocks[lot["block_id"]]
        if block["season_id"] != order["season_id"]:
            continue
        if lot["species"] != order["species"]:
            continue
        if b["height_class"] != order["height_class"]:
            continue
        if lot["status"] != "ACTIVE":
            continue
        if b["standing_count"] - b["reserved_count"] <= 0:
            continue
        out.append(b)
    out.sort(key=lambda b: (
        store.crop_lots[b["crop_lot_id"]]["planted_year"],
        store.crop_lots[b["crop_lot_id"]]["_seq"],
        b["_seq"],
    ))
    return out


def waterfall(order, want_qty):
    """Reserve up to min(want_qty, unallocated remainder) across the ranked
    eligible pool. Returns (allocated_now, allocation_ids). Partial fills
    persist; a zero fill leaves no trace."""
    remaining = min(want_qty, order["quantity"] - order["allocated_qty"])
    if remaining < 0:
        remaining = 0
    allocated_now = 0
    ids = []
    for b in eligible_buckets(order):
        if remaining <= 0:
            break
        take = min(remaining, b["standing_count"] - b["reserved_count"])
        if take <= 0:
            continue
        alloc = new_record({
            "order_id": order["id"],
            "bucket_id": b["id"],
            "quantity": take,
            "cut_qty": 0,
            "loaded_qty": 0,
            "status": "RESERVED",
        })
        store.allocations[alloc["id"]] = alloc
        b["reserved_count"] += take
        touch(b)
        remaining -= take
        allocated_now += take
        ids.append(alloc["id"])
    return allocated_now, ids


def release_allocation(alloc):
    """RESERVED -> RELEASED: return the uncut reservation to the bucket and
    deduct the allocation from the order; an ALLOCATED order regresses."""
    bucket = store.stand_buckets[alloc["bucket_id"]]
    uncut = alloc["quantity"] - alloc["cut_qty"]
    if uncut > 0:
        bucket["reserved_count"] -= uncut
        touch(bucket)
    alloc["status"] = "RELEASED"
    touch(alloc)
    order = store.orders[alloc["order_id"]]
    order["allocated_qty"] -= alloc["quantity"]
    recompute_order_status(order)
    touch(order)


def over_reservation_sweep(bucket):
    """After a survey re-baseline: while reserved exceeds standing, release
    whole RESERVED allocations youngest-first (created_at DESC). CUT/LOADED
    allocations are never swept."""
    while bucket["reserved_count"] > bucket["standing_count"]:
        candidates = [a for a in store.allocations.values()
                      if a["bucket_id"] == bucket["id"] and a["status"] == "RESERVED"]
        if not candidates:
            break
        candidates.sort(key=lambda a: -a["_seq"])
        release_allocation(candidates[0])


# ---------------------------------------------------------------------------
# Invoice + payroll + settlement calculations
# ---------------------------------------------------------------------------

def compute_invoice(quantity, unit_price_cents):
    """order_invoice: exact integer subtotal; tier by quantity (>= inclusive);
    discount from the rounded subtotal, rounded half-up (pinned order)."""
    subtotal = quantity * unit_price_cents
    if quantity >= TIER_3_QTY:
        pct = TIER_3_PCT
    elif quantity >= TIER_2_QTY:
        pct = TIER_2_PCT
    elif quantity >= TIER_1_QTY:
        pct = TIER_1_PCT
    else:
        pct = Decimal("0")
    discount = round_half_up(Decimal(subtotal) * pct)
    total = subtotal - discount
    pct_out = float(pct) if pct != 0 else 0
    return subtotal, pct_out, discount, total


def compute_ticket_pay(lines_with_class, crew_size, hours_worked):
    """crew_ticket_pay: per-line round_half_up(cut_count * rate) summed first;
    floor = size * hours * 1500; gross = max(piece, floor); tie -> PIECE."""
    piece_total = 0
    for height_class, cut_count in lines_with_class:
        piece_total += round_half_up(Decimal(cut_count) * PIECE_RATE_CENTS[height_class])
    floor = round_half_up(
        Decimal(crew_size) * Decimal(str(hours_worked)) * MIN_HOURLY_CENTS_PER_WORKER)
    gross = max(piece_total, floor)
    basis = "PIECE" if piece_total >= floor else "HOURLY_FLOOR"
    return piece_total, floor, gross, basis


def provisional_settlement(delivered_count, unit_price_cents, max_return_pct):
    """consignment_settlement provisional variant: worst-case returns at the
    contractual max_return_pct, rounded half-up."""
    pct = Decimal(str(max_return_pct))
    return round_half_up(Decimal(delivered_count) * Decimal(unit_price_cents)
                         * (Decimal("1") - pct))


def final_settlement(delivered_count, returned_count, unit_price_cents):
    """consignment_settlement final variant: observed returns, rounded half-up."""
    return round_half_up(Decimal(delivered_count - returned_count)
                         * Decimal(unit_price_cents))


def load_line_units(height_class, quantity):
    return quantity * LOAD_UNIT_WEIGHT[height_class]


# ---------------------------------------------------------------------------
# run-ops checkpoint (SCAFFOLD run_ops_sweeps)
# ---------------------------------------------------------------------------

def run_ops_sweeps(season):
    """The four ordered steps of POST /seasons/{id}/run-ops (PRD 3.8)."""
    clk = store.clock
    season_block_ids = {b["id"] for b in store.blocks.values()
                        if b["season_id"] == season["id"]}

    # 1. Expire every ACTIVE tag whose expires_at is at or before the clock.
    for tag in sorted(store.tags.values(), key=lambda t: t["_seq"]):
        if (tag["block_id"] in season_block_ids and tag["status"] == "ACTIVE"
                and tag["expires_at"] <= clk):
            bucket = store.stand_buckets[tag["bucket_id"]]
            bucket["tagged_active_count"] -= 1
            bucket["standing_count"] += 1
            touch(bucket)
            tag["status"] = "EXPIRED"
            touch(tag)

    # 2. Expire every DRAFT order once the clock is past booking_close_at.
    if clk > season["booking_close_at"]:
        for o in sorted(store.orders.values(), key=lambda o: o["_seq"]):
            if o["season_id"] == season["id"] and o["status"] == "DRAFT":
                o["status"] = "EXPIRED"
                touch(o)

    # 3. Backfill SUBMITTED orders (BOOKING/HARVEST only), oldest
    #    submitted_at first, created_at ASC as tie-break.
    if season["posture"] in ("BOOKING", "HARVEST"):
        candidates = [o for o in store.orders.values()
                      if o["season_id"] == season["id"]
                      and o["status"] == "SUBMITTED"
                      and o["allocated_qty"] < o["quantity"]]
        candidates.sort(key=lambda o: (o["submitted_at"], o["_seq"]))
        for o in candidates:
            allocated_now, _ids = waterfall(o, o["quantity"] - o["allocated_qty"])
            if allocated_now > 0:
                o["allocated_qty"] += allocated_now
                recompute_order_status(o)
                touch(o)

    # 4. The checkpoint counter.
    season["ops_run_index"] += 1
    touch(season)


def tag_expiry_instant(created_dt):
    return created_dt + timedelta(hours=TAG_TTL_HOURS)
