"""Payload factories — one per entity, input fields only."""
import itertools

_uniq = itertools.count(1)


def _next_unique_suffix() -> str:
    return f"{next(_uniq):06d}"


DEFAULTS = {
    "COMMUNITY_NAME": "Test Community",
    "REGION_CODE": "RC1",
    "TIMEZONE_OFFSET_MINUTES": 480,
    "LEADER_DISPLAY_NAME": "Test Leader",
    "CUSTOMER_DISPLAY_NAME": "Test Customer",
    "SUPPLIER_NAME": "Test Supplier",
    "WAREHOUSE_NAME": "Test Warehouse",
    "PICKUP_POINT_NAME": "Test Pickup",
    "DEFAULT_SKU": "SKU_DEFAULT",
    "DEFAULT_UNIT_PRICE_CENTS": 100,
}


def create_community_payload(**overrides) -> dict:
    defaults = {
        "name": f"{DEFAULTS['COMMUNITY_NAME']} {_next_unique_suffix()}",
        "region_code": DEFAULTS["REGION_CODE"],
        "timezone_offset_minutes": DEFAULTS["TIMEZONE_OFFSET_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_group_leader_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["LEADER_DISPLAY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(community_id: str, **overrides) -> dict:
    defaults = {
        "community_id": community_id,
        "display_name": DEFAULTS["CUSTOMER_DISPLAY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SUPPLIER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["WAREHOUSE_NAME"],
        "region_code": DEFAULTS["REGION_CODE"],
        "cold_chain_capable": False,
        "handling_periods": 1,
        "cold_handling_periods": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_point_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PICKUP_POINT_NAME"],
        "capacity_packages": 5,
        "cold_storage_capable": False,
    }
    defaults.update(overrides)
    return defaults


def create_flash_campaign_payload(**overrides) -> dict:
    defaults = {
        "sku": "FLASH_SKU",
        "cold_chain_required": False,
        "unit_price_cents": 100,
        "tier_caps": [{"tier": 0, "max_units": 5}],
        "total_stock": 10,
        "opens_at_period": 0,
        "closes_at_period": 100,
    }
    defaults.update(overrides)
    return defaults


def create_group_buy_campaign_payload(supplier_id: str, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "sku": "SKUA",
        "cold_chain_required": False,
        "unit_price_cents": 100,
        "discount_tiers": [{"min_participants": 1, "discount_basis_points": 0}],
        "opens_at_period": 0,
        "deadline_period": 100,
    }
    defaults.update(overrides)
    return defaults


def create_join_payload(customer_id: str, sku: str = "SKUA",
                        unit_price_cents: int = 100, quantity: int = 1,
                        line_items=None, **overrides) -> dict:
    if line_items is None:
        line_items = [{"sku": sku, "unit_price_cents": unit_price_cents, "quantity": quantity}]
    defaults = {
        "customer_id": customer_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_flash_purchase_payload(requested_units: int = 1, **overrides) -> dict:
    defaults = {"requested_units": requested_units}
    defaults.update(overrides)
    return defaults


def create_after_sales_payload(case_type: str, requested_amount_cents: int, **overrides) -> dict:
    defaults = {
        "case_type": case_type,
        "requested_amount_cents": requested_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_resolve_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_plan_shipments_payload(pickup_point_id: str, line_units, **overrides) -> dict:
    defaults = {
        "shipment_plan": [
            {"pickup_point_id": pickup_point_id, "line_units": line_units}
        ]
    }
    defaults.update(overrides)
    return defaults


def create_consolidation_batch_payload(window_start_period: int, window_end_period: int,
                                        shipment_ids, **overrides) -> dict:
    defaults = {
        "window_start_period": window_start_period,
        "window_end_period": window_end_period,
        "shipment_ids": shipment_ids,
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(target_period_index: int, **overrides) -> dict:
    defaults = {"target_period_index": target_period_index}
    defaults.update(overrides)
    return defaults


def create_risk_alert_payload(alert_type: str, target_kind: str, target_id: str,
                               severity: str = "LOW",
                               supporting_supplier_id: str = None, **overrides) -> dict:
    defaults = {
        "alert_type": alert_type,
        "target_kind": target_kind,
        "target_id": target_id,
        "severity": severity,
    }
    if supporting_supplier_id is not None:
        defaults["supporting_supplier_id"] = supporting_supplier_id
    defaults.update(overrides)
    return defaults
