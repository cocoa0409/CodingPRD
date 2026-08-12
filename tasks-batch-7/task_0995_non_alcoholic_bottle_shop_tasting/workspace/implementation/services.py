"""Business logic: classifications, loyalty, inventory FEFO walk, order totals,
club capacity, billing cadence, and system-scheduled (clock) transitions."""
import calendar
from datetime import date, datetime, timedelta

import clock
import db as _db
from db import db, touch
from errors import ApiError

SHOP_HOME_STATE = "CA"

LOYALTY_MULTIPLIER = {"BRONZE": 1.0, "SILVER": 1.25, "GOLD": 1.5, "PLATINUM": 2.0}
DTC_BASE_SHIP_CENTS = 500
DTC_PER_BOTTLE_CENTS = 150
CADENCE_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "ANNUAL": 12}
ADULT_CLASSES = {"ADULT_ONLY_REQUIRED", "ADULT_ONLY_SUGGESTED"}


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up(x):
    """Round a numeric to whole units, halves away from zero."""
    return int(x + 0.5)


# ---------------------------------------------------------------------------
# SKU compliance classification
# ---------------------------------------------------------------------------

def compute_age_neutral_class(category, abv_bps):
    if category["compliance_class"] in ("HEMP_DERIVED", "KAVA"):
        return "PROHIBITED_STATE_LIST"
    if category["compliance_class"] == "FUNCTIONAL_MUSHROOM":
        return "ADULT_ONLY_SUGGESTED"
    if abv_bps > 50:
        return "ADULT_ONLY_REQUIRED"
    return "OPEN"


def state_override_status(sku, state_code):
    """Return 'PROHIBITED' or 'ALLOWED' if an override entry targets the state."""
    for ov in sku.get("ship_state_overrides") or []:
        if not isinstance(ov, dict):
            continue
        if ov.get("state_code") == state_code or ov.get("state") == state_code:
            st = ov.get("status")
            if isinstance(st, str) and st.upper() in ("PROHIBITED", "ALLOWED"):
                return st.upper()
    return None


def sku_prohibited_in_state(sku, category, state_code):
    ov = state_override_status(sku, state_code)
    if ov == "PROHIBITED":
        return True
    if ov == "ALLOWED":
        return False
    return category["compliance_class"] in ("HEMP_DERIVED", "KAVA")


def recompute_on_hand(sku_id):
    sku = db["skus"].get(sku_id)
    if sku is None:
        return
    total = 0
    for lot in db["lots"].values():
        if lot["sku_id"] == sku_id and lot["status"] in ("ACTIVE", "DEPLETED"):
            total += lot["qty_remaining"]
    if sku.get("on_hand_cached") != total:
        sku["on_hand_cached"] = total
        touch(sku)


# ---------------------------------------------------------------------------
# Loyalty
# ---------------------------------------------------------------------------

def derive_tier(lifetime_pts):
    if lifetime_pts >= 50000:
        return "PLATINUM"
    if lifetime_pts >= 20000:
        return "GOLD"
    if lifetime_pts >= 5000:
        return "SILVER"
    return "BRONZE"


def refresh_tier(member):
    tier = derive_tier(member["loyalty_points_lifetime"])
    if member.get("loyalty_tier") != tier:
        member["loyalty_tier"] = tier


def credit_loyalty(member, pts):
    if pts:
        member["loyalty_points_balance"] += pts
        member["loyalty_points_lifetime"] += pts
        refresh_tier(member)
        touch(member)


def clawback_loyalty(member, pts):
    """Order-refund clawback: the only path that reduces lifetime points."""
    if pts:
        member["loyalty_points_balance"] = max(0, member["loyalty_points_balance"] - pts)
        member["loyalty_points_lifetime"] = max(0, member["loyalty_points_lifetime"] - pts)
        refresh_tier(member)
        touch(member)


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------

def recompute_lot_status(lot):
    if lot["status"] == "QUARANTINED":
        return
    if lot["qty_remaining"] == 0:
        lot["status"] = "DEPLETED"
    elif clock.today() > _parse_date(lot["expires_on"]):
        lot["status"] = "EXPIRED"
    else:
        lot["status"] = "ACTIVE"


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def fefo_check(sku_id, qty, allow_quarantined=False):
    """Dry-run: can the FEFO walk satisfy demand? Does not mutate."""
    demand = qty
    for lot in _fefo_lots(sku_id, allow_quarantined):
        demand -= min(lot["qty_remaining"], demand)
        if demand <= 0:
            return True
    return False


def fefo_allocate(sku_id, qty, allow_quarantined=False):
    """FEFO walk: decrement lots, return [{lot_id, qty_taken}]. Mutates."""
    remaining = qty
    allocation = []
    for lot in _fefo_lots(sku_id, allow_quarantined):
        take = min(lot["qty_remaining"], remaining)
        if take <= 0:
            continue
        lot["qty_remaining"] -= take
        if lot["qty_remaining"] == 0 and lot["status"] != "QUARANTINED":
            lot["status"] = "DEPLETED"
        touch(lot)
        allocation.append({"lot_id": lot["id"], "qty_taken": take})
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 422,
                       "FEFO lot walk cannot satisfy demand")
    return allocation


def _fefo_lots(sku_id, allow_quarantined):
    statuses = {"ACTIVE"}
    if allow_quarantined:
        statuses.add("QUARANTINED")
    lots = [l for l in db["lots"].values()
            if l["sku_id"] == sku_id and l["status"] in statuses]
    lots.sort(key=lambda l: (l["expires_on"], l["created_at"], l.get("_seq", 0)))
    return lots


def restore_allocation(allocation):
    for entry in allocation or []:
        lot = db["lots"].get(entry.get("lot_id"))
        if lot is None:
            continue
        lot["qty_remaining"] += entry.get("qty_taken", 0)
        recompute_lot_status(lot)
        touch(lot)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def order_lines(order_id):
    lines = [l for l in db["order_lines"].values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    return lines


def compute_unit_price(sku, order):
    """Locked per-line price: list price less club discount when subscribed."""
    price = sku["base_price_cents"]
    sub_id = order.get("applied_club_subscription_id")
    if sub_id:
        sub = db["club_subscriptions"].get(sub_id)
        if sub is not None and sub["status"] == "ACTIVE":
            plan = db["club_plans"].get(sub["plan_id"])
            if plan is not None:
                bps = plan["discount_bps_on_retail"]
                price = round_half_up(price * (10000 - bps) / 10000.0)
    return price


def _tax_state_rule(order):
    if order["channel"] == "DTC":
        code = order.get("ship_to_state_code")
    else:
        code = SHOP_HOME_STATE
    if not code:
        return None
    for rule in db["shipping_state_rules"].values():
        if rule["state_code"] == code:
            return rule
    return None


def recompute_order_totals(order):
    """Recompute subtotal/discount/shipping/tax/grand + projected points earned."""
    lines = order_lines(order["id"])
    subtotal = sum(l["extended_price_cents"] for l in lines)
    loyalty_discount = order.get("loyalty_points_redeemed") or 0
    bottles = sum(l["qty"] for l in lines)
    if order["channel"] == "DTC":
        rule = _tax_state_rule(order)
        surcharge = rule["surcharge_cents_per_order"] if rule else 0
        shipping = DTC_BASE_SHIP_CENTS + DTC_PER_BOTTLE_CENTS * bottles + surcharge
    else:
        shipping = 0
    rule = _tax_state_rule(order)
    tax_rate = rule["tax_rate_bps"] if rule else 0
    taxable = subtotal - loyalty_discount + shipping
    tax = round_half_up(taxable * tax_rate / 10000.0)
    grand = subtotal - loyalty_discount + shipping + tax
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = loyalty_discount
    order["shipping_charge_cents"] = shipping
    order["tax_cents"] = tax
    order["grand_total_cents"] = grand
    member = db["members"].get(order["member_id"])
    if member is not None:
        mult = LOYALTY_MULTIPLIER.get(member["loyalty_tier"], 1.0)
    else:
        mult = 1.0
    order["loyalty_points_earned"] = round_half_up((grand // 100) * mult)


# ---------------------------------------------------------------------------
# Club plans / subscriptions
# ---------------------------------------------------------------------------

def recompute_plan_count(plan):
    count = 0
    for sub in db["club_subscriptions"].values():
        if sub["plan_id"] == plan["id"] and sub["status"] in ("ACTIVE", "PAST_DUE"):
            count += 1
    if plan.get("active_subscription_count") != count:
        plan["active_subscription_count"] = count
        touch(plan)


def add_months(d, months):
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def advance_billing(sub, plan):
    """Advance next_billing_on by cadence; catch up until >= today."""
    months = CADENCE_MONTHS[plan["cadence"]]
    nxt = _parse_date(sub["next_billing_on"])
    nxt = add_months(nxt, months)
    today = clock.today()
    while nxt < today:
        nxt = add_months(nxt, months)
    sub["next_billing_on"] = nxt.isoformat()


# ---------------------------------------------------------------------------
# Tasting events
# ---------------------------------------------------------------------------

def recompute_compliance_hold(event):
    hold = False
    for item in db["flight_items"].values():
        if item["tasting_event_id"] != event["id"]:
            continue
        sku = db["skus"].get(item["sku_id"])
        if sku is None:
            continue
        category = db["categories"].get(sku["category_id"])
        if category is None:
            continue
        if sku_prohibited_in_state(sku, category, SHOP_HOME_STATE):
            hold = True
            break
    event["compliance_hold"] = hold


def seats_booked(event_id):
    count = 0
    for seat in db["tasting_seats"].values():
        if seat["tasting_event_id"] == event_id and seat["status"] in (
                "RESERVED", "CONFIRMED", "ATTENDED"):
            count += 1
    return count


def event_view(event):
    out = {k: v for k, v in event.items() if not k.startswith("_")}
    out["seats_booked"] = seats_booked(event["id"])
    return out


def restore_event_reservations(event):
    """Restore lot quantities reserved at publish time."""
    affected_skus = set()
    for lot_id, qty in event.get("_reserved_lots", []):
        lot = db["lots"].get(lot_id)
        if lot is not None:
            lot["qty_remaining"] += qty
            recompute_lot_status(lot)
            touch(lot)
            affected_skus.add(lot["sku_id"])
    event["_reserved_lots"] = []
    for sku_id in affected_skus:
        recompute_on_hand(sku_id)


# ---------------------------------------------------------------------------
# Clock-driven system transitions
# ---------------------------------------------------------------------------

def run_scheduled_transitions():
    """Evaluate every pending system-scheduled transition against the clock."""
    now = clock.now()
    today = now.date()

    # ClubSubscription: TRIALING -> ACTIVE when trial elapses
    for sub in list(db["club_subscriptions"].values()):
        if sub["status"] == "TRIALING":
            start = _parse_date(sub["started_on"])
            if today >= start + timedelta(days=sub.get("trial_days") or 0):
                sub["status"] = "ACTIVE"
                touch(sub)
                plan = db["club_plans"].get(sub["plan_id"])
                if plan is not None:
                    recompute_plan_count(plan)

    # InventoryLot: ACTIVE -> EXPIRED when today > expires_on
    affected_skus = set()
    for lot in list(db["lots"].values()):
        if lot["status"] == "ACTIVE" and today > _parse_date(lot["expires_on"]):
            lot["status"] = "EXPIRED"
            touch(lot)
            affected_skus.add(lot["sku_id"])
    for sku_id in affected_skus:
        recompute_on_hand(sku_id)

    # TastingEvent lifecycle
    for event in list(db["tasting_events"].values()):
        status = event["status"]
        starts = _parse_iso(event["starts_at"])
        ends = _parse_iso(event["ends_at"])
        if status == "PUBLISHED" and now >= starts - timedelta(hours=24):
            event["status"] = "LOCKED"
            touch(event)
            status = "LOCKED"
        if status == "LOCKED" and now >= starts:
            event["status"] = "IN_SESSION"
            touch(event)
            status = "IN_SESSION"
        if status == "IN_SESSION" and now >= ends:
            seats = [s for s in db["tasting_seats"].values()
                     if s["tasting_event_id"] == event["id"]]
            for seat in seats:
                if seat["status"] == "CONFIRMED":
                    seat["status"] = "NO_SHOW"
                    touch(seat)
            seats = [s for s in db["tasting_seats"].values()
                     if s["tasting_event_id"] == event["id"]]
            if all(s["status"] in ("ATTENDED", "NO_SHOW", "CANCELLED", "REFUNDED")
                   for s in seats):
                event["status"] = "COMPLETED"
                touch(event)


def _parse_iso(v):
    s = v
    if isinstance(s, str):
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    return v
