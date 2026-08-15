"""Business logic: pricing, totals, credit ledger, promotions, cascades, sweep.

Implements PRD section 3 and the scaffold's state-machine side effects.
All mutation helpers operate on db.store dicts; nothing is persisted to disk.
"""

import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors as E
from db import store, new_id, next_seq, clock_iso, dt_to_iso, parse_dt, stamp_created, touch, sort_key

# ---------------------------------------------------------------------------
# Constants (scaffold calculations table)
# ---------------------------------------------------------------------------
TIER_DISCOUNT = {"SILVER": Decimal("0.00"), "GOLD": Decimal("0.10"), "PLATINUM": Decimal("0.15")}
BACKBAR_DISCOUNT = Decimal("0.20")
LIQ_STEP_DAYS = 14
TIER_MULTIPLIER = {"SILVER": 1, "GOLD": 2, "PLATINUM": 3}
ACCRUAL_DIVISOR_CENTS = 1000
POINT_VALUE_CENTS = 100
GOLD_FLOOR_CENTS = 2_000_000
PLATINUM_FLOOR_CENTS = 5_000_000
TIER_WINDOW_DAYS = 365
BACKBAR_RATIO = 2
BACKBAR_WINDOW_DAYS = 90
STRAIGHT_RATE = Decimal("0.05")
ACC_T1, ACC_T2 = 1_000_000, 3_000_000
ACC_R1, ACC_R2, ACC_R3 = Decimal("0.04"), Decimal("0.06"), Decimal("0.08")
METHOD_BASE_CENTS = {"GROUND": 1200, "AIR": 3000}
HAZMAT_FLAT_CENTS = 2500
HAZMAT_PER_GRAM_CENTS = 2
SEVERITY_POINTS = {"MINOR": 1, "MAJOR": 2, "SEVERE": 3}
ACCRUAL_TYPES = {"PROVISIONAL_ACCRUAL", "FINAL_ACCRUAL"}
TIERS = {"SILVER", "GOLD", "PLATINUM"}
BUFFER_DELTA = timedelta(minutes=30)

ALL_ROLES = {"DistributionAdmin", "ComplianceOfficer", "SalesConsultant", "SalonBuyer", "WarehouseOperator"}


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def pub(obj):
    """Shallow copy without internal underscore-prefixed bookkeeping keys."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def pub_list(items):
    return [pub(i) for i in items]


# ---------------------------------------------------------------------------
# Getters (existence, pipeline step 5)
# ---------------------------------------------------------------------------
def get_salon(sid):
    s = store.salons.get(sid)
    if s is None:
        raise E.salon_not_found()
    return s


def get_license(lid):
    l = store.licenses.get(lid)
    if l is None:
        raise E.license_not_found()
    return l


def get_brand(bid):
    b = store.brands.get(bid)
    if b is None:
        raise E.brand_not_found()
    return b


def get_product(pid):
    p = store.products.get(pid)
    if p is None:
        raise E.product_not_found()
    return p


def get_consultant(cid):
    c = store.consultants.get(cid)
    if c is None:
        raise E.consultant_not_found()
    return c


def get_plan(pid):
    p = store.route_plans.get(pid)
    if p is None:
        raise E.route_plan_not_found()
    return p


def get_stop(sid):
    s = store.route_stops.get(sid)
    if s is None:
        raise E.route_stop_not_found()
    return s


def get_order(oid):
    o = store.orders.get(oid)
    if o is None:
        raise E.order_not_found()
    return o


def get_shipment(sid):
    s = store.shipments.get(sid)
    if s is None:
        raise E.shipment_not_found()
    return s


def get_promotion(pid):
    p = store.promotions.get(pid)
    if p is None:
        raise E.promotion_not_found()
    return p


def get_redemption(rid):
    r = store.redemptions.get(rid)
    if r is None:
        raise E.redemption_not_found()
    return r


def get_case(cid):
    c = store.diversion_cases.get(cid)
    if c is None:
        raise E.diversion_case_not_found()
    return c


# ---------------------------------------------------------------------------
# Ownership scope (pipeline step 4)
# ---------------------------------------------------------------------------
def buyer_scope(ctx, salon_account_id):
    if ctx.role == "SalonBuyer" and ctx.user_id != salon_account_id:
        raise E.forbidden()


def consultant_plan_scope(ctx, plan):
    if ctx.role == "SalesConsultant" and plan["sales_consultant_id"] != ctx.user_id:
        raise E.forbidden()


def consultant_stop_scope(ctx, stop):
    if ctx.role == "SalesConsultant":
        plan = store.route_plans.get(stop["route_plan_id"])
        if plan is None or plan["sales_consultant_id"] != ctx.user_id:
            raise E.forbidden()


def read_scope_salon_resource(ctx, salon_account_id):
    """Buyer reads only own salon's resources; other roles unrestricted."""
    buyer_scope(ctx, salon_account_id)


