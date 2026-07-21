"""Payload factories — one per entity, input fields only.

Uniqueness-scoped fields (sku, email, serial_number) get a per-process unique
token when not overridden, so a single test can create several entities without
tripping the unique constraints. The server DB is fresh for every test, so the
token only needs to be unique within one test run.
"""
import itertools

_counter = itertools.count(1)


def _uniq() -> str:
    return f"{next(_counter):06d}"


def create_product_payload(**overrides) -> dict:
    token = _uniq()
    defaults = {
        "sku": f"SKU-{token}",
        "name": "Voyager 55",
        "category": "HARD_SHELL",
        "msrp_cents": 30000,
        "warranty_months": 24,
        "length_mm": 550,
        "width_mm": 350,
        "height_mm": 230,
    }
    defaults.update(overrides)
    return defaults


def create_airline_payload(**overrides) -> dict:
    token = _uniq()
    defaults = {
        "iata_code": f"A{token[-2:]}",
        "name": "Test Air",
        "carry_on_max_length_mm": 560,
        "carry_on_max_width_mm": 350,
        "carry_on_max_height_mm": 230,
        "checked_linear_limit_mm": 1580,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    token = _uniq()
    defaults = {
        "email": f"cust-{token}@example.com",
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(product_id, customer_id, **overrides) -> dict:
    token = _uniq()
    defaults = {
        "product_id": product_id,
        "customer_id": customer_id,
        "serial_number": f"SER-{token}",
        "purchase_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(registration_id, expected_warranty_registration_version, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "expected_warranty_registration_version": expected_warranty_registration_version,
        "defect_type": "WHEEL",
        "description": "reported defect",
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(customer_id, product_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "product_id": product_id}
    defaults.update(overrides)
    return defaults


def create_repair_line_payload(repair_order_id, **overrides) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "repair_type": "WHEEL",
        "labor_hours": 1,
        "complexity": "STANDARD",
        "parts_cost_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_sales_order_line_payload(sales_order_id, product_id, **overrides) -> dict:
    defaults = {
        "sales_order_id": sales_order_id,
        "product_id": product_id,
        "unit_price_cents": 10000,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(customer_id, product_id, expected_customer_version, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "expected_customer_version": expected_customer_version,
        "condition": "GOOD",
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id, product_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "product_id": product_id, "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_recall_notice_payload(product_id, **overrides) -> dict:
    defaults = {"product_id": product_id, "reason": "defect", "remedy": "REPAIR"}
    defaults.update(overrides)
    return defaults


def create_service_bench_payload(**overrides) -> dict:
    defaults = {"label": "Bench A", "skill": "GENERAL"}
    defaults.update(overrides)
    return defaults


def create_monogram_station_payload(**overrides) -> dict:
    defaults = {"label": "Emboss 1", "method": "EMBOSS"}
    defaults.update(overrides)
    return defaults
