"""Request payload factories — client-supplied input fields only.

Each factory carries the canonical values used across the suite and accepts
`**overrides` so a test can vary exactly the input it is exercising. Optional
inputs are omitted unless a caller supplies them, so that default behaviour
stays observable.
"""

# --------------------------------------------------------------------------- #
# Canonical literals reused across scenarios
# --------------------------------------------------------------------------- #
BRAND_CODE = "BRD1"
OTHER_BRAND_CODE = "BRD2"
VERSION_LABEL = "2026-Q3-CORE"

MARKETPLACE_CHANNEL_CODE = "MARKETMAX"
AGGREGATOR_CHANNEL_CODE = "AGGRPLUS"
PICKUP_ONLY_CHANNEL_CODE = "PICKONLY"

BURGER_SKU = "BURGER"
FRIES_SKU = "FRIES"
PLATTER_SKU = "PLATTER"

BURGER_BASE_PRICE_CENTS = 1099
FRIES_BASE_PRICE_CENTS = 399
PLATTER_BASE_PRICE_CENTS = 46158
STANDARD_TAX_BPS = 875


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
def create_store_payload(**overrides) -> dict:
    payload = {
        "brand_code": BRAND_CODE,
        "name": "Downtown Store",
        "timezone_offset_minutes": -300,
        "base_prep_minutes": 12,
        "prep_capacity_per_bucket": 2,
        "pos_retry_limit": 2,
        "tablet_backlog_threshold": 1,
    }
    payload.update(overrides)
    return payload


def patch_store_payload(**overrides) -> dict:
    """Only the four mutable capacity numbers may be revised."""
    payload = {}
    payload.update(overrides)
    return payload


def create_hour_window_payload(**overrides) -> dict:
    payload = {
        "day_of_week": 0,
        "opens_at_minute": 600,
        "closes_at_minute": 1320,
    }
    payload.update(overrides)
    return payload


