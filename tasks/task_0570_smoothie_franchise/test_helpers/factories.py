"""Payload factories — one per entity, input fields only."""


def create_franchisee_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Acme Juice Co",
        "contact_email": "fr@example.com",
        "base_royalty_rate": 0.06,
        "marketing_fee_rate": 0.02,
    }
    payload.update(overrides)
    return payload


def create_store_payload(**overrides) -> dict:
    payload = {
        "name": "Downtown Store",
        "catering_capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_delivery_vehicle_payload(**overrides) -> dict:
    payload = {
        "label": "VAN-1",
        "headcount_capacity": 20,
    }
    payload.update(overrides)
    return payload


def create_ingredient_payload(**overrides) -> dict:
    payload = {
        "name": "Spinach",
        "unit": "GRAM",
        "standard_cost_cents_per_unit": 2,
    }
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(**overrides) -> dict:
    payload = {
        "qty_received": 100,
        "unit_cost_cents": 2,
        "received_at": "2026-05-01T00:00:00Z",
        "expiry_date": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_menu_item_payload(**overrides) -> dict:
    payload = {
        "name": "Green Machine",
        "category": "SMOOTHIE",
        "base_price_cents": 500,
        "recipe": [],
        "base_calories": 200,
    }
    payload.update(overrides)
    return payload


def create_boost_payload(**overrides) -> dict:
    payload = {
        "name": "Protein",
        "price_cents": 150,
        "calories": 100,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "email": "customer@example.com",
        "full_name": "Test Customer",
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(**overrides) -> dict:
    payload = {
        "tier": "BASIC",
        "monthly_fee_cents": 999,
        "included_smoothie_credits": 4,
    }
    payload.update(overrides)
    return payload


def create_order_payload(store_id, lines, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def order_line(menu_item_id, size="SMALL", boost_ids=None) -> dict:
    return {
        "menu_item_id": menu_item_id,
        "size": size,
        "boost_ids": boost_ids or [],
    }


def create_catering_booking_payload(customer_id, fulfillment_type, headcount, items,
                                    prep_window_start, prep_window_end, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "fulfillment_type": fulfillment_type,
        "headcount": headcount,
        "items": items,
        "prep_window_start": prep_window_start,
        "prep_window_end": prep_window_end,
    }
    payload.update(overrides)
    return payload


def create_reconciliation_payload(business_date, **overrides) -> dict:
    payload = {"business_date": business_date}
    payload.update(overrides)
    return payload
