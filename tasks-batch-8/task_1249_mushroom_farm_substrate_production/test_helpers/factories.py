"""Payload factories — one per entity, input fields only."""
import copy

from .constants import TEST_DEFAULTS, WB1_VARIETY


def create_variety_payload(**overrides) -> dict:
    defaults = copy.deepcopy(WB1_VARIETY)
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> dict:
    defaults = {"name": "Acme Grocery"}
    defaults.update(overrides)
    return defaults


def create_buyer_commitment_payload(**overrides) -> dict:
    defaults = {"buyer_id": None, "reference": "PO-100"}
    defaults.update(overrides)
    return defaults


def create_commitment_line_payload(**overrides) -> dict:
    defaults = {
        "variety_id": None,
        "committed_kg": TEST_DEFAULTS["LINE_COMMITTED_KG"],
        "week_start": TEST_DEFAULTS["LINE_WEEK_START"],
        "week_end": TEST_DEFAULTS["LINE_WEEK_END"],
        "min_grade": "B",
    }
    defaults.update(overrides)
    return defaults


def create_substrate_batch_payload(**overrides) -> dict:
    defaults = {"recipe": "PHASE_II_COMPOST", "tonnage": TEST_DEFAULTS["BATCH_TONNAGE"]}
    defaults.update(overrides)
    return defaults


def create_tunnel_payload(**overrides) -> dict:
    defaults = {"tunnel_code": "T1", "capacity_tonnes": TEST_DEFAULTS["TUNNEL_CAPACITY_TONNES"]}
    defaults.update(overrides)
    return defaults


def create_pasteurization_cycle_payload(**overrides) -> dict:
    defaults = {
        "batch_id": None,
        "tunnel_id": None,
        "planned_start": TEST_DEFAULTS["PASTEURIZATION_WINDOW_START"],
        "planned_end": TEST_DEFAULTS["PASTEURIZATION_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"room_code": "R1", "capacity_tonnes": TEST_DEFAULTS["ROOM_CAPACITY_TONNES"]}
    defaults.update(overrides)
    return defaults


def create_room_cycle_payload(**overrides) -> dict:
    defaults = {
        "room_id": None,
        "batch_id": None,
        "allocated_tonnage": TEST_DEFAULTS["ALLOCATED_TONNAGE"],
        "planned_start": TEST_DEFAULTS["CYCLE_PLANNED_START"],
        "planned_end": TEST_DEFAULTS["CYCLE_PLANNED_END"],
        "expected_room_version": 1,
    }
    defaults.update(overrides)
    return defaults


def record_flush_payload(**overrides) -> dict:
    defaults = {"total_kg": 100.0}
    defaults.update(overrides)
    return defaults


def grade_flush_payload(**overrides) -> dict:
    defaults = {"grade_a_kg": 60.0, "grade_b_kg": 30.0, "cull_kg": 10.0}
    defaults.update(overrides)
    return defaults


def create_packaged_lot_payload(**overrides) -> dict:
    defaults = {"grade": "A", "units": 20, "kg_per_unit": 1.0}
    defaults.update(overrides)
    return defaults


def log_piece_payload(**overrides) -> dict:
    defaults = {"worker_id": None, "kg_picked": 40.0}
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Wanda Picker",
        "crew_code": "C1",
        "piece_rate_cents_per_kg": TEST_DEFAULTS["WORKER_RATE_CENTS_PER_KG"],
    }
    defaults.update(overrides)
    return defaults


def report_contamination_event_payload(**overrides) -> dict:
    defaults = {
        "room_id": None,
        "pathogen": "TRICHODERMA",
        "severity": 4,
        "affected_zone_pct": 35.0,
    }
    defaults.update(overrides)
    return defaults


def reserve_spent_lot_payload(**overrides) -> dict:
    defaults = {"buyer_id": None}
    defaults.update(overrides)
    return defaults


def sell_spent_lot_payload(**overrides) -> dict:
    defaults = {"sale_price_cents": 45000}
    defaults.update(overrides)
    return defaults
