"""Business calculations, cascades, and selector policies (scaffold section 1.3)."""

from datetime import timedelta
from decimal import Decimal

from db import STORES, now
from errors import ApiError
from util import (
    base_record,
    ceil_dec,
    dec,
    fmt_ts,
    pub,
    round0,
    round4,
    sorted_default,
    touch,
)

# ---------------------------------------------------------------------------
# Lazy expiry (PRD section 2.5)
# ---------------------------------------------------------------------------


def lazy_expire_agreement(ag):
    if ag["status"] == "ACTIVE" and now() > ag["_end_dt"]:
        ag["status"] = "EXPIRED"


def lazy_expire_promotion(promo):
    if promo["status"] == "ACTIVE" and now() > promo["_end_dt"]:
        promo["status"] = "EXPIRED"


# ---------------------------------------------------------------------------
# Practice credit ledger. credit_available_cents is a stored field: initialized
# to credit_limit_cents at onboarding, debited at order submit (reservation),
# and credited back only when a SUBMITTED order is cancelled (compensation).
# Delivery does NOT release the reservation.
# ---------------------------------------------------------------------------


def practice_credit_available(practice):
    return practice["credit_available_cents"]


def practice_json(p):
    return pub(p)


# ---------------------------------------------------------------------------
# Order pricing (order_volume_discount, bundle_discount, order_total)
# ---------------------------------------------------------------------------

VOLUME_TIERS = (
    (500000, Decimal("0.10")),
    (200000, Decimal("0.05")),
)
ELITE_TIER_BONUS = Decimal("0.02")


def price_lines(lines_raw):
    """Snapshot unit prices and compute line totals."""
    lines = []
    for entry in lines_raw:
        product = STORES["products"][entry["product_id"]]
        line_total = product["unit_price_cents"] * entry["quantity"]
        lines.append(
            {
                "product_id": product["id"],
                "quantity": entry["quantity"],
                "unit_price_cents": product["unit_price_cents"],
                "line_total_cents": line_total,
            }
        )
    return lines


def compute_totals(practice, promo, lines):
    subtotal = sum(l["line_total_cents"] for l in lines)

    # Volume discount: tier keyed on the PRE-DISCOUNT subtotal.
    pct = Decimal("0")
    for threshold, tier_pct in VOLUME_TIERS:
        if subtotal >= threshold:
            pct = tier_pct
            break
    volume_discount = round0(Decimal(subtotal) * pct)

    # Bundle discount.
    bundle_discount = 0
    if promo is not None:
        required = promo.get("required_product_ids") or []
        line_products = {l["product_id"] for l in lines}
        if all(r in line_products for r in required):
            component_subtotal = sum(
                l["line_total_cents"] for l in lines if l["product_id"] in set(required)
            )
            bonus = ELITE_TIER_BONUS if practice["practice_tier"] == "ELITE" else Decimal("0")
            discount_pct = dec(promo.get("discount_pct") or 0)
            raw = round0(Decimal(component_subtotal) * (discount_pct + bonus))
            cap = promo.get("max_discount_cents")
            bundle_discount = min(raw, cap) if cap is not None else raw

    # Order total.
    if promo is None:
        discount = volume_discount
    elif promo.get("stacking_allowed"):
        discount = volume_discount + bundle_discount
    else:
        discount = max(volume_discount, bundle_discount)
    total = subtotal - discount
    return subtotal, volume_discount, bundle_discount, discount, total


def build_order(practice, kind, promo, lines_raw):
    """Create and store an order record (used by POST /api/orders and by the
    AUTO-order cascade)."""
    lines = price_lines(lines_raw)
    subtotal, volume, bundle, discount, total = compute_totals(practice, promo, lines)
    order = base_record()
    order.update(
        {
            "practice_id": practice["id"],
            "kind": kind,
            "promotion_id": promo["id"] if promo is not None else None,
            "lines": lines,
            "status": "DRAFT",
            "subtotal_cents": subtotal,
            "volume_discount_cents": volume,
            "bundle_discount_cents": bundle,
            "discount_cents": discount,
            "total_cents": total,
            "submitted_at": None,
            "delivered_at": None,
            "_submitted_dt": None,
            "_delivered_dt": None,
        }
    )
    STORES["orders"][order["id"]] = order
    return order


# ---------------------------------------------------------------------------
# Usage profiles: average, accrual, auto-reorder
# ---------------------------------------------------------------------------

USAGE_WINDOW_DAYS = 28
SECONDS_PER_DAY = 86400


def find_profile(practice_id, product_id):
    for profile in STORES["usage_profiles"].values():
        if profile["practice_id"] == practice_id and profile["product_id"] == product_id:
            return profile
    return None


def compute_average_daily_usage(practice_id, product_id):
    """Trailing 28-day window ending at logical now, both bounds inclusive."""
    t_now = now()
    window_start = t_now - timedelta(days=USAGE_WINDOW_DAYS)
    total_qty = 0
    for order in STORES["orders"].values():
        if order["practice_id"] != practice_id or order["status"] != "DELIVERED":
            continue
        delivered = order["_delivered_dt"]
        if delivered is None or delivered < window_start or delivered > t_now:
            continue
        for line in order["lines"]:
            if line["product_id"] == product_id:
                total_qty += line["quantity"]
    return round4(dec(total_qty) / dec(USAGE_WINDOW_DAYS))


def set_profile_quantities(profile, on_hand=None, average=None):
    if on_hand is not None:
        profile["_on_hand"] = round4(on_hand)
        profile["on_hand_estimate"] = float(profile["_on_hand"])
    if average is not None:
        profile["_avg"] = round4(average)
        profile["average_daily_usage"] = float(profile["_avg"])


def has_draft_auto_order(practice_id, product_id):
    for order in STORES["orders"].values():
        if (
            order["kind"] == "AUTO"
            and order["status"] == "DRAFT"
            and order["practice_id"] == practice_id
            and any(l["product_id"] == product_id for l in order["lines"])
        ):
            return True
    return False


def evaluate_auto_reorder(profile):
    """Threshold evaluation (auto_reorder_quantity). Returns the created order
    id, or None. Boundary: on_hand EXACTLY EQUAL to reorder_point triggers."""
    if not profile["auto_replenish_enabled"]:
        return None
    if profile["_on_hand"] > dec(profile["reorder_point"]):
        return None
    if has_draft_auto_order(profile["practice_id"], profile["product_id"]):
        return None
    qty = ceil_dec(dec(profile["target_stock_level"]) - profile["_on_hand"])
    if qty < 1:
        return None
    practice = STORES["practices"][profile["practice_id"]]
    order = build_order(
        practice,
        "AUTO",
        None,
        [{"product_id": profile["product_id"], "quantity": qty}],
    )
    return order["id"]


def deliver_cascade(order):
    """SUBMITTED -> DELIVERED with the usage-profile / auto-reorder hops."""
    t = now()
    order["status"] = "DELIVERED"
    order["delivered_at"] = fmt_ts(t)
    order["_delivered_dt"] = t
    touch(order)

    # Hop 2: aggregate delivered quantities per affected profile.
    additions = {}
    for line in order["lines"]:
        product = STORES["products"].get(line["product_id"])
        if product is None or product["kind"] not in ("CONSUMABLE", "REGULATED"):
            continue
        profile = find_profile(order["practice_id"], line["product_id"])
        if profile is None:
            continue
        additions[profile["id"]] = additions.get(profile["id"], 0) + line["quantity"]

    for profile_id, qty in additions.items():
        profile = STORES["usage_profiles"][profile_id]
        # Deliveries add the full line quantity with no accrual.
        set_profile_quantities(
            profile,
            on_hand=profile["_on_hand"] + dec(qty),
            average=compute_average_daily_usage(
                profile["practice_id"], profile["product_id"]
            ),
        )
        touch(profile)
        # Hop 3: threshold evaluation for each mutated profile.
        evaluate_auto_reorder(profile)


