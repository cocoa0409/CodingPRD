"""Serialization of internal entity dicts into API response shapes.

Internal records hold native datetime objects for date/time fields and a
monotonic _seq for ordering. Serializers project the PRD-visible field set,
formatting datetimes as ISO 8601 UTC with three fractional digits.
"""
import calc
from store import iso_millis, clock


def ser_account(a):
    return {
        "id": a["id"],
        "email": a["email"],
        "full_name": a["full_name"],
        "country_code": a["country_code"],
        "referral_code": a["referral_code"],
        "referred_by_account_id": a["referred_by_account_id"],
        "wallet_credit_cents": compute_wallet_credit(a["id"]),
        "lifetime_referral_grants_cents": compute_lifetime_grants(a["id"]),
        "status": a["status"],
        "created_at": iso_millis(a["created_at"]),
        "updated_at": iso_millis(a["updated_at"]),
        "version": a["version"],
    }


def ser_pet(p):
    return {
        "id": p["id"],
        "account_id": p["account_id"],
        "name": p["name"],
        "species": p["species"],
        "sex": p["sex"],
        "birth_date": iso_millis(p["birth_date"]),
        "current_weight_kg": p["current_weight_kg"],
        "initial_weight_kg": p["initial_weight_kg"],
        "ideal_weight_kg": p["ideal_weight_kg"],
        "activity_level": p["activity_level"],
        "neutered": p["neutered"],
        "body_condition_goal": p["body_condition_goal"],
        "allergen_exclusions": p["allergen_exclusions"],
        "daily_calorie_target": p["daily_calorie_target"],
        "life_stage": p["life_stage"],
        "status": p["status"],
        "created_at": iso_millis(p["created_at"]),
        "updated_at": iso_millis(p["updated_at"]),
        "version": p["version"],
    }


def ser_recipe(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "species": r["species"],
        "kcal_per_gram": r["kcal_per_gram"],
        "price_per_100g_cents": r["price_per_100g_cents"],
        "ingredient_allergens": r["ingredient_allergens"],
        "availability_regions": r["availability_regions"],
        "vet_formulated": r["vet_formulated"],
        "status": r["status"],
        "created_at": iso_millis(r["created_at"]),
        "updated_at": iso_millis(r["updated_at"]),
        "version": r["version"],
    }


def ser_subscription(s):
    return {
        "id": s["id"],
        "account_id": s["account_id"],
        "pet_id": s["pet_id"],
        "recipe_id": s["recipe_id"],
        "cadence_days": s["cadence_days"],
        "pack_grams_per_day": s["pack_grams_per_day"],
        "pack_total_grams": s["pack_total_grams"],
        "cycle_price_cents": s["cycle_price_cents"],
        "transition_remaining_cycles": s["transition_remaining_cycles"],
        "pending_resize_grams_per_day": s["pending_resize_grams_per_day"],
        "resize_effective_at": iso_millis(s["resize_effective_at"]),
        "pause_until": iso_millis(s["pause_until"]),
        "next_order_date": iso_millis(s["next_order_date"]),
        "consecutive_failed_charges": s["consecutive_failed_charges"],
        "status": s["status"],
        "created_at": iso_millis(s["created_at"]),
        "updated_at": iso_millis(s["updated_at"]),
        "version": s["version"],
    }


def ser_weight_log(w):
    return {
        "id": w["id"],
        "created_at": iso_millis(w["created_at"]),
        "pet_id": w["pet_id"],
        "weight_kg": w["weight_kg"],
        "effective_date": iso_millis(w["effective_date"]),
        "status": w["status"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "subscription_id": o["subscription_id"],
        "account_id": o["account_id"],
        "cycle_index": o["cycle_index"],
        "scheduled_ship_date": iso_millis(o["scheduled_ship_date"]),
        "food_grams": o["food_grams"],
        "is_transition_cycle": o["is_transition_cycle"],
        "food_subtotal_cents": o["food_subtotal_cents"],
        "credit_applied_cents": o["credit_applied_cents"],
        "shipping_cents": o["shipping_cents"],
        "total_charged_cents": o["total_charged_cents"],
        "status": o["status"],
        "created_at": iso_millis(o["created_at"]),
        "updated_at": iso_millis(o["updated_at"]),
        "version": o["version"],
    }


def ser_shipment(sh):
    return {
        "id": sh["id"],
        "order_id": sh["order_id"],
        "coolant_packs": sh["coolant_packs"],
        "transit_days": sh["transit_days"],
        "dispatched_at": iso_millis(sh["dispatched_at"]),
        "status": sh["status"],
        "created_at": iso_millis(sh["created_at"]),
        "updated_at": iso_millis(sh["updated_at"]),
        "version": sh["version"],
    }


def ser_referral_credit(rc):
    return {
        "id": rc["id"],
        "referrer_account_id": rc["referrer_account_id"],
        "referred_account_id": rc["referred_account_id"],
        "amount_cents": rc["amount_cents"],
        "beneficiary": rc["beneficiary"],
        "reason": rc["reason"],
        "status": rc["status"],
        "created_at": iso_millis(rc["created_at"]),
        "updated_at": iso_millis(rc["updated_at"]),
        "version": rc["version"],
    }


# --- Computed fiscal fields (PRD §3.1) ------------------------------------
def compute_wallet_credit(account_id):
    """Sum of amount_cents across GRANTED credit rows paying out to this account,
    minus credit consumed by PAID orders; floored at 0.
    """
    from store import referral_credits, orders

    granted = 0
    for rc in referral_credits.values():
        if rc["status"] == "GRANTED" and _beneficiary_account(rc) == account_id:
            granted += rc["amount_cents"]

    consumed = 0
    for o in orders.values():
        if o["status"] == "PAID" and o["account_id"] == account_id:
            consumed += o["credit_applied_cents"]

    return max(0, granted - consumed)


def compute_lifetime_grants(account_id):
    """Cumulative referrer_grant_cents GRANTED with this account as referrer."""
    from store import referral_credits

    total = 0
    for rc in referral_credits.values():
        if (rc["status"] == "GRANTED"
                and rc["reason"] == "SIGNUP"
                and rc["beneficiary"] == "REFERRER"
                and rc["referrer_account_id"] == account_id):
            total += rc["amount_cents"]
    return total


def _beneficiary_account(rc):
    if rc["beneficiary"] == "REFERRER":
        return rc["referrer_account_id"]
    return rc["referred_account_id"]
