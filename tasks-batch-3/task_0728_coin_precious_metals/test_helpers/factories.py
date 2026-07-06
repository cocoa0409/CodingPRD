"""Payload factories — one per entity, input fields only."""


def create_spot_rate_payload(metal="GOLD", price_per_troy_oz_cents=200_000, **overrides) -> dict:
    payload = {"metal": metal, "price_per_troy_oz_cents": price_per_troy_oz_cents}
    payload.update(overrides)
    return payload


def create_product_payload(
    sku="AU-1OZ-BULLION",
    product_type="BULLION",
    metal="GOLD",
    weight_troy_oz=1.0,
    purity=1.0,
    min_sell_spread_pct=0.05,
    buy_spread_pct=0.04,
    **overrides,
) -> dict:
    payload = {
        "sku": sku,
        "product_type": product_type,
        "metal": metal,
        "weight_troy_oz": weight_troy_oz,
        "purity": purity,
        "min_sell_spread_pct": min_sell_spread_pct,
        "buy_spread_pct": buy_spread_pct,
    }
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(product_id, total_qty=5, acquisition_unit_cost_cents=100_000, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "total_qty": total_qty,
        "acquisition_unit_cost_cents": acquisition_unit_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(full_name="Test Customer", **overrides) -> dict:
    payload = {"full_name": full_name}
    payload.update(overrides)
    return payload


def create_ira_account_payload(customer_id, custodian_name="Test Trust", custodian_account_ref="TC-1", **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "custodian_name": custodian_name,
        "custodian_account_ref": custodian_account_ref,
    }
    payload.update(overrides)
    return payload


def create_sell_order_payload(customer_id, product_id, quantity=1, **overrides) -> dict:
    payload = {"customer_id": customer_id, "product_id": product_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_buy_order_payload(customer_id, product_id, quantity=1, **overrides) -> dict:
    payload = {"customer_id": customer_id, "product_id": product_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_layaway_payload(customer_id, product_id, inventory_lot_id, quantity=1, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_id": product_id,
        "inventory_lot_id": inventory_lot_id,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def deposit_payload(amount_cents, expected_layaway_version, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "expected_layaway_version": expected_layaway_version}
    payload.update(overrides)
    return payload


def create_consignment_payload(
    customer_id,
    description="Consigned item",
    reserve_price_cents=50_000,
    commission_pct=0.10,
    buyer_premium_pct=0.05,
    **overrides,
) -> dict:
    payload = {
        "customer_id": customer_id,
        "description": description,
        "reserve_price_cents": reserve_price_cents,
        "commission_pct": commission_pct,
        "buyer_premium_pct": buyer_premium_pct,
    }
    payload.update(overrides)
    return payload


def list_consignment_payload(auction_session_id, **overrides) -> dict:
    payload = {"auction_session_id": auction_session_id}
    payload.update(overrides)
    return payload


def record_sale_payload(hammer_price_cents, expected_consignment_version, **overrides) -> dict:
    payload = {
        "hammer_price_cents": hammer_price_cents,
        "expected_consignment_version": expected_consignment_version,
    }
    payload.update(overrides)
    return payload


def create_hedge_position_payload(metal="GOLD", short_troy_oz=10, **overrides) -> dict:
    payload = {"metal": metal, "short_troy_oz": short_troy_oz}
    payload.update(overrides)
    return payload


def create_settlement_payload(consignment_id, **overrides) -> dict:
    payload = {"consignment_id": consignment_id}
    payload.update(overrides)
    return payload


def create_appraiser_payload(name="Grader One", specialty_metal="GOLD", **overrides) -> dict:
    payload = {"name": name, "specialty_metal": specialty_metal}
    payload.update(overrides)
    return payload


def create_appraisal_appointment_payload(appraiser_id, consignment_id, start_at, end_at, **overrides) -> dict:
    payload = {
        "appraiser_id": appraiser_id,
        "consignment_id": consignment_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_auction_session_payload(room="ROOM-A", scheduled_start="2026-04-01T10:00:00Z", scheduled_end="2026-04-01T12:00:00Z", **overrides) -> dict:
    payload = {"room": room, "scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
    payload.update(overrides)
    return payload
