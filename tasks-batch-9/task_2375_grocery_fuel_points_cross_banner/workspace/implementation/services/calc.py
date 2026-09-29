"""The ten declared calculations."""
from decimal import Decimal

import clock
import db
from services import core

CATEGORIES = ("GROCERY", "GIFT_CARD", "PHARMACY", "FUEL", "TOBACCO", "ALCOHOL")


# ------------------------------------------------------- promo_multiplier_stack

def _promo_sort_key(event):
    return (-event["stack_priority"], event["created_at"], event["_seq"])


def eligible_promos(banner_id, category, transacted_at):
    """ACTIVE events of the banner whose half-open window contains transacted_at."""
    rows = []
    for event in db.promo_events.values():
        if event["banner_id"] != banner_id:
            continue
        if event["status"] != "ACTIVE":
            continue
        if not (event["starts_at"] <= transacted_at < event["ends_at"]):
            continue
        if category not in event["applies_to_categories"]:
            continue
        rows.append(event)
    rows.sort(key=_promo_sort_key)
    return rows


def promo_multiplier_stack(banner, category, transacted_at):
    """Returns (promo_multiplier, applied_events) after the max_stack_count cut."""
    candidates = eligible_promos(banner["id"], category, transacted_at)
    applied = candidates[:banner["max_stack_count"]]
    multiplier = 1
    for event in applied:
        multiplier *= event["multiplier"]
    return multiplier, applied


# ------------------------------------------------------- purchase_point_accrual

def _category_base_points(banner, line):
    category = line["category"]
    if category in ("GROCERY", "GIFT_CARD"):
        return Decimal(line["amount_cents"]) / Decimal(100) * Decimal(banner["base_points_per_dollar"])
    if category == "PHARMACY":
        return Decimal(line["quantity"]) * Decimal(banner["pharmacy_points_per_script"])
    return Decimal(0)


def _category_multiplier(banner, category):
    if category == "GIFT_CARD":
        return banner["gift_card_multiplier"]
    if category == "PHARMACY":
        return banner["pharmacy_multiplier"]
    if category == "GROCERY":
        return 1
    return 0


def purchase_point_accrual(banner, transaction):
    """Round per line, then sum. Returns (gross_points, breakdown, applied_promo_ids)."""
    breakdown = []
    gross = 0
    applied_map = {}
    for index, line in enumerate(transaction["lines"]):
        category = line["category"]
        base = _category_base_points(banner, line)
        category_multiplier = _category_multiplier(banner, category)
        promo_multiplier, applied = promo_multiplier_stack(
            banner, category, transaction["transacted_at"])
        for event in applied:
            applied_map[event["id"]] = event
        effective = category_multiplier * promo_multiplier
        if effective > banner["max_stacked_multiplier"]:
            effective = banner["max_stacked_multiplier"]
        raw = base * Decimal(effective)
        line_points = clock.rhu_int(raw)
        gross += line_points
        breakdown.append({
            "line_index": index,
            "category": category,
            "category_base_points": base,
            "effective_multiplier": effective,
            "line_points_raw": raw,
            "line_points": line_points,
        })
    ordered = sorted(applied_map.values(), key=_promo_sort_key)
    return gross, breakdown, [event["id"] for event in ordered]


# --------------------------------------------------- redemption_authorization

def redemption_authorization(site, site_banner, points_committed):
    block_points = site_banner["points_per_discount_block"]
    cents_per_block = site_banner["cents_off_per_block"]
    blocks_requested = points_committed // block_points
    cents_off_uncapped = blocks_requested * cents_per_block
    if site["site_type"] == "PARTNER_STATION":
        site_cap = site["per_gallon_cap_cents"]
        gallons_authorized = Decimal(site["max_gallons_per_redemption"])
    else:
        site_cap = site_banner["max_cents_off_per_gallon"]
        gallons_authorized = Decimal(site_banner["owned_max_gallons_per_redemption"])
    cents_off_per_gallon = min(cents_off_uncapped, site_cap)
    blocks_effective = cents_off_per_gallon // cents_per_block
    points_debited = blocks_effective * block_points
    return {
        "blocks_effective": blocks_effective,
        "cents_off_per_gallon": cents_off_per_gallon,
        "points_debited_at_auth": points_debited,
        "gallons_authorized": clock.rhu(gallons_authorized, 3),
    }


# ------------------------------------------------- redemption_discount_amount

def redemption_discount_amount(redemption, gallons_dispensed):
    return clock.rhu_int(gallons_dispensed * Decimal(redemption["cents_off_per_gallon"]))


# --------------------------------------------- settlement_batch_reimbursement

def _tier_rate(gallons_total):
    """PRD 3.6 step 3: a flat rate on the entire volume.

    Band edges are inclusive upper bounds of the lower band, so exactly 500.000
    is still the low tier and the mid tier begins at 500.001.
    """
    if gallons_total <= Decimal(500):
        return Decimal("0.85")
    if gallons_total <= Decimal(2000):
        return Decimal("0.90")
    return Decimal("0.95")


def settlement_batch_reimbursement(redemptions):
    gallons_total = Decimal(0)
    gross_discount_cents = 0
    for redemption in redemptions:
        gallons_total += redemption["gallons_dispensed"] or Decimal(0)
        gross_discount_cents += redemption["discount_amount_cents"] or 0
    gallons_total = clock.rhu(gallons_total, 3)
    rate = _tier_rate(gallons_total)
    pre_fee = clock.rhu_int(Decimal(gross_discount_cents) * rate)
    admin_fee = min(50000, clock.rhu_int(Decimal(pre_fee) * Decimal("0.015")))
    return {
        "redemption_count": len(redemptions),
        "gallons_total": gallons_total,
        "gross_discount_cents": gross_discount_cents,
        "tier_rate_pct": rate,
        "pre_fee_reimbursement_cents": pre_fee,
        "admin_fee_cents": admin_fee,
        "reimbursement_cents": pre_fee - admin_fee,
    }


# ------------------------------------------------ points_summary_projection

def points_summary(member):
    banner = db.banners[member["banner_id"]]
    balance = core.available_points(member["id"])
    pending = 0
    for redemption in db.fuel_redemptions.values():
        if redemption["member_id"] == member["id"] \
                and redemption["authorization_status"] == "AUTHORIZED":
            pending += redemption["points_debited_at_auth"]
    cycle = core.open_cycle(member["banner_id"])
    if cycle is None:
        projected_expiring = 0
        projected_rollover = 0
    else:
        projected_expiring, projected_rollover, _expired = core.sweep_amounts(
            member, banner, cycle)
    return {
        "member_id": member["id"],
        "available_points": balance,
        "open_cycle_id": cycle["id"] if cycle else None,
        "pending_authorized_points": pending,
        "projected_expiring_points": projected_expiring,
        "projected_rollover_points": projected_rollover,
        "projected_available_after_close": balance - projected_expiring,
    }
