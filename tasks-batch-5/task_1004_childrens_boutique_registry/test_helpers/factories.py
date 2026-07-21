"""Payload factories — one per entity, input fields only.

Each factory returns a fresh dict so overrides never bleed across tests. The
server is restarted (empty DB) before every test, so the module-level unique
counters reset each run — no cross-test collisions.
"""
import itertools

_email_counter = itertools.count(10000)
_code_counter = itertools.count(10000)


def fresh_email(prefix: str = "cust") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


def fresh_sku_code(prefix: str = "SKU") -> str:
    return f"{prefix}{next(_code_counter)}"


# ---- Store ----
def create_store_payload(**overrides) -> dict:
    defaults = {"name": "Test Store", "state_code": "CA"}
    defaults.update(overrides)
    return defaults


# ---- Customer ----
def create_customer_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Customer", "email": fresh_email()}
    defaults.update(overrides)
    return defaults


# ---- SKU ----
def create_sku_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "sku_code": fresh_sku_code(),
        "name": "Onesie",
        "category": "CLOTHING",
        "size_stage": "M0_3",
        "base_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


# ---- Registry ----
def create_registry_payload(registrant_customer_id, **overrides) -> dict:
    defaults = {
        "registrant_customer_id": registrant_customer_id,
        "title": "Baby R",
        "event_date": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ---- Registry Item ----
def create_registry_item_payload(sku_id, desired_qty, **overrides) -> dict:
    defaults = {"sku_id": sku_id, "desired_qty": desired_qty}
    defaults.update(overrides)
    return defaults


# ---- Registry Gift ----
def create_gift_payload(registry_item_id, qty, expected_registry_version, **overrides) -> dict:
    defaults = {
        "registry_item_id": registry_item_id,
        "qty": qty,
        "expected_registry_version": expected_registry_version,
    }
    defaults.update(overrides)
    return defaults


# ---- Order ----
def create_order_payload(customer_id, store_id, lines, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "store_id": store_id,
        "lines": lines,
        "pickup_start": "2026-07-01T10:00:00Z",
        "pickup_end": "2026-07-01T10:30:00Z",
        "station_no": 1,
    }
    defaults.update(overrides)
    return defaults


def order_line(sku_id, qty) -> dict:
    return {"sku_id": sku_id, "qty": qty}


# ---- Consignment Shelf ----
def create_shelf_payload(**overrides) -> dict:
    defaults = {"shelf_code": "SH1", "capacity": 5, "season": "SPRING_SUMMER"}
    defaults.update(overrides)
    return defaults


# ---- Consignment Item ----
def create_consignment_item_payload(consignor_customer_id, store_id, **overrides) -> dict:
    defaults = {
        "consignor_customer_id": consignor_customer_id,
        "store_id": store_id,
        "title": "Stroller",
        "condition": "GOOD",
        "season": "IN_SEASON",
        "list_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def display_payload(shelf_id, display_start, display_end, **overrides) -> dict:
    defaults = {
        "shelf_id": shelf_id,
        "display_start": display_start,
        "display_end": display_end,
    }
    defaults.update(overrides)
    return defaults


# ---- Trade-In ----
def create_trade_in_payload(customer_id, sku_id, submitted_condition="GOOD", **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sku_id": sku_id,
        "submitted_condition": submitted_condition,
    }
    defaults.update(overrides)
    return defaults


# ---- Special Order ----
def create_special_order_payload(customer_id, sku_id, store_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "sku_id": sku_id, "store_id": store_id}
    defaults.update(overrides)
    return defaults
