"""Payload factories, one per resource, carrying only client-supplied fields."""
from .constants import SHOW_CALENDAR, TEST_DEFAULTS

FACTORY_DEFAULTS = {
    "VENUE_NAME": "Metro Convention Center",
    "VENUE_CITY": "Chicago",
    "WAREHOUSE_NAME": "Chicago Advance WH",
    "WAREHOUSE_CITY": "Chicago",
    "SHOW_NAME": "AutoTech 2026",
    "COMPANY_NAME": "Acme Motors",
    "CONTACT_EMAIL": "ops@acme.test",
    "BOOTH_NUMBER": "1024",
    "BOOTH_SQFT": 400,
    "BOOTH_TYPE": "ISLAND",
    "CRATE_LABEL": "ACME-C1",
    "CRATE_TYPE": "WOOD_CRATE",
    "CRATE_WEIGHT_LBS": 1250,
    "ASSET_LIST_VALUE_CENTS": 1500000,
    "ASSET_SHIPPING_WEIGHT_LBS": 1400,
    "DESIGN_SQFT": 400,
    "DESIGN_LINEAR_FEET": 40,
    "STRAIGHT_TIME_RATE": TEST_DEFAULTS["STRAIGHT_TIME_RATE_CENTS_PER_HOUR"],
}


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": FACTORY_DEFAULTS["VENUE_NAME"],
        "city": FACTORY_DEFAULTS["VENUE_CITY"],
    }
    payload.update(overrides)
    return payload


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "trade": "RIGGING",
        "straight_time_rate_cents_per_hour": FACTORY_DEFAULTS["STRAIGHT_TIME_RATE"],
    }
    payload.update(overrides)
    return payload


def create_warehouse_payload(**overrides) -> dict:
    payload = {
        "name": FACTORY_DEFAULTS["WAREHOUSE_NAME"],
        "city": FACTORY_DEFAULTS["WAREHOUSE_CITY"],
        "capacity_cwt": TEST_DEFAULTS["WAREHOUSE_CAPACITY_CWT"],
    }
    payload.update(overrides)
    return payload


def create_show_payload(venue_id, **overrides) -> dict:
    payload = {"venue_id": venue_id, "name": FACTORY_DEFAULTS["SHOW_NAME"]}
    payload.update(SHOW_CALENDAR)
    payload.update(overrides)
    return payload


def create_exhibitor_payload(**overrides) -> dict:
    payload = {
        "company_name": FACTORY_DEFAULTS["COMPANY_NAME"],
        "contact_email": FACTORY_DEFAULTS["CONTACT_EMAIL"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_booth_payload(show_id, exhibitor_id, **overrides) -> dict:
    payload = {
        "show_id": show_id,
        "exhibitor_id": exhibitor_id,
        "booth_number": FACTORY_DEFAULTS["BOOTH_NUMBER"],
        "sqft": FACTORY_DEFAULTS["BOOTH_SQFT"],
        "booth_type": FACTORY_DEFAULTS["BOOTH_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_exhibit_asset_payload(exhibitor_id, **overrides) -> dict:
    payload = {
        "exhibitor_id": exhibitor_id,
        "acquisition_mode": "PURCHASE",
        "list_value_cents": FACTORY_DEFAULTS["ASSET_LIST_VALUE_CENTS"],
        "shipping_weight_lbs": FACTORY_DEFAULTS["ASSET_SHIPPING_WEIGHT_LBS"],
    }
    payload.update(overrides)
    return payload


def create_exhibit_design_payload(exhibitor_id, booth_id, **overrides) -> dict:
    payload = {
        "exhibitor_id": exhibitor_id,
        "booth_id": booth_id,
        "sqft": FACTORY_DEFAULTS["DESIGN_SQFT"],
        "linear_feet": FACTORY_DEFAULTS["DESIGN_LINEAR_FEET"],
        "selected_acquisition_mode": "RENTAL",
    }
    payload.update(overrides)
    return payload


def service_order_line(line_seq, catalog_item_code="ELEC-20A", unit_qty=4,
                       unit_rate_cents=32500, discount_pct=0) -> dict:
    return {
        "line_seq": line_seq,
        "catalog_item_code": catalog_item_code,
        "unit_qty": unit_qty,
        "unit_rate_cents": unit_rate_cents,
        "discount_pct": discount_pct,
    }


def create_service_order_payload(booth_id, expected_booth_version, **overrides) -> dict:
    payload = {
        "booth_id": booth_id,
        "service_type": "ELECTRICAL",
        "lines": [service_order_line(1)],
        "expected_booth_version": expected_booth_version,
    }
    payload.update(overrides)
    return payload


def create_crate_payload(exhibitor_id, **overrides) -> dict:
    payload = {
        "exhibitor_id": exhibitor_id,
        "crate_label": FACTORY_DEFAULTS["CRATE_LABEL"],
        "crate_type": FACTORY_DEFAULTS["CRATE_TYPE"],
        "weight_lbs": FACTORY_DEFAULTS["CRATE_WEIGHT_LBS"],
    }
    payload.update(overrides)
    return payload


def create_drayage_shipment_payload(show_id, exhibitor_id, crate_ids, **overrides) -> dict:
    payload = {
        "show_id": show_id,
        "exhibitor_id": exhibitor_id,
        "channel": "ADVANCE_WAREHOUSE",
        "crate_ids": list(crate_ids),
        "received_at": "2026-09-08T10:00:00Z",
        "dock_window_start": "2026-09-08T08:00:00Z",
        "dock_window_end": "2026-09-08T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_labor_call_payload(booth_id, jurisdiction_id, **overrides) -> dict:
    payload = {
        "booth_id": booth_id,
        "jurisdiction_id": jurisdiction_id,
        "scheduled_start": "2026-09-21T13:00:00Z",
        "scheduled_end": "2026-09-21T17:00:00Z",
        "crew_size": 4,
    }
    payload.update(overrides)
    return payload


def create_change_order_payload(booth_id, target_type, target_id, **overrides) -> dict:
    payload = {
        "booth_id": booth_id,
        "target_type": target_type,
        "target_id": target_id,
        "delta_kind": "QTY_INCREASE",
        "delta_qty": 2,
        "reason": "Two extra 20A drops requested on the floor",
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(exhibitor_id, show_id, service_order_ids, **overrides) -> dict:
    payload = {
        "exhibitor_id": exhibitor_id,
        "show_id": show_id,
        "service_order_ids": list(service_order_ids),
    }
    payload.update(overrides)
    return payload


def create_damage_claim_payload(exhibitor_id, asset_id, **overrides) -> dict:
    payload = {
        "exhibitor_id": exhibitor_id,
        "asset_id": asset_id,
        "claim_type": "DAMAGE",
        "declared_value_cents": 900000,
        "incident_at": "2026-09-09T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_refurb_work_order_payload(asset_id, warehouse_id, **overrides) -> dict:
    payload = {
        "asset_id": asset_id,
        "warehouse_id": warehouse_id,
        "scope": "GRAPHICS_REFRESH",
        "estimate_cents": 500000,
    }
    payload.update(overrides)
    return payload


def create_lead_capture_license_payload(booth_id, **overrides) -> dict:
    payload = {"booth_id": booth_id, "device_count": 2}
    payload.update(overrides)
    return payload
