"""Payload factories — one per entity, input fields only."""


def create_store_payload(**overrides) -> dict:
    payload = {
        "name": "Test Store",
        "region_code": "CA",
        "oversized_slots_per_day": 2,
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    payload = {
        "sku": "SKU-TEST",
        "name": "Test Product",
        "category": "DECOR",
        "base_price_cents": 1000,
        "clearance_floor_cents": 100,
        "first_received_at": "2026-06-25T00:00:00Z",
        "is_treasure_hunt": False,
    }
    payload.update(overrides)
    return payload


def create_store_inventory_payload(store_id, product_id, allocated_qty=10, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "product_id": product_id,
        "allocated_qty": allocated_qty,
    }
    payload.update(overrides)
    return payload


def adjust_inventory_payload(delta_qty, **overrides) -> dict:
    payload = {"delta_qty": delta_qty}
    payload.update(overrides)
    return payload


def create_loyalty_member_payload(email="member@x.com", full_name="Test Member", **overrides) -> dict:
    payload = {"email": email, "full_name": full_name}
    payload.update(overrides)
    return payload


def create_order_payload(store_id, order_type="CARRYOUT", **overrides) -> dict:
    payload = {"store_id": store_id, "order_type": order_type}
    payload.update(overrides)
    return payload


def create_order_line_payload(product_id, qty=1, **overrides) -> dict:
    payload = {"product_id": product_id, "qty": qty}
    payload.update(overrides)
    return payload


def create_assembly_crew_payload(store_id, name="Test Crew", **overrides) -> dict:
    payload = {"store_id": store_id, "name": name}
    payload.update(overrides)
    return payload


def create_delivery_booking_payload(order_id, store_id, delivery_date, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "store_id": store_id,
        "delivery_date": delivery_date,
    }
    payload.update(overrides)
    return payload


def create_return_payload(order_id, product_id, returned_qty=1, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "product_id": product_id,
        "returned_qty": returned_qty,
    }
    payload.update(overrides)
    return payload


def create_registry_payload(owner_member_id, title="Housewarming", event_date="2026-12-01", **overrides) -> dict:
    payload = {
        "owner_member_id": owner_member_id,
        "title": title,
        "event_date": event_date,
    }
    payload.update(overrides)
    return payload


def create_registry_item_payload(product_id, desired_qty=1, **overrides) -> dict:
    payload = {"product_id": product_id, "desired_qty": desired_qty}
    payload.update(overrides)
    return payload


def create_special_order_payload(store_id, member_id, description="Custom item", **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "member_id": member_id,
        "description": description,
    }
    payload.update(overrides)
    return payload


def quote_special_order_payload(quoted_price_cents, expected_special_order_version, **overrides) -> dict:
    payload = {
        "quoted_price_cents": quoted_price_cents,
        "expected_special_order_version": expected_special_order_version,
    }
    payload.update(overrides)
    return payload
