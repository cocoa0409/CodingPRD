"""Domain operations: entity factories, recompute cascades, state transitions.

These functions own the business rules in PRD §3. Route handlers in app.py call
into here after performing auth/existence/state checks.
"""
import calc
import errors
from store import (
    clock, new_id, next_seq,
    accounts, pets, recipes, subscriptions, weight_logs, orders,
    shipments, referral_credits,
)
import serialize


# --------------------------------------------------------------------------
# Common system-field helpers
# --------------------------------------------------------------------------
def _stamp_new(rec, versioned=True):
    now = clock.now()
    rec["_seq"] = next_seq()
    rec["created_at"] = now
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.5/§2.7)."""
    rec["updated_at"] = clock.now()
    rec["version"] += 1


# --------------------------------------------------------------------------
# Account
# --------------------------------------------------------------------------
def gen_referral_code():
    import random
    import string
    alpha = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(alpha, k=8))
        if not any(a["referral_code"] == code for a in accounts.values()):
            return code


def create_account(email, full_name, country_code, referred_by_account_id):
    rec = {
        "id": new_id(),
        "email": email,
        "full_name": full_name,
        "country_code": country_code,
        "referral_code": gen_referral_code(),
        "referred_by_account_id": referred_by_account_id,
        "status": "ACTIVE",
    }
    _stamp_new(rec)
    accounts[rec["id"]] = rec
    return rec


def find_account_by_referral_code(code):
    for a in accounts.values():
        if a["referral_code"] == code:
            return a
    return None


def find_account_by_email(email):
    low = email.lower()
    for a in accounts.values():
        if a["email"].lower() == low:
            return a
    return None


def mint_signup_credits(referrer, referred):
    """Two PENDING SIGNUP rows: REFERRER + REFERRED. Amounts computed but not
    yet spendable; locked at first PAID order. (PRD §3.1/§3.8)
    """
    referrer_amt = calc.referrer_grant_cents(
        serialize.compute_lifetime_grants(referrer["id"]))
    referred_amt = calc.referred_grant_cents()

    rows = []
    for beneficiary, amt in (("REFERRER", referrer_amt), ("REFERRED", referred_amt)):
        rc = {
            "id": new_id(),
            "referrer_account_id": referrer["id"],
            "referred_account_id": referred["id"],
            "amount_cents": amt,
            "beneficiary": beneficiary,
            "reason": "SIGNUP",
            "status": "PENDING",
        }
        _stamp_new(rc)
        referral_credits[rc["id"]] = rc
        rows.append(rc)
    return rows


# --------------------------------------------------------------------------
# Pet
# --------------------------------------------------------------------------
def recompute_pet_nutrition(pet):
    target, stage = calc.daily_calorie_target(pet, clock.now())
    pet["daily_calorie_target"] = target
    pet["life_stage"] = stage


def create_pet(account_id, name, species, sex, birth_date, initial_weight_kg,
               ideal_weight_kg, activity_level, neutered, body_condition_goal,
               allergen_exclusions):
    rec = {
        "id": new_id(),
        "account_id": account_id,
        "name": name,
        "species": species,
        "sex": sex,
        "birth_date": birth_date,
        "current_weight_kg": initial_weight_kg,
        "initial_weight_kg": initial_weight_kg,
        "ideal_weight_kg": ideal_weight_kg,
        "activity_level": activity_level,
        "neutered": neutered,
        "body_condition_goal": body_condition_goal,
        "allergen_exclusions": allergen_exclusions,
        "daily_calorie_target": 0,
        "life_stage": "ADULT",
        "status": "ACTIVE",
    }
    _stamp_new(rec)
    recompute_pet_nutrition(rec)
    pets[rec["id"]] = rec
    return rec


def pet_has_blocking_subscription(pet_id):
    for s in subscriptions.values():
        if s["pet_id"] == pet_id and s["status"] in ("ACTIVE", "PAUSED", "PAST_DUE"):
            return True
    return False


# --------------------------------------------------------------------------
# WeightLog
# --------------------------------------------------------------------------
def create_weight_log(pet, weight_kg, effective_date):
    rec = {
        "id": new_id(),
        "pet_id": pet["id"],
        "weight_kg": weight_kg,
        "effective_date": effective_date,
        "status": "APPLIED",
    }
    # WeightLog carries only id + created_at (no updated_at / version).
    rec["_seq"] = next_seq()
    rec["created_at"] = clock.now()
    weight_logs[rec["id"]] = rec
    _reapply_weight_logs(pet)
    return rec


def _reapply_weight_logs(pet):
    """Exactly one log APPLIED: latest effective_date, ties broken by earlier
    created_at (ascending). Recompute current_weight_kg + daily_calorie_target.
    """
    logs = [w for w in weight_logs.values() if w["pet_id"] == pet["id"]]
    if not logs:
        return
    winner = _select_applied(logs)
    for w in logs:
        w["status"] = "APPLIED" if w["id"] == winner["id"] else "SUPERSEDED"
    pet["current_weight_kg"] = winner["weight_kg"]
    recompute_pet_nutrition(pet)


def _select_applied(logs):
    # latest effective_date; tie-break earliest created_at (ascending), then _seq.
    best = None
    for w in logs:
        if best is None:
            best = w
            continue
        if w["effective_date"] > best["effective_date"]:
            best = w
        elif w["effective_date"] == best["effective_date"]:
            if w["created_at"] < best["created_at"]:
                best = w
            elif w["created_at"] == best["created_at"] and w["_seq"] < best["_seq"]:
                best = w
    return best


# --------------------------------------------------------------------------
# Recipe
# --------------------------------------------------------------------------
def create_recipe(name, species, kcal_per_gram, price_per_100g_cents,
                  ingredient_allergens, availability_regions, vet_formulated):
    rec = {
        "id": new_id(),
        "name": name,
        "species": species,
        "kcal_per_gram": kcal_per_gram,
        "price_per_100g_cents": price_per_100g_cents,
        "ingredient_allergens": ingredient_allergens,
        "availability_regions": availability_regions,
        "vet_formulated": vet_formulated,
        "status": "DRAFT",
    }
    _stamp_new(rec)
    recipes[rec["id"]] = rec
    return rec


# --------------------------------------------------------------------------
# Subscription
# --------------------------------------------------------------------------
def compute_estimate(sub, pet, recipe):
    """estimate variant: uses live Pet.daily_calorie_target; writes the pack and
    cycle_price fields on the subscription.
    """
    gpd, total, price = calc.pack_and_price(
        pet["daily_calorie_target"], recipe["kcal_per_gram"],
        sub["cadence_days"], recipe["price_per_100g_cents"])
    sub["pack_grams_per_day"] = gpd
    sub["pack_total_grams"] = total
    sub["cycle_price_cents"] = price


def create_subscription(account_id, pet_id, recipe_id, cadence_days, pet, recipe):
    rec = {
        "id": new_id(),
        "account_id": account_id,
        "pet_id": pet_id,
        "recipe_id": recipe_id,
        "cadence_days": cadence_days,
        "pack_grams_per_day": 0,
        "pack_total_grams": 0,
        "cycle_price_cents": 0,
        "transition_remaining_cycles": 0,
        "pending_resize_grams_per_day": None,
        "resize_effective_at": None,
        "pause_until": None,
        "next_order_date": None,
        "consecutive_failed_charges": 0,
        "status": "DRAFT",
    }
    _stamp_new(rec)
    compute_estimate(rec, pet, recipe)
    subscriptions[rec["id"]] = rec
    return rec


def _price_from_grams(total_grams, recipe):
    """cycle_price_cents from a given pack_total_grams (grams already rounded)."""
    from decimal import Decimal
    hundreds = Decimal(total_grams) / Decimal(100)
    discount = calc.volume_discount(total_grams)
    tier_rate = Decimal(recipe["price_per_100g_cents"]) * (Decimal(1) - discount)
    return int(calc.round_half_up(hundreds * tier_rate, 0))


def realize_resize(sub, pet, recipe):
    """Realize a staged resize: staged grams -> pack fields, recompute price."""
    gpd = sub["pending_resize_grams_per_day"]
    total = gpd * sub["cadence_days"]
    sub["pack_grams_per_day"] = gpd
    sub["pack_total_grams"] = total
    sub["cycle_price_cents"] = _price_from_grams(total, recipe)
    sub["pending_resize_grams_per_day"] = None
    sub["resize_effective_at"] = None


def maybe_realize_due_resize(sub):
    """If a staged resize is due (resize_effective_at <= clock), realize it."""
    if sub["pending_resize_grams_per_day"] is not None \
            and sub["resize_effective_at"] is not None \
            and sub["resize_effective_at"] <= clock.now():
        pet = pets[sub["pet_id"]]
        recipe = recipes[sub["recipe_id"]]
        realize_resize(sub, pet, recipe)


def maybe_auto_resume(sub):
    """PAUSED auto-resume on order generation when clock >= pause_until."""
    if sub["status"] == "PAUSED" and sub["pause_until"] is not None \
            and clock.now() >= sub["pause_until"]:
        sub["status"] = "ACTIVE"
        sub["pause_until"] = None
        nod = sub["next_order_date"]
        now = clock.now()
        sub["next_order_date"] = max(nod, now) if nod is not None else now


def account_has_paid_order(account_id):
    for o in orders.values():
        if o["account_id"] == account_id and o["status"] == "PAID":
            return True
    return False


def revoke_pending_signup_if_no_paid(account_id):
    """If the account has no PAID order across all its subscriptions, revoke its
    PENDING SIGNUP referral-credit rows where it is referred_account_id.
    """
    if account_has_paid_order(account_id):
        return
    for rc in referral_credits.values():
        if (rc["reason"] == "SIGNUP"
                and rc["status"] == "PENDING"
                and rc["referred_account_id"] == account_id):
            rc["status"] = "REVOKED"
            touch(rc)


def skip_scheduled_orders(sub):
    """Cascade: every SCHEDULED order for this subscription -> SKIPPED."""
    for o in orders.values():
        if o["subscription_id"] == sub["id"] and o["status"] == "SCHEDULED":
            o["status"] = "SKIPPED"
            touch(o)


def clear_pending_resize(sub):
    sub["pending_resize_grams_per_day"] = None
    sub["resize_effective_at"] = None


def cancel_cascade(sub):
    """Shared cancel cascade for explicit cancel and PAST_DUE->CANCELLED."""
    skip_scheduled_orders(sub)
    clear_pending_resize(sub)
    revoke_pending_signup_if_no_paid(sub["account_id"])


def sub_has_charging_order(sub_id):
    for o in orders.values():
        if o["subscription_id"] == sub_id and o["status"] == "CHARGING":
            return True
    return False


# --------------------------------------------------------------------------
# Order
# --------------------------------------------------------------------------
def next_cycle_index(sub_id):
    existing = [o["cycle_index"] for o in orders.values()
                if o["subscription_id"] == sub_id]
    return (max(existing) + 1) if existing else 1


def generate_order(sub):
    """Generate the next cycle order. Realizes due resume + resize first, then
    snapshots grams and the actual cycle-price variant onto the order.
    """
    maybe_auto_resume(sub)
    maybe_realize_due_resize(sub)

    pet = pets[sub["pet_id"]]
    recipe = recipes[sub["recipe_id"]]

    food_grams = sub["pack_total_grams"]
    # actual variant: food_subtotal from the subscription's CURRENT pack snapshot.
    food_subtotal = _price_from_grams(food_grams, recipe)

    is_transition = sub["transition_remaining_cycles"] > 0

    rec = {
        "id": new_id(),
        "subscription_id": sub["id"],
        "account_id": sub["account_id"],
        "cycle_index": next_cycle_index(sub["id"]),
        "scheduled_ship_date": sub["next_order_date"],
        "food_grams": food_grams,
        "is_transition_cycle": is_transition,
        "food_subtotal_cents": food_subtotal,
        "credit_applied_cents": 0,
        "shipping_cents": 0,
        "total_charged_cents": 0,
        "status": "SCHEDULED",
    }
    _stamp_new(rec)
    orders[rec["id"]] = rec
    touch(sub)  # generating the order increments the subscription's version
    return rec


def finalize_billing(order, account_id):
    """Finalize shipping/credit/total from current wallet at charge time."""
    wallet = serialize.compute_wallet_credit(account_id)
    shipping, credit, total = calc.settle_charge(order["food_subtotal_cents"], wallet)
    order["shipping_cents"] = shipping
    order["credit_applied_cents"] = credit
    order["total_charged_cents"] = total


def settle_succeeded(order, sub):
    """CHARGING -> PAID cascade (PRD §3.7)."""
    referred_account_id = sub["account_id"]
    had_paid_before = account_has_paid_order(referred_account_id)

    order["status"] = "PAID"
    touch(order)

    # consecutive_failed_charges reset; PAST_DUE -> ACTIVE recovery.
    sub["consecutive_failed_charges"] = 0
    if sub["status"] == "PAST_DUE":
        sub["status"] = "ACTIVE"
    # next_order_date += cadence; transition_remaining_cycles -1 floor 0.
    _advance_next_order_date(sub)
    sub["transition_remaining_cycles"] = max(0, sub["transition_remaining_cycles"] - 1)

    # Shipment created PENDING for this order.
    create_shipment(order)

    # First PAID order for the referred account -> GRANT pending SIGNUP rows.
    if not had_paid_before:
        grant_signup_credits(referred_account_id)

    touch(sub)


def settle_declined(order, sub):
    """CHARGING -> FAILED cascade (PRD §3.7)."""
    order["status"] = "FAILED"
    touch(order)

    sub["consecutive_failed_charges"] += 1
    if sub["status"] == "ACTIVE":
        sub["status"] = "PAST_DUE"

    if sub["consecutive_failed_charges"] >= calc.MAX_FAILED_CHARGES:
        # PAST_DUE -> CANCELLED cascade.
        sub["status"] = "CANCELLED"
        cancel_cascade(sub)

    touch(sub)


def _advance_next_order_date(sub):
    from datetime import timedelta
    sub["next_order_date"] = sub["next_order_date"] + timedelta(days=sub["cadence_days"])


def grant_signup_credits(referred_account_id):
    """Flip the referred account's PENDING SIGNUP rows to GRANTED and lock amounts.

    The referrer_grant amount is recomputed/clamped against the referrer's
    lifetime grants at grant time so the lifetime cap is honored.
    """
    rows = [rc for rc in referral_credits.values()
            if rc["reason"] == "SIGNUP" and rc["status"] == "PENDING"
            and rc["referred_account_id"] == referred_account_id]
    for rc in rows:
        if rc["beneficiary"] == "REFERRER":
            lifetime = serialize.compute_lifetime_grants(rc["referrer_account_id"])
            rc["amount_cents"] = calc.referrer_grant_cents(lifetime)
        rc["status"] = "GRANTED"
        touch(rc)


# --------------------------------------------------------------------------
# Shipment
# --------------------------------------------------------------------------
def create_shipment(order):
    transit_days = 2
    rec = {
        "id": new_id(),
        "order_id": order["id"],
        "transit_days": transit_days,
        "coolant_packs": calc.coolant_packs(order["food_grams"], transit_days),
        "dispatched_at": None,
        "status": "PENDING",
    }
    _stamp_new(rec)
    shipments[rec["id"]] = rec
    return rec


def recompute_coolant(shipment, order):
    shipment["coolant_packs"] = calc.coolant_packs(
        order["food_grams"], shipment["transit_days"])


def mint_make_good(order):
    """Spoilage compensation: MAKE_GOOD ReferralCredit GRANTED to owning account
    for credit_applied_cents + total_charged_cents (full refund as wallet credit).
    """
    amount = order["credit_applied_cents"] + order["total_charged_cents"]
    rc = {
        "id": new_id(),
        "referrer_account_id": order["account_id"],
        "referred_account_id": order["account_id"],
        "amount_cents": amount,
        "beneficiary": "REFERRED",
        "reason": "MAKE_GOOD",
        "status": "GRANTED",
    }
    _stamp_new(rc)
    referral_credits[rc["id"]] = rc
    return rc
