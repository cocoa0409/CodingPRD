"""Calculation rules (scaffold section 1.3): maturity, pricing ladder,
freshness projection, zone capacity, allocation, watering, reseed, cutoffs."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

import db
from util import D, r2, r4, hours_between

GRADE_PALLET_FIELD = {
    "PREMIUM": "pallet_sqft_premium",
    "STANDARD": "pallet_sqft_standard",
    "ECONOMY": "pallet_sqft_economy",
}
GRADE_RATE_FIELD = {
    "PREMIUM": "rate_premium",
    "STANDARD": "rate_standard",
    "ECONOMY": "rate_economy",
}
ZONE_RATE_FIELD = {1: "zone1_rate", 2: "zone2_rate", 3: "zone3_rate"}

# Fallback defaults used only when no PriceConfig exists (fleet-side windows).
DEFAULTS = {
    "slab_sqft": Decimal("5"),
    "roll_sqft": Decimal("10"),
    "pallet_sqft_premium": Decimal("100"),
    "pallet_sqft_standard": Decimal("50"),
    "pallet_sqft_economy": Decimal("20"),
    "rate_premium": Decimal("0.855"),
    "rate_standard": Decimal("0.70"),
    "rate_economy": Decimal("0.50"),
    "zone1_rate": Decimal("1.20"),
    "zone2_rate": Decimal("1.80"),
    "zone3_rate": Decimal("2.60"),
    "freight_sqft_unit": 500,
    "zone_truck_capacity": 4,
    "delivery_window_hours": 2,
    "delivery_earliest_start_hour": 6,
    "delivery_latest_start_hour": 16,
    "same_day_cutoff_hours": 2,
    "future_day_cutoff_hour": 14,
    "freshness_limit_hours": Decimal("24"),
    "card_fee_pct": Decimal("0.02"),
    "cash_discount_pct": Decimal("0.03"),
    "volume_t1_turf_min": Decimal("2000"),
    "volume_t1_pre_min": Decimal("4000"),
    "volume_t1_pct": Decimal("0.06"),
    "volume_t2_turf_min": Decimal("8000"),
    "volume_t2_pre_min": Decimal("15000"),
    "volume_t2_pct": Decimal("0.15"),
    "harvest_earliest_start_hour": 6,
    "harvest_latest_end_hour": 18,
}


def current_config():
    for cfg in db.store.price_configs.values():
        if cfg["is_current"]:
            return cfg
    return None


def config_or_defaults(cfg):
    """Return a dict-like with config values or documented defaults."""
    if cfg is not None:
        return cfg
    return DEFAULTS


# ------------------------------------------------------------- maturity
def compute_maturity(field):
    """age_days (floor) + maturity_state against the variety windows."""
    planted = field["last_planted_at"]
    delta = db.now() - planted
    age_days = delta.days if delta.total_seconds() >= 0 else delta.days  # floor semantics
    # timedelta.days already floors toward negative infinity for aware deltas.
    variety = db.store.variety_configs.get(field["variety_id"])
    if variety is None:
        return age_days, "SEEDED"
    if age_days <= variety["germination_max_days"]:
        return age_days, "SEEDED"
    if age_days <= variety["growing_max_days"]:
        return age_days, "GROWING"
    if age_days <= variety["ready_max_days"]:
        return age_days, "READY"
    if age_days <= variety["mature_max_days"]:
        return age_days, "MATURE"
    return age_days, "OVERAGED"


# ------------------------------------------------------------- pallet yield
def line_yield_sqft(cfg, pallet_count, grade, shortfall_slabs, shortfall_rolls):
    cfg = config_or_defaults(cfg)
    full = D(pallet_count) * D(cfg[GRADE_PALLET_FIELD[grade]])
    y = full - D(shortfall_slabs) * D(cfg["slab_sqft"]) - D(shortfall_rolls) * D(cfg["roll_sqft"])
    return full, y


# ------------------------------------------------------------- quote pricing
def price_quote(cfg, settlement_method, z1, z2, z3, lines):
    """Full pricing ladder. Returns a dict of computed quote fields.

    Pinned rounding order: per-line turf rounding then sum; freight rounded
    before joining the subtotal; ladder rounded at each pinned step.
    """
    total_pallets = sum(ln["pallet_count"] for ln in lines)
    line_yields = []
    turf = Decimal("0")
    for ln in lines:
        _, y = line_yield_sqft(cfg, ln["pallet_count"], ln["grade"],
                               ln["shortfall_slabs"], ln["shortfall_rolls"])
        line_yields.append(y)
        rate = D(cfg[GRADE_RATE_FIELD[ln["grade"]]])
        turf += r2(y * rate)

    freight_factor = (D(z1) * D(cfg["zone1_rate"])
                      + D(z2) * D(cfg["zone2_rate"])
                      + D(z3) * D(cfg["zone3_rate"]))
    freight = r2(turf * freight_factor / D(cfg["freight_sqft_unit"]))
    pre = turf + freight

    if turf >= D(cfg["volume_t2_turf_min"]) and pre >= D(cfg["volume_t2_pre_min"]):
        tier, tier_pct = "T2", D(cfg["volume_t2_pct"])
    elif turf >= D(cfg["volume_t1_turf_min"]) and pre >= D(cfg["volume_t1_pre_min"]):
        tier, tier_pct = "T1", D(cfg["volume_t1_pct"])
    else:
        tier, tier_pct = "T0", Decimal("0")

    cash_price = r2(pre * (Decimal("1") - D(cfg["cash_discount_pct"])))
    if settlement_method == "CARD":
        volume_discount = r2(pre * tier_pct)
        gross = pre - volume_discount
        card_fee = r2(gross * D(cfg["card_fee_pct"]))
        total_price = r2(gross + card_fee)
        additive_total = r2(pre * (Decimal("1") + tier_pct) * (Decimal("1") + D(cfg["card_fee_pct"])))
    else:  # CASH_CHECK: tier discount and card fee do not apply
        volume_discount = Decimal("0.00")
        card_fee = Decimal("0.00")
        total_price = cash_price
        additive_total = cash_price

    counts = [(1, z1), (2, z2), (3, z3)]
    capacity_zone = max(counts, key=lambda p: (p[1], -p[0]))[0]

    return {
        "total_pallets": total_pallets,
        "capacity_zone": capacity_zone,
        "turf_sqft": turf,
        "freight_amount": freight,
        "pre_discount_subtotal": pre,
        "volume_tier": tier,
        "volume_discount": volume_discount,
        "card_fee": card_fee,
        "total_price": total_price,
        "additive_total": additive_total,
        "cash_price": cash_price,
        "line_yields": line_yields,
    }


# ------------------------------------------------------------- freshness
def projected_harvest_end(batch):
    if batch["status"] == "COMPLETE":
        return batch["actual_harvest_end"]
    # PENDING: scheduled_date at 08:00 UTC
    return datetime.combine(batch["scheduled_date"], time(8, 0, 0), tzinfo=timezone.utc)


def projected_freshness_hours(batch, delivery_window_end):
    return hours_between(projected_harvest_end(batch), delivery_window_end)


def freshness_eligible(batch, delivery_window_end, limit_hours):
    pf = projected_freshness_hours(batch, delivery_window_end)
    return Decimal("0") <= pf <= D(limit_hours)


# ------------------------------------------------------------- zone capacity
def windows_overlap(s1, e1, s2, e2):
    """Half-open [s, e) overlap; touching endpoints do NOT overlap."""
    return s1 < e2 and s2 < e1


def zone_consumers(zone, window_start, window_end):
    n = 0
    for o in db.store.orders.values():
        if (o["status"] in ("CONFIRMED", "OUT_FOR_DELIVERY")
                and o["capacity_zone"] == zone
                and o["delivery_window_start"] is not None
                and windows_overlap(o["delivery_window_start"], o["delivery_window_end"],
                                    window_start, window_end)):
            n += 1
    for t in db.store.truck_blocks.values():
        if (t["freight_zone"] == zone
                and windows_overlap(t["window_start"], t["window_end"], window_start, window_end)):
            n += 1
    return n


# ------------------------------------------------------------- allocation
def try_allocate(quote, cfg, window_end):
    """Dry-run the freshness-aware waterfall allocation.

    Returns (status, selection):
      ("ok", [batches])          - all lines satisfied
      ("not_fresh", None)        - matched unlinked batches existed but all stale
      ("under", None)            - genuine quantity shortfall
    """
    selected_ids = set()
    selection = []
    for ln, y in zip(quote["lines"], quote["_line_yields"]):
        candidates = []
        excluded_by_freshness = False
        for b in db.store.harvest_batches.values():
            if b["status"] not in ("PENDING", "COMPLETE"):
                continue
            if b["order_id"] is not None or b["id"] in selected_ids:
                continue
            if b["variety_id"] != ln["variety_id"] or b["grade"] != ln["grade"]:
                continue
            if not freshness_eligible(b, window_end, cfg["freshness_limit_hours"]):
                excluded_by_freshness = True
                continue
            candidates.append(b)
        # freshest first (projected end DESC), then smaller sellable, then earlier created
        candidates.sort(key=lambda b: (-projected_harvest_end(b).timestamp(),
                                       D(b["sellable_sqft"]), b["_seq"]))
        cumulative = Decimal("0")
        for b in candidates:
            selection.append(b)
            selected_ids.add(b["id"])
            cumulative += D(b["sellable_sqft"])
            if cumulative >= D(y):
                break
        if cumulative < D(y):
            # roll back this line's picks from the committed selection
            selection = [b for b in selection if b["id"] not in
                         {c["id"] for c in candidates}]
            if excluded_by_freshness:
                return ("not_fresh", None)
            return ("under", None)
    return ("ok", selection)


# ------------------------------------------------------------- confirm cutoff
def confirm_cutoff(order, cfg):
    delivery_date = order["delivery_date"]
    if delivery_date == db.today():
        return order["created_at"] + timedelta(hours=int(cfg["same_day_cutoff_hours"]))
    day_before = delivery_date - timedelta(days=1)
    return datetime.combine(day_before, time(int(cfg["future_day_cutoff_hour"]), 0, 0),
                            tzinfo=timezone.utc)


# ------------------------------------------------------------- delivery check
def delivery_check_compute(order, check_index, prev_delivered_cumulative, total_paid):
    A = D(order["turf_sqft"])
    P = D(order["delivered_sqft"])
    B = D(total_paid)
    baseline = r2(Decimal("0.95") * A)
    window_size = r2((baseline + B) * Decimal("0.60"))
    in_window = P >= window_size
    chunk = P if check_index == 1 else (P - D(prev_delivered_cumulative))
    strict_in_window = chunk >= r2(baseline * Decimal("0.60"))
    shortfall_sqft = max(Decimal("0"), A - P)
    blended_rate = r4(D(order["total_price"]) / A) if A > 0 else Decimal("0")
    shortfall_credit = r2(shortfall_sqft * blended_rate)
    chargeable_after = r2(D(order["total_price"]) - shortfall_credit)
    return {
        "promised_sqft": A,
        "delivered_cumulative": P,
        "prior_payments": B,
        "baseline_sqft": baseline,
        "window_size": window_size,
        "in_window": in_window,
        "strict_in_window": strict_in_window,
        "shortfall_sqft": shortfall_sqft,
        "blended_rate": blended_rate,
        "shortfall_credit": shortfall_credit,
        "chargeable_after": chargeable_after,
    }


# ------------------------------------------------------------- watering
def watering_credits(moisture):
    m = D(moisture)
    if m >= Decimal("40"):
        return 140
    if m >= Decimal("30"):
        return 120
    return 60


WEATHER_TARGET = {"W1": 500, "W2": 400, "W3": 300}


# ------------------------------------------------------------- reseed
def target_seed_lbs(field, variety):
    return r2(D(field["field_sqft"]) * D(variety["seed_lbs_per_1000_sqft"]) / Decimal("1000"))


# ------------------------------------------------------------- field availability
def pending_reserved_sqft(field_id):
    total = Decimal("0")
    for b in db.store.harvest_batches.values():
        if b["field_id"] == field_id and b["status"] == "PENDING":
            total += D(b["sellable_sqft"])
    return total
