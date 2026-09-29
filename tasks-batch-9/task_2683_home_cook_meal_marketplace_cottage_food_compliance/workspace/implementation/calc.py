"""The nine calculation rules of the PRD (sections 2.8, 3.2 - 3.9)."""
from datetime import timedelta
from decimal import Decimal

from core import ApiError, db, parse_date, parse_dt, pct, rhu

SERVICE_FEE_RATE = "0.09"
SPOILAGE_RATE = "0.10"
DOOR_SURCHARGE_PER_MEAL = 75
HUB_SURCHARGE_PER_MEAL = 40
HOT_MAX_HANDOFF_MINUTES = 120
HUB_BUFFER_MINUTES = 45
SHARED_SPLIT_RATE = "0.50"
WARNED_HOLD_RATE = "0.10"
CAP_WARNING_NUMERATOR = 9
CAP_WARNING_DENOMINATOR = 10

SEVERITY_POINTS = {"MINOR": 5, "MODERATE": 12, "SEVERE": 25, "CRITICAL": 50}

TIER_1_CEILING = 1000000
TIER_2_CEILING = 5000000
TIER_1_RATE = "0.225"
TIER_2_RATE = "0.185"
TIER_3_RATE = "0.150"


# ------------------------------------------------------- commission tier tables
def commission_rate_for(ytd_gross_sales_cents):
    """PRD 3.5 / 3.8: inclusive-below, exclusive-at boundaries."""
    if ytd_gross_sales_cents < TIER_1_CEILING:
        return TIER_1_RATE
    if ytd_gross_sales_cents < TIER_2_CEILING:
        return TIER_2_RATE
    return TIER_3_RATE


# ------------------------------------------------- helpers over the object graph
def cook_orders(cook_id):
    return [o for o in db.orders.values() if o["cook_id"] == cook_id]


def window_orders(window_id):
    return [o for o in db.orders.values() if o["production_window_id"] == window_id]


def cook_incidents(cook_id):
    return [i for i in db.incidents.values() if i["cook_id"] == cook_id]


def cook_documents(cook_id, doc_type=None):
    rows = [d for d in db.documents.values() if d["cook_id"] == cook_id]
    if doc_type is not None:
        rows = [d for d in rows if d["doc_type"] == doc_type]
    return rows


def cook_menu_items(cook_id):
    return [m for m in db.menu_items.values() if m["cook_id"] == cook_id]


def cook_windows(cook_id):
    return [w for w in db.windows.values() if w["cook_id"] == cook_id]


def policy_for_state(state_code):
    for p in db.state_policies.values():
        if p["state_code"] == state_code:
            return p
    return None


def policy_for_cook(cook):
    """PRD 2.10: the implicit resolution of a cook's state_code."""
    policy = policy_for_state(cook["state_code"])
    if policy is None:
        raise ApiError("ERR_STATE_POLICY_NOT_FOUND", "no state policy for %s" % cook["state_code"])
    return policy


def has_live_cert(cook_id):
    """PRD ladder 22: VERIFIED FOOD_HANDLER_CERT with expires_on after clock date."""
    today = db.now().date()
    for d in cook_documents(cook_id, "FOOD_HANDLER_CERT"):
        if d["review_status"] != "VERIFIED":
            continue
        expires = parse_date(d.get("expires_on"))
        if expires is not None and expires > today:
            return True
    return False


# ------------------------------------------- 1. order charge breakdown (PRD 3.5)
def order_pricing(menu_item, quantity, cook):
    snapshot = int(menu_item["unit_price_cents"])
    subtotal = snapshot * quantity
    fee = pct(subtotal, SERVICE_FEE_RATE)
    rate = commission_rate_for(int(cook["ytd_gross_sales_cents"]))
    commission = pct(subtotal, rate)
    return {
        "unit_price_cents_snapshot": snapshot,
        "subtotal_cents": subtotal,
        "diner_service_fee_cents": fee,
        "cold_chain_surcharge_cents": 0,
        "total_charge_cents": subtotal + 0 + fee,
        "commission_rate": float(Decimal(rate)),
        "platform_commission_cents": commission,
        "cook_earnings_cents": subtotal - commission,
    }


