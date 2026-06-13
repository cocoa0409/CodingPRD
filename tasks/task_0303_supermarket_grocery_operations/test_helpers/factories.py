"""Payload factories — one per entity, input fields only (PRD §3).

Factories produce minimal valid payloads; pass **overrides to control any
field a test needs to pin or omit.
"""

DEFAULTS = {
    "DEPT_CODE": "GROCERY",
    "DEPT_NAME": "Grocery",
    "PRODUCT_NAME": "Test Product",
    "UNIT_PRICE_CENTS": 100,
    "VENDOR_NAME": "Test Vendor",
    "AD_PRICE_CENTS": 150,
    "WINDOW_START": "2026-06-01T00:00:00Z",
    "WINDOW_END": "2026-06-30T00:00:00Z",
}


def create_department_payload(**overrides) -> dict:
    payload = {
        "code": DEFAULTS["DEPT_CODE"],
        "name": DEFAULTS["DEPT_NAME"],
    }
    payload.update(overrides)
    return payload


def create_product_payload(department_id, **overrides) -> dict:
    """Each-sold product by default (sku required, sell_by_weight=false)."""
    payload = {
        "department_id": department_id,
        "name": DEFAULTS["PRODUCT_NAME"],
        "sku": "SKU-TEST",
        "sell_by_weight": False,
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "is_perishable": False,
        "reorder_point_qty": 0,
    }
    payload.update(overrides)
    return payload


def create_weighed_product_payload(department_id, **overrides) -> dict:
    """Weighed product (plu required, sell_by_weight=true)."""
    payload = {
        "department_id": department_id,
        "name": "Test Weighed Product",
        "plu": "4011",
        "sell_by_weight": True,
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "is_perishable": True,
        "reorder_point_qty": 0,
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(reference_code="REF-TEST", expected_total_cents=500, **overrides) -> dict:
    payload = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "reference_code": reference_code,
        "expected_total_cents": expected_total_cents,
    }
    payload.update(overrides)
    return payload


def create_shipment_line_payload(product_id, ordered_qty=5, unit_cost_cents=100, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "ordered_qty": ordered_qty,
        "accepted_qty": ordered_qty,
        "unit_cost_cents": unit_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_price_plan_payload(product_id, expected_product_version, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "ad_price_cents": DEFAULTS["AD_PRICE_CENTS"],
        "effective_start": DEFAULTS["WINDOW_START"],
        "effective_end": DEFAULTS["WINDOW_END"],
        "expected_product_version": expected_product_version,
    }
    payload.update(overrides)
    return payload


def create_promotion_payload(product_id, promo_type="PERCENT_OFF", **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "promo_type": promo_type,
        "min_qty": 1,
        "stackable": False,
        "effective_start": DEFAULTS["WINDOW_START"],
        "effective_end": DEFAULTS["WINDOW_END"],
    }
    if promo_type == "PERCENT_OFF":
        payload["percent_off_bps"] = 2000
    elif promo_type == "FIXED_OFF":
        payload["fixed_off_cents"] = 50
    payload.update(overrides)
    return payload


def create_coupon_payload(product_id, code="COUPON1", discount_cents=50, **overrides) -> dict:
    payload = {
        "code": code,
        "product_id": product_id,
        "discount_cents": discount_cents,
        "min_spend_cents": 0,
        "stackable": False,
        "effective_start": DEFAULTS["WINDOW_START"],
        "effective_end": DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(email="shopper@example.com", full_name="Test Shopper", **overrides) -> dict:
    payload = {
        "email": email,
        "full_name": full_name,
    }
    payload.update(overrides)
    return payload


def create_sale_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_line_item_payload(product_id, **overrides) -> dict:
    payload = {"product_id": product_id}
    payload.update(overrides)
    return payload


def create_cycle_count_payload(department_id, product_id, **overrides) -> dict:
    payload = {
        "department_id": department_id,
        "product_id": product_id,
    }
    payload.update(overrides)
    return payload


def create_eod_payload(department_id, business_date="2026-06-05T00:00:00Z", **overrides) -> dict:
    payload = {
        "department_id": department_id,
        "business_date": business_date,
    }
    payload.update(overrides)
    return payload
