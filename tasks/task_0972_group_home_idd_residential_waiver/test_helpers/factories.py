"""Payload factories — one per entity, input fields only.

Defaults are chosen to satisfy PRD constraints (e.g. goals_summary >= 10
chars). Tests override via keyword args.
"""
import itertools

from .constants import TEST_DEFAULTS


# Monotonic suffix generator so unique-per-system fields (medicaid_id,
# license_number) never collide inside a single test run.
_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_agency_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["AGENCY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_home_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "name": TEST_DEFAULTS["HOME_NAME"],
        "license_number": _uniq("LIC"),
        "certified_bed_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_individual_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "legal_name": "Ind One",
        "medicaid_id": _uniq("MCD"),
        "date_of_birth": "1990-01-01",
        "mobility_level": "AMBULATORY",
    }
    defaults.update(overrides)
    return defaults


def create_isp_payload(individual_id: str, expected_individual_version, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "plan_year_start": TEST_DEFAULTS["PLAN_YEAR_START"],
        "plan_year_end": TEST_DEFAULTS["PLAN_YEAR_END"],
        "goals_summary": TEST_DEFAULTS["GOALS_SUMMARY"],
        "expected_individual_version": expected_individual_version,
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(individual_id: str, isp_id: str, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "isp_id": isp_id,
        "service_code": "DAY_PROG",
        "unit_type": "FIFTEEN_MIN",
        "authorized_units": TEST_DEFAULTS["DEFAULT_AUTH_UNITS"],
        "rate_cents": TEST_DEFAULTS["DEFAULT_RATE_CENTS"],
        "span_start": TEST_DEFAULTS["SPAN_START"],
        "span_end": TEST_DEFAULTS["SPAN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(agency_id: str, staff_role: str = "DSP", **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "full_name": "Staff Member",
        "staff_role": staff_role,
        "certifications": ["CPR"],
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(home_id: str, staff_member_id: str, **overrides) -> dict:
    defaults = {
        "home_id": home_id,
        "staff_member_id": staff_member_id,
        "window_start": "2026-06-02T07:00:00Z",
        "window_end": "2026-06-02T15:00:00Z",
        "shift_type": "DAY",
    }
    defaults.update(overrides)
    return defaults


def create_bed_assignment_payload(home_id: str, bed_label: str, individual_id: str, **overrides) -> dict:
    defaults = {
        "home_id": home_id,
        "bed_label": bed_label,
        "individual_id": individual_id,
        "move_in_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_medication_order_payload(individual_id: str, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "drug_name": "Metformin",
        "dosage": "500mg",
        "schedule_times": ["08:00"],
        "start_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_admin_event_payload(medication_order_id: str, **overrides) -> dict:
    defaults = {
        "medication_order_id": medication_order_id,
        "scheduled_time": "2026-06-02T08:00:00Z",
        "outcome": "GIVEN",
        "administered_time": "2026-06-02T08:05:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_behavior_plan_payload(individual_id: str, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "level": "LEVEL_1",
        "restrictive_interventions": [],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(individual_id: str, home_id: str, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "home_id": home_id,
        "category": "INJURY",
        "severity": "CRITICAL",
        "occurred_at": "2026-06-02T08:00:00Z",
        "discovered_at": "2026-06-02T08:30:00Z",
        "description": "Resident fell in bathroom",
    }
    defaults.update(overrides)
    return defaults


def create_evv_visit_payload(individual_id: str, authorization_id: str, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "authorization_id": authorization_id,
        "service_date": "2026-06-02",
        "check_in_at": "2026-06-02T09:00:00Z",
        "check_out_at": "2026-06-02T10:00:00Z",
        "geo_within_radius": True,
    }
    defaults.update(overrides)
    return defaults


def create_transport_leg_payload(individual_id: str, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "wheelchair_seat": False,
        "pickup_at": "2026-06-02T09:00:00Z",
        "dropoff_at": "2026-06-02T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_transport_trip_payload(home_id: str, legs, **overrides) -> dict:
    defaults = {
        "home_id": home_id,
        "vehicle_id": "VAN-1",
        "trip_date": "2026-06-02",
        "depart_at": "2026-06-02T09:00:00Z",
        "return_at": "2026-06-02T11:00:00Z",
        "legs": legs,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(individual_id: str, **overrides) -> dict:
    defaults = {
        "individual_id": individual_id,
        "service_period_start": "2026-06-02",
        "service_period_end": "2026-06-02",
    }
    defaults.update(overrides)
    return defaults
