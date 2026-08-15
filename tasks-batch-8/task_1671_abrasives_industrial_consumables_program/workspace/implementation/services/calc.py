"""Calculation rules (scaffold 1.3): pricing, lot expiry, billing total,
consumption variance, FEFO allocation, hazard month mass."""
from datetime import date
from decimal import Decimal

from db import db
from util import (
    add_months, last_day_of_month, parse_date, round_half_up_cents, round2, round4,
    to_decimal,
)


# ---------------------------------------------------------------------------
# release_price_at_date: threshold pricing with INCLUSIVE boundaries.
# ---------------------------------------------------------------------------

def price_at(eval_date: date, line: dict, contract: dict) -> int:
    """price_at(eval_date): on/before price_hold_end -> base; on/after
    escalation_effective_date -> round_half_up(base * (1 + escalation_pct));
    in the gap between them -> base. All comparisons at ISO-date granularity."""
    base = int(line["base_unit_price_cents"])
    hold_end = parse_date(contract["price_hold_end"])
    esc_date = parse_date(contract["escalation_effective_date"])
    if eval_date <= hold_end:
        return base
    if eval_date >= esc_date:
        pct = to_decimal(contract["escalation_pct"])
        return round_half_up_cents(Decimal(base) * (Decimal(1) + pct))
    return base


def find_contract_line(contract_id: str, product_id: str):
    for line in db["contract_lines"].values():
        if line["contract_id"] == contract_id and line["product_id"] == product_id:
            return line
    return None


# ---------------------------------------------------------------------------
# lot_expiry_date: EXACT_DAY anniversary vs END_OF_MONTH last day.
# ---------------------------------------------------------------------------

def lot_expiry_date(product: dict, manufacture_date: date):
    months = product.get("shelf_life_months")
    if months is None:
        return None
    target = add_months(manufacture_date, months)  # clamps day-of-month on overflow
    if product.get("shelf_life_policy") == "END_OF_MONTH":
        return last_day_of_month(target)
    return target


# ---------------------------------------------------------------------------
# release_billing_total: pinned five-step rounding order.
# ---------------------------------------------------------------------------

TIER2_MIN_QTY = 2000
TIER2_DISCOUNT_PCT = Decimal("0.06")
TIER1_MIN_QTY = 500
TIER1_DISCOUNT_PCT = Decimal("0.03")


def release_billing_total(unit_cents: int, allocations, committed_qty: int) -> int:
    # Step 1: unit price already rounded (unit_cents is final_unit_price_cents).
    # Steps 2-3: exact per-line extension and sum.
    gross = sum(unit_cents * int(line["qty"]) for line in allocations)
    if committed_qty >= TIER2_MIN_QTY:
        tier_pct = TIER2_DISCOUNT_PCT
    elif committed_qty >= TIER1_MIN_QTY:
        tier_pct = TIER1_DISCOUNT_PCT
    else:
        tier_pct = Decimal("0")
    # Step 4: discount rounded half-up exactly once at order level.
    discount = round_half_up_cents(Decimal(gross) * tier_pct)
    # Step 5: subtract.
    return gross - discount


# ---------------------------------------------------------------------------
# consumption_variance: 4dp rates, strictly-greater OVER threshold, rolling
# 5-record window, needs_review trigger, machine consumption_flag.
# ---------------------------------------------------------------------------

OVER_THRESHOLD_PCT = Decimal("0.10")
UNDER_THRESHOLD_PCT = Decimal("-0.10")
WINDOW_SIZE = 5
TRIGGER_COUNT = 3


def compute_usage_metrics(qty_used: int, parts_produced: int, standard: dict):
    actual = round4(Decimal(qty_used) / Decimal(parts_produced))
    std = standard["standard_qty_per_part"]  # Decimal
    variance = round4((actual - std) / std)
    if variance > OVER_THRESHOLD_PCT:
        band = "OVER"
    elif variance < UNDER_THRESHOLD_PCT:
        band = "UNDER"
    else:
        band = "IN_BAND"
    return actual, variance, band


