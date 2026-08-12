"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import (
    BOOK_DEFAULTS,
    DEFAULT_EVENT_DATE,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)


# --- Price books -------------------------------------------------------------

def price_book_payload(
    lines,
    scope_label="standard-2026",
    effective_from="2026-04-01T00:00:00Z",
    pallet_deposit_cents=None,
    delivery_fee_cents=None,
    free_delivery_threshold_cents=None,
    volume_discount_tiers=None,
    surge_surcharge_bps=None,
):
    """Generic price-book payload (PRD §3.1)."""
    return {
        "scope_label": scope_label,
        "effective_from": effective_from,
        "lines": lines,
        "pallet_deposit_cents": (
            BOOK_DEFAULTS["pallet_deposit_cents"]
            if pallet_deposit_cents is None
            else pallet_deposit_cents
        ),
        "delivery_fee_cents": (
            BOOK_DEFAULTS["delivery_fee_cents"]
            if delivery_fee_cents is None
            else delivery_fee_cents
        ),
        "free_delivery_threshold_cents": (
            BOOK_DEFAULTS["free_delivery_threshold_cents"]
            if free_delivery_threshold_cents is None
            else free_delivery_threshold_cents
        ),
        "volume_discount_tiers": (
            [
                {"threshold_cents": 50000, "discount_bps": 500},
                {"threshold_cents": 100000, "discount_bps": 1000},
            ]
            if volume_discount_tiers is None
            else volume_discount_tiers
        ),
        "surge_surcharge_bps": (
            BOOK_DEFAULTS["surge_surcharge_bps"]
            if surge_surcharge_bps is None
            else surge_surcharge_bps
        ),
    }


FULL_BOOK_LINES = [
    {"product_form": "CUBE", "packaging": "BAG", "tier_min_units": 1, "tier_max_units": 19, "unit_price_cents": 350},
    {"product_form": "CUBE", "packaging": "BAG", "tier_min_units": 20, "tier_max_units": 99, "unit_price_cents": 300},
    {"product_form": "CUBE", "packaging": "BAG", "tier_min_units": 100, "tier_max_units": None, "unit_price_cents": 275},
    {"product_form": "CUBE", "packaging": "PALLET", "tier_min_units": 1, "tier_max_units": 4, "unit_price_cents": 28000},
    {"product_form": "CUBE", "packaging": "PALLET", "tier_min_units": 5, "tier_max_units": None, "unit_price_cents": 26000},
    {"product_form": "BLOCK", "packaging": "BAG", "tier_min_units": 1, "tier_max_units": 9, "unit_price_cents": 900},
    {"product_form": "BLOCK", "packaging": "BAG", "tier_min_units": 10, "tier_max_units": None, "unit_price_cents": 800},
    {"product_form": "BLOCK", "packaging": "PALLET", "tier_min_units": 1, "tier_max_units": None, "unit_price_cents": 21000},
    {"product_form": "DRY_ICE", "packaging": "BAG", "tier_min_units": 1, "tier_max_units": 9, "unit_price_cents": 1500},
    {"product_form": "DRY_ICE", "packaging": "BAG", "tier_min_units": 10, "tier_max_units": 49, "unit_price_cents": 1350},
    {"product_form": "DRY_ICE", "packaging": "BAG", "tier_min_units": 50, "tier_max_units": None, "unit_price_cents": 1200},
    {"product_form": "DRY_ICE", "packaging": "PALLET", "tier_min_units": 1, "tier_max_units": None, "unit_price_cents": 60000},
]


def full_book_payload(**overrides):
    """Full tiered book covering every (product_form, packaging) pair."""
    payload = price_book_payload(list(FULL_BOOK_LINES), **overrides)
    return payload


def mini_book_payload(**overrides):
    """Lean book with a single BLOCK/PALLET row (flat 21000)."""
    payload = price_book_payload(
        [{"product_form": "BLOCK", "packaging": "PALLET", "tier_min_units": 1, "tier_max_units": None, "unit_price_cents": 21000}],
        scope_label="mini",
    )
    payload["volume_discount_tiers"] = [{"threshold_cents": 50000, "discount_bps": 500}]
    payload.update(overrides)
    return payload


def mini_cube_book_payload(**overrides):
    """Lean book with CUBE/BAG tiers plus the BLOCK/PALLET row."""
    payload = price_book_payload(
        [
            {"product_form": "CUBE", "packaging": "BAG", "tier_min_units": 1, "tier_max_units": 19, "unit_price_cents": 350},
            {"product_form": "CUBE", "packaging": "BAG", "tier_min_units": 20, "tier_max_units": 99, "unit_price_cents": 300},
            {"product_form": "BLOCK", "packaging": "PALLET", "tier_min_units": 1, "tier_max_units": None, "unit_price_cents": 21000},
        ],
        scope_label="mini-cube",
    )
    payload["volume_discount_tiers"] = [{"threshold_cents": 50000, "discount_bps": 500}]
    payload.update(overrides)
    return payload


