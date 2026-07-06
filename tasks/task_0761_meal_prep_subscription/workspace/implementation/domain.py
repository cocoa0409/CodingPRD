"""Domain lookups, ownership checks, par reconciliation, pricing and cascades."""
from decimal import Decimal, ROUND_HALF_UP

import store
from store import db, now_clock, touch, base_fields, format_ms
from helpers import ApiError, wallet_balance, recompute_run_par


# --------------------------------------------------------------------------
# Lookups (existence — priority 3)
# --------------------------------------------------------------------------
def get_zone(zid):
    z = db.zones.get(zid)
    if z is None:
        raise ApiError("ERR_ZONE_NOT_FOUND", 404, "Shipping zone not found")
    return z


def get_plan(pid):
    p = db.plans.get(pid)
    if p is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404, "Plan not found")
    return p


def get_meal(mid):
    m = db.meals.get(mid)
    if m is None:
        raise ApiError("ERR_MEAL_NOT_FOUND", 404, "Meal not found")
    return m


def get_run(rid):
    r = db.runs.get(rid)
    if r is None:
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "Production run not found")
    return r


def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    return c


def get_subscription(sid):
    s = db.subscriptions.get(sid)
    if s is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    return s


def get_box(bid):
    b = db.boxes.get(bid)
    if b is None:
        raise ApiError("ERR_BOX_NOT_FOUND", 404, "Box not found")
    return b


def get_box_item(iid):
    i = db.box_items.get(iid)
    if i is None:
        raise ApiError("ERR_BOX_ITEM_NOT_FOUND", 404, "Box item not found")
    return i


def get_plan_change(pcid):
    pc = db.plan_changes.get(pcid)
    if pc is None:
        raise ApiError("ERR_PLAN_CHANGE_NOT_FOUND", 404, "Plan change not found")
    return pc


def get_referral(rid):
    r = db.referrals.get(rid)
    if r is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", 404, "Referral not found")
    return r


def get_ledger(lid):
    e = db.ledger.get(lid)
    if e is None:
        raise ApiError("ERR_CREDIT_NOT_FOUND", 404, "Credit ledger entry not found")
    return e


# --------------------------------------------------------------------------
# Ownership (priority 2 — checked after existence so the entity is loaded)
# --------------------------------------------------------------------------
def customer_id_of_subscription(sub):
    return sub["customer_id"]


def owns_subscription(uid, sub):
    return sub["customer_id"] == uid


def owns_box(uid, box):
    sub = db.subscriptions.get(box["subscription_id"])
    return sub is not None and sub["customer_id"] == uid


def owns_box_item(uid, item):
    box = db.boxes.get(item["box_id"])
    return box is not None and owns_box(uid, box)


def owns_pause(uid, pw):
    sub = db.subscriptions.get(pw["subscription_id"])
    return sub is not None and sub["customer_id"] == uid


def owns_plan_change(uid, pc):
    sub = db.subscriptions.get(pc["subscription_id"])
    return sub is not None and sub["customer_id"] == uid


def owns_referral(uid, ref):
    return uid in (ref["referrer_customer_id"], ref["referee_customer_id"])


def owns_ledger(uid, entry):
    return entry["customer_id"] == uid


def customer_of_box(box):
    sub = db.subscriptions.get(box["subscription_id"])
    return db.customers.get(sub["customer_id"]) if sub else None


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
def add_ledger(customer_id, amount_cents, reason, box_id=None):
    entry = base_fields(mutable=False)
    entry["customer_id"] = customer_id
    entry["box_id"] = box_id
    entry["amount_cents"] = amount_cents
    entry["reason"] = reason
    db.ledger[entry["id"]] = entry
    return entry


# --------------------------------------------------------------------------
# Par reconciliation
# --------------------------------------------------------------------------
def reconcile_run(run):
    """Recompute par from SELECTED items and flip AVAILABLE<->SOLD_OUT."""
    old_reserved = run.get("par_reserved")
    old_status = run["status"]
    recompute_run_par(run)
    if run["status"] == "AVAILABLE" and run["par_remaining"] == 0:
        run["status"] = "SOLD_OUT"
    elif run["status"] == "SOLD_OUT" and run["par_remaining"] > 0:
        run["status"] = "AVAILABLE"
    if run.get("par_reserved") != old_reserved or run["status"] != old_status:
        touch(run)


def find_available_run(meal_id, delivery_date, quantity):
    candidates = []
    for r in db.runs.values():
        if (r["status"] == "AVAILABLE" and r["meal_id"] == meal_id
                and r["delivery_date"] == delivery_date):
            recompute_run_par(r)
            if r["par_remaining"] >= quantity:
                candidates.append(r)
    if not candidates:
        return None
    candidates.sort(key=lambda r: r["_seq"])
    return candidates[0]


def release_selected_items(box, new_status="REMOVED"):
    """Move every SELECTED item of the box to new_status and release its par."""
    for item in db.box_items.values():
        if item["box_id"] == box["id"] and item["status"] == "SELECTED":
            item["status"] = new_status
            run = db.runs.get(item.get("reserved_run_id"))
            item["reserved_run_id"] = None
            touch(item)
            if run is not None:
                reconcile_run(run)


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def selected_items(box):
    return [i for i in db.box_items.values()
            if i["box_id"] == box["id"] and i["status"] == "SELECTED"]


def referee_first_box_discount(box, customer):
    if not box.get("is_first_box") or not customer.get("referred_by_code"):
        return 0
    total = 0
    price = box["plan_price_per_meal_cents"]
    for item in selected_items(box):
        line_gross = price * item["quantity"]
        total += round_half_up(Decimal(line_gross) * Decimal(store.REFEREE_DISCOUNT_PCT))
    return total


def compute_box_charge(box):
    """Pinned-order box charge; pins credit_applied but does not consume it."""
    customer = customer_of_box(box)
    price = box["plan_price_per_meal_cents"]
    items = selected_items(box)
    meals_count = sum(i["quantity"] for i in items)
    subtotal = price * meals_count
    discount = referee_first_box_discount(box, customer)
    shipping = 0 if meals_count >= store.FREE_SHIP_MIN_MEALS else box["base_shipping_fee_cents"]
    cold_pack = box["cold_pack_fee_snapshot_cents"]
    gross = subtotal - discount + shipping + cold_pack
    if gross < 0:
        gross = 0
    wallet = wallet_balance(customer["id"])
    credit_applied = min(gross, wallet)
    if credit_applied < 0:
        credit_applied = 0
    total_charged = gross - credit_applied
    box["subtotal_cents"] = subtotal
    box["discount_cents"] = discount
    box["shipping_fee_cents"] = shipping
    box["cold_pack_fee_cents"] = cold_pack
    box["credit_applied_cents"] = credit_applied
    box["total_charged_cents"] = total_charged


# --------------------------------------------------------------------------
# Referral reward
# --------------------------------------------------------------------------
def referral_reward_cents(referee_meals_per_week):
    if referee_meals_per_week >= store.PREMIUM_MIN_MEALS:
        return store.REFERRAL_BASE_CENTS + store.PREMIUM_BONUS_CENTS
    return store.REFERRAL_BASE_CENTS


def fire_referral_reward(box):
    """When a referee's first box ships, reward the referrer."""
    if not box.get("is_first_box"):
        return
    customer = customer_of_box(box)
    if customer is None or customer["status"] != "ACTIVE":
        return
    ref = None
    for r in db.referrals.values():
        if r["status"] == "PENDING" and r["referee_customer_id"] == customer["id"]:
            ref = r
            break
    if ref is None:
        return
    sub = db.subscriptions.get(box["subscription_id"])
    reward = referral_reward_cents(sub["meals_per_week"])
    ref["reward_cents"] = reward
    ref["status"] = "REWARDED"
    touch(ref)
    add_ledger(ref["referrer_customer_id"], reward, "REFERRAL_REWARD", box_id=None)


# --------------------------------------------------------------------------
# Customer's boxes (for is_first_box)
# --------------------------------------------------------------------------
def customer_has_box(customer_id):
    for box in db.boxes.values():
        sub = db.subscriptions.get(box["subscription_id"])
        if sub is not None and sub["customer_id"] == customer_id:
            return True
    return False


def customer_first_box_shipped(customer_id):
    for box in db.boxes.values():
        sub = db.subscriptions.get(box["subscription_id"])
        if (sub is not None and sub["customer_id"] == customer_id
                and box.get("is_first_box")
                and box["fulfillment_status"] in ("SHIPPED", "DELIVERED")):
            return True
    return False
