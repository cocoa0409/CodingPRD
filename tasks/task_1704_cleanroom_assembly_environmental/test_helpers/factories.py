"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ROOM_CODE": "CR-100",
    "ISO_CLASS": "ISO_7",
    "PARTICLE_ALERT": 300000,
    "PARTICLE_ACTION": 352000,
    "VIABLE_ALERT": 50,
    "VIABLE_ACTION": 100,
    "RECERT_DAYS": 180,
    "POINT_CODE": "SP-01",
    "SAMPLED_AT": "2026-08-01T09:00:00Z",
    "EXECUTED_AT": "2026-08-01T00:00:00Z",
    "ROOT_CAUSE": "Root cause narrative exceeding twenty characters",
    "EMPLOYEE_CODE": "EMP-100",
    "FULL_NAME": "Test Operator",
    "ROLE_TITLE": "Assembler",
    "MATERIAL_LOT": "LOT-100",
    "ITEM_DESCRIPTION": "Sealed component tray",
    "BATCH_NUMBER": "B-100",
    "PRODUCT_CODE": "PWB-1",
    "STEP_DESCRIPTION": "Assemble component",
    "METHOD_CODE": "MOP-STD",
    "CUSTOMER_CODE": "CUST-100",
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-08-02T00:00:00Z",
    "FINDING_DESCRIPTION": "Audit finding narrative",
}


def create_room_payload(**overrides) -> dict:
    defaults = {
        "room_code": DEFAULTS["ROOM_CODE"],
        "iso_class": DEFAULTS["ISO_CLASS"],
        "particle_alert_limit": DEFAULTS["PARTICLE_ALERT"],
        "particle_action_limit": DEFAULTS["PARTICLE_ACTION"],
        "viable_alert_limit": DEFAULTS["VIABLE_ALERT"],
        "viable_action_limit": DEFAULTS["VIABLE_ACTION"],
        "recert_interval_days": DEFAULTS["RECERT_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_sampling_point_payload(**overrides) -> dict:
    defaults = {
        "point_code": DEFAULTS["POINT_CODE"],
        "metric": "PARTICLE",
        "zone_iso_class": DEFAULTS["ISO_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(sampling_point_id, **overrides) -> dict:
    defaults = {
        "sampling_point_id": sampling_point_id,
        "result_value": 0,
        "sampled_at": DEFAULTS["SAMPLED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_investigation_payload(**overrides) -> dict:
    defaults = {
        "root_cause": DEFAULTS["ROOT_CAUSE"],
        "product_impact": "NONE",
        "disposition": "RELEASE",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(expected_room_version, **overrides) -> dict:
    defaults = {
        "executed_at": DEFAULTS["EXECUTED_AT"],
        "location_mean_values": [10, 20],
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_personnel_payload(**overrides) -> dict:
    defaults = {
        "employee_code": DEFAULTS["EMPLOYEE_CODE"],
        "full_name": DEFAULTS["FULL_NAME"],
        "role_title": DEFAULTS["ROLE_TITLE"],
    }
    defaults.update(overrides)
    return defaults


def create_gowning_qualification_payload(personnel_id, cleanroom_id, **overrides) -> dict:
    defaults = {"personnel_id": personnel_id, "cleanroom_id": cleanroom_id}
    defaults.update(overrides)
    return defaults


def create_entry_log_payload(personnel_id, cleanroom_id, **overrides) -> dict:
    defaults = {"personnel_id": personnel_id, "cleanroom_id": cleanroom_id}
    defaults.update(overrides)
    return defaults


def create_material_transfer_payload(cleanroom_id, **overrides) -> dict:
    defaults = {
        "cleanroom_id": cleanroom_id,
        "material_lot": DEFAULTS["MATERIAL_LOT"],
        "item_description": DEFAULTS["ITEM_DESCRIPTION"],
        "dwell_minutes": 0,
        "wiped_down": True,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(cleanroom_id, **overrides) -> dict:
    defaults = {
        "cleanroom_id": cleanroom_id,
        "batch_number": DEFAULTS["BATCH_NUMBER"],
        "product_code": DEFAULTS["PRODUCT_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_traveler_payload(**overrides) -> dict:
    defaults = {
        "step_sequence": 1,
        "step_description": DEFAULTS["STEP_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_cleaning_program_payload(cleanroom_id, **overrides) -> dict:
    defaults = {
        "cleanroom_id": cleanroom_id,
        "method_code": DEFAULTS["METHOD_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_cleaning_cycle_payload(**overrides) -> dict:
    defaults = {"result": "PASS"}
    defaults.update(overrides)
    return defaults


def create_audit_payload(cleanroom_id, **overrides) -> dict:
    defaults = {
        "customer_code": DEFAULTS["CUSTOMER_CODE"],
        "cleanroom_id": cleanroom_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(**overrides) -> dict:
    defaults = {
        "severity": "MINOR",
        "description": DEFAULTS["FINDING_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults
