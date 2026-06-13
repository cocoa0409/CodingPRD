"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
  - Product: split_allowed/perishable/substitute_product_id are optional (have defaults).
  - Route: min_delivery_gap_days optional (defaults 0).
  - Customer: split_fee_cents optional (defaults 0).
  - OrderGuideItem: on_hand_splits optional (defaults 0).
  - InventoryLot: expires_on optional (defaults null).
  - OrderLine: order_guide_item_id optional (defaults null).
"""

DEFAULTS = {
    "DISTRIBUTOR_NAME": "FreshCo",
    "WAREHOUSE_CODE": "WH1",
    "WAREHOUSE_NAME": "Main",
    "ROUTE_CODE": "R1",
    "DELIVERY_DOW": 2,            # Wednesday
    "CUTOFF_LEAD_HOURS": 24,
    "PRODUCT_SKU": "P-1",
    "PRODUCT_NAME": "Cheddar",
    "PRODUCT_CATEGORY": "DAIRY",
    "SPLITS_PER_CASE": 12,
    "CASE_COST_CENTS": 1000,
    "LOT_CODE": "L1",
    "CUSTOMER_NAME": "Diner A",
    "CREDIT_LIMIT_CENTS": 100000,
    "DELIVERY_DATE": "2026-06-17T00:00:00Z",
}


def create_distributor_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["DISTRIBUTOR_NAME"]}
    defaults.update(overrides)
    return defaults


def set_current_utc_payload(distributor_id: str, to_iso8601: str, **overrides) -> dict:
    defaults = {"distributor_id": distributor_id, "to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(distributor_id: str, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "code": DEFAULTS["WAREHOUSE_CODE"],
        "name": DEFAULTS["WAREHOUSE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(distributor_id: str, warehouse_id: str, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "warehouse_id": warehouse_id,
        "code": DEFAULTS["ROUTE_CODE"],
        "delivery_dow": DEFAULTS["DELIVERY_DOW"],
        "cutoff_lead_hours": DEFAULTS["CUTOFF_LEAD_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(distributor_id: str, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "sku": DEFAULTS["PRODUCT_SKU"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "category": DEFAULTS["PRODUCT_CATEGORY"],
        "splits_per_case": DEFAULTS["SPLITS_PER_CASE"],
        "case_cost_cents": DEFAULTS["CASE_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_price_tier_payload(product_id: str, min_cases: int, case_price_cents: int, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "min_cases": min_cases,
        "case_price_cents": case_price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(product_id: str, warehouse_id: str, on_hand_splits: int, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "lot_code": DEFAULTS["LOT_CODE"],
        "on_hand_splits": on_hand_splits,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(distributor_id: str, route_id: str, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "route_id": route_id,
        "name": DEFAULTS["CUSTOMER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_guide_payload(customer_id: str, name: str = "WEEKLY", **overrides) -> dict:
    defaults = {"customer_id": customer_id, "name": name}
    defaults.update(overrides)
    return defaults


def create_order_guide_item_payload(order_guide_id: str, product_id: str, par_level_splits: int, **overrides) -> dict:
    defaults = {
        "order_guide_id": order_guide_id,
        "product_id": product_id,
        "par_level_splits": par_level_splits,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, requested_delivery_date: str = None, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "requested_delivery_date": requested_delivery_date or DEFAULTS["DELIVERY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id: str, uom: str, ordered_qty: int, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "uom": uom,
        "ordered_qty": ordered_qty,
    }
    defaults.update(overrides)
    return defaults


def approve_credit_payload(expected_customer_version: int, **overrides) -> dict:
    defaults = {"expected_customer_version": expected_customer_version}
    defaults.update(overrides)
    return defaults


def pod_payload(pod_signature: str, **overrides) -> dict:
    defaults = {"pod_signature": pod_signature}
    defaults.update(overrides)
    return defaults


def create_return_payload(customer_id: str, order_id: str, order_line_id: str,
                          reason: str, return_splits: int, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "order_id": order_id,
        "order_line_id": order_line_id,
        "reason": reason,
        "return_splits": return_splits,
    }
    defaults.update(overrides)
    return defaults
