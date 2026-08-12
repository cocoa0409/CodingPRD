"""Payload factories — one per creatable resource, input fields only (PRD §3)."""


def create_shop_payload(**overrides) -> dict:
    defaults = {
        "name": "Shop",
        "stalls": 2,
        "dwell_rate_cents_per_hour": 500,
    }
    defaults.update(overrides)
    return defaults


def create_car_owner_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "name": "Owner A",
        "scac_code": "OWNA",
    }
    defaults.update(overrides)
    return defaults


def create_handling_line_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "name": "Line A",
        "mark": "LNA",
    }
    defaults.update(overrides)
    return defaults


def create_price_master_entry_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "job_code": "J-AIR-HOSE",
        "description": "Air hose replacement",
        "labor_rate_cents_per_hour": 9000,
        "mobile_labor_rate_cents_per_hour": 11000,
        "standard_labor_hours": 1.5,
        "mobile_trip_surcharge_cents": 25000,
        "mobile_eligible": True,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "part_number": "H-100",
        "description": "Gladhand air hose",
        "unit_price_cents": 4500,
        "on_hand_qty": 10,
        "reorder_threshold": 2,
    }
    defaults.update(overrides)
    return defaults


def create_wheelset_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "serial_number": "WS-001",
        "flange_thickness_mm": 30.0,
        "tread_wear_mm": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_shop_slot_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "stall_id": "S1",
        "starts_at": "2026-05-02T08:00:00Z",
        "ends_at": "2026-05-02T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_railcar_payload(shop_id, owner_id, handling_line_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "reporting_mark": "OWNA",
        "car_number": "1001",
        "owner_id": owner_id,
        "handling_line_id": handling_line_id,
        "built_date": "2020-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_defect_payload(**overrides) -> dict:
    defaults = {
        "aar_defect_code": "AAR-1204",
        "defect_group": "AIR_HOSE",
        "cause_code": "WEAR",
        "severity": "MAJOR",
        "location": "A-end",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(railcar_id, inspection_id, expected_railcar_version, **overrides) -> dict:
    defaults = {
        "railcar_id": railcar_id,
        "inspection_id": inspection_id,
        "routing": "SHOP",
        "expected_railcar_version": expected_railcar_version,
    }
    defaults.update(overrides)
    return defaults


def create_repair_line_payload(defect_finding_id, job_code, **overrides) -> dict:
    defaults = {
        "defect_finding_id": defect_finding_id,
        "job_code": job_code,
    }
    defaults.update(overrides)
    return defaults


def planned_part(part_item_id, quantity) -> dict:
    return {"part_item_id": part_item_id, "quantity": quantity}


def line_actual(repair_line_id, actual_labor_hours, parts_used=None) -> dict:
    return {
        "repair_line_id": repair_line_id,
        "actual_labor_hours": actual_labor_hours,
        "actual_parts": parts_used or [],
    }


def create_billing_repair_card_payload(work_order_id, expected_work_order_version) -> dict:
    return {
        "work_order_id": work_order_id,
        "expected_work_order_version": expected_work_order_version,
    }


def counter_item(brc_line_id, counter_amount_cents, reason="dispute") -> dict:
    return {
        "brc_line_id": brc_line_id,
        "counter_amount_cents": counter_amount_cents,
        "reason": reason,
    }


def create_counter_bill_payload(items) -> dict:
    return {"items": items}


def create_warranty_claim_payload(repair_line_id, **overrides) -> dict:
    defaults = {
        "repair_line_id": repair_line_id,
        "failure_defect_group": "AIR_HOSE",
        "claimed_rework_cost_cents": 5000,
        "description": "failure after repair",
    }
    defaults.update(overrides)
    return defaults
