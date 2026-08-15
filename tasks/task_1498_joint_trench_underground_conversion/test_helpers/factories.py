"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "ESTIMATED_TOTAL_COST_CENTS": 1_000_000,
    "TARGET_CUTOVER_ON": "2026-12-31T00:00:00Z",
    "UTILITY_NAME": "Utility Co",
    "UTILITY_TYPE": "ELECTRIC",
    "COST_SHARE_BP": 5000,
    "SEQUENCE_ORDER": 1,
    "SEGMENT_CODE": "SEG-1",
    "LENGTH_FT": 100,
    "MAX_DEPTH_INCHES": 60,
    "ADDRESS": "1 Main St",
    "OWNER_NAME": "Owner",
    "EXISTING_PANEL_AMPS": 200,
    "LOAD_CALC_AMPS": 100,
    "EASEMENT_TYPE": "TRENCH",
    "PERMIT_TYPE": "ENCROACHMENT",
    "PERMIT_VALID_FROM": "2026-08-01T00:00:00Z",
    "PERMIT_VALID_TO": "2026-12-31T00:00:00Z",
    "EXCAVATION_START_ON": "2026-09-01T00:00:00Z",
    "EXCAVATION_END_ON": "2026-09-10T00:00:00Z",
    "DEPTH_TOP_INCHES": 36,
    "DEPTH_BOTTOM_INCHES": 60,
    "INSTALL_START_AT": "2026-09-01T00:00:00Z",
    "INSTALL_END_AT": "2026-09-03T00:00:00Z",
    "FEEDER_ID": "F1",
    "OUTAGE_START_AT": "2026-09-05T10:00:00Z",
    "OUTAGE_END_AT": "2026-09-05T14:00:00Z",
    "DESCRIPTION": "Change order",
    "COST_CODE": "JOINT_TRENCH",
    "AMOUNT_CENTS": 1000,
    "INCURRED_ON": "2026-09-20T00:00:00Z",
    "TASK_TYPE": "HARDSCAPE",
}


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "rule20_credit_cents": 0,
        "estimated_total_cost_cents": DEFAULTS["ESTIMATED_TOTAL_COST_CENTS"],
        "target_cutover_on": DEFAULTS["TARGET_CUTOVER_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_participation_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "utility_name": DEFAULTS["UTILITY_NAME"],
        "utility_type": DEFAULTS["UTILITY_TYPE"],
        "cost_share_bp": DEFAULTS["COST_SHARE_BP"],
        "sequence_order": DEFAULTS["SEQUENCE_ORDER"],
    }
    defaults.update(overrides)
    return defaults


def create_trench_segment_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "segment_code": DEFAULTS["SEGMENT_CODE"],
        "length_ft": DEFAULTS["LENGTH_FT"],
        "max_depth_inches": DEFAULTS["MAX_DEPTH_INCHES"],
    }
    defaults.update(overrides)
    return defaults


def schedule_segment_payload(**overrides) -> dict:
    defaults = {
        "excavation_start_on": DEFAULTS["EXCAVATION_START_ON"],
        "excavation_end_on": DEFAULTS["EXCAVATION_END_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_occupancy_slot_payload(trench_segment_id, participation_id, **overrides) -> dict:
    defaults = {
        "trench_segment_id": trench_segment_id,
        "participation_id": participation_id,
        "depth_top_inches": DEFAULTS["DEPTH_TOP_INCHES"],
        "depth_bottom_inches": DEFAULTS["DEPTH_BOTTOM_INCHES"],
        "install_start_at": DEFAULTS["INSTALL_START_AT"],
        "install_end_at": DEFAULTS["INSTALL_END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "address": DEFAULTS["ADDRESS"],
        "owner_name": DEFAULTS["OWNER_NAME"],
        "existing_panel_amps": DEFAULTS["EXISTING_PANEL_AMPS"],
        "load_calc_amps": DEFAULTS["LOAD_CALC_AMPS"],
    }
    defaults.update(overrides)
    return defaults


def create_easement_payload(parcel_id, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "easement_type": DEFAULTS["EASEMENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "permit_type": DEFAULTS["PERMIT_TYPE"],
        "valid_from": DEFAULTS["PERMIT_VALID_FROM"],
        "valid_to": DEFAULTS["PERMIT_VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_service_conversion_payload(parcel_id, project_id, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "project_id": project_id,
    }
    defaults.update(overrides)
    return defaults


def create_outage_window_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "feeder_id": DEFAULTS["FEEDER_ID"],
        "start_at": DEFAULTS["OUTAGE_START_AT"],
        "end_at": DEFAULTS["OUTAGE_END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "description": DEFAULTS["DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_actual_cost_entry_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "cost_code": DEFAULTS["COST_CODE"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "incurred_on": DEFAULTS["INCURRED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_restoration_task_payload(trench_segment_id, parcel_id, **overrides) -> dict:
    defaults = {
        "trench_segment_id": trench_segment_id,
        "parcel_id": parcel_id,
        "task_type": DEFAULTS["TASK_TYPE"],
    }
    defaults.update(overrides)
    return defaults
