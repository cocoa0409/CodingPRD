"""Payload factories — one per entity, input fields only.

Defaults reproduce the canonical LV_600 THHN 12 AWG copper line: a COPPER
settlement quote effective 2026-07-30 at 4.10 USD/lb, a qualified PVC insulation
compound on an ACTIVE UL file, a released SKU drawing 19.8 lbs per kft, one
customer with a 100000.00 credit limit and a 20000.00 lb copper rod heat.
"""

from .constants import TEST_DEFAULTS, THHN_12_CU_MARKING


def create_metal_price_quote_payload(**overrides) -> dict:
    payload = {
        "metal": "COPPER",
        "effective_date": TEST_DEFAULTS["COPPER_QUOTE_DATE"],
        "settlement_price_usd_per_lb": TEST_DEFAULTS["COPPER_QUOTE_PRICE"],
        "source": "COMEX",
    }
    payload.update(overrides)
    return payload


def create_rod_purchase_lot_payload(**overrides) -> dict:
    payload = {
        "metal": "COPPER",
        "supplier_code": "SUP-1",
        "rod_diameter_mm": 8.0,
        "heat_number": TEST_DEFAULTS["ROD_HEAT_NUMBER"],
        "purchase_weight_lbs": TEST_DEFAULTS["ROD_WEIGHT_LBS"],
        "purchase_price_usd_per_lb": TEST_DEFAULTS["ROD_PRICE_USD_PER_LB"],
        "pricing_basis": "SPOT",
        "received_date": "2026-07-25",
    }
    payload.update(overrides)
    return payload


def create_insulation_compound_payload(**overrides) -> dict:
    payload = {
        "compound_code": "PVC-90-INS",
        "layer_role": "INSULATION",
        "temp_rating_c": 90,
        "flame_test": "VW_1",
        "max_voltage_v": 600,
        "wet_rated": True,
        "filler_pct": 12.5,
    }
    payload.update(overrides)
    return payload


def create_jacket_compound_payload(**overrides) -> dict:
    payload = {
        "compound_code": "NYL-JKT",
        "layer_role": "JACKET",
        "temp_rating_c": 90,
        "flame_test": "VW_1",
        "max_voltage_v": 600,
        "wet_rated": True,
        "filler_pct": 5.0,
    }
    payload.update(overrides)
    return payload


def create_listing_certification_payload(**overrides) -> dict:
    payload = {
        "agency": "UL",
        "file_number": TEST_DEFAULTS["CERT_FILE_NUMBER"],
        "product_family_code": "BLDG-WIRE",
        "initial_listing_date": "2026-06-01",
        "inspection_interval_days": 90,
    }
    payload.update(overrides)
    return payload


def create_factory_inspection_payload(**overrides) -> dict:
    payload = {
        "inspection_date": "2026-06-05",
        "inspector_code": "INS-7",
        "findings_count": 0,
        "outcome": "PASS",
    }
    payload.update(overrides)
    return payload


def create_catalog_product_payload(insulation_compound_id, listing_certification_id,
                                  **overrides) -> dict:
    payload = {
        "product_code": "THHN-12-CU",
        "awg_size": "12",
        "conductor_metal": "COPPER",
        "conductor_construction": "STRANDED_7",
        "application_rating": "THHN",
        "voltage_class": "LV_600",
        "temp_rating_c": 90,
        "insulation_thickness_mils": 28.0,
        "conductor_lbs_per_kft": TEST_DEFAULTS["THHN_LBS_PER_KFT"],
        "insulation_compound_id": insulation_compound_id,
        "listing_certification_id": listing_certification_id,
        "base_target_kft": 100.0,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "account_code": "ACME",
        "name": "Acme Electric Supply",
        "market_region": "MIDWEST",
        "credit_limit_usd": TEST_DEFAULTS["CREDIT_LIMIT_USD"],
        "pass_through_enabled": True,
        "reel_program": "RETURNABLE",
    }
    payload.update(overrides)
    return payload


