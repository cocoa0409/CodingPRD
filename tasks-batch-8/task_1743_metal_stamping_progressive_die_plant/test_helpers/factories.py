"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools
import uuid

from . import constants as C

_counter = itertools.count(1)


def _tag() -> str:
    """Short unique suffix so multiple same-type creations never collide."""
    return f"{next(_counter)}-{uuid.uuid4().hex[:6]}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": f"Customer {_tag()}",
        "customer_code": f"CUST-{_tag()}",
        "steel_index_basis": "CRU_HRC",
        "base_index_value": C.DEFAULT_BASE_INDEX_VALUE,
        "pass_through_pct": C.DEFAULT_PASS_THROUGH_PCT,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "part_number": f"P-{_tag()}",
        "material_spec": C.DEFAULT_MATERIAL_SPEC,
        "thickness_mm": C.DEFAULT_THICKNESS_MM,
        "net_weight_kg": C.DEFAULT_NET_WEIGHT_KG,
        "base_piece_price_cents": C.DEFAULT_BASE_PIECE_PRICE_CENTS,
        "ppap_required_level": 1,
    }
    defaults.update(overrides)
    return defaults


def create_die_payload(**overrides) -> dict:
    defaults = {
        "die_code": f"D-{_tag()}",
        "die_type": "PROGRESSIVE",
        "total_stations": 6,
        "rated_tonnage": 300,
        "min_bed_width_mm": 1800,
        "repair_threshold_shots": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_press_payload(**overrides) -> dict:
    defaults = {
        "press_code": f"PR-{_tag()}",
        "tonnage": 500,
        "bed_width_mm": 2500,
        "strokes_per_min": 45,
    }
    defaults.update(overrides)
    return defaults


def create_part_die_assignment_payload(part_id: str, die_id: str, **overrides) -> dict:
    defaults = {"part_id": part_id, "die_id": die_id}
    defaults.update(overrides)
    return defaults


def create_steel_coil_payload(**overrides) -> dict:
    defaults = {
        "coil_number": f"C-{_tag()}",
        "heat_lot_number": f"HL-{_tag()}",
        "material_spec": C.DEFAULT_MATERIAL_SPEC,
        "thickness_mm": C.DEFAULT_THICKNESS_MM,
        "received_weight_kg": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_strip_layout_payload(part_id: str, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "revision": f"R-{_tag()}",
        "strip_width_mm": 250,
        "pitch_mm": 120,
        "parts_per_strip_segment": 1,
        "gross_weight_per_part_kg": C.DEFAULT_GROSS_WEIGHT_PER_PART_KG,
    }
    defaults.update(overrides)
    return defaults


def create_production_order_payload(part_id: str, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "quantity_ordered": 100,
        "due_date": C.ORDER_DUE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_die_change_event_payload(press_id: str, to_die_id: str, **overrides) -> dict:
    defaults = {
        "press_id": press_id,
        "to_die_id": to_die_id,
        "planned_start": C.CHANGEOVER_START,
        "planned_end": C.CHANGEOVER_END,
        "smed_target_minutes": 40,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(
    production_order_id: str, press_id: str, die_id: str, coil_id: str, **overrides
) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "press_id": press_id,
        "die_id": die_id,
        "coil_id": coil_id,
        "scheduled_start": C.RUN_WINDOW_START,
        "scheduled_end": C.RUN_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_reject_event_payload(**overrides) -> dict:
    defaults = {
        "station_number": 1,
        "sensor_code": "MISFEED",
        "quantity": 1,
        "sensed_at": "2026-08-01T08:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_outside_processing_order_payload(production_order_id: str, **overrides) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "operation_type": "PLATING",
        "quantity_sent": 10,
    }
    defaults.update(overrides)
    return defaults


def create_ppap_submission_payload(part_id: str, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "level": 1,
        "control_plan_attached": False,
    }
    defaults.update(overrides)
    return defaults


def create_layered_audit_payload(press_id: str, **overrides) -> dict:
    defaults = {
        "press_id": press_id,
        "audit_tier": 1,
        "scheduled_date": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_index_publication_payload(**overrides) -> dict:
    defaults = {
        "index_code": "CRU_HRC",
        "published_at": C.DEFAULT_CLOCK_ISO,
        "value_usd_per_ton": 950,
    }
    defaults.update(overrides)
    return defaults
