"""Payload factories — one per entity, carrying only client-supplied fields."""
import itertools

from .constants import TEST_DEFAULTS

_code_counter = itertools.count(1)


def unique_project_code(prefix: str = "TAD") -> str:
    """A programme code that is unique across all programmes in one test."""
    return f"{prefix}-{next(_code_counter):04d}"


def create_project_payload(**overrides) -> dict:
    defaults = {
        "project_code": unique_project_code(),
        "name": "Skyward Saga",
        "design_day_attendance": TEST_DEFAULTS["DESIGN_DAY_ATTENDANCE"],
        "peak_hour_share": TEST_DEFAULTS["PEAK_HOUR_SHARE"],
        "budget_ceiling_cents": TEST_DEFAULTS["BUDGET_CEILING_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_ride_system_payload(project_id: str, **overrides) -> dict:
    """The reference candidate: dispatch interval 20 s, theoretical 1440,
    operational 1179 guests per hour."""
    defaults = {
        "project_id": project_id,
        "vendor_name": TEST_DEFAULTS["RIDE_VENDOR_NAME"],
        "system_type": TEST_DEFAULTS["RIDE_SYSTEM_TYPE"],
        "vehicle_count": TEST_DEFAULTS["RIDE_VEHICLE_COUNT"],
        "riders_per_vehicle": TEST_DEFAULTS["RIDE_RIDERS_PER_VEHICLE"],
        "block_zone_count": TEST_DEFAULTS["RIDE_BLOCK_ZONE_COUNT"],
        "cycle_time_seconds": TEST_DEFAULTS["RIDE_CYCLE_TIME_SECONDS"],
        "availability_pct": TEST_DEFAULTS["RIDE_AVAILABILITY_PCT"],
        "load_efficiency_pct": TEST_DEFAULTS["RIDE_LOAD_EFFICIENCY_PCT"],
        "show_stops_per_hour": TEST_DEFAULTS["RIDE_SHOW_STOPS_PER_HOUR"],
    }
    defaults.update(overrides)
    return defaults


def create_show_scene_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "scene_label": "Prologue",
        "sequence_index": 1,
        "duration_seconds": 180,
    }
    defaults.update(overrides)
    return defaults


def create_effect_cue_payload(scene_id: str, **overrides) -> dict:
    defaults = {
        "scene_id": scene_id,
        "cue_label": "Reveal burst",
        "discipline_channel": "LIGHTING",
        "offset_ms": 1000,
        "duration_ms": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_queue_segment_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "segment_label": "Switchback A",
        "length_meters": 100.00,
        "width_meters": 2.00,
        "routing_type": "STANDARD",
        "position_index": 1,
    }
    defaults.update(overrides)
    return defaults


def create_design_package_payload(project_id: str, ride_system_id: str,
                                  expected_project_version: int, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "ride_system_id": ride_system_id,
        "package_label": "Integrated Set A",
        "discipline_scope": "INTEGRATED",
        "base_construction_cost_cents": TEST_DEFAULTS["PACKAGE_BASE_COST_CENTS"],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_safety_review_payload(design_package_id: str,
                                 expected_package_version: int, **overrides) -> dict:
    defaults = {
        "design_package_id": design_package_id,
        "standard_code": "ASTM_F2291",
        "expected_package_version": expected_package_version,
    }
    defaults.update(overrides)
    return defaults


def create_safety_finding_payload(safety_review_id: str, **overrides) -> dict:
    defaults = {
        "safety_review_id": safety_review_id,
        "severity": "MAJOR",
        "description": "Evacuation walkway handrail height below standard on lift hill",
        "remediation_cost_estimate_cents": 12000000,
    }
    defaults.update(overrides)
    return defaults


def create_value_engineering_item_payload(project_id: str, **overrides) -> dict:
    """Defaults are arithmetically consistent: scope_impact_delta_cents equals
    implementation_cost_cents minus gross_saving_cents."""
    defaults = {
        "project_id": project_id,
        "title": "Substitute sculpted rockwork with pre-cast panels",
        "gross_saving_cents": 350000021,
        "rework_loss_pct": 75,
        "implementation_cost_cents": 4000000,
        "capacity_impact_guests_per_hour": -300,
        "scope_impact_delta_cents": -346000021,
    }
    defaults.update(overrides)
    return defaults


def create_ve_ballot_payload(value_engineering_item_id: str, party_role: str,
                             decision: str, **overrides) -> dict:
    defaults = {
        "value_engineering_item_id": value_engineering_item_id,
        "party_role": party_role,
        "decision": decision,
    }
    defaults.update(overrides)
    return defaults


def create_rehearsal_run_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "run_kind": "TECHNICAL_REHEARSAL",
        "window_start_utc": "2026-08-01T09:00:00Z",
        "window_end_utc": "2026-08-01T13:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(project_id: str, expected_project_version: int,
                                **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "entry_kind": "CHANGE_ORDER",
        "amount_cents": 1000,
        "memo": "Owner-directed change order",
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_item_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "part_number": "VK-ROLLER-114",
        "description": "Upstop wheel assembly for ride vehicle bogie",
        "criticality": "SHOW_CRITICAL",
        "annual_consumption_rate": 7.30,
        "lead_time_days": 100,
    }
    defaults.update(overrides)
    return defaults
