"""Payload factories: only the input fields the PRD declares for each write."""


def supplier_payload(**overrides) -> dict:
    payload = {
        "supplier_code": "SUP-CH",
        "name": "Cascade Chassis Works",
        "component_categories": ["CHASSIS"],
    }
    payload.update(overrides)
    return payload


def floor_plan_payload(**overrides) -> dict:
    payload = {
        "model_code": "FP-TOW",
        "chassis_class": "TOWABLE",
        "length_ft": 28,
        "base_msrp_cents": 8000000,
        "base_station_hours": 40.00,
        "base_dry_weight_lbs": 6000,
        "gvwr_lbs": 9000,
        "required_wheelbase_in": 180,
        "electrical_service_amps": 50,
        "fresh_water_capacity_gal": 60,
    }
    payload.update(overrides)
    return payload


def option_item_payload(**overrides) -> dict:
    payload = {
        "option_code": "OPT-E1",
        "category": "ELECTRICAL",
        "install_station": "ROUGH_IN",
        "price_cents": 100000,
        "weight_lbs": 0,
        "added_station_hours": 1.00,
        "amp_draw": 20,
        "water_demand_gal": 0,
    }
    payload.update(overrides)
    return payload


def dealer_payload(**overrides) -> dict:
    payload = {
        "dealer_code": "D-TOW",
        "region": "CENTRAL",
        "allocation_share_bp": 1500,
        "floor_plan_credit_limit_cents": 100000000,
        "goodwill_budget_cents": 500000,
    }
    payload.update(overrides)
    return payload


def production_line_payload(**overrides) -> dict:
    payload = {
        "line_code": "LINE-T",
        "chassis_class_supported": "TOWABLE",
        "daily_station_hour_capacity": 240.00,
        "max_units_per_day": 4,
    }
    payload.update(overrides)
    return payload


def test_booth_payload(**overrides) -> dict:
    payload = {
        "booth_code": "BOOTH-W",
        "booth_type": "WATER_TEST",
        "bay_count": 1,
        "turnaround_minutes": 30,
    }
    payload.update(overrides)
    return payload


def chassis_receipt_payload(supplier_id: str, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "chassis_serial": "CH-T1",
        "chassis_class": "TOWABLE",
        "gvwr_lbs": 9000,
        "wheelbase_in": 180,
    }
    payload.update(overrides)
    return payload


def component_lot_payload(supplier_id: str, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "part_number": "PN-FRIDGE",
        "lot_code": "L-1",
        "category": "APPLIANCE",
        "quantity_received": 10,
    }
    payload.update(overrides)
    return payload


def unit_order_payload(dealer_id: str, floor_plan_id: str, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "floor_plan_id": floor_plan_id,
        "order_type": "STOCK",
        "selected_option_ids": [],
        "requested_delivery_date": "2026-09-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def configuration_payload(selected_option_ids, **overrides) -> dict:
    payload = {"selected_option_ids": list(selected_option_ids)}
    payload.update(overrides)
    return payload


def production_slot_payload(line_id: str, slot_date: str, expected_version: int, **overrides) -> dict:
    payload = {
        "line_id": line_id,
        "slot_date": slot_date,
        "expected_unit_order_version": expected_version,
    }
    payload.update(overrides)
    return payload


def advance_payload(to_station: str, station_hours_used, **overrides) -> dict:
    payload = {"to_station": to_station, "station_hours_used": station_hours_used}
    payload.update(overrides)
    return payload


def component_installation_payload(
    unit_build_id: str, component_lot_id: str, station: str, quantity: int, **overrides
) -> dict:
    payload = {
        "unit_build_id": unit_build_id,
        "component_lot_id": component_lot_id,
        "station": station,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def quality_inspection_payload(unit_build_id: str, inspection_type: str, **overrides) -> dict:
    payload = {"unit_build_id": unit_build_id, "inspection_type": inspection_type}
    payload.update(overrides)
    return payload


def complete_inspection_payload(defect_points: int, leak_detected: bool, **overrides) -> dict:
    payload = {"defect_points": defect_points, "leak_detected": leak_detected}
    payload.update(overrides)
    return payload


def warranty_claim_payload(unit_build_id: str, claim_type: str, **overrides) -> dict:
    payload = {
        "unit_build_id": unit_build_id,
        "claim_type": claim_type,
        "labor_hours": 2.00,
        "parts_cost_cents": 0,
        "narrative": "Unit exhibited a fault during dealer inspection.",
    }
    payload.update(overrides)
    return payload


def recall_campaign_payload(supplier_id: str, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "campaign_code": "RC-1",
        "part_number": "PN-FRIDGE",
        "lot_codes": ["L-1"],
        "severity": "COMPLIANCE",
    }
    payload.update(overrides)
    return payload


def expand_campaign_payload(additional_lot_codes, expected_version: int, **overrides) -> dict:
    payload = {
        "additional_lot_codes": list(additional_lot_codes),
        "expected_recall_campaign_version": expected_version,
    }
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


def delivered_unit_payload(dealer_id: str, floor_plan_id: str, **overrides) -> dict:
    payload = {"dealer_id": dealer_id, "floor_plan_id": floor_plan_id}
    payload.update(overrides)
    return payload
