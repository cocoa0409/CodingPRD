"""Payload factories — one per resource, carrying only client-supplied fields."""


def brewer_payload(**overrides) -> dict:
    payload = {
        "name": "Test Brewing Co",
        "brewery_license_no": "BR-9001",
    }
    payload.update(overrides)
    return payload


def credit_profile_payload(expected_brewer_version, **overrides) -> dict:
    payload = {"expected_brewer_version": expected_brewer_version}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def volume_adjustment_payload(legacy_trailing_lbs, **overrides) -> dict:
    payload = {"legacy_trailing_lbs": legacy_trailing_lbs}
    payload.update(overrides)
    return payload


def crop_year_program_payload(**overrides) -> dict:
    payload = {
        "crop_year": 2026,
        "contract_open_date": "2026-01-15T00:00:00Z",
        "harvest_report_due_date": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def hop_variety_payload(**overrides) -> dict:
    payload = {
        "variety_code": "CITRA",
        "name": "Citra",
        "substitution_group": "CITRUS_AROMA",
        "alpha_acid_target_pct": 12.50,
        "spot_price_cents_per_lb": 1500.00,
    }
    payload.update(overrides)
    return payload


def hop_contract_payload(brewer_id, variety_id, crop_year_program_id,
                         **overrides) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "variety_id": variety_id,
        "crop_year_program_id": crop_year_program_id,
        "contract_type": "FIXED_CROP_YEAR",
        "contracted_lbs": 10000,
        "price_per_lb_cents": 1200.00,
        "delivery_window_start": "2026-09-01T00:00:00Z",
        "delivery_window_end": "2027-03-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def carry_forward_request_payload(carry_forward_target_program_id,
                                  requested_lbs, **overrides) -> dict:
    payload = {
        "carry_forward_target_program_id": carry_forward_target_program_id,
        "requested_lbs": requested_lbs,
    }
    payload.update(overrides)
    return payload


def substitution_offer_payload(expected_hop_contract_version, selection_mode,
                                offered_lbs, **overrides) -> dict:
    payload = {
        "expected_hop_contract_version": expected_hop_contract_version,
        "selection_mode": selection_mode,
        "offered_lbs": offered_lbs,
    }
    payload.update(overrides)
    return payload


def malt_product_payload(**overrides) -> dict:
    payload = {
        "sku": "PALE-ALE",
        "name": "Pale Ale Malt",
        "malt_class": "BASE",
        "list_price_cents_per_lb": 85.00,
    }
    payload.update(overrides)
    return payload


def malt_lot_payload(malt_product_id, **overrides) -> dict:
    payload = {
        "malt_product_id": malt_product_id,
        "lot_code": "LOT-0001",
        "quantity_lbs": 20000,
    }
    payload.update(overrides)
    return payload


def analysis_payload(**overrides) -> dict:
    payload = {
        "color_lovibond": 2.50,
        "extract_pct": 80.00,
        "moisture_pct": 4.20,
        "protein_pct": 10.50,
        "diastatic_power": 120.00,
    }
    payload.update(overrides)
    return payload


def yeast_strain_payload(**overrides) -> dict:
    payload = {
        "strain_code": "WLP001",
        "name": "California Ale",
        "fermentation_type": "ALE",
        "propagation_lead_time_days": 14,
        "list_price_cents_per_l": 400.00,
    }
    payload.update(overrides)
    return payload


def brewer_recipe_payload(brewer_id, malt_product_id, yeast_strain_id,
                          **overrides) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "malt_product_id": malt_product_id,
        "yeast_strain_id": yeast_strain_id,
        "name": "House IPA",
        "batch_volume_bbl": 30.00,
        "original_gravity_plato": 15.00,
        "target_color_lovibond": 3.00,
        "target_extract_pct": 80.00,
        "target_protein_pct": 10.50,
        "requested_pitch_rate_million_cells_per_ml_per_plato": 0.750,
    }
    payload.update(overrides)
    return payload


def propagation_job_payload(brewer_id, recipe_id, yeast_strain_id, pitch_date,
                            **overrides) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "recipe_id": recipe_id,
        "yeast_strain_id": yeast_strain_id,
        "pitch_date": pitch_date,
    }
    payload.update(overrides)
    return payload


def sales_order_payload(brewer_id, **overrides) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "requested_ship_date": "2026-09-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def hop_spot_line_payload(hop_variety_id, quantity, **overrides) -> dict:
    payload = {
        "item_type": "HOP",
        "quantity": quantity,
        "uom": "LB",
        "allocation_source": "SPOT",
        "hop_variety_id": hop_variety_id,
    }
    payload.update(overrides)
    return payload


def hop_contract_line_payload(hop_variety_id, hop_contract_id, quantity,
                              **overrides) -> dict:
    payload = {
        "item_type": "HOP",
        "quantity": quantity,
        "uom": "LB",
        "allocation_source": "CONTRACT",
        "hop_variety_id": hop_variety_id,
        "hop_contract_id": hop_contract_id,
    }
    payload.update(overrides)
    return payload


def malt_line_payload(malt_lot_id, quantity, **overrides) -> dict:
    payload = {
        "item_type": "MALT",
        "quantity": quantity,
        "uom": "LB",
        "malt_lot_id": malt_lot_id,
    }
    payload.update(overrides)
    return payload


def yeast_line_payload(yeast_propagation_job_id, quantity, **overrides) -> dict:
    payload = {
        "item_type": "YEAST",
        "quantity": quantity,
        "uom": "L",
        "yeast_propagation_job_id": yeast_propagation_job_id,
    }
    payload.update(overrides)
    return payload


def cold_storage_zone_payload(**overrides) -> dict:
    payload = {
        "zone_code": "ZONE-A",
        "temp_setpoint_c": 2.00,
        "capacity_pallets": 20,
    }
    payload.update(overrides)
    return payload


def shipment_payload(sales_order_id, cold_storage_zone_id,
                     expected_sales_order_version, **overrides) -> dict:
    payload = {
        "sales_order_id": sales_order_id,
        "cold_storage_zone_id": cold_storage_zone_id,
        "expected_sales_order_version": expected_sales_order_version,
        "pallet_count": 4,
        "stage_from": "2026-08-01T00:00:00Z",
        "stage_until": "2026-08-05T00:00:00Z",
        "reefer_setpoint_c": 2.00,
    }
    payload.update(overrides)
    return payload


def reading_payload(temp_c, recorded_at, **overrides) -> dict:
    payload = {"temp_c": temp_c, "recorded_at": recorded_at}
    payload.update(overrides)
    return payload
