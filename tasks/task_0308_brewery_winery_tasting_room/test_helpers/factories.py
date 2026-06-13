"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults for required input fields; optional
fields (Product.is_age_restricted, TastingOrder.member_id/guest_age_verified/
redeem_points, Reservation.is_event) are omitted unless overridden.
"""

DEFAULTS = {
    "WINERY_NAME": "Test Winery",
    "HOME_STATE": "CA",
    "LOT_CODE": "LOT-1",
    "BEVERAGE_CLASS": "WINE",
    "VOLUME_GALLONS": 100,
    "ABV_PERCENT": 13.5,
    "SKU": "SKU-1",
    "VINTAGE_YEAR": 2024,
    "BOTTLE_VOLUME_ML": 750,
    "LIST_PRICE_CENTS": 5000,
    "DOB_ADULT": "1990-01-01T00:00:00Z",
    "SHIP_STATE": "CA",
    "TIER": "SILVER",
    "CADENCE_MONTHS": 3,
    "BOTTLES_PER_SHIPMENT": 6,
}


def create_winery_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["WINERY_NAME"],
        "ttb_permit_number": "TTB-1",
        "home_state_code": DEFAULTS["HOME_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(winery_id, **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "lot_code": DEFAULTS["LOT_CODE"],
        "beverage_class": DEFAULTS["BEVERAGE_CLASS"],
        "volume_in_gallons": DEFAULTS["VOLUME_GALLONS"],
        "abv_percent": DEFAULTS["ABV_PERCENT"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(winery_id, source_batch_id, **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "source_batch_id": source_batch_id,
        "sku": DEFAULTS["SKU"],
        "vintage_year": DEFAULTS["VINTAGE_YEAR"],
        "bottle_volume_ml": DEFAULTS["BOTTLE_VOLUME_ML"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(winery_id, product_id, **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "product_id": product_id,
        "pool_bottles": 6,
        "per_member_cap": 6,
        "opens_at": "2026-06-01T00:00:00Z",
        "closes_at": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(winery_id, **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "full_name": "Ada Adult",
        "email": "ada@x.com",
        "date_of_birth": DEFAULTS["DOB_ADULT"],
        "ship_to_state_code": DEFAULTS["SHIP_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(winery_id, member_id, **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "member_id": member_id,
        "tier": DEFAULTS["TIER"],
        "cadence_months": DEFAULTS["CADENCE_MONTHS"],
        "bottles_per_shipment": DEFAULTS["BOTTLES_PER_SHIPMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(winery_id, membership_id, release_id, requested_bottles=6, **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "membership_id": membership_id,
        "release_id": release_id,
        "requested_bottles": requested_bottles,
    }
    defaults.update(overrides)
    return defaults


def create_tasting_order_payload(winery_id, line_items, **overrides) -> dict:
    """Required: winery_id, line_items. Optional: member_id, guest_age_verified,
    redeem_points — pass via overrides only when the test needs them."""
    defaults = {
        "winery_id": winery_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def bottle_line(product_id, quantity=1, **extra) -> dict:
    line = {"product_id": product_id, "kind": "BOTTLE", "quantity": quantity}
    line.update(extra)
    return line


def create_reservation_payload(winery_id, table_code="T1", party_size=2,
                               starts_at="2026-06-20T18:00:00Z",
                               ends_at="2026-06-20T19:00:00Z", **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "table_code": table_code,
        "party_size": party_size,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_order_payload(winery_id, product_id, case_count=1, **overrides) -> dict:
    defaults = {
        "winery_id": winery_id,
        "product_id": product_id,
        "retailer_license_number": "RET-1",
        "dest_state_code": "CA",
        "case_count": case_count,
    }
    defaults.update(overrides)
    return defaults