def covering_standard(machine_id: str, product_id: str, usage_date: date):
    """The ACTIVE standard whose half-open window [effective_from, effective_to)
    contains usage_date."""
    for std in db["standards"].values():
        if (
            std["machine_id"] == machine_id
            and std["product_id"] == product_id
            and std["status"] == "ACTIVE"
            and parse_date(std["effective_from"]) <= usage_date
            and (std["effective_to"] is None or usage_date < parse_date(std["effective_to"]))
        ):
            return std
    return None


def update_needs_review(standard: dict) -> bool:
    """Rolling window: 5 most recent usage records for (machine, product),
    usage_date DESC then created_at DESC, inclusive of the just-accepted record.
    needs_review := (count of OVER in W) >= 3. Returns True if changed."""
    records = [
        r for r in db["usage_records"].values()
        if r["machine_id"] == standard["machine_id"] and r["product_id"] == standard["product_id"]
    ]
    records.sort(key=lambda r: (r["usage_date"], r["created_at"]), reverse=True)
    window = records[:WINDOW_SIZE]
    over_count = sum(1 for r in window if r["variance_band"] == "OVER")
    new_val = over_count >= TRIGGER_COUNT
    changed = standard["needs_review"] != new_val
    standard["needs_review"] = new_val
    return changed


def recompute_consumption_flag(machine: dict) -> bool:
    """ELEVATED iff any ACTIVE standard on the machine has needs_review true.
    Returns True if changed."""
    elevated = any(
        s["machine_id"] == machine["id"] and s["status"] == "ACTIVE" and s["needs_review"]
        for s in db["standards"].values()
    )
    new_val = "ELEVATED" if elevated else "NORMAL"
    changed = machine["consumption_flag"] != new_val
    machine["consumption_flag"] = new_val
    return changed


# ---------------------------------------------------------------------------
# fefo_allocation: candidate pool, ranking, waterfall.
# ---------------------------------------------------------------------------

def fefo_candidates(product_id: str, scheduled_ship_date: date):
    pool = []
    for lot in db["lots"].values():
        if lot["product_id"] != product_id:
            continue
        if lot["status"] != "AVAILABLE" or lot["qty_on_hand"] <= 0:
            continue
        if lot["expiry_date"] is not None and parse_date(lot["expiry_date"]) < scheduled_ship_date:
            # expiry strictly before ship date is excluded; ship ON expiry day allowed
            continue
        pool.append(lot)
    # Rank: expiry_date ASC (NULLS LAST), then manufacture_date ASC, then created_at ASC.
    pool.sort(key=lambda l: (
        l["expiry_date"] is None,
        l["expiry_date"] or "9999-12-31",
        l["manufacture_date"],
        l["created_at"],
    ))
    return pool


def fefo_waterfall(pool, qty: int):
    """Walk the ranking taking min(on_hand, remaining_need) per lot.
    Caller guarantees sum(pool) >= qty. Returns allocation lines in order."""
    lines = []
    remaining = qty
    for lot in pool:
        if remaining <= 0:
            break
        take = min(lot["qty_on_hand"], remaining)
        if take > 0:
            lines.append({"lot_id": lot["id"], "qty": take, "_lot": lot})
            remaining -= take
    return lines


# ---------------------------------------------------------------------------
# hazard_month_mass: calendar-month aggregation over hazard-class records.
# ---------------------------------------------------------------------------

HAZARD_MONTH_THRESHOLD_KG = Decimal("1000.00")


def hazard_month_mass(customer_ref: str, disposed_at: date, extra_weight: Decimal) -> Decimal:
    """Total gross_weight_kg over hazard-class disposal records of the same
    customer_ref in the same calendar month [first day, next month first day),
    INCLUDING the new record's own weight (passed as extra_weight)."""
    month_start = disposed_at.replace(day=1)
    month_end = add_months(month_start, 1)
    total = Decimal("0")
    for rec in db["disposal_records"].values():
        if rec["customer_ref"] != customer_ref:
            continue
        product = db["products"].get(rec["product_id"])
        if product is None or product.get("used_media_hazard_class") == "NONE":
            continue
        rec_date = parse_date(rec["disposed_at"])
        if month_start <= rec_date < month_end:
            total += rec["gross_weight_kg"]
    total += extra_weight
    return round2(total)
