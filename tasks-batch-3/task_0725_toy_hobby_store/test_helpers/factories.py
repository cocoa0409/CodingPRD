"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)
_sku_counter = itertools.count(1)


def unique_email(prefix="cust") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_sku(prefix="SKU") -> str:
    return f"{prefix}-{next(_sku_counter)}"


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": unique_sku(),
        "name": "Test Product",
        "category": "PLUSH",
        "age_grade_min_months": 0,
        "safety_labels": ["NONE"],
        "msrp_cents": 1000,
        "is_exclusive": False,
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {"name": "Test Store", "state_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_inventory_payload(product_id, store_id, on_hand_qty=100, **overrides) -> dict:
    defaults = {"product_id": product_id, "store_id": store_id, "on_hand_qty": on_hand_qty}
    defaults.update(overrides)
    return defaults


def create_allocation_payload(product_id, store_id, allocated_qty=10,
                              season_start="2026-03-01T00:00:00Z",
                              season_end="2026-12-01T00:00:00Z", **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "store_id": store_id,
        "allocated_qty": allocated_qty,
        "season_start": season_start,
        "season_end": season_end,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "Test Customer", "email": unique_email()}
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, store_id, fulfillment_type="BOPIS", **overrides) -> dict:
    defaults = {"customer_id": customer_id, "store_id": store_id, "fulfillment_type": fulfillment_type}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id, qty=1, recipient_age_months=60, **overrides) -> dict:
    defaults = {"product_id": product_id, "qty": qty, "recipient_age_months": recipient_age_months}
    defaults.update(overrides)
    return defaults


def create_layaway_payload(customer_id, total_cents=9000, installment_count=3, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "total_cents": total_cents, "installment_count": installment_count}
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id, product_id, requested_qty=1, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "product_id": product_id, "requested_qty": requested_qty}
    defaults.update(overrides)
    return defaults


def quote_payload(unit_price_cents, deposit_cents, expected_special_order_version, **overrides) -> dict:
    defaults = {
        "unit_price_cents": unit_price_cents,
        "deposit_cents": deposit_cents,
        "expected_special_order_version": expected_special_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(product_id, severity="MANDATORY", reason="hazard", **overrides) -> dict:
    defaults = {"product_id": product_id, "severity": severity, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_event_payload(store_id, product_id, start_at="2026-04-01T10:00:00Z",
                        end_at="2026-04-01T11:00:00Z", capacity=5, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "product_id": product_id,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_registry_payload(customer_id, registry_type="WISHLIST", **overrides) -> dict:
    defaults = {"customer_id": customer_id, "registry_type": registry_type}
    defaults.update(overrides)
    return defaults


def create_registry_item_payload(product_id, desired_qty=1, **overrides) -> dict:
    defaults = {"product_id": product_id, "desired_qty": desired_qty}
    defaults.update(overrides)
    return defaults


def create_return_payload(order_id, lines, **overrides) -> dict:
    defaults = {"order_id": order_id, "lines": lines}
    defaults.update(overrides)
    return defaults
