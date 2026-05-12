"""Settlement, refund, and payout-batch logic."""
import math
from decimal import Decimal

import db
from clock import now, parse_iso, iso
from errors import err
from services.audit import audit
from services.constants import (
    DIST_FREE_KM, DIST_PRICE_PER_KM_CENTS,
    DAY_BPS, NIGHT_BPS, WEEKEND_BPS, TAX_BPS,
    REFUND_WINDOW_HOURS,
)
from services.util import round_half_up_int, check_occ


def _tod_multiplier_bps(dt) -> int:
    h = dt.hour
    if h < 6 or h >= 22:
        return NIGHT_BPS
    if dt.weekday() >= 5:
        return WEEKEND_BPS
    return DAY_BPS


def _surcharge(base: int, multiplier_bps: int) -> int:
    if multiplier_bps == DAY_BPS:
        return 0
    delta = multiplier_bps - DAY_BPS
    return round_half_up_int(Decimal(base) * Decimal(delta) / Decimal(10000))


def _distance_surcharge(distance_km: float) -> int:
    excess = max(0.0, float(distance_km) - DIST_FREE_KM)
    return int(math.ceil(excess)) * DIST_PRICE_PER_KM_CENTS


# --------------------------------------------------- Final settlement --
def build_final_settlement(order: dict, sr: dict) -> dict:
    item = db.service_items.get(order["service_item_code"])
    base = int(item["base_price_cents"])
    # Find ACCEPTED dispatch
    nurse_id = None
    distance_km = 0.0
    for d in db.dispatches.values():
        if d.get("order_id") == order["id"] and d.get("status") == "ACCEPTED":
            nurse_id = d.get("nurse_id")
            distance_km = float(d.get("distance_km") or 0.0)
            break
    nurse = db.nurses.get(nurse_id or "")
    revenue_share_bps = int((nurse or {}).get("revenue_share_bps") or 7000)

    distance_surcharge = _distance_surcharge(distance_km)
    checkin_dt = parse_iso(sr["checkin_at"])
    multiplier = _tod_multiplier_bps(checkin_dt)
    tod_surcharge = _surcharge(base, multiplier)

    # Package deduction: base if package_id present and order's package was active when used
    package_deduction = 0
    if order.get("package_id"):
        pkg = db.packages.get(order["package_id"])
        if pkg is not None:
            package_deduction = base

    gross = max(0, base + distance_surcharge + tod_surcharge - package_deduction)
    tax = round_half_up_int(Decimal(gross) * Decimal(TAX_BPS) / Decimal(10000))
    nurse_share = round_half_up_int(Decimal(gross) * Decimal(revenue_share_bps) / Decimal(10000))
    platform_share = gross - nurse_share

    settlement = {
        "order_id": order["id"],
        "gross_fee_cents": gross,
        "distance_surcharge_cents": distance_surcharge,
        "time_of_day_surcharge_cents": tod_surcharge,
        "package_deduction_cents": package_deduction,
        "refund_cents": 0,
        "tax_cents": tax,
        "nurse_revenue_share_cents": nurse_share,
        "platform_share_cents": platform_share,
        "payout_batch_id": None,
        "status": "FINALIZED",
    }
    db.stamp_create(settlement, common_fields=False)
    db.settlements[settlement["id"]] = settlement
    return settlement


def get_settlement_for_order(order_id: str):
    for s in db.settlements.values():
        if s.get("order_id") == order_id:
            return s
    return None


# ---------------------------------------------------------- Refund --
def refund_order(order_id: str, body: dict) -> dict:
    from services.order import get_order
    order = get_order(order_id)
    if order["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", f"order is {order['status']}")
    settlement = get_settlement_for_order(order_id)
    if settlement is None:
        raise err("ERR_INVALID_STATE", "no settlement for order")
    if settlement["status"] not in ("FINALIZED", "PAID_OUT"):
        raise err("ERR_INVALID_STATE", f"settlement is {settlement['status']}")

    sr = None
    for r in db.service_records.values():
        if r.get("order_id") == order_id:
            sr = r
            break
    if sr is None or not sr.get("completed_at"):
        raise err("ERR_INVALID_STATE", "no completed service record")

    completed_dt = parse_iso(sr["completed_at"])
    elapsed_hours = (now() - completed_dt).total_seconds() / 3600.0
    if elapsed_hours > REFUND_WINDOW_HOURS:
        raise err("ERR_REFUND_WINDOW_EXPIRED", "refund window expired")

    check_occ(order, body or {})

    total = int(settlement["gross_fee_cents"]) + int(settlement["tax_cents"])
    if elapsed_hours <= 1.0:
        refund = total
    elif elapsed_hours <= 6.0:
        refund = round_half_up_int(Decimal(total) * Decimal("0.5"))
    elif elapsed_hours <= 24.0:
        refund = round_half_up_int(Decimal(total) * Decimal("0.2"))
    else:
        raise err("ERR_REFUND_WINDOW_EXPIRED", "refund window expired")

    settlement["refund_cents"] = refund
    prior_status = settlement["status"]
    settlement["status"] = "REVERSED"
    if order.get("payment_status") == "CAPTURED":
        order["payment_status"] = "REFUNDED"
        db.stamp_update(order)
    audit("ORDER", order_id, "REFUND",
          payload={"refund_cents": refund, "prior_settlement_status": prior_status})
    return settlement


# -------------------------------------------------- Payout batch --
def build_payout_batch(body: dict) -> dict:
    from services.util import require_str
    cutoff_raw = require_str(body, "cutoff_at")
    try:
        cutoff_dt = parse_iso(cutoff_raw)
    except ValueError as e:
        raise err("ERR_INVALID_REQUEST", str(e))

    # Concurrency: any BUILDING batch -> reject
    for b in db.payout_batches.values():
        if b.get("status") == "BUILDING":
            raise err("ERR_PAYOUT_BATCH_ALREADY_BUILDING",
                      "another payout batch is already BUILDING")

    batch = {
        "cutoff_at": iso(cutoff_dt),
        "total_settlements": 0,
        "total_nurse_share_cents": 0,
        "total_platform_share_cents": 0,
        "status": "BUILDING",
    }
    db.stamp_create(batch, common_fields=False)
    db.payout_batches[batch["id"]] = batch

    cutoff_iso = batch["cutoff_at"]
    eligible = [
        s for s in db.settlements.values()
        if s.get("status") == "FINALIZED"
        and s.get("payout_batch_id") is None
        and s.get("created_at") <= cutoff_iso
    ]
    for s in eligible:
        s["payout_batch_id"] = batch["id"]
        s["status"] = "PAID_OUT"
        batch["total_settlements"] += 1
        batch["total_nurse_share_cents"] += int(s["nurse_revenue_share_cents"])
        batch["total_platform_share_cents"] += int(s["platform_share_cents"])

    batch["status"] = "PAID"
    return batch


def list_payout_batches(limit: int, offset: int):
    rows = list(db.payout_batches.values())
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total
