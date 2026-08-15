"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
import uuid

from .constants import TEST_DEFAULTS


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_fishery_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("BSAI"),
        "name": "Test Fishery",
        "region": TEST_DEFAULTS["REGION"],
        "coverage_target_pct": TEST_DEFAULTS["COVERAGE_TARGET_PCT"],
        "priority_gear": TEST_DEFAULTS["PRIORITY_GEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_vessel_operator_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Ops LLC",
        "license_number": _uniq("LIC"),
        "contact_person_ref": _uniq("person-op"),
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "vessel_name": "FV Test",
        "permit_number": _uniq("PERMIT"),
        "home_port": TEST_DEFAULTS["HOME_PORT"],
        "length_ft": 55,
        "gear_type": TEST_DEFAULTS["PRIORITY_GEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_observer_payload(**overrides) -> dict:
    defaults = {
        "person_ref": _uniq("person-obs"),
        "full_name": "Test Observer",
        "home_port": TEST_DEFAULTS["HOME_PORT"],
        "certification_level": "LEAD",
    }
    defaults.update(overrides)
    return defaults


def create_debriefer_payload(**overrides) -> dict:
    defaults = {
        "person_ref": _uniq("person-deb"),
        "full_name": "Test Debriefer",
    }
    defaults.update(overrides)
    return defaults


def create_em_reviewer_payload(**overrides) -> dict:
    defaults = {
        "person_ref": _uniq("person-rev"),
        "full_name": "Test Reviewer",
    }
    defaults.update(overrides)
    return defaults


def create_coverage_plan_payload(**overrides) -> dict:
    defaults = {
        "period_start": TEST_DEFAULTS["PLAN_PERIOD_START"],
        "period_end": TEST_DEFAULTS["PLAN_PERIOD_END"],
        "projected_fleet_effort_days": 100,
        "projected_em_effort_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_selection_run_payload(**overrides) -> dict:
    defaults = {
        "notice_response_deadline": TEST_DEFAULTS["NOTICE_RESPONSE_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_deployment_payload(**overrides) -> dict:
    defaults = {
        "scheduled_departure_date": TEST_DEFAULTS["DEPARTURE"],
        "scheduled_return_date": TEST_DEFAULTS["RETURN"],
    }
    defaults.update(overrides)
    return defaults


def create_safety_inspection_payload(**overrides) -> dict:
    defaults = {
        "life_raft_certified": True,
        "epirb_registered": True,
        "immersion_suits_adequate": True,
        "fire_suppression_ok": True,
        "comms_equipment_ok": True,
    }
    defaults.update(overrides)
    return defaults


def create_haul_sample_payload(**overrides) -> dict:
    defaults = {
        "haul_date": TEST_DEFAULTS["HAUL_DATE"],
        "haul_number": 1,
        "species_code": "PLCK",
        "sampled_weight_kg": 100,
        "total_haul_weight_kg": 500,
    }
    defaults.update(overrides)
    return defaults


def create_harassment_report_payload(**overrides) -> dict:
    defaults = {
        "report_type": "HARASSMENT",
        "narrative": "Crew interference with sampling duties",
        "incident_date": "2026-09-11T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_em_enrollment_payload(**overrides) -> dict:
    defaults = {
        "equipment_vendor": "DeckCam Inc",
        "equipment_install_date": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_em_trip_payload(**overrides) -> dict:
    defaults = {
        "departure_date": "2026-10-01T00:00:00Z",
        "return_date": "2026-10-08T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {"adjustment_cents": 1000, "reason": "Correction"}
    defaults.update(overrides)
    return defaults
