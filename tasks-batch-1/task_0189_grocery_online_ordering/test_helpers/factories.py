"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the request-body input fields for the entity's
create/transition endpoint. Pass **overrides to control values per test.
Computed and system fields are never set here.
"""


def create_store_payload(**overrides) -> dict:
    """POST /v1/stores. Only `name` is required; timezone/ebt_enabled/
    cold_chain_hold_minutes are optional with server defaults."""
    payload = {"name": "Test Store"}
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    """POST /v1/customers. email, full_name, date_of_birth required;
    snap_ebt_balance_cents optional (defaults to 0)."""
    payload = {
        "email": "customer@example.com",
        "full_name": "Test Customer",
        "date_of_birth": "1990-01-01",
    }
    payload.update(overrides)
    return payload


def create_picker_payload(**overrides) -> dict:
    """POST /v1/pickers. store_id, full_name required;
    window_cooldown_minutes optional (defaults to 15)."""
    payload = {
        "full_name": "Test Picker",
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    """POST /v1/products. store_id, sku, name, pricing_mode, unit_price_cents
    required; ebt_eligible/age_restricted/cold_chain/on_hand_qty optional."""
    payload = {
        "sku": "SKU-1",
        "name": "Test Product",
        "pricing_mode": "UNIT",
        "unit_price_cents": 349,
    }
    payload.update(overrides)
    return payload


def create_slot_payload(**overrides) -> dict:
    """POST /v1/slots. store_id, slot_type, window_start, window_end, capacity
    all required."""
    payload = {
        "slot_type": "PICKUP",
        "window_start": "2026-06-15T09:00:00Z",
        "window_end": "2026-06-15T11:00:00Z",
        "capacity": 1,
    }
    payload.update(overrides)
    return payload


def create_order_payload(**overrides) -> dict:
    """POST /v1/orders. store_id, customer_id, slot_id, expected_slot_version,
    lines required; tip_cents optional (defaults to 0)."""
    payload = {
        "lines": [],
    }
    payload.update(overrides)
    return payload


def order_line_entry(**overrides) -> dict:
    """One entry inside an order's `lines` array (line at placement time)."""
    payload = {
        "requested_qty": 1,
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(**overrides) -> dict:
    """POST /v1/order-lines (cart edit). order_id, product_id, requested_qty
    required; estimated_weight_kg/substitution_policy optional."""
    payload = {
        "requested_qty": 1,
    }
    payload.update(overrides)
    return payload


def create_substitution_payload(**overrides) -> dict:
    """POST /v1/substitutions. order_line_id, substitute_product_id,
    substitute_qty required; substitute_weight_kg optional (WEIGHT substitutes)."""
    payload = {
        "substitute_qty": 1,
    }
    payload.update(overrides)
    return payload


def pick_payload(**overrides) -> dict:
    """POST /v1/order-lines/{id}/pick. picked_qty (UNIT) or actual_weight_kg
    (WEIGHT)."""
    payload = {}
    payload.update(overrides)
    return payload


def claim_payload(**overrides) -> dict:
    """POST /v1/orders/{id}/claim. window_start, window_end required."""
    payload = {
        "window_start": "2026-06-15T08:00:00Z",
        "window_end": "2026-06-15T08:45:00Z",
    }
    payload.update(overrides)
    return payload


def create_age_check_payload(**overrides) -> dict:
    """POST /v1/age-checks. order_id, verifier_user_id, verified_birth_date
    required."""
    payload = {
        "verifier_user_id": "ops-1",
    }
    payload.update(overrides)
    return payload
