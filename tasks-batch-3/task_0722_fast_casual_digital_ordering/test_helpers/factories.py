"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_WINDOW_START, DEFAULT_WINDOW_END

_email_counter = [0]


def unique_email(prefix="user") -> str:
    """Generate a process-unique email so duplicate-email rejection does not interfere."""
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_store_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Store",
        "state_code": "TX",
        "throughput_capacity_per_slot": 10,
        "locker_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(store_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "name": "Harvest Bowl",
        "base_price_cents": 1450,
        "base_calories": 600,
    }
    defaults.update(overrides)
    return defaults


def create_modifier_payload(menu_item_id: str, **overrides) -> dict:
    defaults = {
        "menu_item_id": menu_item_id,
        "name": "Extra Avocado",
        "price_delta_cents": 50,
        "calorie_delta": 20,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_slot_payload(store_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "window_start_utc": DEFAULT_WINDOW_START,
        "window_end_utc": DEFAULT_WINDOW_END,
        "channel": "COUNTER",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(home_store_id: str, **overrides) -> dict:
    defaults = {
        "email": unique_email("cust"),
        "full_name": "Test Customer",
        "home_store_id": home_store_id,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "tier_name": "PERKS_PLUS",
        "monthly_fee_cents": 999,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, plan_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, store_id: str, pickup_slot_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "store_id": store_id,
        "pickup_slot_id": pickup_slot_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(menu_item_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {
        "menu_item_id": menu_item_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_challenge_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "target_order_count": 1,
        "bonus_points": 500,
    }
    defaults.update(overrides)
    return defaults


def wallet_adjustment_payload(delta_cents: int, reason: str = "SEED") -> dict:
    return {"delta_cents": delta_cents, "reason": reason}


def points_ledger_payload(loyalty_account_id: str, delta_points: int, reason: str = "ADJUSTMENT") -> dict:
    return {
        "loyalty_account_id": loyalty_account_id,
        "delta_points": delta_points,
        "reason": reason,
    }
