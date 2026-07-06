"""Payload factories — one per creatable entity, input fields only.

Each factory returns a request body for the corresponding POST endpoint. Only
client-supplied (source: input) fields are included; system/computed fields
(status, on_hand_g, deposit_cents, totals, balances, version) are never set by
the client. Optional fields default to their PRD defaults and are supplied only
when relevant to a test.
"""

# ─── Reusable unique-value counters (fresh DB per test, but a single test may
#     register several members/vehicles that must not collide). ──────────────
_email_seq = [0]
_plate_seq = [0]


def unique_email(prefix: str = "m") -> str:
    _email_seq[0] += 1
    return f"{prefix}{_email_seq[0]}@example.com"


def unique_plate(prefix: str = "PLATE") -> str:
    _plate_seq[0] += 1
    return f"{prefix}-{_plate_seq[0]}"


def create_member_payload(**overrides) -> dict:
    """POST /v1/members. membership_tier optional (defaults to BASIC server-side)."""
    payload = {
        "email": unique_email("member"),
        "full_name": "Test Member",
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    """POST /v1/products. allergen_tags/taxable optional. Default: Oats bulk SKU."""
    payload = {
        "name": "Oats",
        "category": "GRAINS",
        "unit_price_cents_per_100g": 40,
        "bulk_tier_threshold_g": 1000,
        "bulk_tier_price_cents_per_100g": 30,
    }
    payload.update(overrides)
    return payload


def create_station_payload(**overrides) -> dict:
    """POST /v1/stations. station_status optional (defaults to OPEN server-side)."""
    payload = {"name": "S1"}
    payload.update(overrides)
    return payload


def create_bin_payload(product_id: str, station_id: str, **overrides) -> dict:
    """POST /v1/bins. on_hand_g is server-initialized to last_recount_g."""
    payload = {
        "product_id": product_id,
        "station_id": station_id,
        "capacity_g": 8000,
        "reorder_threshold_g": 1000,
        "last_recount_g": 5000,
    }
    payload.update(overrides)
    return payload


def create_container_payload(container_type: str = "BYO", declared_tare_g: int = 200,
                             member_id: str = None, **overrides) -> dict:
    """POST /v1/containers. deposit_cents is derived from container_type."""
    payload = {
        "container_type": container_type,
        "declared_tare_g": declared_tare_g,
    }
    if member_id is not None:
        payload["member_id"] = member_id
    payload.update(overrides)
    return payload


def create_order_payload(member_id: str, station_id: str,
                         fill_window_start_at: str = "2026-03-02T09:00:00Z",
                         fill_window_end_at: str = "2026-03-02T10:00:00Z",
                         **overrides) -> dict:
    """POST /v1/orders. fulfillment_channel optional (defaults to IN_STORE)."""
    payload = {
        "member_id": member_id,
        "station_id": station_id,
        "fill_window_start_at": fill_window_start_at,
        "fill_window_end_at": fill_window_end_at,
    }
    payload.update(overrides)
    return payload


def add_line_payload(product_id: str, container_id: str,
                     estimated_gross_g: int = 1150, **overrides) -> dict:
    """POST /v1/orders/{orderId}/lines."""
    payload = {
        "product_id": product_id,
        "container_id": container_id,
        "estimated_gross_g": estimated_gross_g,
    }
    payload.update(overrides)
    return payload


def fill_line_payload(gross_weight_g: int, measured_tare_g: int, **overrides) -> dict:
    """POST /v1/refill-lines/{lineId}/fill."""
    payload = {"gross_weight_g": gross_weight_g, "measured_tare_g": measured_tare_g}
    payload.update(overrides)
    return payload


def create_subscription_payload(member_id: str, product_id: str, station_id: str,
                                target_net_g: int = 500, interval_days: int = 7,
                                **overrides) -> dict:
    """POST /v1/subscriptions."""
    payload = {
        "member_id": member_id,
        "product_id": product_id,
        "station_id": station_id,
        "target_net_g": target_net_g,
        "interval_days": interval_days,
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(capacity_orders: int = 5, plate: str = None, **overrides) -> dict:
    """POST /v1/delivery-vehicles. plate unique across vehicles."""
    payload = {
        "plate": plate if plate is not None else unique_plate("VAN"),
        "capacity_orders": capacity_orders,
    }
    payload.update(overrides)
    return payload


def create_delivery_payload(order_id: str, vehicle_id: str,
                            window_start_at: str = "2026-03-02T12:00:00Z",
                            window_end_at: str = "2026-03-02T13:00:00Z",
                            **overrides) -> dict:
    """POST /v1/deliveries."""
    payload = {
        "order_id": order_id,
        "vehicle_id": vehicle_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload
