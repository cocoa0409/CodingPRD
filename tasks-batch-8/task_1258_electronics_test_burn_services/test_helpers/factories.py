"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULT_BIN_MAP = {"1": "PASS", "2": "SOFT_FAIL", "9": "HARD_FAIL"}
PASS_ONLY_BIN_MAP = {"1": "PASS"}
DEFAULT_BURN_PROFILE = [{"target_temp_c": 55, "ramp_rate_c_per_min": 7, "soak_minutes": 30}]
TWO_SEGMENT_BURN_PROFILE = [
    {"target_temp_c": 55, "ramp_rate_c_per_min": 7, "soak_minutes": 30},
    {"target_temp_c": 95, "ramp_rate_c_per_min": 3, "soak_minutes": 45},
]


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Customer",
        "tier": "STANDARD",
        "requires_esd_certification": False,
    }
    defaults.update(overrides)
    return defaults


def create_test_program_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "part_number": "PN-1000",
        "bin_map": dict(DEFAULT_BIN_MAP),
        "max_retests_per_unit": 2,
        "burn_profile": [dict(s) for s in DEFAULT_BURN_PROFILE],
    }
    defaults.update(overrides)
    return defaults


def create_fixture_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "serial_number": "FX-1000",
        "site_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_chamber_payload(**overrides) -> dict:
    defaults = {
        "name": "CH-1000",
        "area_code": "AREA-1000",
        "slot_count": 4,
        "supported_profile_classes": ["A"],
    }
    defaults.update(overrides)
    return defaults


def create_chamber_reservation_payload(
    chamber_id: str, lot_id: str, fixture_id: str, **overrides
) -> dict:
    defaults = {
        "chamber_id": chamber_id,
        "lot_id": lot_id,
        "fixture_id": fixture_id,
        "profile_class": "A",
        "start_at": "2026-06-01T10:00:00Z",
        "end_at": "2026-06-01T11:00:00Z",
        "slot_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(customer_id: str, program_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "part_number": "PN-1000",
        "quantity": 1,
        "program_id": program_id,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "serial_number": "SN-1000",
    }
    defaults.update(overrides)
    return defaults


def create_test_result_payload(unit_id: str, fixture_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "fixture_id": fixture_id,
        "bin_code": 1,
    }
    defaults.update(overrides)
    return defaults


def create_retest_authorization_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "reason": "retest authorized",
    }
    defaults.update(overrides)
    return defaults


def create_customer_equipment_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "equipment_type": "TESTER",
        "serial_number": "EQ-1000",
        "calibration_interval_days": 365,
        "last_calibrated_at": "2026-04-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_order_payload(target_type: str, target_id: str, **overrides) -> dict:
    defaults = {
        "target_type": target_type,
        "target_id": target_id,
        "kind": "PREVENTIVE",
        "window_start": "2026-06-01T10:00:00Z",
        "window_end": "2026-06-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_esd_audit_payload(**overrides) -> dict:
    defaults = {
        "area_code": "AREA-1000",
        "findings": [],
    }
    defaults.update(overrides)
    return defaults


def create_rma_case_payload(lot_id: str, unit_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "unit_id": unit_id,
        "failure_mode": "field failure reported by customer",
    }
    defaults.update(overrides)
    return defaults
