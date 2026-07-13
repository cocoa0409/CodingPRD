"""Pricing / payout calculations and derived-aggregate recomputation."""
from common import (
    db, rhu, rhu2, touch,
    BUNDLE_MIN_ADDONS, BUNDLE_DISCOUNT_BPS, MAX_BUNDLE_DISCOUNT_CENTS,
    AFTER_HOURS_FLAT_CENTS, AFTER_HOURS_BPS,
    STANDARD_START_HOUR_UTC, STANDARD_END_HOUR_UTC,
    PLATFORM_COMMISSION_BPS, parse_iso,
)


def addons_gross(wo):
    total = 0
    for aid in wo.get("selected_addon_ids", []):
        addon = db.addons.get(aid)
        if addon:
            total += addon["price_cents"]
    return total


def bundle_discount(wo):
    gross = addons_gross(wo)
    if len(wo.get("selected_addon_ids", [])) >= BUNDLE_MIN_ADDONS:
        return min(rhu(gross * BUNDLE_DISCOUNT_BPS, 10000), MAX_BUNDLE_DISCOUNT_CENTS)
    return 0


def final_addons(wo):
    return addons_gross(wo) - bundle_discount(wo)


def parts_billed_total(wo):
    total = 0
    for p in db.parts.values():
        if p["work_order_id"] == wo["id"]:
            total += p["line_billed_cents"]
    return total


def zone_surcharge(wo, task):
    start = parse_iso(wo["scheduled_start"]) if isinstance(wo["scheduled_start"], str) else wo["scheduled_start"]
    end = parse_iso(wo["scheduled_end"]) if isinstance(wo["scheduled_end"], str) else wo["scheduled_end"]
    if start.hour < STANDARD_START_HOUR_UTC or end.hour > STANDARD_END_HOUR_UTC:
        return max(AFTER_HOURS_FLAT_CENTS, rhu(task["base_price_cents"] * AFTER_HOURS_BPS, 10000))
    return 0


def work_order_final_price(wo, task):
    base = task["base_price_cents"]
    return base + final_addons(wo) + parts_billed_total(wo) + zone_surcharge(wo, task)


def parts_reimbursement_cents(wo):
    total = 0
    for p in db.parts.values():
        if p["work_order_id"] == wo["id"]:
            total += p["unit_cost_cents"] * p["quantity"]
    return total


def payout_money_fields(wo, task):
    """Provisional payout money fields (used at PayoutRecord creation)."""
    gross = task["base_price_cents"] + final_addons(wo)
    commission = rhu(gross * PLATFORM_COMMISSION_BPS, 10000)
    parts_reimb = parts_reimbursement_cents(wo)
    provisional = gross - commission + parts_reimb
    return {
        "gross_task_cents": gross,
        "commission_cents": commission,
        "parts_reimbursement_cents": parts_reimb,
        "payout_cents": provisional,
    }


def referral_fee_cents(task, retailer):
    return rhu(task["base_price_cents"] * retailer["commission_rate_bps"], 10000)


# ---------------------------------------------------------------------------
# Derived-aggregate recomputation
# ---------------------------------------------------------------------------
def recompute_pro(pro):
    reserved = 0
    for a in db.assignments.values():
        if a["pro_id"] == pro["id"] and a["status"] in ("OFFERED", "ACCEPTED"):
            reserved += 1
    pending = 0
    for pr in db.payouts.values():
        if pr["pro_id"] == pro["id"] and pr["status"] in ("PENDING", "RELEASED"):
            pending += pr["payout_cents"]
    rating_sum = 0
    rating_count = 0
    for r in db.ratings.values():
        if r["pro_id"] == pro["id"]:
            rating_sum += r["stars"]
            rating_count += 1
    rating_avg = rhu2(rating_sum, rating_count) if rating_count else 0
    changed = (
        pro["reserved_slot_count"] != reserved
        or pro["pending_payout_cents"] != pending
        or pro["rating_sum"] != rating_sum
        or pro["rating_count"] != rating_count
        or pro["rating_avg"] != rating_avg
    )
    pro["reserved_slot_count"] = reserved
    pro["pending_payout_cents"] = pending
    pro["rating_sum"] = rating_sum
    pro["rating_count"] = rating_count
    pro["rating_avg"] = rating_avg
    if changed:
        touch(pro)


def recompute_retailer(retailer):
    bal = 0
    for e in db.settlement_entries.values():
        if e["retailer_id"] == retailer["id"] and e["status"] == "PENDING":
            bal += e["amount_cents"]
    changed = retailer["settlement_balance_cents"] != bal
    retailer["settlement_balance_cents"] = bal
    if changed:
        touch(retailer)
