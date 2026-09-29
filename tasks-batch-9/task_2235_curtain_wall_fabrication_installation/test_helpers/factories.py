"""Payload factories — one per entity and per action, input fields only."""
from .constants import TEST_DEFAULTS, ZONE_A, ZONE_B


# ---------------------------------------------------------------------------
# The logical project clock
# ---------------------------------------------------------------------------
def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Facade package
# ---------------------------------------------------------------------------
def create_facade_package_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PACKAGE_NAME"],
        "floor_count": TEST_DEFAULTS["FLOOR_COUNT"],
        "total_area_sqm": TEST_DEFAULTS["TOTAL_AREA_SQM"],
        "contract_value_cents": TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
        "unit_rate_cents_per_sqm": TEST_DEFAULTS["UNIT_RATE_CENTS_PER_SQM"],
        "base_labor_rate_cents_per_hour": TEST_DEFAULTS["BASE_LABOR_RATE_CENTS_PER_HOUR"],
        "design_temp_delta_c": TEST_DEFAULTS["DESIGN_TEMP_DELTA_C"],
        "weather_tightness_deadline_date": TEST_DEFAULTS["WEATHER_TIGHTNESS_DEADLINE_DATE"],
    }
    payload.update(overrides)
    return payload


def system_decision_payload(system_type: str = "UNITIZED", **overrides) -> dict:
    payload = {"system_type": system_type}
    payload.update(overrides)
    return payload


def close_out_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Installation zone
# ---------------------------------------------------------------------------
def create_installation_zone_payload(package_id: str, **overrides) -> dict:
    payload = {"package_id": package_id}
    payload.update(ZONE_A)
    payload.update(overrides)
    return payload


def zone_b_payload(package_id: str, **overrides) -> dict:
    payload = {"package_id": package_id}
    payload.update(ZONE_B)
    payload.update(overrides)
    return payload


def retune_joint_payload(designed_joint_mm: float, **overrides) -> dict:
    payload = {"designed_joint_mm": designed_joint_mm}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Shop drawing submittal
# ---------------------------------------------------------------------------
def create_submittal_payload(package_id: str, **overrides) -> dict:
    payload = {
        "package_id": package_id,
        "submittal_type": "SHOP_DRAWING",
        "title": TEST_DEFAULTS["SUBMITTAL_TITLE"],
        "drawing_set_ref": TEST_DEFAULTS["DRAWING_SET_REF"],
        "delegated_design_scope": True,
    }
    payload.update(overrides)
    return payload


def seal_payload(seal_license_no: str = None, **overrides) -> dict:
    payload = {"seal_license_no": seal_license_no or TEST_DEFAULTS["SEAL_LICENSE_NO"]}
    payload.update(overrides)
    return payload


def start_review_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def review_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resubmit_payload(drawing_set_ref: str, **overrides) -> dict:
    payload = {"drawing_set_ref": drawing_set_ref}
    payload.update(overrides)
    return payload


def reopen_review_payload(reopen_reason: str, **overrides) -> dict:
    payload = {"reopen_reason": reopen_reason}
    payload.update(overrides)
    return payload


def close_notes_payload(notes_closed: int, **overrides) -> dict:
    payload = {"notes_closed": notes_closed}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Glass order
# ---------------------------------------------------------------------------
def create_glass_order_payload(package_id: str, **overrides) -> dict:
    payload = {
        "package_id": package_id,
        "supplier_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "coating_code": TEST_DEFAULTS["COATING_CODE"],
        "quoted_lead_time_days": TEST_DEFAULTS["QUOTED_LEAD_TIME_DAYS"],
        "ordered_lites": TEST_DEFAULTS["ORDERED_LITES"],
    }
    payload.update(overrides)
    return payload


def start_production_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def coating_revision_payload(coating_code: str, re_fire_required: bool = True, **overrides) -> dict:
    payload = {"coating_code": coating_code, "re_fire_required": re_fire_required}
    payload.update(overrides)
    return payload


def request_expedite_payload(expedite_tier: int, **overrides) -> dict:
    payload = {"expedite_tier": expedite_tier}
    payload.update(overrides)
    return payload


def receive_payload(received_lites: int, **overrides) -> dict:
    payload = {"received_lites": received_lites}
    payload.update(overrides)
    return payload


def recompute_risk_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Fabrication release and panel lots
# ---------------------------------------------------------------------------
def create_fabrication_release_payload(
    package_id: str,
    submittal_id: str,
    glass_order_id: str,
    zone_ids: list,
    expected_package_version: int,
    panels_per_zone: int = 36,
    lites_per_panel: int = 2,
    **overrides,
) -> dict:
    payload = {
        "package_id": package_id,
        "submittal_id": submittal_id,
        "glass_order_id": glass_order_id,
        "zone_ids": list(zone_ids),
        "panels_per_zone": panels_per_zone,
        "lites_per_panel": lites_per_panel,
        "expected_package_version": expected_package_version,
    }
    payload.update(overrides)
    return payload