def read_scope_order(ctx, order):
    buyer_scope(ctx, order["salon_account_id"])


def read_scope_stop(ctx, stop):
    if ctx.role == "SalesConsultant":
        consultant_stop_scope(ctx, stop)
    elif ctx.role == "SalonBuyer":
        if stop["salon_account_id"] != ctx.user_id:
            raise E.forbidden()


def read_scope_plan(ctx, plan):
    if ctx.role == "SalesConsultant":
        consultant_plan_scope(ctx, plan)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
def items_of_order(order_id):
    return [i for i in store.order_items.values() if i["order_id"] == order_id]


def shipments_of_order(order_id):
    return [s for s in store.shipments.values() if s["order_id"] == order_id]


def orders_of_salon(salon_id):
    return [o for o in store.orders.values() if o["salon_account_id"] == salon_id]


def licenses_of_salon(salon_id):
    return [l for l in store.licenses.values() if l["salon_account_id"] == salon_id]


def stops_of_plan(plan_id):
    return [s for s in store.route_stops.values() if s["route_plan_id"] == plan_id]


def credit_entries_of_salon(salon_id):
    return [e for e in store.credit_entries.values() if e["salon_account_id"] == salon_id]


def ledger_sort_key(e):
    return (e.get("earned_at") or "", e.get("created_at") or "", e.get("_seq", 0))


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def round_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Pricing engine (calculations.line_unit_pricing / liquidation_price)
# ---------------------------------------------------------------------------
def price_line(product, salon):
    """Return (unit_price_cents, pricing_snapshot) per pinned rules."""
    base = product["base_price_cents"]
    if product["lifecycle_status"] == "LIQUIDATION":
        started = parse_dt(product["liquidation_started_at"])
        elapsed_days = (store.clock - started).days
        if elapsed_days < 14:
            pct = Decimal("0.20")
        elif elapsed_days < 28:
            pct = Decimal("0.40")
        else:
            pct = Decimal("0.60")
        unit = round_cents(Decimal(base) * (Decimal(1) - pct))
        snapshot = f"LIQUIDATION_W{elapsed_days // 7}"
        return unit, snapshot
    tier_pct = TIER_DISCOUNT[salon["tier"]]
    tiered = round_cents(Decimal(base) * (Decimal(1) - tier_pct))
    if product["variant_type"] == "BACKBAR":
        unit = round_cents(Decimal(tiered) * (Decimal(1) - BACKBAR_DISCOUNT))
        snapshot = f"{salon['tier']}+BACKBAR"
    else:
        unit = tiered
        snapshot = salon["tier"]
    return unit, snapshot


def add_order_item(order, product, quantity, unit_price, snapshot, is_promotional):
    item = {
        "id": new_id(),
        "order_id": order["id"],
        "product_id": product["id"],
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": unit_price * quantity,
        "is_promotional": is_promotional,
        "pricing_snapshot": snapshot,
    }
    stamp_created(item)
    store.order_items[item["id"]] = item
    return item


# ---------------------------------------------------------------------------
# Order totals (calculations.order_totals, pinned evaluation order)
# ---------------------------------------------------------------------------
def recompute_order_totals(order):
    items = items_of_order(order["id"])
    order["merchandise_total_cents"] = sum(i["line_total_cents"] for i in items)
    order["net_merch_cents"] = order["merchandise_total_cents"] - order["credit_applied_cents"]
    ships = [s for s in shipments_of_order(order["id"]) if not s.get("_voided", False)]
    order["shipping_total_cents"] = sum(s["shipping_charge_cents"] for s in ships)
    order["grand_total_cents"] = order["net_merch_cents"] + order["shipping_total_cents"]


