"""Payload factories — one per creation operation, client-supplied fields only."""

import itertools

from .constants import TEST_DEFAULTS

_apn_counter = itertools.count(1)
_license_counter = itertools.count(1)


def unique_apn(prefix: str = "APN") -> str:
    return f"{prefix}-{next(_apn_counter):05d}"


def unique_license_number(prefix: str = "LIC") -> str:
    return f"{prefix}-{next(_license_counter):05d}"


def create_parcel_payload(**overrides) -> dict:
    payload = {
        "apn": unique_apn(),
        "county_code": "OR",
        "site_address": "1 Perc Road",
        "lot_size_sqft": TEST_DEFAULTS["LOT_SIZE_SQFT"],
        "water_source": "PUBLIC_WATER",
    }
    payload.update(overrides)
    return payload


def create_well_payload(parcel_id: str, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "well_type": "DOMESTIC",
        "location_x_ft": 0,
        "location_y_ft": 0,
        "depth_ft": 120,
    }
    payload.update(overrides)
    return payload


def create_water_sample_payload(**overrides) -> dict:
    payload = {
        "collected_at": "2026-05-01T06:00:00Z",
        "nitrate_mg_l": 1.0,
        "coliform_present": False,
    }
    payload.update(overrides)
    return payload


def create_site_evaluation_payload(parcel_id: str, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "evaluated_on": TEST_DEFAULTS["EVALUATED_ON"],
        "soil_group": "LOAMY",
        "depth_to_limiting_layer_in": TEST_DEFAULTS["DEPTH_TO_LIMITING_LAYER_IN"],
    }
    payload.update(overrides)
    return payload


def create_perc_hole_payload(**overrides) -> dict:
    payload = {
        "hole_number": 1,
        "drop_inches": TEST_DEFAULTS["PERC_DROP_INCHES"],
        "elapsed_minutes": TEST_DEFAULTS["PERC_ELAPSED_MINUTES"],
        "presoak_ok": True,
    }
    payload.update(overrides)
    return payload


def create_system_design_payload(
    site_evaluation_id: str, expected_site_evaluation_version: int, **overrides
) -> dict:
    payload = {
        "site_evaluation_id": site_evaluation_id,
        "expected_site_evaluation_version": expected_site_evaluation_version,
        "system_type": "CONVENTIONAL",
        "bedrooms": TEST_DEFAULTS["BEDROOMS"],
        "tank_capacity_gal": TEST_DEFAULTS["TANK_CAPACITY_GAL"],
        "drainfield_x_ft": 150,
        "drainfield_y_ft": 0,
    }
    payload.update(overrides)
    return payload


def create_contractor_payload(**overrides) -> dict:
    payload = {
        "business_name": "Cascade Septic",
        "license_number": unique_license_number(),
        "license_class": "DUAL",
        "license_expires_on": TEST_DEFAULTS["LICENSE_EXPIRES_ON"],
        "bond_amount_cents": TEST_DEFAULTS["BOND_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_construction_permit_payload(
    system_design_id: str, contractor_id: str, **overrides
) -> dict:
    payload = {
        "system_design_id": system_design_id,
        "contractor_id": contractor_id,
        "valid_from": TEST_DEFAULTS["PERMIT_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["PERMIT_VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(construction_permit_id: str, **overrides) -> dict:
    payload = {
        "construction_permit_id": construction_permit_id,
        "inspection_type": "COVER",
        "scheduled_start": "2026-05-01T09:00:00Z",
        "scheduled_end": "2026-05-01T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_operating_permit_payload(construction_permit_id: str, **overrides) -> dict:
    payload = {
        "construction_permit_id": construction_permit_id,
        "household_size": TEST_DEFAULTS["HOUSEHOLD_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_pumping_record_payload(operating_permit_id: str, **overrides) -> dict:
    payload = {
        "operating_permit_id": operating_permit_id,
        "pumped_on": "2026-05-01T00:00:00Z",
        "gallons_removed": 900,
        "sludge_depth_in": 12.5,
        "scum_depth_in": 4.0,
    }
    payload.update(overrides)
    return payload


def create_repair_order_payload(operating_permit_id: str, **overrides) -> dict:
    payload = {
        "operating_permit_id": operating_permit_id,
        "failure_type": "STRUCTURAL",
        "reported_on": "2026-05-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_transfer_inspection_payload(
    parcel_id: str, operating_permit_id: str, expected_parcel_version: int, **overrides
) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "operating_permit_id": operating_permit_id,
        "expected_parcel_version": expected_parcel_version,
        "requested_on": "2026-05-01T00:00:00Z",
        "buyer_name": "Buyer One",
        "seller_name": "Seller One",
        "inspection_mode": "DESK_REVIEW",
    }
    payload.update(overrides)
    return payload
