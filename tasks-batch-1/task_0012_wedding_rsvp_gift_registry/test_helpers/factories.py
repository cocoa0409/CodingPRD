"""Payload factories — one per entity, input fields only."""


def create_wedding_payload(
    couple_user_id: str = "couple-default",
    title: str = "Test Wedding",
    ceremony_at: str = "2027-06-01T18:00:00Z",
    rsvp_deadline_at: str = "2027-05-15T23:59:59Z",
    **overrides,
) -> dict:
    """POST /weddings input fields."""
    defaults = {
        "couple_user_id": couple_user_id,
        "title": title,
        "ceremony_at": ceremony_at,
        "rsvp_deadline_at": rsvp_deadline_at,
    }
    defaults.update(overrides)
    return defaults


def create_meal_option_payload(
    code: str = "ADULT",
    label: str = "Adult plate",
    max_servings: int = 10,
    **overrides,
) -> dict:
    """POST /weddings/{id}/meal-options input fields."""
    defaults = {
        "code": code,
        "label": label,
        "max_servings": max_servings,
    }
    # is_kids is optional, default false per PRD §3.1
    if "is_kids" in overrides:
        defaults["is_kids"] = overrides.pop("is_kids")
    defaults.update(overrides)
    return defaults


def create_table_payload(
    table_number: int = 1,
    capacity: int = 4,
    **overrides,
) -> dict:
    """POST /weddings/{id}/tables input fields."""
    defaults = {
        "table_number": table_number,
        "capacity": capacity,
    }
    if "kids_only" in overrides:
        defaults["kids_only"] = overrides.pop("kids_only")
    defaults.update(overrides)
    return defaults


def create_guest_payload(
    full_name: str = "Test Guest",
    email: str = "guest@example.com",
    **overrides,
) -> dict:
    """POST /weddings/{id}/guests input fields."""
    defaults = {
        "full_name": full_name,
        "email": email,
    }
    if "is_child" in overrides:
        defaults["is_child"] = overrides.pop("is_child")
    if "plus_one_allowed" in overrides:
        defaults["plus_one_allowed"] = overrides.pop("plus_one_allowed")
    defaults.update(overrides)
    return defaults


def create_plus_one_payload(
    full_name: str = "Test Partner",
    **overrides,
) -> dict:
    """POST /guests/{id}/plus-ones input fields."""
    defaults = {
        "full_name": full_name,
    }
    if "is_child" in overrides:
        defaults["is_child"] = overrides.pop("is_child")
    if "meal_option_id" in overrides:
        defaults["meal_option_id"] = overrides.pop("meal_option_id")
    defaults.update(overrides)
    return defaults


def create_seating_assignment_payload(
    wedding_id: str,
    table_id: str,
    assignee_type: str,
    assignee_id: str,
    **overrides,
) -> dict:
    """POST /seating-assignments input fields."""
    defaults = {
        "wedding_id": wedding_id,
        "table_id": table_id,
        "assignee_type": assignee_type,
        "assignee_id": assignee_id,
    }
    defaults.update(overrides)
    return defaults


def create_registry_item_payload(
    sku: str = "SKU-1",
    title: str = "Gift item",
    target_quantity: int = 2,
    unit_price_cents: int = 1000,
    **overrides,
) -> dict:
    """POST /weddings/{id}/registry-items input fields."""
    defaults = {
        "sku": sku,
        "title": title,
        "target_quantity": target_quantity,
        "unit_price_cents": unit_price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_payload(
    platform_code: str = "STORE_A",
    external_purchase_id: str = "ext-1",
    purchaser_name: str = "Test Buyer",
    quantity: int = 1,
    occurred_at: str = "2027-01-02T10:00:00Z",
    **overrides,
) -> dict:
    """POST /registry-items/{id}/purchases input fields."""
    defaults = {
        "platform_code": platform_code,
        "external_purchase_id": external_purchase_id,
        "purchaser_name": purchaser_name,
        "quantity": quantity,
        "occurred_at": occurred_at,
    }
    defaults.update(overrides)
    return defaults


def guest_rsvp_payload(attending: bool, meal_option_id: str = None) -> dict:
    """POST /guests/{id}/rsvp body. meal_option_id only included when supplied."""
    payload = {"attending": attending}
    if meal_option_id is not None:
        payload["meal_option_id"] = meal_option_id
    return payload


def plus_one_rsvp_payload(attending: bool, meal_option_id: str = None) -> dict:
    """POST /plus-ones/{id}/rsvp body."""
    payload = {"attending": attending}
    if meal_option_id is not None:
        payload["meal_option_id"] = meal_option_id
    return payload