def advance_fabrication_payload(to_status: str, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Breakage draws
# ---------------------------------------------------------------------------
def create_breakage_draw_payload(
    glass_order_id: str,
    panel_lot_id: str,
    quantity_lites: int,
    expected_glass_order_version: int,
    reason: str = "FIELD_BREAKAGE",
    **overrides,
) -> dict:
    payload = {
        "glass_order_id": glass_order_id,
        "panel_lot_id": panel_lot_id,
        "quantity_lites": quantity_lites,
        "reason": reason,
        "expected_glass_order_version": expected_glass_order_version,
    }
    payload.update(overrides)
    return payload


def cancel_breakage_draw_payload(cancelled_reason: str, **overrides) -> dict:
    payload = {"cancelled_reason": cancelled_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test laboratory and mockup tests
# ---------------------------------------------------------------------------
def create_test_lab_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["LAB_NAME"],
        "chamber_capacity": TEST_DEFAULTS["LAB_CHAMBER_CAPACITY"],
        "accreditation_ref": TEST_DEFAULTS["LAB_ACCREDITATION_REF"],
    }
    payload.update(overrides)
    return payload


def create_mockup_test_payload(
    package_id: str,
    test_lab_id: str,
    window_start: str = "2026-08-05T06:00:00Z",
    window_end: str = "2026-08-05T20:00:00Z",
    chambers_required: int = 1,
    **overrides,
) -> dict:
    payload = {
        "package_id": package_id,
        "test_lab_id": test_lab_id,
        "window_start": window_start,
        "window_end": window_end,
        "chambers_required": chambers_required,
    }
    payload.update(overrides)
    return payload


def record_mockup_result_payload(
    water_penetration_observed: bool = False,
    air_infiltration_cfm: float = 0.04,
    structural_deflection_mm: float = 15.0,
    **overrides,
) -> dict:
    payload = {
        "water_penetration_observed": water_penetration_observed,
        "air_infiltration_cfm": air_infiltration_cfm,
        "structural_deflection_mm": structural_deflection_mm,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Anchor embed survey
# ---------------------------------------------------------------------------
def create_embed_survey_payload(**overrides) -> dict:
    payload = {
        "embed_layout_ref": TEST_DEFAULTS["EMBED_LAYOUT_REF"],
        "planned_anchor_count": TEST_DEFAULTS["PLANNED_ANCHOR_COUNT"],
    }
    payload.update(overrides)
    return payload


def record_survey_payload(
    surveyed_anchor_count: int = 72, max_deviation_mm: float = 12.0, **overrides
) -> dict:
    payload = {
        "surveyed_anchor_count": surveyed_anchor_count,
        "max_deviation_mm": max_deviation_mm,
    }
    payload.update(overrides)
    return payload


def confirm_pour_payload(poured_at: str = "2026-08-06T12:00:00Z", **overrides) -> dict:
    payload = {"poured_at": poured_at}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Installation sequence
# ---------------------------------------------------------------------------
def set_anchors_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def hang_panels_payload(hoist_reservation_id: str, **overrides) -> dict:
    payload = {"hoist_reservation_id": hoist_reservation_id}
    payload.update(overrides)
    return payload


def certify_weather_tight_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Crew days
# ---------------------------------------------------------------------------
def create_crew_day_payload(
    work_date: str,
    crew_size: int = 4,
    shift_hours: float = 8.0,
    panels_installed: int = 12,
    **overrides,
) -> dict:
    payload = {
        "work_date": work_date,
        "crew_size": crew_size,
        "shift_hours": shift_hours,
        "panels_installed": panels_installed,
    }
    payload.update(overrides)
    return payload


def void_crew_day_payload(void_reason: str, **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Hoisting
# ---------------------------------------------------------------------------
def create_hoist_rig_payload(package_id: str, **overrides) -> dict:
    payload = {
        "package_id": package_id,
        "rig_code": TEST_DEFAULTS["RIG_CODE"],
        "rig_kind": "MAST_CLIMBER",
        "capacity_panels_per_shift": TEST_DEFAULTS["RIG_CAPACITY_PANELS_PER_SHIFT"],
        "changeover_buffer_minutes": 45,
    }
    payload.update(overrides)
    return payload


def create_hoist_reservation_payload(
    rig_id: str,
    zone_id: str,
    window_start: str,
    window_end: str,
    planned_panel_count: int = 36,
    **overrides,
) -> dict:
    payload = {
        "rig_id": rig_id,
        "zone_id": zone_id,
        "window_start": window_start,
        "window_end": window_end,
        "planned_panel_count": planned_panel_count,
    }
    payload.update(overrides)
    return payload


def cancel_reservation_payload(cancelled_reason: str, **overrides) -> dict:
    payload = {"cancelled_reason": cancelled_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Field tests
# ---------------------------------------------------------------------------
def schedule_field_test_payload(test_kind: str, scheduled_for: str, **overrides) -> dict:
    payload = {"test_kind": test_kind, "scheduled_for": scheduled_for}
    payload.update(overrides)
    return payload


def water_result_payload(water_penetration_observed: bool = False, **overrides) -> dict:
    payload = {"water_penetration_observed": water_penetration_observed}
    payload.update(overrides)
    return payload


def air_result_payload(measured_air_leakage_cfm: float = 0.04, **overrides) -> dict:
    payload = {"measured_air_leakage_cfm": measured_air_leakage_cfm}
    payload.update(overrides)
    return payload


def deflection_result_payload(measured_deflection_mm: float, **overrides) -> dict:
    payload = {"measured_deflection_mm": measured_deflection_mm}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Defect items
# ---------------------------------------------------------------------------
def create_defect_item_payload(
    package_id: str,
    origin: str = "PUNCH_LIST",
    severity: str = "MINOR",
    description: str = "sealant tooling at grid 4",
    **overrides,
) -> dict:
    payload = {
        "package_id": package_id,
        "origin": origin,
        "severity": severity,
        "description": description,
    }
    payload.update(overrides)
    return payload


def submit_remediation_payload(remediation_note: str, **overrides) -> dict:
    payload = {"remediation_note": remediation_note}
    payload.update(overrides)
    return payload


def reinspect_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def waive_payload(waiver_ref: str, **overrides) -> dict:
    payload = {"waiver_ref": waiver_ref}
    payload.update(overrides)
    return payload