def replenishment_run():
    """Accrue consumption on every profile, then evaluate auto-reorder."""
    t = now()
    created_order_ids = []
    profiles = sorted_default(STORES["usage_profiles"].values())
    for profile in profiles:
        # The average is recomputed before any consumption is accrued.
        set_profile_quantities(
            profile,
            average=compute_average_daily_usage(
                profile["practice_id"], profile["product_id"]
            ),
        )
        elapsed_seconds = (t - profile["_last_eval_dt"]).total_seconds()
        elapsed_days = int(elapsed_seconds // SECONDS_PER_DAY)
        if elapsed_days < 0:
            elapsed_days = 0
        set_profile_quantities(
            profile,
            on_hand=max(
                Decimal("0"), profile["_on_hand"] - profile["_avg"] * dec(elapsed_days)
            ),
        )
        profile["_last_eval_dt"] = t
        profile["last_evaluated_at"] = fmt_ts(t)
        touch(profile)
        created = evaluate_auto_reorder(profile)
        if created is not None:
            created_order_ids.append(created)
    return {
        "evaluated_profile_count": len(profiles),
        "created_order_ids": created_order_ids,
    }


# ---------------------------------------------------------------------------
# Scheduling geometry (PRD section 2.9)
# ---------------------------------------------------------------------------


def technician_commitments(technician_id):
    """Half-open intervals on a technician's calendar: SCHEDULED dispatch jobs
    and INSTALL_SCHEDULED equipment-sale install windows."""
    intervals = []
    for job in STORES["dispatch_jobs"].values():
        if job["technician_id"] == technician_id and job["status"] == "SCHEDULED":
            intervals.append((job["_start_dt"], job["_end_dt"]))
    for sale in STORES["equipment_sales"].values():
        if (
            sale["installer_technician_id"] == technician_id
            and sale["status"] == "INSTALL_SCHEDULED"
        ):
            intervals.append((sale["_win_start"], sale["_win_end"]))
    return intervals


def half_open_conflict(existing_start, existing_end, new_start, new_end):
    return existing_start < new_end and new_start < existing_end


def check_install_conflicts(sale, technician, window_start, window_end):
    # Technician calendar (half-open).
    for s, e in technician_commitments(technician["id"]):
        if half_open_conflict(s, e, window_start, window_end):
            raise ApiError(
                "ERR_TECHNICIAN_SCHEDULE_CONFLICT",
                409,
                "Window overlaps an existing commitment on the technician's calendar",
            )
    # Practice install bay (closed interval; touching endpoints conflict).
    for other in STORES["equipment_sales"].values():
        if other["id"] == sale["id"]:
            continue
        if other["practice_id"] != sale["practice_id"]:
            continue
        if other["status"] != "INSTALL_SCHEDULED":
            continue
        if window_start <= other["_win_end"] and other["_win_start"] <= window_end:
            raise ApiError(
                "ERR_INSTALL_WINDOW_CONFLICT",
                409,
                "Window overlaps another install scheduled at the same practice",
            )


def select_dispatch_technician(practice, req_start, req_end):
    """dispatch_technician_selection: certification gate first, then the
    eligibility pool, then least-loaded ranking."""
    technicians = list(STORES["technicians"].values())
    certified = [
        t
        for t in technicians
        if t["status"] == "ACTIVE" and "REPAIR" in t["certifications"]
    ]
    if not certified:
        raise ApiError(
            "ERR_CERTIFICATION_MISSING",
            422,
            "No active technician holds the REPAIR certification",
        )

    pool = []
    for tech in certified:
        if tech["region"] != practice["region"]:
            continue
        conflict = any(
            half_open_conflict(s, e, req_start, req_end)
            for s, e in technician_commitments(tech["id"])
        )
        if not conflict:
            pool.append(tech)
    if not pool:
        raise ApiError(
            "ERR_TECHNICIAN_UNAVAILABLE",
            409,
            "No eligible technician is free in the requested window",
        )

    day_start = req_start.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    def scheduled_minutes(tech):
        total = Decimal("0")
        for s, e in technician_commitments(tech["id"]):
            lo, hi = max(s, day_start), min(e, day_end)
            if lo < hi:
                total += dec((hi - lo).total_seconds()) / dec(60)
        return total

    pool.sort(key=lambda t: (scheduled_minutes(t), t["_created_dt"], t["_seq"]))
    return pool[0]


# ---------------------------------------------------------------------------
# Coverage determination and repair cost
# ---------------------------------------------------------------------------

LABOR_RATE_CENTS_PER_MINUTE = 200
DIAGNOSTIC_ESTIMATE_CENTS = 7500


def determine_coverage(equipment_sale_id):
    """Priority selection: WARRANTY wins outright; else earliest-ending
    SERVICE_PLAN (tie-break earliest created_at); else BILLABLE."""
    t = now()
    candidates = []
    for ag in STORES["coverage_agreements"].values():
        if ag["equipment_sale_id"] != equipment_sale_id:
            continue
        lazy_expire_agreement(ag)
        if ag["status"] != "ACTIVE":
            continue
        if ag["_start_dt"] <= t <= ag["_end_dt"]:
            candidates.append(ag)
    candidates.sort(key=lambda a: (a["_created_dt"], a["_seq"]))
    for ag in candidates:
        if ag["coverage_type"] == "WARRANTY":
            return "WARRANTY", ag["id"]
    plans = [a for a in candidates if a["coverage_type"] == "SERVICE_PLAN"]
    if plans:
        plans.sort(key=lambda a: (a["_end_dt"], a["_created_dt"], a["_seq"]))
        return "SERVICE_PLAN", plans[0]["id"]
    return "BILLABLE", None


def compute_repair_cost(ticket, parts_used, labor_minutes):
    """Returns (gross_cents, customer_due_cents, plan_share_cents)."""
    parts_cost = 0
    for entry in parts_used:
        product = STORES["products"][entry["product_id"]]
        parts_cost += product["unit_price_cents"] * entry["quantity"]
    gross = parts_cost + labor_minutes * LABOR_RATE_CENTS_PER_MINUTE

    determination = ticket["coverage_determination"]
    if determination == "WARRANTY":
        return gross, 0, 0
    if determination == "SERVICE_PLAN":
        agreement = STORES["coverage_agreements"][ticket["coverage_agreement_id"]]
        share = max(0, gross - agreement["deductible_cents"])
        cap = agreement["coverage_cap_cents"]
        if cap is not None:
            remaining_cap = max(0, cap - agreement["used_cents"])
            share = min(share, remaining_cap)
        return gross, gross - share, share
    # BILLABLE
    return gross, gross, 0


# ---------------------------------------------------------------------------
# Rebates
# ---------------------------------------------------------------------------

TIER_MULTIPLIERS = {
    "STANDARD": Decimal("1.0"),
    "PREMIER": Decimal("1.1"),
    "ELITE": Decimal("1.25"),
}


def compute_rebate_amount(practice, order, promo):
    """Round each eligible line first (half up, whole cents), then sum."""
    multiplier = TIER_MULTIPLIERS[practice["practice_tier"]]
    eligible = set(promo.get("eligible_product_ids") or [])
    rate = promo.get("rebate_per_unit_cents") or 0
    total = 0
    for line in order["lines"]:
        if line["product_id"] in eligible:
            total += round0(dec(line["quantity"]) * dec(rate) * multiplier)
    return total


# ---------------------------------------------------------------------------
# Trade-in valuation
# ---------------------------------------------------------------------------

CONDITION_FACTORS = {
    "WORKING": Decimal("1.0"),
    "NEEDS_REPAIR": Decimal("0.6"),
    "SCRAP": Decimal("0.2"),
}
SCRAP_TABLE = {"WORKING": 25000, "NEEDS_REPAIR": 10000, "SCRAP": 4000}
MONTHLY_RETENTION = Decimal("0.98")
FLOOR_FRACTION = Decimal("0.10")


def appraise_trade_in(trade_in, method):
    if method == "SCRAP_VALUE":
        return SCRAP_TABLE[trade_in["condition"]]
    # MARKET_VALUE: exponential age depreciation with condition factor and a
    # 10% floor.
    base = dec(trade_in["category_base_value_cents"])
    raw = (
        base
        * (MONTHLY_RETENTION ** trade_in["equipment_age_months"])
        * CONDITION_FACTORS[trade_in["condition"]]
    )
    floor_value = round0(FLOOR_FRACTION * base)
    return max(round0(raw), floor_value)
