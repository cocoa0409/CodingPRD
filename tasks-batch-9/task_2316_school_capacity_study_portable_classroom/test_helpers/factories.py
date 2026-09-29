"""Request payload builders.

Every builder returns a valid payload for its endpoint and accepts `**overrides`
so a test can vary exactly the field it is interested in.
"""

from itertools import count
from typing import Any, Dict

_asset_tag_counter = count(1)
_pad_code_counter = count(1)
_room_counter = count(1)


# The generated labels carry an `-AUTO-` marker so that they can never land on a
# label a test spells out by hand.  PRD 2.6 rule 32 makes a room unique on
# (`school_id`, `room_number`), a pad unique on (`school_id`, `pad_code`) and a
# portable unique on `asset_tag`; without the marker a counter that happened to
# reach, say, `R103` or `PAD-150` would occupy the very label the test then asks
# the server to register, and the server would be right to answer
# `ERR_DUPLICATE_ROOM` / `ERR_DUPLICATE_PAD_CODE`.  Widths stay inside the PRD
# limits: 24 characters for `asset_tag`, 20 for `pad_code` and `room_number`.
def next_asset_tag(prefix: str = "PU") -> str:
    return f"{prefix}-AUTO-{next(_asset_tag_counter):04d}"


def next_pad_code(prefix: str = "PAD") -> str:
    return f"{prefix}-AUTO-{next(_pad_code_counter):04d}"


def next_room_number(prefix: str = "R") -> str:
    return f"{prefix}-AUTO-{next(_room_counter):04d}"


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def school_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Larkspur Middle",
        "grade_configuration": "MIDDLE_68",
        "site_acreage": 12.5,
        "fire_lane_clear_width_ft": 24,
        "electrical_spare_capacity_kw": 60,
        "sewer_spare_connections": 2,
        "consecutive_reliance_years": 0,
    }
    payload.update(overrides)
    return payload


def policy_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "grade_band": "G7_8",
        "effective_school_year": "2027-28",
        "max_class_size": 28,
        "min_area_sqft_per_seat": 30,
        "lab_area_premium_sqft": 20,
    }
    payload.update(overrides)
    return payload


def room_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "room_number": next_room_number(),
        "room_type": "STANDARD_CLASSROOM",
        "area_sqft": 900,
    }
    payload.update(overrides)
    return payload


def set_aside_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "program_type": "SPED_SELF_CONTAINED",
        "reserved_room_type": "SPED_RESOURCE",
        "reserved_room_count": 1,
        "seats_excluded_per_room": 12,
    }
    payload.update(overrides)
    return payload


def projection_payload(school_id: str, grade_level: int, projected_students: int,
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "school_year": "2027-28",
        "grade_level": grade_level,
        "projected_students": projected_students,
        "source": "COHORT_SURVIVAL",
        "confidence_tier": "HIGH",
    }
    payload.update(overrides)
    return payload


def budget_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fiscal_year": "2027-28",
        "authorized_cents": 500_000_000,
    }
    payload.update(overrides)
    return payload


def crew_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Crew Alpha",
        "max_concurrent_jobs": 2,
        "certified_work_types": ["SET", "RELOCATE"],
    }
    payload.update(overrides)
    return payload


def site_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "pad_code": next_pad_code(),
        "pad_length_ft": 60,
        "pad_width_ft": 34,
        "distance_to_fire_lane_ft": 40,
        "electrical_drop_available_kw": 20,
        "sewer_connection_available": False,
        "ada_path_of_travel_compliant": True,
    }
    payload.update(overrides)
    return payload


def assess_site_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"candidate_size_class": "SINGLE_24x40"}
    payload.update(overrides)
    return payload


def unit_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "asset_tag": next_asset_tag(),
        "size_class": "SINGLE_24x40",
        "condition_grade": "B",
        "ada_ramp_installed": True,
        "acquisition_cost_cents": 9_600_000,
        "in_service_year": 2019,
    }
    payload.update(overrides)
    return payload


def condition_payload(condition_status: str, condition_grade: str,
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "condition_status": condition_status,
        "condition_grade": condition_grade,
    }
    payload.update(overrides)
    return payload


def legacy_placement_payload(school_id: str, placement_site_id: str,
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "placement_site_id": placement_site_id,
        "installed_on": "2027-03-01",
    }
    payload.update(overrides)
    return payload


def study_payload(school_id: str, class_size_policy_id: str,
                  expected_school_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "class_size_policy_id": class_size_policy_id,
        "school_year": "2027-28",
        "method": "DISTRICT_POLICY",
        "expected_school_version": expected_school_version,
    }
    payload.update(overrides)
    return payload


def placement_request_payload(capacity_study_id: str, placement_site_id: str,
                              capital_budget_id: str, expected_study_version: int,
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "capacity_study_id": capacity_study_id,
        "placement_site_id": placement_site_id,
        "capital_budget_id": capital_budget_id,
        "requested_window_start": "2027-06-15",
        "requested_window_end": "2027-06-25",
        "haul_miles": 14,
        "expected_study_version": expected_study_version,
    }
    payload.update(overrides)
    return payload


def schedule_payload(placement_request_id: str, installation_crew_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_request_id": placement_request_id,
        "installation_crew_id": installation_crew_id,
        "work_type": "SET",
        "window_start": "2027-06-15",
        "window_end": "2027-06-25",
    }
    payload.update(overrides)
    return payload


def permit_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def permit_resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"correction_response": "Corrections attached."}
    payload.update(overrides)
    return payload


def disposal_payload(portable_unit_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "portable_unit_id": portable_unit_id,
        "method": "SCRAP",
        "valuation_basis": "CONDITION_ADJUSTED",
        "proceeds_cents": 0,
    }
    payload.update(overrides)
    return payload


def reason_payload(reason: str = "Boundary change adopted instead.") -> Dict[str, Any]:
    return {"reason": reason}