# ---------------------------------------------------------------------------
# Territory exclusivity (validations priority 11)
# ---------------------------------------------------------------------------
def check_territory(product, salon):
    exs = [e for e in store.exclusives.values() if e["brand_id"] == product["brand_id"]]
    if not exs:
        return
    now = store.clock
    for e in exs:
        if e["territory_code"] != salon["territory_code"]:
            continue
        if parse_dt(e["effective_from"]) <= now < parse_dt(e["effective_to"]):
            return
    raise E.brand_territory_restricted()


# ---------------------------------------------------------------------------
# Education-credit ledger (PRD 3.9)
# ---------------------------------------------------------------------------
def post_credit_entry(salon, order_id, entry_type, points, with_expiry=False):
    earned = clock_iso()
    expires = None
    if with_expiry:
        expires = dt_to_iso(add_months(store.clock, 12))
    entry = {
        "id": new_id(),
        "salon_account_id": salon["id"],
        "order_id": order_id,
        "entry_type": entry_type,
        "points": points,
        "consumed_points": 0 if entry_type in ACCRUAL_TYPES else None,
        "earned_at": earned,
        "expires_at": expires,
        "created_at": earned,
        "_seq": next_seq(),
    }
    store.credit_entries[entry["id"]] = entry
    salon["education_credit_points"] += points
    touch(salon)
    return entry


def redeemable_points(salon):
    now = store.clock
    total = 0
    for e in credit_entries_of_salon(salon["id"]):
        if e["entry_type"] not in ACCRUAL_TYPES:
            continue
        if e["expires_at"] is None or parse_dt(e["expires_at"]) <= now:
            continue
        total += e["points"] - e["consumed_points"]
    return total


def redeem_credits(salon, order, points):
    """Post REDEMPTION entry and consume non-expired accruals FIFO."""
    entry = post_credit_entry(salon, order["id"], "REDEMPTION", -points)
    remaining = points
    consumed_from = []
    now = store.clock
    accruals = [e for e in credit_entries_of_salon(salon["id"])
                if e["entry_type"] in ACCRUAL_TYPES and e["expires_at"] is not None
                and parse_dt(e["expires_at"]) > now and (e["points"] - e["consumed_points"]) > 0]
    accruals.sort(key=ledger_sort_key)
    for a in accruals:
        if remaining <= 0:
            break
        resid = a["points"] - a["consumed_points"]
        take = min(resid, remaining)
        a["consumed_points"] += take
        consumed_from.append([a["id"], take])
        remaining -= take
    entry["_consumed_from"] = consumed_from
    return entry


def reverse_order_credit_redemptions(order):
    """REVERSAL entries restoring points for each unreversed REDEMPTION."""
    salon = store.salons.get(order["salon_account_id"])
    for e in sorted(credit_entries_of_salon(order["salon_account_id"]), key=ledger_sort_key):
        if e["order_id"] != order["id"] or e["entry_type"] != "REDEMPTION":
            continue
        if e.get("_reversed"):
            continue
        post_credit_entry(salon, order["id"], "REVERSAL", -e["points"])
        for acc_id, take in e.get("_consumed_from", []):
            acc = store.credit_entries.get(acc_id)
            if acc is not None:
                acc["consumed_points"] -= take
        e["_reversed"] = True


def reverse_order_provisional(order):
    """REVERSAL entry cancelling the PROVISIONAL_ACCRUAL, if any."""
    salon = store.salons.get(order["salon_account_id"])
    for e in sorted(credit_entries_of_salon(order["salon_account_id"]), key=ledger_sort_key):
        if e["order_id"] != order["id"] or e["entry_type"] != "PROVISIONAL_ACCRUAL":
            continue
        if e.get("_reversed"):
            continue
        post_credit_entry(salon, order["id"], "REVERSAL", -e["points"])
        # neutralize residual so a later sweep does not expire it again
        e["consumed_points"] = e["points"]
        e["_reversed"] = True


