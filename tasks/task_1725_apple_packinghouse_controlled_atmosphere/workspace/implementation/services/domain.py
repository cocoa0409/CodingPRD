"""Domain calculations and cascades (PRD 3; scaffold Tables 2-3).

Constants discovered by the domain spec:
  O2_TOLERANCE_PCT = 0.3            (seal safety / atmosphere alarm threshold)
  ROOM_EMPTY_DAYS = 21              (must_empty_by = actual_opened_at + 21d)
  PRIORITY_OPEN_DAYS = 7            (priority cascade pulls planned_open_date to now + 7d)
  PRIORITY_RELEASE_DAYS = 10        (priority cascade pulls must_release_by to now + 10d)
  DECAY_PRIORITY_THRESHOLD_PCT = 5.0 (inclusive)
  PACKING_CHARGE_PER_CARTON_CENTS = 650
  ESTIMATED_PRICE_FLOOR_CENTS = 1000
  ADVANCE_RATE = 0.60
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.core import new_record, touch
from util import CLOCK, add_days, dec, parse_dt, round_half_up, whole_days_between

O2_TOLERANCE_PCT = Decimal("0.3")
ROOM_EMPTY_DAYS = 21
PRIORITY_OPEN_DAYS = 7
PRIORITY_RELEASE_DAYS = 10
DECAY_PRIORITY_THRESHOLD_PCT = Decimal("5.0")
PACKING_CHARGE_PER_CARTON_CENTS = 650
ESTIMATED_PRICE_FLOOR_CENTS = 1000
ADVANCE_RATE = Decimal("0.60")

ALARM_BONUS = 40
PRIORITY_BONUS = 30
AGE_CAP_DAYS = 20
URGENCY_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Room bins (calc room_bins): derived from ACTIVE allocations
# ---------------------------------------------------------------------------

def bins_allocated(room_id) -> int:
    return sum(
        a["bins"] for a in db["allocations"].values()
        if a["room_id"] == room_id and a["status"] == "ACTIVE"
    )


def room_active_allocations(room_id):
    return [
        a for a in db["allocations"].values()
        if a["room_id"] == room_id and a["status"] == "ACTIVE"
    ]


# ---------------------------------------------------------------------------
# release_priority_score (calc release_priority_score)
# ---------------------------------------------------------------------------

def compute_release_score(room, alloc) -> Decimal:
    now = CLOCK.now()
    score = Decimal("2.0") * dec(room["disorder_index"])
    if room["atmosphere_alarm"]:
        score += ALARM_BONUS
    if room["priority_release"]:
        score += PRIORITY_BONUS
    days_open = 0
    if room["status"] == "OPENED" and room["actual_opened_at"]:
        delta = (now - parse_dt(room["actual_opened_at"])).total_seconds()
        days_open = max(0, math.floor(delta / 86400))
    score += min(AGE_CAP_DAYS, days_open)
    days_remaining = max(0, whole_days_between(CLOCK.now_iso(), alloc["must_release_by"]))
    score += URGENCY_WINDOW_DAYS - min(URGENCY_WINDOW_DAYS, days_remaining)
    return round_half_up(score, 1)


def recompute_room_scores(room):
    """Recompute and store scores of the room's ACTIVE allocations; touch those changed."""
    for alloc in room_active_allocations(room["id"]):
        new_score = compute_release_score(room, alloc)
        if new_score != alloc["release_priority_score"]:
            alloc["release_priority_score"] = new_score
            touch(alloc)


# ---------------------------------------------------------------------------
# Lot aggregates (calc weight_balance, packout_percentage variant actual)
# ---------------------------------------------------------------------------

def lot_completed_runs(lot_id):
    """COMPLETED non-VOIDED runs of the lot (SCHEDULED/CANCELLED/VOIDED excluded)."""
    return [
        r for r in db["packing_runs"].values()
        if r["lot_id"] == lot_id and r["status"] == "COMPLETED"
    ]


def recompute_lot_actual_packout(lot):
    runs = lot_completed_runs(lot["id"])
    if not runs:
        lot["actual_packout_pct"] = None
        return
    packed = sum((dec(r["packed_weight_lbs"]) for r in runs), Decimal("0"))
    total = sum(
        (dec(r["packed_weight_lbs"]) + dec(r["cull_weight_lbs"]) + dec(r["juice_weight_lbs"])
         for r in runs),
        Decimal("0"),
    )
    lot["actual_packout_pct"] = round_half_up(Decimal("100") * packed / total, 1)


# ---------------------------------------------------------------------------
# Allocation release cascade (state_machines.StorageAllocation ACTIVE->RELEASED)
# ---------------------------------------------------------------------------

def release_allocation(alloc, room, reason: str):
    """Shared release cascade for MANUAL / SELECTED / DIVERSION reasons."""
    now = CLOCK.now_iso()
    alloc["status"] = "RELEASED"
    alloc["released_at"] = now
    alloc["release_reason"] = reason
    touch(alloc)

    # Cascade hop 1 (allocation -> room): bins_allocated falls; an OPENED room
    # emptied to zero cycles back to AVAILABLE with clearing.
    if bins_allocated(room["id"]) == 0 and room["status"] in ("OPENED", "FILLING"):
        room["status"] = "AVAILABLE"
        room["atmosphere_alarm"] = False
        room["priority_release"] = False
        room["actual_opened_at"] = None
        room["must_empty_by"] = None
    touch(room)

    # Cascade hop 1 (allocation -> lot): first release moves IN_STORAGE -> RELEASED.
    lot = db["lots"].get(alloc["lot_id"])
    if lot is not None and lot["status"] == "IN_STORAGE":
        lot["status"] = "RELEASED"
        touch(lot)


