"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_shop_payload(**overrides) -> dict:
    """POST /shops input fields (PRD §3.1)."""
    defaults = {
        "name": "Test Print Shop",
        "tax_rate_bps": 0,
        "rush_surcharge_bps": 0,
        "rush_cutoff_hour_utc": 14,
        "standard_turnaround_days": 3,
        "rush_turnaround_days": 1,
        "daily_unit_capacity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(shop_id: str, **overrides) -> dict:
    """POST /products input fields (PRD §3.1). unit_size/requires_proof/requires_press/
    active are optional with PRD defaults 1/false/false/true."""
    defaults = {
        "shop_id": shop_id,
        "name": "Color Copy 8.5x11",
        "category": "COPIES",
        "base_unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_tier_payload(product_id: str, min_quantity: int, discount_bps: int,
                                **overrides) -> dict:
    """POST /pricing-tiers input fields (PRD §3.1)."""
    defaults = {
        "product_id": product_id,
        "min_quantity": min_quantity,
        "discount_bps": discount_bps,
    }
    defaults.update(overrides)
    return defaults


def create_finishing_option_payload(product_id: str, code: str, surcharge_kind: str,
                                    surcharge_cents: int, **overrides) -> dict:
    """POST /finishing-options input fields (PRD §3.1)."""
    defaults = {
        "product_id": product_id,
        "code": code,
        "surcharge_kind": surcharge_kind,
        "surcharge_cents": surcharge_cents,
    }
    defaults.update(overrides)
    return defaults


def create_press_payload(shop_id: str, **overrides) -> dict:
    """POST /presses input fields (PRD §3.5). cleanup_buffer_minutes optional, default 0."""
    defaults = {
        "shop_id": shop_id,
        "name": "Large Format Press",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(shop_id: str, **overrides) -> dict:
    """POST /customers input fields (PRD §3.2)."""
    defaults = {
        "shop_id": shop_id,
        "email": "customer@example.com",
        "name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(shop_id: str, customer_id: str, **overrides) -> dict:
    """POST /orders input fields (PRD §3.2)."""
    defaults = {
        "shop_id": shop_id,
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(order_id: str, product_id: str, quantity: int,
                              **overrides) -> dict:
    """POST /order-lines input fields (PRD §3.2). finishing_codes optional (default []),
    service_level optional (default STANDARD)."""
    defaults = {
        "order_id": order_id,
        "product_id": product_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_artwork_payload(order_line_id: str, **overrides) -> dict:
    """POST /artworks input fields (PRD §3.3). Defaults pass preflight (dpi>=150, bleed>=3)."""
    defaults = {
        "order_line_id": order_line_id,
        "file_name": "artwork.pdf",
        "page_count": 1,
        "dpi": 600,
        "bleed_mm": 3,
    }
    defaults.update(overrides)
    return defaults


def create_proof_payload(order_line_id: str, **overrides) -> dict:
    """POST /proofs input fields (PRD §3.4)."""
    defaults = {
        "order_line_id": order_line_id,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_fulfillment_payload(order_id: str, **overrides) -> dict:
    """POST /fulfillments PICKUP variant (PRD §3.7): no address, ship_fee_cents 0."""
    defaults = {
        "order_id": order_id,
        "method": "PICKUP",
        "ship_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_ship_fulfillment_payload(order_id: str, ship_fee_cents: int = 1500,
                                    ship_address: str = "1 Main St", **overrides) -> dict:
    """POST /fulfillments SHIP variant (PRD §3.7): requires address and fee > 0."""
    defaults = {
        "order_id": order_id,
        "method": "SHIP",
        "ship_address": ship_address,
        "ship_fee_cents": ship_fee_cents,
    }
    defaults.update(overrides)
    return defaults


def create_press_booking_payload(press_id: str, order_line_id: str, start_utc: str,
                                end_utc: str, **overrides) -> dict:
    """POST /press-bookings input fields (PRD §3.5)."""
    defaults = {
        "press_id": press_id,
        "order_line_id": order_line_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults
