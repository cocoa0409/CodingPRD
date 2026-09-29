"""Payload factories with valid defaults plus keyword overrides.

The default values are the canonical service-catalogue used throughout the
suite: the Cascade Service Hub centre, the Ascent 2P / Ascent 3P tent pair, a
PRO customer and the AS2 part lots. Each factory returns a plain dict so a
test can mutate or drop keys to exercise a validation.
"""

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- catalogue
CENTER_NAME = "Cascade Service Hub"
CENTER_REGION = "US-OR"
MODEL_CODE = "TNT-ASCENT-2"
SUCCESSOR_MODEL_CODE = "TNT-ASCENT-3"
PANEL_PART_CODE = "AS2-FLOOR-PANEL"
ZIP_PART_CODE = "AS2-ZIP-SLIDER"
CLIP_PART_CODE = "AS2-POLE-CLIP"
SERIAL_A = "AS2-00417"
SERIAL_B = "AS2-00418"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel: pass field=OMIT to drop a field from the payload entirely."""

    def __repr__(self):  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


def service_center_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": CENTER_NAME,
            "region_code": CENTER_REGION,
            "liability_cap_cents": 5000000,
            "bench_capacity_blocks_per_day": 24,
        },
        overrides,
    )


def surge_window_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "label": "June repair rush",
            "start_date": "2026-06-01T00:00:00Z",
            "end_date": "2026-06-30T23:59:59Z",
            "multiplier": 1.50,
        },
        overrides,
    )


def gear_model_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "model_code": MODEL_CODE,
            "name": "Ascent 2P Tent",
            "category": "TENT_SHELTER",
            "msrp_cents": 79900,
            "release_year": 2019,
            "warranty_years": 5,
        },
        overrides,
    )


def successor_model_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "model_code": SUCCESSOR_MODEL_CODE,
            "name": "Ascent 3P Tent",
            "category": "TENT_SHELTER",
            "msrp_cents": 99900,
            "release_year": 2024,
            "warranty_years": 5,
        },
        overrides,
    )


def customer_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Rowan Ives",
            "email": "rowan@example.com",
            "loyalty_tier": "PRO",
        },
        overrides,
    )


def gear_item_payload(gear_model_id: str, owner_customer_id: str, **overrides):
    return _merge(
        {
            "gear_model_id": gear_model_id,
            "owner_customer_id": owner_customer_id,
            "serial_number": SERIAL_A,
            "purchase_date": "2023-05-10T00:00:00Z",
            "purchase_price_cents": 74900,
            "proof_of_purchase_type": "RECEIPT",
            "proof_of_purchase_ref": "POS-88213",
            "condition_grade": "B",
        },
        overrides,
    )


def technician_payload(service_center_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "service_center_id": service_center_id,
            "employee_code": "T-101",
            "full_name": "Ines Park",
            "certifications": [
                {"work_type": "FABRIC", "level": 3},
                {"work_type": "ZIPPER", "level": 2},
                {"work_type": "FRAME", "level": 2},
            ],
        },
        overrides,
    )


def part_lot_payload(gear_model_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "gear_model_id": gear_model_id,
            "part_code": PANEL_PART_CODE,
            "part_kind": "FABRIC_PANEL",
            "on_hand_units": 5,
            "unit_price_cents": 4200,
            "low_watermark_units": 2,
        },
        overrides,
    )


def warranty_claim_payload(service_center_id: str, gear_item_id: str, **overrides):
    return _merge(
        {
            "service_center_id": service_center_id,
            "gear_item_id": gear_item_id,
            "intake_kind": "WARRANTY_CLAIM",
            "reported_defect_type": "SEAM_FAILURE",
            "customer_narrative": "Floor seam split along the taped edge.",
        },
        overrides,
    )


def assessment_payload(expected_claim_version: int, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "expected_claim_version": expected_claim_version,
            "determination": "MANUFACTURING_DEFECT",
            "required_work_types": ["FABRIC"],
            "estimated_labor_lines": [{"work_type": "FABRIC", "minutes": 120}],
            "estimated_parts_cents": 4200,
            "defect_notes": "Factory bond line failure.",
        },
        overrides,
    )


def repair_order_payload(warranty_claim_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"warranty_claim_id": warranty_claim_id}, overrides)


def estimate_payload(expected_repair_order_version: int, **overrides):
    return _merge(
        {
            "expected_repair_order_version": expected_repair_order_version,
            "labor_lines": [{"work_type": "FABRIC", "minutes": 25}],
            "parts_lines": [],
        },
        overrides,
    )


def work_block_payload(repair_order_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "repair_order_id": repair_order_id,
            "work_type": "FABRIC",
            "start_at": "2026-06-16T09:00:00Z",
            "end_at": "2026-06-16T11:00:00Z",
        },
        overrides,
    )


def parts_reservation_payload(part_lot_id: str, required_part_code: str, units: int = 1):
    return {
        "part_lot_id": part_lot_id,
        "required_part_code": required_part_code,
        "units": units,
    }


def labor_line(work_type: str, minutes: int) -> Dict[str, Any]:
    return {"work_type": work_type, "minutes": minutes}


def parts_line(part_code: str, units: int, unit_price_cents: int) -> Dict[str, Any]:
    return {
        "part_code": part_code,
        "units": units,
        "unit_price_cents": unit_price_cents,
    }


def certification(work_type: str, level: int) -> Dict[str, Any]:
    return {"work_type": work_type, "level": level}


def work_log_entry(work_block_id: str, actual_minutes: int) -> Dict[str, Any]:
    return {"work_block_id": work_block_id, "actual_minutes": actual_minutes}


def work_log(entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"work_log": entries or []}
