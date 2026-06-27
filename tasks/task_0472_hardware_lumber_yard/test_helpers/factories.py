"""Payload factories — one per entity, input fields only.

Field names match the PRD exactly. Optional fields with server defaults are
omitted unless overridden.
"""
import itertools

# Monotonic counters so factory calls produce unique SKU / asset_tag / bin
# locations within a single test (each test runs against a fresh database).
_sku_counter = itertools.count(1)
_tag_counter = itertools.count(1)
_bin_counter = itertools.count(1)


def unique_sku(prefix="SKU"):
    return f"{prefix}-{next(_sku_counter)}"


def unique_asset_tag(prefix="TAG"):
    return f"{prefix}-{next(_tag_counter)}"


def unique_bin():
    """Returns a unique (aisle, bin) pair as a 2-tuple."""
    n = next(_bin_counter)
    return (f"A{n}", f"B{n}")


def create_vendor_payload(**overrides) -> dict:
    """name required; drop_ship_capable and coop_rebate_pct optional (defaults
    false / 0)."""
    defaults = {"name": "Test Vendor"}
    defaults.update(overrides)
    return defaults


def create_product_payload(vendor_id: str, **overrides) -> dict:
    """sku, vendor_id, sell_mode, aisle, bin, reorder_point, reorder_qty
    required; pricing fields optional (default 0 where the mode does not need
    them)."""
    aisle, bin_ = unique_bin()
    defaults = {
        "sku": unique_sku(),
        "vendor_id": vendor_id,
        "sell_mode": "EACH",
        "aisle": aisle,
        "bin": bin_,
        "list_price_cents": 1000,
        "reorder_point": 0,
        "reorder_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_account_payload(**overrides) -> dict:
    """business_name, credit_limit_cents, net_terms_days required."""
    defaults = {
        "business_name": "Test Contractor",
        "credit_limit_cents": 1000000,
        "net_terms_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(**overrides) -> dict:
    """contractor_account_id optional (cash sale when omitted)."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id: str, qty, **overrides) -> dict:
    """product_id, qty required; cut_count optional (default 0)."""
    defaults = {"product_id": product_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def create_rental_asset_payload(**overrides) -> dict:
    """asset_tag, category, daily_rate_cents, deposit_cents required."""
    defaults = {
        "asset_tag": unique_asset_tag(),
        "category": "AUGER",
        "daily_rate_cents": 5000,
        "deposit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_rental_agreement_payload(rental_asset_id: str, start_at: str,
                                    due_at: str, **overrides) -> dict:
    """rental_asset_id, start_at, due_at required; contractor_account_id
    optional (cash renter)."""
    defaults = {
        "rental_asset_id": rental_asset_id,
        "start_at": start_at,
        "due_at": due_at,
    }
    defaults.update(overrides)
    return defaults


def create_service_station_payload(**overrides) -> dict:
    """name required; buffer_minutes optional (default 0)."""
    defaults = {"name": "Test Station"}
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(service_station_id: str, service_type: str,
                                  scheduled_start: str, scheduled_end: str,
                                  **overrides) -> dict:
    """service_station_id, service_type, scheduled_start, scheduled_end
    required; contractor_account_id and cylinder_certified optional
    (default null / false)."""
    defaults = {
        "service_station_id": service_station_id,
        "service_type": service_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(vendor_id: str, contractor_account_id: str,
                                qty: int, **overrides) -> dict:
    """vendor_id, contractor_account_id, description, qty required."""
    defaults = {
        "vendor_id": vendor_id,
        "contractor_account_id": contractor_account_id,
        "description": "Test special item",
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(vendor_id: str, lines: list, **overrides) -> dict:
    """vendor_id and lines required; each line is
    {product_id, qty, unit_cost_cents}."""
    defaults = {"vendor_id": vendor_id, "lines": lines}
    defaults.update(overrides)
    return defaults
