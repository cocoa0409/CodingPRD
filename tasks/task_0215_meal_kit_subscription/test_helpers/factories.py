"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) are produced here. System-managed
and computed fields (referral_code, credit_balance_cents, lifetime_box_count,
status, version, cutoff_at, charges, scheduled_resume_date) are never sent.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    """A process-unique email so registrations never collide on the unique constraint."""
    return f"{prefix}-{next(_email_counter)}@example.com"


# ---- Plan ----
def create_plan_payload(**overrides) -> dict:
    """code, servings_per_meal, meals_per_week required; is_active optional (default true)."""
    defaults = {
        "code": "COUPLE_3",
        "servings_per_meal": 2,
        "meals_per_week": 3,
    }
    defaults.update(overrides)
    return defaults


# ---- ShippingZone ----
def create_shipping_zone_payload(**overrides) -> dict:
    """zone_code, cold_pack_surcharge_cents, cutoff_weekday required; serviceable optional."""
    defaults = {
        "zone_code": "ZONE_A",
        "cold_pack_surcharge_cents": 0,
        "cutoff_weekday": 5,
    }
    defaults.update(overrides)
    return defaults


# ---- Recipe ----
def create_recipe_payload(**overrides) -> dict:
    """title required; is_premium, contains_allergens, diet_tags, is_available optional."""
    defaults = {
        "title": "Test Recipe",
    }
    defaults.update(overrides)
    return defaults


# ---- Member ----
def create_member_payload(shipping_zone_id: str, **overrides) -> dict:
    """email, full_name, shipping_zone_id required; referred_by_member_id optional."""
    defaults = {
        "email": unique_email("member"),
        "full_name": "Test Member",
        "shipping_zone_id": shipping_zone_id,
    }
    defaults.update(overrides)
    return defaults


# ---- Subscription ----
def create_subscription_payload(member_id: str, plan_id: str, **overrides) -> dict:
    """member_id, plan_id, billing_cycle_day required; diet_preference, blocked_allergens,
    monthly_addon_fee_cents optional."""
    defaults = {
        "member_id": member_id,
        "plan_id": plan_id,
        "billing_cycle_day": 1,
    }
    defaults.update(overrides)
    return defaults


# ---- WeeklyBox ----
def create_weekly_box_payload(subscription_id: str, delivery_date: str, **overrides) -> dict:
    """subscription_id, delivery_date required."""
    defaults = {
        "subscription_id": subscription_id,
        "delivery_date": delivery_date,
    }
    defaults.update(overrides)
    return defaults


# ---- BoxRecipe ----
def add_recipe_payload(recipe_id: str, **overrides) -> dict:
    """recipe_id required."""
    defaults = {"recipe_id": recipe_id}
    defaults.update(overrides)
    return defaults


# ---- Referral ----
def create_referral_payload(referrer_member_id: str, referee_member_id: str, **overrides) -> dict:
    """referrer_member_id, referee_member_id required."""
    defaults = {
        "referrer_member_id": referrer_member_id,
        "referee_member_id": referee_member_id,
    }
    defaults.update(overrides)
    return defaults


# ---- Plan change (OCC) ----
def plan_change_payload(plan_id: str, expected_subscription_version: int, **overrides) -> dict:
    """plan_id, expected_subscription_version required."""
    defaults = {
        "plan_id": plan_id,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


# ---- Pause ----
def pause_payload(resume_date: str, **overrides) -> dict:
    """resume_date required."""
    defaults = {"resume_date": resume_date}
    defaults.update(overrides)
    return defaults


# ---- Clock ----
def clock_payload(now_iso8601: str) -> dict:
    return {"now_iso8601": now_iso8601}