def mini_cube_pallet_book_payload(**overrides):
    """Lean book with a single CUBE/PALLET tier row (1-4 @ 28000)."""
    payload = price_book_payload(
        [{"product_form": "CUBE", "packaging": "PALLET", "tier_min_units": 1, "tier_max_units": 4, "unit_price_cents": 28000}],
        scope_label="mini-cp",
    )
    payload["volume_discount_tiers"] = [{"threshold_cents": 50000, "discount_bps": 500}]
    payload.update(overrides)
    return payload


def mini_dry_book_payload(**overrides):
    """Lean book with a single DRY_ICE/BAG row (flat 1500)."""
    payload = price_book_payload(
        [{"product_form": "DRY_ICE", "packaging": "BAG", "tier_min_units": 1, "tier_max_units": None, "unit_price_cents": 1500}],
        scope_label="mini-dry",
    )
    payload["volume_discount_tiers"] = [{"threshold_cents": 50000, "discount_bps": 500}]
    payload.update(overrides)
    return payload


# --- Simple entity payloads ---------------------------------------------------

def depot_payload(name="Depot", freezer_capacity_pallets=10):
    return {"name": name, "freezer_capacity_pallets": freezer_capacity_pallets}


def customer_payload(
    account_name="Customer",
    kind="BAR_RESTAURANT",
    tier="STANDARD",
    credit_terms="NET_30",
    credit_limit_cents=200000,
):
    return {
        "account_name": account_name,
        "kind": kind,
        "tier": tier,
        "credit_terms": credit_terms,
        "credit_limit_cents": credit_limit_cents,
    }


def certification_payload(
    handler_name="Hank Handler",
    certificate_number="CERT-1",
    max_dry_ice_lbs=1000,
    expires_at="2027-01-01T00:00:00Z",
):
    return {
        "handler_name": handler_name,
        "certificate_number": certificate_number,
        "max_dry_ice_lbs": max_dry_ice_lbs,
        "expires_at": expires_at,
    }


def surge_window_payload(
    depot_id,
    start_date,
    end_date,
    admission_policy,
    daily_pallet_cap=None,
):
    payload = {
        "depot_id": depot_id,
        "start_date": start_date,
        "end_date": end_date,
        "admission_policy": admission_policy,
    }
    if daily_pallet_cap is not None:
        payload["daily_pallet_cap"] = daily_pallet_cap
    return payload


def route_payload(
    customer_id,
    depot_id,
    weekday="MON",
    window_start="08:00",
    window_end="10:00",
    standing_lines=None,
):
    return {
        "customer_id": customer_id,
        "depot_id": depot_id,
        "weekday": weekday,
        "window_start": window_start,
        "window_end": window_end,
        "standing_lines": standing_lines
        or [{"product_form": "BLOCK", "packaging": "PALLET", "quantity_units": 1}],
    }


def order_line(product_form, packaging, quantity_units):
    return {
        "product_form": product_form,
        "packaging": packaging,
        "quantity_units": quantity_units,
    }


def order_payload(
    customer_id,
    depot_id,
    lines,
    channel="WILL_CALL",
    event_date=DEFAULT_EVENT_DATE,
    window_start=DEFAULT_WINDOW_START,
    window_end=DEFAULT_WINDOW_END,
):
    return {
        "customer_id": customer_id,
        "depot_id": depot_id,
        "channel": channel,
        "event_date": event_date,
        "window_start": window_start,
        "window_end": window_end,
        "lines": lines,
    }


def slot_payload(
    depot_id,
    date="2026-05-12",
    window_start="08:00",
    window_end="18:00",
    capacity_pallets=5,
):
    return {
        "depot_id": depot_id,
        "date": date,
        "window_start": window_start,
        "window_end": window_end,
        "capacity_pallets": capacity_pallets,
    }


def dispatch_run_payload(
    depot_id,
    run_date="2026-05-12",
    vehicle_label="TRUCK-1",
    max_pallets=5,
    ventilated_dry_ice_cap_lbs=0,
):
    return {
        "depot_id": depot_id,
        "run_date": run_date,
        "vehicle_label": vehicle_label,
        "max_pallets": max_pallets,
        "ventilated_dry_ice_cap_lbs": ventilated_dry_ice_cap_lbs,
    }


def invoice_generate_payload(customer_id, period_start, period_end):
    return {
        "customer_id": customer_id,
        "period_start": period_start,
        "period_end": period_end,
    }


def payment_payload(customer_id, amount_cents, method="ACH"):
    return {"customer_id": customer_id, "amount_cents": amount_cents, "method": method}