def surcharge_for(menu_item, zone, quantity):
    if not menu_item["requires_refrigeration"]:
        return 0
    per_meal = (
        DOOR_SURCHARGE_PER_MEAL if zone["service_mode"] == "DOOR_DELIVERY" else HUB_SURCHARGE_PER_MEAL
    )
    return per_meal * quantity


# ------------------------------------- 2. effective production capacity (PRD 3.3)
def ceil_pct(value, rate):
    prod = Decimal(int(value)) * Decimal(rate)
    floor = int(prod // 1)
    return floor if prod == floor else floor + 1


def derive_window_capacity(window):
    """Refresh the two derived fields from the persisted committed_meals."""
    committed = int(window["committed_meals"])
    reserve = ceil_pct(committed, SPOILAGE_RATE)
    window["spoilage_reserve_meals"] = reserve
    window["effective_capacity_meals"] = int(window["capacity_meals"]) - reserve


def admission_check(window, quantity):
    """Pinned evaluation order: reserve and effective capacity from the
    pre-admission committed count."""
    pre = int(window["committed_meals"])
    reserve = ceil_pct(pre, SPOILAGE_RATE)
    effective = int(window["capacity_meals"]) - reserve
    return (pre + quantity) <= effective


# -------------------------------------- 3. cottage revenue recognition (PRD 3.6)
RECOGNISED_PAYMENT_STATES = ("CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED")
IN_FLIGHT_FULFILMENT = ("PLACED", "ROUTED", "IN_PRODUCTION", "HANDED_OFF")


def recognised_amounts(cook_id):
    year = db.now().year
    recognised = 0
    reversed_amount = 0
    for o in cook_orders(cook_id):
        if o["effective_year"] != year:
            continue
        if o["payment_status"] not in RECOGNISED_PAYMENT_STATES:
            continue
        recognised += int(o["subtotal_cents"])
        reversed_amount += int(o["cook_chargeback_cents"]) + int(o["commission_reversed_cents"])
    return recognised, reversed_amount


# ------------------------------------------ 4. cottage cap projection (PRD 3.5)
def in_flight_exposure(cook_id):
    total = 0
    for o in cook_orders(cook_id):
        if o["payment_status"] == "AUTHORIZED" and o["fulfillment_status"] in IN_FLIGHT_FULFILMENT:
            total += int(o["subtotal_cents"])
    return total


def cap_status_for(recognised_cottage_revenue, cap):
    if recognised_cottage_revenue >= cap:
        return "CAP_REACHED"
    if cap > 0 and (
        recognised_cottage_revenue * CAP_WARNING_DENOMINATOR >= cap * CAP_WARNING_NUMERATOR
    ):
        return "CAP_WARNING"
    return "UNDER_CAP"


# ------------------------------------------ 5. handoff routing decision (PRD 3.6)
def handoff_minutes(window):
    start = parse_dt(window["handoff_start_at"])
    end = parse_dt(window["handoff_end_at"])
    return int((end - start).total_seconds() // 60)


def routing_mode_for(menu_item, zone, window, cook):
    minutes = handoff_minutes(window)
    hot = (
        menu_item["handoff_mode"] == "SAME_DAY_HOT"
        and zone["service_mode"] == "DOOR_DELIVERY"
        and minutes <= HOT_MAX_HANDOFF_MINUTES
        and (menu_item["food_category"] != "TCS" or cook["verified_kitchen_type"] == "COMMERCIAL_SHARED")
    )
    return "SAME_DAY_HOT" if hot else "BATCH_COOK_AND_CHILL"


def cold_chain_check(menu_item, zone, window, routing_mode):
    if not menu_item["requires_refrigeration"]:
        return
    if routing_mode == "SAME_DAY_HOT":
        raise ApiError("ERR_COLD_CHAIN_INFEASIBLE", "a refrigerated dish may not be routed SAME_DAY_HOT")
    if handoff_minutes(window) > int(zone["max_cold_chain_minutes"]):
        raise ApiError("ERR_COLD_CHAIN_INFEASIBLE", "handoff span exceeds the zone cold-chain ceiling")


# --------------------------------------------------- 6. hub selector (PRD 3.6)
HUB_HOLDING_FULFILMENT = ("ROUTED", "IN_PRODUCTION", "HANDED_OFF", "DELIVERED")


def buffered_interval(window):
    start = parse_dt(window["handoff_start_at"]) - timedelta(minutes=HUB_BUFFER_MINUTES)
    end = parse_dt(window["handoff_end_at"]) + timedelta(minutes=HUB_BUFFER_MINUTES)
    return start, end


def intervals_collide(a, b):
    """Closed intervals - touching endpoints do collide (PRD 3.6)."""
    return a[0] <= b[1] and b[0] <= a[1]


def hub_assigned_count(hub):
    """PRD 3.4: a pure count over orders holding a slot on this hub."""
    total = 0
    for o in db.orders.values():
        if o["pickup_hub_id"] == hub["id"] and o["fulfillment_status"] in HUB_HOLDING_FULFILMENT:
            total += 1
    return total


def eligible_hubs(zone_id, window):
    handoff_start = parse_dt(window["handoff_start_at"])
    handoff_end = parse_dt(window["handoff_end_at"])
    out = []
    for hub in db.hubs.values():
        if hub["delivery_zone_id"] != zone_id:
            continue
        if hub["status"] != "OPEN":
            continue
        if parse_dt(hub["hub_window_start_at"]) > handoff_start:
            continue
        if parse_dt(hub["hub_window_end_at"]) < handoff_end:
            continue
        if int(hub["assigned_order_count"]) >= int(hub["slot_capacity_orders"]):
            continue
        out.append(hub)
    return out


def rank_hubs(hubs):
    return sorted(
        hubs,
        key=lambda h: (
            -(int(h["slot_capacity_orders"]) - int(h["assigned_order_count"])),
            h["hub_window_start_at"],
            h["created_at"],
            h["_seq"],
        ),
    )


def hub_slot_conflict(hub, window):
    """True when another window already holding slots on this hub collides."""
    mine = buffered_interval(window)
    for o in db.orders.values():
        if o["pickup_hub_id"] != hub["id"]:
            continue
        if o["fulfillment_status"] not in HUB_HOLDING_FULFILMENT:
            continue
        if o["production_window_id"] == window["id"]:
            continue
        other = db.windows.get(o["production_window_id"])
        if other is None:
            continue
        if intervals_collide(mine, buffered_interval(other)):
            return True
    return False


# ------------------------------------------------ 7. cook safety score (PRD 3.7)
def _decay_weight(incident):
    created = parse_dt(incident["created_at"])
    weeks = int((db.now() - created).total_seconds() // (7 * 24 * 3600))
    if weeks < 8:
        return Decimal("1.00")
    if weeks < 26:
        return Decimal("0.50")
    return Decimal("0.25")


def safety_score(cook_id, advisory=False):
    charge = Decimal(0)
    for inc in cook_incidents(cook_id):
        status = inc["status"]
        if status == "SUBSTANTIATED":
            weight = Decimal(1)
        elif advisory and status in ("INTAKE", "TRIAGED"):
            weight = Decimal("0.5")
        else:
            continue
        points = Decimal(SEVERITY_POINTS.get(inc["severity"], 0))
        charge += points * _decay_weight(inc) * weight
    total = rhu(charge)
    return max(0, 100 - total)


def standing_band(score):
    if score < 60:
        return "SUSPENDED"
    if score < 80:
        return "WARNED"
    return "CLEAR"


# ------------------------------------------------ 8. cook payout net (PRD 3.8)
def statement_inclusion_set(cook, window, basis):
    orders = window_orders(window["id"])
    if basis == "ACCRUAL_WINDOW":
        included = [o for o in orders if o["fulfillment_status"] in ("HANDED_OFF", "DELIVERED")]
        order_ids = set(o["id"] for o in orders)
        refunds = [r for r in db.refunds.values() if r["order_id"] in order_ids]
    else:
        included = [
            o
            for o in orders
            if o["fulfillment_status"] == "DELIVERED"
            and o["payment_status"] in RECOGNISED_PAYMENT_STATES
        ]
        order_ids = set(o["id"] for o in orders)
        refunds = [
            r
            for r in db.refunds.values()
            if r["order_id"] in order_ids and r["status"] == "SETTLED"
        ]
    return included, refunds


def payout_numbers(cook, window, basis):
    tier_rate = commission_rate_for(int(cook["ytd_gross_sales_cents"]))
    included, refunds = statement_inclusion_set(cook, window, basis)
    gross = sum(int(o["subtotal_cents"]) for o in included)
    # Pinned rounding order: round per order, then sum.
    commission = sum(pct(int(o["subtotal_cents"]), tier_rate) for o in included)
    chargeback = sum(int(r["cook_chargeback_cents"]) for r in refunds)
    base = gross - commission
    standing = cook["compliance_standing"]
    if standing == "CLEAR":
        hold = 0
    elif standing == "WARNED":
        hold = pct(base, WARNED_HOLD_RATE)
    else:
        hold = base
    net = gross - commission - chargeback - hold
    return {
        "tier_rate": float(Decimal(tier_rate)),
        "included_order_count": len(included),
        "gross_sales_cents": gross,
        "commission_cents": commission,
        "refund_chargeback_cents": chargeback,
        "safety_hold_cents": hold,
        "net_payout_cents": max(0, net),
    }


def pending_payout(cook_id):
    """PRD 3.8: captured / partially refunded orders not covered by a live statement."""
    covered = set()
    for s in db.statements.values():
        if s["cook_id"] == cook_id and s["status"] in ("FINALIZED", "PAID"):
            covered.add(s["production_window_id"])
    total = 0
    for o in cook_orders(cook_id):
        if o["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
            continue
        if o["production_window_id"] in covered:
            continue
        total += int(o["cook_earnings_cents"]) - int(o["cook_chargeback_cents"])
    return total


def lifetime_paid(cook_id):
    return sum(
        int(s["net_payout_cents"])
        for s in db.statements.values()
        if s["cook_id"] == cook_id and s["status"] == "PAID"
    )


# --------------------------------------------- 9. refund chargeback split (3.9)
def refund_split(order, fault_party, amount):
    cook_capacity = int(order["cook_earnings_cents"]) - int(order["cook_chargeback_cents"])
    commission_capacity = int(order["platform_commission_cents"]) - int(
        order["commission_reversed_cents"]
    )
    cook_capacity = max(0, cook_capacity)
    commission_capacity = max(0, commission_capacity)

    if fault_party == "COOK":
        cook_part = min(amount, cook_capacity)
        remaining = amount - cook_part
        commission_part = min(remaining, commission_capacity)
        remaining -= commission_part
        platform_part = remaining
    elif fault_party == "PLATFORM":
        cook_part = 0
        commission_part = min(amount, commission_capacity)
        platform_part = amount - commission_part
    else:
        target = pct(amount, SHARED_SPLIT_RATE)
        cook_part = min(target, cook_capacity)
        remaining = amount - cook_part
        commission_part = min(remaining, commission_capacity)
        platform_part = amount - cook_part - commission_part
    return cook_part, commission_part, platform_part


# ------------------------------------------- deterministic cascade orderings
def _by_creation(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def ordered_items(cook_id):
    return _by_creation(cook_menu_items(cook_id))


def ordered_windows(cook_id):
    return _by_creation(cook_windows(cook_id))


def ordered_window_orders(window_id):
    return _by_creation(window_orders(window_id))


def ordered_documents(cook_id):
    return _by_creation(cook_documents(cook_id))