# ---------------------------------------------------------------------------
# Promotion redemption reversal
# ---------------------------------------------------------------------------
def reverse_order_promotion_redemptions(order, reason):
    for r in sorted((r for r in store.redemptions.values() if r["order_id"] == order["id"]),
                    key=sort_key):
        if r["status"] != "APPLIED":
            continue
        r["status"] = "REVERSED"
        r["reversal_reason"] = reason
        touch(r)
        promo = store.promotions.get(r["promotion_id"])
        if promo is not None:
            if promo["remaining_budget_units"] is not None:
                promo["remaining_budget_units"] += r["units_consumed"]
            # a promotion that already ENDED stays ENDED
            touch(promo)


# ---------------------------------------------------------------------------
# Order compensation (PRD 3.6)
# ---------------------------------------------------------------------------
def cancel_order_with_compensation(order, promo_reason):
    ps = order["payment_status"]
    if ps == "AUTHORIZED":
        order["payment_status"] = "VOIDED"
    elif ps == "CAPTURED":
        order["payment_status"] = "REFUNDED"
    reverse_order_provisional(order)
    reverse_order_credit_redemptions(order)
    reverse_order_promotion_redemptions(order, promo_reason)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)


def reject_order_with_compensation(order):
    if order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "VOIDED"
    reverse_order_provisional(order)
    reverse_order_credit_redemptions(order)
    reverse_order_promotion_redemptions(order, "ORDER_REJECTED")
    order["fulfillment_status"] = "REJECTED"
    touch(order)


def cancel_salon_open_orders(salon):
    orders = sorted(orders_of_salon(salon["id"]), key=sort_key)
    for order in orders:
        fs = order["fulfillment_status"]
        if fs == "SUBMITTED":
            cancel_order_with_compensation(order, "ORDER_CANCELLED")
        elif fs == "APPROVED":
            cancel_order_with_compensation(order, "ACCOUNT_SUSPENDED")


# ---------------------------------------------------------------------------
# Salon standing (PRD 3.3)
# ---------------------------------------------------------------------------
def suspend_salon(salon, reason):
    salon["status"] = "SUSPENDED"
    salon["suspension_reason"] = reason
    touch(salon)
    cancel_salon_open_orders(salon)


def deactivate_salon(salon):
    salon["status"] = "DEACTIVATED"
    salon["suspension_reason"] = None
    touch(salon)
    cancel_salon_open_orders(salon)


def salon_has_valid_license(salon):
    now = store.clock
    for l in licenses_of_salon(salon["id"]):
        if l["status"] == "VERIFIED" and parse_dt(l["valid_until"]) > now:
            return True
    return False


def evaluate_salon_tier(salon):
    now = store.clock
    start = now - timedelta(days=TIER_WINDOW_DAYS)
    vol = 0
    for o in orders_of_salon(salon["id"]):
        if o["fulfillment_status"] != "DELIVERED" or not o["delivered_at"]:
            continue
        d = parse_dt(o["delivered_at"])
        if start <= d <= now:
            vol += o["net_merch_cents"]
    salon["trailing_12m_delivered_volume_cents"] = vol
    if not salon["tier_override_active"]:
        if vol >= PLATINUM_FLOOR_CENTS:
            salon["tier"] = "PLATINUM"
        elif vol >= GOLD_FLOOR_CENTS:
            salon["tier"] = "GOLD"
        else:
            salon["tier"] = "SILVER"
    touch(salon)


# ---------------------------------------------------------------------------
# Backbar quota (calculations.backbar_quota_check)
# ---------------------------------------------------------------------------
def backbar_quota_ok(salon, order):
    now = store.clock
    start = now - timedelta(days=BACKBAR_WINDOW_DAYS)
    hist_b = hist_r = 0
    for o in orders_of_salon(salon["id"]):
        if o["fulfillment_status"] != "DELIVERED" or not o["delivered_at"]:
            continue
        d = parse_dt(o["delivered_at"])
        if not (start <= d <= now):
            continue
        for i in items_of_order(o["id"]):
            if i["is_promotional"]:
                continue
            p = store.products.get(i["product_id"])
            if p is None:
                continue
            if p["variant_type"] == "BACKBAR":
                hist_b += i["quantity"]
            else:
                hist_r += i["quantity"]
    proj_b, proj_r = hist_b, hist_r
    for i in items_of_order(order["id"]):
        if i["is_promotional"]:
            continue
        p = store.products.get(i["product_id"])
        if p is None:
            continue
        if p["variant_type"] == "BACKBAR":
            proj_b += i["quantity"]
        else:
            proj_r += i["quantity"]
    return proj_b <= BACKBAR_RATIO * proj_r


