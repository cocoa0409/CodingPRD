"""Payload factories — one per entity, input fields only.

Each factory supplies sensible defaults for required fields and accepts **overrides.
Optional fields (those the PRD declares with a default) are only included when the
caller passes them, so omission tests can exercise server-side defaults.
"""

# Reusable default literals.
DEFAULT_LIST_PRICE_CENTS = 20000
DEFAULT_COST_CENTS = 9000


def create_part_payload(sku="TEST-PART", description="Test part",
                        list_price_cents=DEFAULT_LIST_PRICE_CENTS,
                        cost_cents=DEFAULT_COST_CENTS, **overrides) -> dict:
    """Required: sku, description, list_price_cents, cost_cents.
    Optional (server defaults): core_charge_cents, is_rebuildable, warranty_days,
    stockable, reorder_point, reorder_qty."""
    payload = {
        "sku": sku,
        "description": description,
        "list_price_cents": list_price_cents,
        "cost_cents": cost_cents,
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(year=2020, make="TOYOTA", model="CAMRY", **overrides) -> dict:
    """Required: year, make, model. Optional: engine."""
    payload = {"year": year, "make": make, "model": model}
    payload.update(overrides)
    return payload


def create_fitment_payload(part_id, vehicle_id, **overrides) -> dict:
    """Required: part_id, vehicle_id. Optional: position, notes."""
    payload = {"part_id": part_id, "vehicle_id": vehicle_id}
    payload.update(overrides)
    return payload


def create_cross_reference_payload(part_id, interchange_part_id, **overrides) -> dict:
    """Required: part_id, interchange_part_id. Optional: relation."""
    payload = {"part_id": part_id, "interchange_part_id": interchange_part_id}
    payload.update(overrides)
    return payload


def create_price_tier_payload(name="JOBBER", discount_pct=0.30, **overrides) -> dict:
    """Required: name, discount_pct. Optional: core_discount_pct, min_margin_pct."""
    payload = {"name": name, "discount_pct": discount_pct}
    payload.update(overrides)
    return payload


def create_account_payload(name="Test Account", account_type="WHOLESALE",
                           price_tier_id=None, **overrides) -> dict:
    """Required: name, account_type, price_tier_id. Optional: credit_limit_cents."""
    payload = {"name": name, "account_type": account_type, "price_tier_id": price_tier_id}
    payload.update(overrides)
    return payload


def create_sales_order_payload(account_id, channel="WHOLESALE", **overrides) -> dict:
    """Required: account_id, channel. Optional: hotshot_requested."""
    payload = {"account_id": account_id, "channel": channel}
    payload.update(overrides)
    return payload


def create_order_line_payload(order_id, part_id, qty=1, **overrides) -> dict:
    """Required: order_id, part_id, qty."""
    payload = {"order_id": order_id, "part_id": part_id, "qty": qty}
    payload.update(overrides)
    return payload


def allocate_payload(expected_sales_order_version, **overrides) -> dict:
    """Required: expected_sales_order_version (PRD §2.9)."""
    payload = {"expected_sales_order_version": expected_sales_order_version}
    payload.update(overrides)
    return payload


def ship_payload(expected_sales_order_version, **overrides) -> dict:
    """Required: expected_sales_order_version (PRD §2.9)."""
    payload = {"expected_sales_order_version": expected_sales_order_version}
    payload.update(overrides)
    return payload


def receive_stock_payload(qty, **overrides) -> dict:
    """Required: qty."""
    payload = {"qty": qty}
    payload.update(overrides)
    return payload


def create_core_return_payload(order_line_id, qty=1, **overrides) -> dict:
    """Required: order_line_id, qty."""
    payload = {"order_line_id": order_line_id, "qty": qty}
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(order_line_id, qty=1, reason="defective",
                                  **overrides) -> dict:
    """Required: order_line_id, qty, reason. Optional: resolution, restock_defective."""
    payload = {"order_line_id": order_line_id, "qty": qty, "reason": reason}
    payload.update(overrides)
    return payload


def create_reorder_request_payload(part_id, **overrides) -> dict:
    """Required: part_id (qty_ordered is snapshotted server-side from Part.reorder_qty)."""
    payload = {"part_id": part_id}
    payload.update(overrides)
    return payload


def receive_reorder_payload(receive_qty, **overrides) -> dict:
    """Required: receive_qty."""
    payload = {"receive_qty": receive_qty}
    payload.update(overrides)
    return payload


def create_driver_payload(name="Driver", **overrides) -> dict:
    """Required: name. Optional: turnaround_min."""
    payload = {"name": name}
    payload.update(overrides)
    return payload


def create_bay_payload(code="BAY-1", **overrides) -> dict:
    """Required: code."""
    payload = {"code": code}
    payload.update(overrides)
    return payload


def create_delivery_run_payload(order_id, driver_id, bay_id,
                                window_start_min, window_end_min, **overrides) -> dict:
    """Required: order_id, driver_id, bay_id, window_start_min, window_end_min."""
    payload = {
        "order_id": order_id,
        "driver_id": driver_id,
        "bay_id": bay_id,
        "window_start_min": window_start_min,
        "window_end_min": window_end_min,
    }
    payload.update(overrides)
    return payload
