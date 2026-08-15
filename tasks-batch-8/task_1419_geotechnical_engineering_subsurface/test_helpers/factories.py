"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    DEFAULT_APPLIED_BEARING_PSF,
    DEFAULT_AUTH_CAP_CENTS,
    DEFAULT_BASE_FEE_CENTS,
    DEFAULT_FOOTING_WIDTH_FT,
    DEFAULT_FS_REQUIRED,
    DEFAULT_GWT_DEPTH_FT,
    DEFAULT_PLANNED_DEPTH_FT,
    DEFAULT_TARGET_REPORT_DATE,
    TICKET_ISSUED_ON,
    WINDOW_END,
    WINDOW_START,
)


def create_client_payload(**overrides) -> dict:
    defaults = {"name": "Acme Dev", "contact_email": "a@x.com"}
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "name": "P1",
        "site_address": "1 Way",
        "target_report_date": DEFAULT_TARGET_REPORT_DATE,
        "base_fee_cents": DEFAULT_BASE_FEE_CENTS,
        "additional_auth_cap_cents": DEFAULT_AUTH_CAP_CENTS,
        "assumed_gwt_depth_ft": DEFAULT_GWT_DEPTH_FT,
    }
    defaults.update(overrides)
    return defaults


def create_boring_plan_payload(expected_project_version, **overrides) -> dict:
    defaults = {
        "planned_boring_count": 1,
        "planned_total_footage_ft": 30,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_payload(**overrides) -> dict:
    defaults = {
        "name": "DrillCo",
        "license_no": "LIC-1",
        "day_rate_cents": 90000,
        "max_concurrent_rigs": 2,
    }
    defaults.update(overrides)
    return defaults


def create_rig_assignment_payload(subcontractor_id, **overrides) -> dict:
    defaults = {
        "subcontractor_id": subcontractor_id,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_boring_payload(**overrides) -> dict:
    defaults = {
        "boring_no": "B-1",
        "planned_depth_ft": DEFAULT_PLANNED_DEPTH_FT,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(**overrides) -> dict:
    defaults = {
        "ticket_number": "T-1",
        "issued_on": TICKET_ISSUED_ON,
    }
    defaults.update(overrides)
    return defaults


def drill_boring_payload(**overrides) -> dict:
    """Payload for the CLEARED -> DRILLED transition report."""
    defaults = {
        "to": "DRILLED",
        "actual_depth_ft": 30,
        "rock_depth_ft": 0,
        "groundwater_depth_ft": 12,
        "avg_n60": 12,
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(**overrides) -> dict:
    defaults = {
        "depth_top_ft": 10,
        "depth_bottom_ft": 11.5,
        "sampler_type": "SPT",
        "recovery_pct": 80,
    }
    defaults.update(overrides)
    return defaults


def create_lab_test_order_payload(sample_id, **overrides) -> dict:
    defaults = {
        "sample_id": sample_id,
        "test_type": "MOISTURE_CONTENT",
        "priority": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_lab_result_payload(**fields) -> dict:
    """Result payload: only the measurement fields the test produced."""
    return dict(fields)


def create_foundation_analysis_payload(**overrides) -> dict:
    defaults = {
        "method": "ALLOWABLE_STRESS",
        "fs_required": DEFAULT_FS_REQUIRED,
        "footing_width_ft": DEFAULT_FOOTING_WIDTH_FT,
        "applied_bearing_psf": DEFAULT_APPLIED_BEARING_PSF,
    }
    defaults.update(overrides)
    return defaults


def create_observation_visit_payload(**overrides) -> dict:
    defaults = {"visit_date": "2026-08-10T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claimed_amount_cents": 120000,
        "basis_text": "Soft subgrade vs report baseline",
    }
    defaults.update(overrides)
    return defaults


def create_exploration_authorization_payload(**overrides) -> dict:
    defaults = {
        "authorized_amount_cents": 100000,
        "extra_boring_count": 1,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