# ---------------------------------------------------------------------------
# Education-credit accrual (calculations.education_credit_accrual)
# ---------------------------------------------------------------------------
def post_provisional_accrual(order, salon):
    points = (order["net_merch_cents"] // ACCRUAL_DIVISOR_CENTS) * TIER_MULTIPLIER[salon["tier"]]
    return post_credit_entry(salon, order["id"], "PROVISIONAL_ACCRUAL", points, with_expiry=True)


def post_final_accrual(order, salon):
    base = (sum(i["line_total_cents"] for i in items_of_order(order["id"]) if not i["is_promotional"])
            - order["credit_applied_cents"])
    final_points = (base // ACCRUAL_DIVISOR_CENTS) * TIER_MULTIPLIER[salon["tier"]]
    provisional = 0
    for e in credit_entries_of_salon(salon["id"]):
        if e["order_id"] == order["id"] and e["entry_type"] == "PROVISIONAL_ACCRUAL" and not e.get("_reversed"):
            provisional += e["points"]
    delta = final_points - provisional
    return post_credit_entry(salon, order["id"], "FINAL_ACCRUAL", delta, with_expiry=True)


# ---------------------------------------------------------------------------
# Consultant commission (calculations.consultant_commission)
# ---------------------------------------------------------------------------
def _overlap(a, b, lo, hi):
    upper = b if hi is None else min(b, hi)
    return max(0, upper - max(a, lo))


def attribute_commission(order, salon):
    cid = salon["assigned_consultant_id"]
    if not cid:
        return
    c = store.consultants.get(cid)
    if c is None or c["status"] != "ACTIVE":
        return
    base = order["net_merch_cents"]
    now = store.clock
    month = f"{now.year:04d}-{now.month:02d}"
    if c["commission_month"] != month:
        c["commission_month"] = month
        c["commission_month_volume_cents"] = 0
    if c["commission_model"] == "STRAIGHT":
        commission = round_cents(Decimal(base) * STRAIGHT_RATE)
    else:
        v0 = c["commission_month_volume_cents"]
        v1 = v0 + base
        commission = round_cents(
            ACC_R1 * _overlap(v0, v1, 0, ACC_T1)
            + ACC_R2 * _overlap(v0, v1, ACC_T1, ACC_T2)
            + ACC_R3 * _overlap(v0, v1, ACC_T2, None))
    c["commission_accrued_cents"] += commission
    c["commission_month_volume_cents"] += base
    touch(c)


# ---------------------------------------------------------------------------
# Delivery side effects
# ---------------------------------------------------------------------------
def finalize_order_delivery(order):
    salon = store.salons.get(order["salon_account_id"])
    order["delivered_at"] = clock_iso()
    order["fulfillment_status"] = "DELIVERED"
    if salon is not None:
        post_final_accrual(order, salon)
        attribute_commission(order, salon)
    touch(order)


def shipment_coverage_complete(order):
    """Every ordered unit covered by IN_TRANSIT or DELIVERED shipments (per line)."""
    items = items_of_order(order["id"])
    covered = {i["id"]: 0 for i in items}
    for s in shipments_of_order(order["id"]):
        if s["status"] not in ("IN_TRANSIT", "DELIVERED"):
            continue
        for el in s["items"]:
            if el["order_item_id"] in covered:
                covered[el["order_item_id"]] += el["quantity"]
    return all(covered[i["id"]] >= i["quantity"] for i in items)


def maybe_mark_shipped(order):
    if order["fulfillment_status"] == "FULFILLING" and shipment_coverage_complete(order):
        order["fulfillment_status"] = "SHIPPED"
        touch(order)


def maybe_mark_delivered(order):
    if order["fulfillment_status"] not in ("FULFILLING", "SHIPPED"):
        return
    ships = shipments_of_order(order["id"])
    if ships and all(s["status"] == "DELIVERED" for s in ships):
        finalize_order_delivery(order)


# ---------------------------------------------------------------------------
# Diversion risk score (calculations.diversion_risk_score)
# ---------------------------------------------------------------------------
def recompute_risk_score(salon):
    now = store.clock
    cutoff12 = add_months(now, -12)
    cutoff24 = add_months(now, -24)
    total = Decimal("0")
    for case in store.diversion_cases.values():
        if case["salon_account_id"] != salon["id"] or case["status"] != "SUBSTANTIATED":
            continue
        at = parse_dt(case["updated_at"])
        if at > cutoff12:
            w = Decimal("1.0")
        elif at >= cutoff24:
            w = Decimal("0.5")
        else:
            w = Decimal("0")
        total += Decimal(SEVERITY_POINTS[case["severity"]]) * w
    if total > Decimal("100"):
        total = Decimal("100")
    salon["diversion_risk_score"] = float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Route stops (PRD 3.10)
# ---------------------------------------------------------------------------
def buffer_ok(plan_id, start_at, end_at, exclude_stop_id=None):
    for s in stops_of_plan(plan_id):
        if s["status"] == "CANCELLED" or s["id"] == exclude_stop_id:
            continue
        ss = parse_dt(s["start_at"])
        se = parse_dt(s["end_at"])
        if start_at >= se:
            if start_at - se < BUFFER_DELTA:
                return False
        elif ss >= end_at:
            if ss - end_at < BUFFER_DELTA:
                return False
        else:
            return False
    return True


def maybe_complete_plan(plan):
    if plan["status"] != "PUBLISHED":
        return
    stops = stops_of_plan(plan["id"])
    if not stops:
        return
    if all(s["status"] in ("COMPLETED", "CANCELLED") for s in stops) and \
            any(s["status"] == "COMPLETED" for s in stops):
        plan["status"] = "COMPLETED"
        touch(plan)


# ---------------------------------------------------------------------------
# Product lifecycle / brand cascade (PRD 3.2)
# ---------------------------------------------------------------------------
def pause_promotions_referencing(product_id):
    for promo in store.promotions.values():
        if promo["status"] != "ACTIVE":
            continue
        if product_id in (promo.get("required_product_id"), promo.get("free_product_id"),
                          promo.get("sample_product_id")):
            promo["status"] = "PAUSED"
            touch(promo)


def discontinue_product(product):
    product["lifecycle_status"] = "DISCONTINUED"
    product["discontinued_at"] = clock_iso()
    touch(product)
    pause_promotions_referencing(product["id"])


# ---------------------------------------------------------------------------
# Daily sweep (PRD 2.4)
# ---------------------------------------------------------------------------
def run_daily_sweep():
    now = store.clock
    expired_license_count = 0
    suspended_salon_count = 0
    expired_credit_points = 0
    ended_promotion_count = 0

    for lic in sorted(store.licenses.values(), key=sort_key):
        if lic["status"] == "VERIFIED" and parse_dt(lic["valid_until"]) < now:
            lic["status"] = "EXPIRED"
            touch(lic)
            expired_license_count += 1
            salon = store.salons.get(lic["salon_account_id"])
            if salon is not None and salon["status"] == "ACTIVE" and not salon_has_valid_license(salon):
                suspend_salon(salon, "LICENSE_EXPIRED")
                suspended_salon_count += 1

    for promo in sorted(store.promotions.values(), key=sort_key):
        if promo["status"] in ("ACTIVE", "PAUSED") and parse_dt(promo["ends_at"]) < now:
            promo["status"] = "ENDED"
            touch(promo)
            ended_promotion_count += 1

    for entry in sorted(list(store.credit_entries.values()), key=ledger_sort_key):
        if entry["entry_type"] not in ACCRUAL_TYPES or entry["expires_at"] is None:
            continue
        if parse_dt(entry["expires_at"]) >= now:
            continue
        residual = entry["points"] - entry["consumed_points"]
        if residual <= 0:
            continue
        entry["consumed_points"] = entry["points"]
        salon = store.salons.get(entry["salon_account_id"])
        if salon is not None:
            post_credit_entry(salon, None, "EXPIRY", -residual)
        expired_credit_points += residual

    return {
        "expired_license_count": expired_license_count,
        "suspended_salon_count": suspended_salon_count,
        "expired_credit_points": expired_credit_points,
        "ended_promotion_count": ended_promotion_count,
    }