# ---------------------------------------------------------------------------
# Pool economics (calc pool_price)
# ---------------------------------------------------------------------------

def recompute_pool_totals(pool):
    """total_deductions_cents and the floored estimated price (variant estimated)."""
    pool["total_deductions_cents"] = (
        pool["total_packed_cartons"] * PACKING_CHARGE_PER_CARTON_CENTS
        + pool["total_sale_deductions_cents"]
    )
    cartons = pool["total_packed_cartons"]
    if cartons == 0:
        pool["estimated_price_cents"] = ESTIMATED_PRICE_FLOOR_CENTS
    else:
        net = pool["total_sales_cents"] - pool["total_deductions_cents"]
        est = (Decimal(net) / Decimal(cartons)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        pool["estimated_price_cents"] = max(ESTIMATED_PRICE_FLOOR_CENTS, int(est))


# ---------------------------------------------------------------------------
# Grower settlements (calc settlement_value; auto-creation on run completion)
# ---------------------------------------------------------------------------

def get_settlement(grower_id, pool_id):
    for s in db["settlements"].values():
        if s["grower_id"] == grower_id and s["pool_id"] == pool_id:
            return s
    return None


def get_or_create_settlement(grower_id, pool_id):
    s = get_settlement(grower_id, pool_id)
    if s is None:
        s = new_record("settlements", {
            "grower_id": grower_id,
            "pool_id": pool_id,
            "attributed_cartons": 0,
            "advance_amount_cents": 0,
            "final_payment_cents": 0,
            "paid_final_cents": 0,
            "clawback_cents": 0,
            "status": "ACCRUING",
        })
    return s


def recompute_attributed_cartons(settlement):
    total = 0
    for r in db["packing_runs"].values():
        if r["status"] != "COMPLETED" or r["pool_id"] != settlement["pool_id"]:
            continue
        lot = db["lots"].get(r["lot_id"])
        if lot is not None and lot["grower_id"] == settlement["grower_id"]:
            total += r["cartons_produced"]
    if settlement["attributed_cartons"] != total:
        settlement["attributed_cartons"] = total
        touch(settlement)


# ---------------------------------------------------------------------------
# Pool close / reopen cascades (state_machines.Pool, GrowerSettlement, Lot)
# ---------------------------------------------------------------------------

def settlement_pools_touching_lot(lot_id):
    """Pools the lot has fed via COMPLETED non-VOIDED runs."""
    return {r["pool_id"] for r in lot_completed_runs(lot_id)}


def pool_close_cascade(pool):
    """Hop 1: settle settlements. Hop 2: close PACKED lots fully settled."""
    price = pool["pool_price_per_carton_cents"]
    pool_settlements = sorted(
        (s for s in db["settlements"].values() if s["pool_id"] == pool["id"]),
        key=lambda s: s["_seq"],
    )
    for s in pool_settlements:
        if s["status"] not in ("ACCRUING", "ADVANCE_PAID"):
            continue
        value = s["attributed_cartons"] * price
        delta = value - s["advance_amount_cents"] - s["paid_final_cents"]
        final_payment = max(0, delta)
        s["final_payment_cents"] = final_payment
        s["clawback_cents"] += max(0, -delta)
        s["paid_final_cents"] += final_payment
        s["status"] = "SETTLED"
        touch(s)

    fed_lot_ids = {
        r["lot_id"] for r in db["packing_runs"].values()
        if r["pool_id"] == pool["id"] and r["status"] == "COMPLETED"
    }
    for lot_id in sorted(fed_lot_ids, key=lambda lid: db["lots"][lid]["_seq"]):
        lot = db["lots"].get(lot_id)
        if lot is None or lot["status"] != "PACKED":
            continue
        touching = [
            get_settlement(lot["grower_id"], p)
            for p in settlement_pools_touching_lot(lot_id)
        ]
        if all(s is not None and s["status"] == "SETTLED" for s in touching):
            lot["status"] = "CLOSED"
            touch(lot)


def pool_reopen_cascade(pool):
    """Settlements revert SETTLED -> ADVANCE_PAID; lots revert CLOSED -> PACKED."""
    for s in db["settlements"].values():
        if s["pool_id"] == pool["id"] and s["status"] == "SETTLED":
            s["status"] = "ADVANCE_PAID"
            touch(s)
    fed_lot_ids = {
        r["lot_id"] for r in db["packing_runs"].values()
        if r["pool_id"] == pool["id"] and r["status"] == "COMPLETED"
    }
    for lot_id in fed_lot_ids:
        lot = db["lots"].get(lot_id)
        if lot is not None and lot["status"] == "CLOSED":
            lot["status"] = "PACKED"
            touch(lot)