def create_customer_order_payload(customer_id, product_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_id": product_id,
        "order_number": "SO-1001",
        "ordered_kft": 5.0,
        "price_basis": "ORDER_DATE_LOCK",
        "conversion_price_usd_per_kft": TEST_DEFAULTS["CONVERSION_PRICE_USD_PER_KFT"],
        "order_date": TEST_DEFAULTS["COPPER_QUOTE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_production_lot_payload(product_id, rod_lot_id, expected_rod_lot_version,
                                  **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "rod_lot_id": rod_lot_id,
        "lot_code": "LOT-A",
        "planned_length_ft": 5000,
        "line_code": "EXT-1",
        "scheduled_start_at": "2026-08-02T08:00:00Z",
        "scheduled_end_at": "2026-08-02T12:00:00Z",
        "expected_rod_lot_version": expected_rod_lot_version,
    }
    payload.update(overrides)
    return payload


def drawing_step_payload(**overrides) -> dict:
    payload = {"step": "DRAWING"}
    payload.update(overrides)
    return payload


def stranding_step_payload(**overrides) -> dict:
    payload = {"step": "STRANDING"}
    payload.update(overrides)
    return payload


def extrusion_step_payload(**overrides) -> dict:
    """In-tolerance extrusion for THHN-12-CU: min wall 25.5 of a 30.0 max, so
    concentricity is 85.00 and the minimum wall requirement of 25.20 is met."""
    payload = {
        "step": "EXTRUSION",
        "measured_min_wall_mils": 25.5,
        "measured_max_wall_mils": 30.0,
        "measured_avg_od_mm": 4.1,
        "surface_marking_text": THHN_12_CU_MARKING,
    }
    payload.update(overrides)
    return payload


def spark_test_payload(**overrides) -> dict:
    payload = {"test_type": "SPARK", "duration_sec": 60, "faults_detected": 0}
    payload.update(overrides)
    return payload


def hipot_test_payload(**overrides) -> dict:
    payload = {
        "test_type": "HIPOT",
        "duration_sec": 300,
        "test_voltage_kv": 2.5,
        "breakdown_detected": False,
    }
    payload.update(overrides)
    return payload


def partial_discharge_test_payload(**overrides) -> dict:
    payload = {"test_type": "PARTIAL_DISCHARGE", "duration_sec": 600, "pd_level_pc": 5.0}
    payload.update(overrides)
    return payload


def rework_disposition_payload(**overrides) -> dict:
    payload = {
        "disposition": "REWORK",
        "rewind_to": "STRANDED",
        "reason": "measurements outside tolerance",
    }
    payload.update(overrides)
    return payload


def scrap_disposition_payload(**overrides) -> dict:
    payload = {"disposition": "SCRAPPED", "reason": "unrecoverable nonconformance"}
    payload.update(overrides)
    return payload


def create_reel_payload(**overrides) -> dict:
    payload = {
        "reel_serial": "R-001",
        "reel_type": "WOOD_RETURNABLE",
        "deposit_usd": TEST_DEFAULTS["REEL_DEPOSIT_USD"],
        "capacity_ft": TEST_DEFAULTS["REEL_CAPACITY_FT"],
    }
    payload.update(overrides)
    return payload


def load_reel_payload(lot_id, load_length_ft, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "load_length_ft": load_length_ft,
        "occupancy_start_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(order_id, lot_id, reel_id, shipped_length_ft,
                            expected_order_version, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "lot_id": lot_id,
        "reel_id": reel_id,
        "shipped_length_ft": shipped_length_ft,
        "ship_date": "2026-08-01",
        "cuts_count": 0,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_reel_return_payload(shipment_id, returned_date, condition="GOOD",
                               **overrides) -> dict:
    payload = {
        "shipment_id": shipment_id,
        "returned_date": returned_date,
        "condition": condition,
    }
    payload.update(overrides)
    return payload
