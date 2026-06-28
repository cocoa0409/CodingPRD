"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides so tests can pin
the exact values they need to control.
"""

DEFAULTS = {
    "EVENT_START": "2026-06-10T00:00:00Z",
    "EVENT_END": "2026-06-10T04:00:00Z",
    "STREET_DATE": "2026-09-01T00:00:00Z",
}


def create_customer_payload(**overrides) -> dict:
    payload = {"display_name": "Test Customer", "email": "test@example.com"}
    payload.update(overrides)
    return payload


def create_inventory_item_payload(**overrides) -> dict:
    payload = {
        "title": "Test Card",
        "product_kind": "SINGLE",
        "market_price_cents": 1000,
    }
    payload.update(overrides)
    return payload


def create_credit_adjustment_payload(delta_cents=5000, **overrides) -> dict:
    payload = {"delta_cents": delta_cents}
    payload.update(overrides)
    return payload


def create_buylist_submission_payload(customer_id, payout_method="STORE_CREDIT",
                                      **overrides) -> dict:
    payload = {"customer_id": customer_id, "payout_method": payout_method}
    payload.update(overrides)
    return payload


def create_buylist_line_payload(buylist_submission_id, inventory_item_id,
                                quantity=1, **overrides) -> dict:
    payload = {
        "buylist_submission_id": buylist_submission_id,
        "inventory_item_id": inventory_item_id,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def create_release_product_payload(**overrides) -> dict:
    payload = {
        "title": "Test Booster Box",
        "street_date": DEFAULTS["STREET_DATE"],
        "allocation_pool": 10,
        "unit_price_cents": 1000,
        "deposit_required_cents": 500,
    }
    payload.update(overrides)
    return payload


def create_pre_order_payload(customer_id, release_product_id,
                             requested_quantity=1, deposit_paid_cents=500,
                             **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "release_product_id": release_product_id,
        "requested_quantity": requested_quantity,
        "deposit_paid_cents": deposit_paid_cents,
    }
    payload.update(overrides)
    return payload


def create_event_payload(**overrides) -> dict:
    payload = {
        "title": "Test Event",
        "format": "STANDARD",
        "starts_at": DEFAULTS["EVENT_START"],
        "ends_at": DEFAULTS["EVENT_END"],
        "capacity": 8,
        "entry_fee_cents": 1000,
        "tables_required": 1,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(event_id, customer_id, **overrides) -> dict:
    payload = {"event_id": event_id, "customer_id": customer_id}
    payload.update(overrides)
    return payload


def create_pairing_payload(event_id, registration_a_id,
                           registration_b_id=None, **overrides) -> dict:
    payload = {"event_id": event_id, "registration_a_id": registration_a_id}
    if registration_b_id is not None:
        payload["registration_b_id"] = registration_b_id
    payload.update(overrides)
    return payload


def create_grading_submission_payload(customer_id, inventory_item_id,
                                      declared_value_cents=5000,
                                      service_tier="STANDARD", **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "declared_value_cents": declared_value_cents,
        "service_tier": service_tier,
    }
    payload.update(overrides)
    return payload


def create_consignment_case_payload(customer_id, inventory_item_id,
                                    quantity=1, ask_price_cents=1000,
                                    commission_rate_bps=1500, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "quantity": quantity,
        "ask_price_cents": ask_price_cents,
        "commission_rate_bps": commission_rate_bps,
    }
    payload.update(overrides)
    return payload
