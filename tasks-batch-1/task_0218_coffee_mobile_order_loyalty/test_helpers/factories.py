"""Payload factories — one per entity, input fields only.

Each factory returns a body suitable for the corresponding POST/PATCH endpoint.
Only fields the client supplies (source: input) are included; system/computed
fields (status, balances, totals, stars) are never set by the client.
"""

DEFAULTS = {
    "MEMBER_EMAIL": "member@example.com",
    "MEMBER_NAME": "Test Member",
    "BIRTH_MONTH_DAY": "03-14",
    "STORE_NAME": "Test Store",
    "TIMEZONE": "America/Los_Angeles",
    "SLOT_CAPACITY": 5,
    "PREP_MINUTES": 0,
    "MENU_ITEM_NAME": "Test Latte",
    "BASE_PRICE_CENTS": 615,
    "CATEGORY": "BEVERAGE",
    "MODIFIER_NAME": "Oat Milk",
    "GROUP_CODE": "MILK",
    "PRICE_DELTA_CENTS": 70,
}

# A reusable unique-email counter so repeated registrations in one test don't collide.
_email_seq = [0]


def unique_email(prefix: str = "m") -> str:
    _email_seq[0] += 1
    return f"{prefix}{_email_seq[0]}@example.com"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email("member"),
        "full_name": DEFAULTS["MEMBER_NAME"],
        "birth_month_day": DEFAULTS["BIRTH_MONTH_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["STORE_NAME"],
        "timezone": DEFAULTS["TIMEZONE"],
        "slot_capacity": DEFAULTS["SLOT_CAPACITY"],
        "prep_minutes": DEFAULTS["PREP_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["MENU_ITEM_NAME"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "category": DEFAULTS["CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_modifier_payload(**overrides) -> dict:
    defaults = {
        "group_code": DEFAULTS["GROUP_CODE"],
        "name": DEFAULTS["MODIFIER_NAME"],
        "price_delta_cents": DEFAULTS["PRICE_DELTA_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_pickup_slot_payload(window_start, window_end, **overrides) -> dict:
    defaults = {"window_start": window_start, "window_end": window_end}
    defaults.update(overrides)
    return defaults


def reload_card_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def update_card_payload(**overrides) -> dict:
    """All fields are optional on the card-config PATCH (PRD §3.1)."""
    return dict(overrides)


def create_order_payload(store_id, pickup_slot_id, applied_reward_id=None, **overrides) -> dict:
    defaults = {"store_id": store_id, "pickup_slot_id": pickup_slot_id}
    if applied_reward_id is not None:
        defaults["applied_reward_id"] = applied_reward_id
    defaults.update(overrides)
    return defaults


def add_line_payload(menu_item_id, quantity=1, modifiers=None, **overrides) -> dict:
    defaults = {"menu_item_id": menu_item_id, "quantity": quantity}
    if modifiers is not None:
        defaults["modifiers"] = modifiers
    defaults.update(overrides)
    return defaults


def pay_payload(pay_method, expected_card_version=None, **overrides) -> dict:
    defaults = {"pay_method": pay_method}
    if expected_card_version is not None:
        defaults["expected_card_version"] = expected_card_version
    defaults.update(overrides)
    return defaults


def place_payload(expected_slot_version, **overrides) -> dict:
    defaults = {"expected_slot_version": expected_slot_version}
    defaults.update(overrides)
    return defaults


def pause_payload(paused: bool) -> dict:
    return {"paused": paused}


def refund_payload(destination, **overrides) -> dict:
    defaults = {"destination": destination}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
