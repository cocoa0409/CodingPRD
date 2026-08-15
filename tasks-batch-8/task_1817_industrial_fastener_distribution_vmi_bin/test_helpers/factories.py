"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import (
    ROUTE_DATE, STATION_WINDOW_END, STATION_WINDOW_START,
    WINDOW_END, WINDOW_START,
)

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_site_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Test Site {n}",
        "ship_to_code": f"SHP-{n:04d}",
        "credit_limit_cents": 100_000_000,
        "delivery_mode": "DOCK_TO_STOCK",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "sku": f"SKU-{n:04d}",
        "description": f"Test part {n}",
        "is_critical": False,
        "unit_price_cents": 1000,
        "total_stock_qty": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_part_cross_reference_payload(**overrides) -> dict:
    defaults = {
        "from_part_id": None,
        "to_part_id": None,
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


# Sentinel: flat_bin_price_cents omitted unless the caller asks for it.
_OMIT = object()


def create_bin_agreement_payload(site_id, part_id, **overrides) -> dict:
    """PRD §3.2: flat_bin_price_cents is required exactly when pricing_mode is
    COST_PER_BIN, so the factory omits it under UNIT_PRICE unless overridden."""
    n = _seq()
    flat = overrides.pop("flat_bin_price_cents", _OMIT)
    defaults = {
        "site_id": site_id,
        "part_id": part_id,
        "bin_location": f"BIN-{n:04d}",
        "pricing_mode": "UNIT_PRICE",
        "min_qty": 10,
        "max_qty": 100,
    }
    defaults.update(overrides)
    if flat is _OMIT:
        if defaults["pricing_mode"] == "COST_PER_BIN":
            defaults["flat_bin_price_cents"] = 7500
    else:
        defaults["flat_bin_price_cents"] = flat
    return defaults


def create_route_payload(site_id, expected_site_version, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "route_date": ROUTE_DATE,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(bin_agreement_id, **overrides) -> dict:
    defaults = {"bin_agreement_id": bin_agreement_id}
    defaults.update(overrides)
    return defaults


def create_lot_certificate_payload(part_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "part_id": part_id,
        "lot_number": f"LOT-{n:04d}",
        "cert_expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_kit_job_payload(site_id, component_part_ids, **overrides) -> dict:
    n = _seq()
    defaults = {
        "site_id": site_id,
        "kit_name": f"Kit {n}",
        "component_part_ids": list(component_part_ids),
        "qty_per_part": 1,
        "kit_count": 1,
        "station_window_start": STATION_WINDOW_START,
        "station_window_end": STATION_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults
