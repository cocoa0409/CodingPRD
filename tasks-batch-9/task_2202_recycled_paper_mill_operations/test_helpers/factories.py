"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def unique_suffix() -> int:
    return next(_seq)


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": "Northbound Converting Co",
        "allocation_priority_tier": "P2",
        "max_roll_diameter_mm": 1500,
        "max_roll_width_mm": 2400,
        "wrap_spec": "KRAFT_ONLY",
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "name": "Harbor Recovered Fiber LLC",
        "freight_per_ton": 12.50,
    }
    payload.update(overrides)
    return payload


def create_fiber_grade_payload(**overrides) -> dict:
    payload = {
        "grade_code": "OCC_11",
        "index_symbol": "PPI_OCC",
        "max_contamination_pct": 3.00,
        "max_moisture_pct": 12.00,
        "nominal_yield_pct": 88.00,
        "deink_required": False,
        "downgrade_target_grade_code": None,
        "rank_order": 10,
    }
    payload.update(overrides)
    return payload


def create_market_index_quote_payload(**overrides) -> dict:
    payload = {
        "index_symbol": "PPI_OCC",
        "effective_month": "2026-07",
        "published_price_per_ton": 150.00,
    }
    payload.update(overrides)
    return payload


def create_paper_grade_spec_payload(**overrides) -> dict:
    payload = {
        "product_code": "TL_140",
        "family": "CONTAINERBOARD",
        "basis_weight_gsm": 140.0,
        "target_moisture_pct": 7.00,
        "moisture_tolerance_pct": 1.00,
        "min_sct_kn_m": 2.50,
        "min_brightness_iso": None,
        "requires_deink_pulp": False,
        "rank_order": 20,
    }
    payload.update(overrides)
    return payload


def create_paper_machine_payload(**overrides) -> dict:
    payload = {
        "name": f"PM{unique_suffix()}",
        "wire_width_mm": 4000,
        "max_tons_per_hour": 25.00,
        "changeover_buffer_minutes": 30,
        "steam_tph_per_ton": 2.500,
    }
    payload.update(overrides)
    return payload


def create_purchase_order_payload(supplier_id, fiber_grade_code, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "fiber_grade_code": fiber_grade_code,
        "contracted_tons": 100.00,
        "index_basis": "CURRENT_MONTH",
        "priced_for_month": "2026-08",
        "negotiated_delta_per_ton": 0.00,
    }
    payload.update(overrides)
    return payload


def sublot(sublot_no, gross_tons, tare_tons, moisture_pct, contamination_pct) -> dict:
    return {
        "sublot_no": sublot_no,
        "gross_tons": gross_tons,
        "tare_tons": tare_tons,
        "moisture_pct": moisture_pct,
        "contamination_pct": contamination_pct,
    }


def create_receipt_payload(**overrides) -> dict:
    payload = {
        "truck_reference": f"TRK-{unique_suffix():04d}",
        "sublots": [sublot(1, 26.000, 6.000, 10.00, 2.00)],
    }
    payload.update(overrides)
    return payload


def furnish_line(inventory_lot_id, tons_charged) -> dict:
    return {"inventory_lot_id": inventory_lot_id, "tons_charged": tons_charged}


def create_pulp_batch_payload(target_product_code, furnish_lines, **overrides) -> dict:
    payload = {
        "pulper_line": "OCC_LINE",
        "target_product_code": target_product_code,
        "furnish_lines": furnish_lines,
    }
    payload.update(overrides)
    return payload


def create_run_payload(product_code, pulp_batch_id, expected_machine_version, **overrides) -> dict:
    payload = {
        "product_code": product_code,
        "pulp_batch_id": pulp_batch_id,
        "window_start": "2026-09-01T06:00:00Z",
        "window_end": "2026-09-01T14:00:00Z",
        "pulp_draw_tons": 10.000,
        "expected_machine_version": expected_machine_version,
    }
    payload.update(overrides)
    return payload


def reel_reading(reel_no, reel_tons, basis_weight_gsm, moisture_pct, sct_kn_m) -> dict:
    return {
        "reel_no": reel_no,
        "reel_tons": reel_tons,
        "basis_weight_gsm": basis_weight_gsm,
        "moisture_pct": moisture_pct,
        "sct_kn_m": sct_kn_m,
    }


def complete_run_payload(reel_readings=None, broke_tons=0.000, **overrides) -> dict:
    payload = {
        "reel_readings": reel_readings if reel_readings is not None
        else [reel_reading(1, 5.000, 140.0, 7.00, 3.00)],
        "broke_tons": broke_tons,
    }
    payload.update(overrides)
    return payload


def create_roll_set_payload(**overrides) -> dict:
    payload = {
        "slit_width_mm": 2400,
        "diameter_mm": 1400,
        "roll_count": 4,
        "net_tons": 5.000,
    }
    payload.update(overrides)
    return payload


def create_customer_order_payload(customer_id, product_code, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_code": product_code,
        "ordered_tons": 10.00,
        "requested_ship_date": "2026-09-15T00:00:00Z",
        "roll_width_mm": 2400,
        "roll_diameter_mm": 1400,
        "wrap_spec": "KRAFT_ONLY",
    }
    payload.update(overrides)
    return payload


def create_effluent_permit_payload(**overrides) -> dict:
    payload = {
        "permit_number": f"NPDES-{unique_suffix():05d}",
        "bod_limit_kg_per_day": 1000.00,
        "tss_limit_kg_per_day": 1200.00,
        "flow_limit_m3_per_day": 5000.00,
        "rolling_window_days": 30,
    }
    payload.update(overrides)
    return payload


def create_effluent_reading_payload(**overrides) -> dict:
    payload = {
        "reading_date": "2026-08-01",
        "flow_m3": 1000.00,
        "bod_kg": 100.00,
        "tss_kg": 100.00,
    }
    payload.update(overrides)
    return payload


def create_sludge_manifest_payload(reject_stream_ids, **overrides) -> dict:
    payload = {
        "manifest_number": f"MAN-{unique_suffix():05d}",
        "destination": "LANDFILL",
        "reject_stream_ids": reject_stream_ids,
    }
    payload.update(overrides)
    return payload


def create_steam_allocation_payload(**overrides) -> dict:
    payload = {
        "consumer_kind": "EVAPORATOR",
        "consumer_ref_id": None,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-01T02:00:00Z",
        "demand_tph": 50.000,
        "priority_rank": 2,
    }
    payload.update(overrides)
    return payload
