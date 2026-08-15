"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS

# Canonical show window used across the suite (occupancy 2026-09-01 .. 2026-09-03).
DEFAULT_LOAD_IN = "2026-09-01T08:00:00Z"
DEFAULT_SHOW = "2026-09-02T19:00:00Z"
DEFAULT_LOAD_OUT = "2026-09-03T23:00:00Z"
DEFAULT_CALL_START = "2026-09-01T08:00:00Z"
DEFAULT_CALL_END = "2026-09-01T18:00:00Z"
DEFAULT_PREP_START = "2026-08-25T09:00:00Z"
DEFAULT_PREP_END = "2026-08-25T17:00:00Z"
DEFAULT_DOCK_WINDOW_START = "2026-09-01T08:00:00Z"
DEFAULT_DOCK_WINDOW_END = "2026-09-01T12:00:00Z"


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "Arena IATSE",
        "union_ruleset": "IATSE",
        "max_point_capacity_kg": TEST_DEFAULTS["MAX_POINT_CAPACITY_KG"],
        "bay_aggregate_limit_kg": TEST_DEFAULTS["BAY_AGGREGATE_LIMIT_KG"],
        "house_power_amps_per_phase": TEST_DEFAULTS["HOUSE_POWER_AMPS_PER_PHASE"],
        "dock_doors": TEST_DEFAULTS["DOCK_DOORS"],
        "min_call_hours": 4,
        "ot1_threshold_hours": 8,
        "ot2_threshold_hours": 12,
        "turnaround_min_hours": 8,
        "crew_call_publish_lead_hours": 48,
        "engineering_submission_lead_hours": 72,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Lt One",
        "union_card_no": "U-1001",
        "classification": "LIGHTING_TECH",
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_production_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "name": "P1",
        "load_in_at": DEFAULT_LOAD_IN,
        "show_at": DEFAULT_SHOW,
        "load_out_at": DEFAULT_LOAD_OUT,
    }
    defaults.update(overrides)
    return defaults


def create_plot_payload(expected_production_version, **overrides) -> dict:
    defaults = {
        "title": "Main Rig",
        "expected_production_version": expected_production_version,
    }
    defaults.update(overrides)
    return defaults


def create_rigging_point_payload(expected_plot_version, **overrides) -> dict:
    defaults = {
        "point_label": "A1",
        "bay_index": 0,
        "hang_type": "DEAD_HANG",
        "motor_count": 0,
        "deadweight_kg": 100,
        "expected_plot_version": expected_plot_version,
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": "ML-001",
        "asset_class": "MOVING_LIGHT",
        "weight_kg": 25,
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "replacement_cost_cents": TEST_DEFAULTS["REPLACEMENT_COST_CENTS"],
        "acquired_at": TEST_DEFAULTS["ACQUIRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_pull_list_entry_payload(asset_id, **overrides) -> dict:
    defaults = {"asset_id": asset_id}
    defaults.update(overrides)
    return defaults


def create_crew_call_payload(**overrides) -> dict:
    defaults = {
        "department": "LIGHTING",
        "call_start": DEFAULT_CALL_START,
        "call_end": DEFAULT_CALL_END,
        "required_headcount": 1,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(technician_id, **overrides) -> dict:
    defaults = {"technician_id": technician_id}
    defaults.update(overrides)
    return defaults


def create_power_plan_payload(**overrides) -> dict:
    defaults = {
        "phase_l1_watts": 10000,
        "phase_l2_watts": 10000,
        "phase_l3_watts": 10000,
        "feeder_length_m": 0,
        "generator_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    defaults = {"plate_no": "T-1", "capacity_kg": 10000}
    defaults.update(overrides)
    return defaults


def create_load_schedule_payload(truck_id, **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "direction": "LOAD_IN",
        "dock_door_index": 0,
        "window_start": DEFAULT_DOCK_WINDOW_START,
        "window_end": DEFAULT_DOCK_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(inspection_type, **overrides) -> dict:
    defaults = {"inspection_type": inspection_type}
    defaults.update(overrides)
    return defaults


def create_damage_report_payload(pull_list_entry_id, report_type="DAMAGE", **overrides) -> dict:
    defaults = {"pull_list_entry_id": pull_list_entry_id, "report_type": report_type}
    defaults.update(overrides)
    return defaults


def assess_report_payload(valuation_method="DEPRECIATED", **overrides) -> dict:
    defaults = {"valuation_method": valuation_method}
    defaults.update(overrides)
    return defaults