def publish_menu_payload(menu_version_id: str, expected_store_version: int, **overrides) -> dict:
    payload = {
        "menu_version_id": menu_version_id,
        "expected_store_version": expected_store_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Channel
# --------------------------------------------------------------------------- #
def create_channel_payload(**overrides) -> dict:
    """Marketplace channel: nickel grid, honors 86s, suppresses on throttle,
    reviews adjustments by hand and withholds its commission."""
    payload = {
        "code": MARKETPLACE_CHANNEL_CODE,
        "name": "MarketMax Marketplace",
        "channel_type": "MARKETPLACE",
        "markup_bps": 1500,
        "rounding_mode": "NICKEL",
        "service_fee_cents": 299,
        "commission_bps": 2500,
        "settlement_mode": "NET_MODE",
        "eighty_six_policy": "HONOR_86",
        "throttle_policy": "SUPPRESS_ON_THROTTLE",
        "adjustment_review_mode": "CHANNEL_REVIEW",
    }
    payload.update(overrides)
    return payload


def create_aggregator_channel_payload(**overrides) -> dict:
    """Aggregator channel: cent grid, ignores 86s and throttle, auto-accepts
    adjustments and remits gross."""
    payload = {
        "code": AGGREGATOR_CHANNEL_CODE,
        "name": "AggrPlus Aggregator",
        "channel_type": "AGGREGATOR",
        "markup_bps": 800,
        "rounding_mode": "CENT",
        "service_fee_cents": 149,
        "commission_bps": 1800,
        "settlement_mode": "GROSS_MODE",
        "eighty_six_policy": "IGNORE_86",
        "throttle_policy": "IGNORE_THROTTLE",
        "adjustment_review_mode": "AUTO_ACCEPT",
    }
    payload.update(overrides)
    return payload


def patch_channel_payload(expected_channel_version: int, **overrides) -> dict:
    payload = {"expected_channel_version": expected_channel_version}
    payload.update(overrides)
    return payload


def patch_listing_payload(suppressed: bool) -> dict:
    return {"suppressed": suppressed}


# --------------------------------------------------------------------------- #
# Menu authoring
# --------------------------------------------------------------------------- #
def create_menu_version_payload(**overrides) -> dict:
    payload = {"brand_code": BRAND_CODE, "version_label": VERSION_LABEL}
    payload.update(overrides)
    return payload


def create_menu_item_payload(**overrides) -> dict:
    payload = {
        "sku": BURGER_SKU,
        "name": "Signature Burger",
        "base_price_cents": BURGER_BASE_PRICE_CENTS,
        "tax_bps": STANDARD_TAX_BPS,
    }
    payload.update(overrides)
    return payload


def burger_item_payload(**overrides) -> dict:
    return create_menu_item_payload(**overrides)


def fries_item_payload(**overrides) -> dict:
    payload = {
        "sku": FRIES_SKU,
        "name": "Skin-On Fries",
        "base_price_cents": FRIES_BASE_PRICE_CENTS,
        "tax_bps": STANDARD_TAX_BPS,
    }
    payload.update(overrides)
    return payload


def platter_item_payload(**overrides) -> dict:
    """A high-priced, zero-tax item that may not leave the building."""
    payload = {
        "sku": PLATTER_SKU,
        "name": "Family Platter",
        "base_price_cents": PLATTER_BASE_PRICE_CENTS,
        "tax_bps": 0,
        "is_delivery_eligible": False,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Availability events
# --------------------------------------------------------------------------- #
def create_availability_event_payload(store_id: str, menu_item_id: str, event_type: str = "EIGHTY_SIX", **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "menu_item_id": menu_item_id,
        "event_type": event_type,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #
def order_line(sku: str, quantity: int = 1) -> dict:
    return {"sku": sku, "quantity": quantity}


def create_order_payload(store_id: str, channel_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "channel_id": channel_id,
        "external_ref": "EXT-1",
        "fulfillment_mode": "DELIVERY",
        "lines": [order_line(BURGER_SKU, 2), order_line(FRIES_SKU, 1)],
        "tip_cents": 200,
    }
    payload.update(overrides)
    return payload


def inject_payload(pos_result_code: str = "OK") -> dict:
    return {"pos_result_code": pos_result_code}


def cancel_order_payload(reason_code: str = "GUEST_CANCELLED") -> dict:
    return {"reason_code": reason_code}


# --------------------------------------------------------------------------- #
# Courier networks and delivery assignments
# --------------------------------------------------------------------------- #
def create_courier_network_payload(**overrides) -> dict:
    payload = {
        "code": "N_FAST",
        "name": "Fast Courier Co",
        "network_type": "COURIER",
        "priority_rank": 10,
        "per_delivery_fee_cents": 650,
        "handoff_sla_seconds": 600,
        "dispatch_buffer_seconds": 120,
        "max_concurrent_assignments": 2,
    }
    payload.update(overrides)
    return payload


def decline_assignment_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Adjustments
# --------------------------------------------------------------------------- #
def create_adjustment_payload(order_id: str, expected_order_version: int, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "adjustment_type": "REFUND",
        "amount_cents": 1000,
        "reason_code": "MISSING_ITEM",
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def request_revision_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def revise_adjustment_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def reverse_adjustment_payload(reason_code: str = "PROPOSED_IN_ERROR") -> dict:
    return {"reason_code": reason_code}


# --------------------------------------------------------------------------- #
# Remittance statements
# --------------------------------------------------------------------------- #
def create_statement_payload(channel_id: str, **overrides) -> dict:
    payload = {
        "channel_id": channel_id,
        "period_start": "2026-08-03T00:00:00Z",
        "period_end": "2026-08-04T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def assign_orders_payload(order_ids) -> dict:
    return {"order_ids": list(order_ids)}


def dispute_statement_payload(reason_code: str = "FIGURES_DISPUTED") -> dict:
    return {"reason_code": reason_code}
