"""Public serialization of entities (SCAFFOLD §1.1, PRD §2.4).

Each serializer emits the common audit fields (id, created_at, updated_at,
version) plus the entity-specific fields. Internal-only keys (e.g. _seq) are
never exposed.
"""

COMMON = ("id", "created_at", "updated_at", "version")


def _common(e):
    return {k: e[k] for k in COMMON}


def plan(e):
    d = _common(e)
    d.update({
        "code": e["code"],
        "servings_per_meal": e["servings_per_meal"],
        "meals_per_week": e["meals_per_week"],
        "is_active": e["is_active"],
    })
    return d


def shipping_zone(e):
    d = _common(e)
    d.update({
        "zone_code": e["zone_code"],
        "cold_pack_surcharge_cents": e["cold_pack_surcharge_cents"],
        "cutoff_weekday": e["cutoff_weekday"],
        "serviceable": e["serviceable"],
    })
    return d


def recipe(e):
    d = _common(e)
    d.update({
        "title": e["title"],
        "is_premium": e["is_premium"],
        "contains_allergens": list(e["contains_allergens"]),
        "diet_tags": list(e["diet_tags"]),
        "is_available": e["is_available"],
    })
    return d


def member(e):
    d = _common(e)
    d.update({
        "email": e["email"],
        "full_name": e["full_name"],
        "shipping_zone_id": e["shipping_zone_id"],
        "referred_by_member_id": e["referred_by_member_id"],
        "referral_code": e["referral_code"],
        "credit_balance_cents": e["credit_balance_cents"],
        "lifetime_box_count": e["lifetime_box_count"],
        "status": e["status"],
    })
    return d


def subscription(e):
    d = _common(e)
    d.update({
        "member_id": e["member_id"],
        "plan_id": e["plan_id"],
        "diet_preference": e["diet_preference"],
        "blocked_allergens": list(e["blocked_allergens"]),
        "monthly_addon_fee_cents": e["monthly_addon_fee_cents"],
        "billing_cycle_day": e["billing_cycle_day"],
        "scheduled_resume_date": e["scheduled_resume_date"],
        "status": e["status"],
    })
    return d


def weekly_box(e):
    d = _common(e)
    d.update({
        "subscription_id": e["subscription_id"],
        "delivery_date": e["delivery_date"],
        "cutoff_at": e["cutoff_at"],
        "provisional_charge_cents": e["provisional_charge_cents"],
        "final_charge_cents": e["final_charge_cents"],
        "selection_status": e["selection_status"],
        "fulfillment_status": e["fulfillment_status"],
    })
    return d


def box_recipe(e):
    d = _common(e)
    d.update({
        "box_id": e["box_id"],
        "recipe_id": e["recipe_id"],
        "is_premium_snapshot": e["is_premium_snapshot"],
    })
    return d


def referral(e):
    d = _common(e)
    d.update({
        "referrer_member_id": e["referrer_member_id"],
        "referee_member_id": e["referee_member_id"],
        "reward_cents": e["reward_cents"],
        "status": e["status"],
    })
    return d
