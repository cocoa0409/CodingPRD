"""Payload factories — one per record type, request-input fields only."""

DEFAULTS = {
    "STUDY_NAME": "2028 Elementary Boundary Study",
    "DISTRICT_NAME": "Riverbend USD",
    "TARGET_SCHOOL_YEAR": 2028,
    "HORIZON_YEARS": 5,
    "CAPACITY_TARGET_LOW_PCT": 85.0,
    "CAPACITY_TARGET_HIGH_PCT": 100.0,
    "REQUIRED_PROGRAM_TYPES": ["DUAL_LANGUAGE"],
    "PROGRAM_TYPE": "DUAL_LANGUAGE",
    "SCHOOL_NAME": "Cedar Elementary",
    "LEVEL": "ELEMENTARY",
    "CORE_CAPACITY_SEATS": 500,
    "PORTABLE_CAPACITY_SEATS": 0,
    "AREA_CODE": "A-01",
    "GRADE_BAND": "ELEMENTARY",
    "RESIDENT_STUDENT_COUNT": 300,
    "FRL_STUDENT_COUNT": 90,
    "ELL_STUDENT_COUNT": 40,
    "MEDIAN_HOUSEHOLD_INCOME_USD": 78000,
    "ANNUAL_ABSORPTION_CAP_UNITS": 250,
    "SHARED_BOUNDARY_LENGTH_FT": 5000,
    "DEVELOPMENT_NAME": "Willow Ridge",
    "UNIT_TYPE": "SINGLE_FAMILY",
    "TOTAL_UNITS": 120,
    "FIRST_OCCUPANCY_DATE": "2027-01-01T00:00:00Z",
    "BUILDOUT_MONTHS": 24,
    "SCENARIO_NAME": "Scenario A",
    "IMPACT_VARIANT": "RESIDENT_BASED",
    "VARIANT": "COHORT_SURVIVAL",
    "COMMENT_BODY": "This boundary change lengthens our walk to school.",
    "EFFECTIVE_DATE": "2027-07-01T00:00:00Z",
    "EFFECTIVE_SCHOOL_YEAR": 2028,
    "REGIME_YEARS": 3,
    "TRANSFER_DEADLINE_DATE": "2027-08-15T00:00:00Z",
    "TRANSFER_CAP_PCT": 105.0,
    "VARIANCE_TOLERANCE_PCT": 5.0,
    "VOTES_FOR": 5,
    "VOTES_AGAINST": 2,
    "VOTES_ABSTAIN": 0,
    "BOARD_MEMBER_COUNT": 7,
    "STUDENT_REFERENCE": "STU-001",
    "STUDENT_GRADE": 3,
    "TRANSFER_REASON": "HARDSHIP",
    "RULE_TYPE": "TERMINAL_GRADE_GRANDFATHER",
    "SUNSET_SCHOOL_YEAR": 2030,
}


def travel_option(school_id, walk_distance_miles, bus_minutes, has_safe_route):
    """One entry of a planning area's travel_options list."""
    return {
        "school_id": school_id,
        "walk_distance_miles": walk_distance_miles,
        "bus_minutes": bus_minutes,
        "has_safe_route": has_safe_route,
    }


def program_placement(school_id, seats, program_type=None):
    """One entry of a scenario's program_placements list."""
    return {
        "program_type": program_type or DEFAULTS["PROGRAM_TYPE"],
        "school_id": school_id,
        "seats": seats,
    }


def create_study_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["STUDY_NAME"],
        "district_name": DEFAULTS["DISTRICT_NAME"],
        "target_school_year": DEFAULTS["TARGET_SCHOOL_YEAR"],
        "horizon_years": DEFAULTS["HORIZON_YEARS"],
        "capacity_target_low_pct": DEFAULTS["CAPACITY_TARGET_LOW_PCT"],
        "capacity_target_high_pct": DEFAULTS["CAPACITY_TARGET_HIGH_PCT"],
        "portables_count_toward_capacity": True,
        "required_program_types": list(DEFAULTS["REQUIRED_PROGRAM_TYPES"]),
    }
    payload.update(overrides)
    return payload


def create_school_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SCHOOL_NAME"],
        "level": DEFAULTS["LEVEL"],
        "core_capacity_seats": DEFAULTS["CORE_CAPACITY_SEATS"],
        "portable_capacity_seats": DEFAULTS["PORTABLE_CAPACITY_SEATS"],
    }
    payload.update(overrides)
    return payload


def create_planning_area_payload(study_id, current_school_id, travel_options, **overrides) -> dict:
    payload = {
        "study_id": study_id,
        "area_code": DEFAULTS["AREA_CODE"],
        "grade_band": DEFAULTS["GRADE_BAND"],
        "current_school_id": current_school_id,
        "resident_student_count": DEFAULTS["RESIDENT_STUDENT_COUNT"],
        "frl_student_count": DEFAULTS["FRL_STUDENT_COUNT"],
        "ell_student_count": DEFAULTS["ELL_STUDENT_COUNT"],
        "median_household_income_usd": DEFAULTS["MEDIAN_HOUSEHOLD_INCOME_USD"],
        "annual_absorption_cap_units": DEFAULTS["ANNUAL_ABSORPTION_CAP_UNITS"],
        "travel_options": travel_options,
    }
    payload.update(overrides)
    return payload


def create_area_adjacency_payload(area_id, neighbor_area_id, **overrides) -> dict:
    payload = {
        "area_id": area_id,
        "neighbor_area_id": neighbor_area_id,
        "shared_boundary_length_ft": DEFAULTS["SHARED_BOUNDARY_LENGTH_FT"],
    }
    payload.update(overrides)
    return payload


def create_housing_development_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DEVELOPMENT_NAME"],
        "unit_type": DEFAULTS["UNIT_TYPE"],
        "total_units": DEFAULTS["TOTAL_UNITS"],
        "first_occupancy_date": DEFAULTS["FIRST_OCCUPANCY_DATE"],
        "buildout_months": DEFAULTS["BUILDOUT_MONTHS"],
    }
    payload.update(overrides)
    return payload


def create_projection_run_payload(expected_study_version, **overrides) -> dict:
    payload = {
        "variant": DEFAULTS["VARIANT"],
        "expected_study_version": expected_study_version,
    }
    payload.update(overrides)
    return payload


def create_scenario_payload(study_id, projection_run_id, program_placements=None, **overrides) -> dict:
    payload = {
        "study_id": study_id,
        "projection_run_id": projection_run_id,
        "name": DEFAULTS["SCENARIO_NAME"],
        "program_placements": program_placements if program_placements is not None else [],
        "impact_variant": DEFAULTS["IMPACT_VARIANT"],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(scenario_id, area_id, assigned_school_id, expected_scenario_version, **overrides) -> dict:
    payload = {
        "scenario_id": scenario_id,
        "area_id": area_id,
        "assigned_school_id": assigned_school_id,
        "expected_scenario_version": expected_scenario_version,
    }
    payload.update(overrides)
    return payload


def create_comment_payload(scenario_id, **overrides) -> dict:
    payload = {"scenario_id": scenario_id, "body": DEFAULTS["COMMENT_BODY"]}
    payload.update(overrides)
    return payload


def create_adoption_payload(study_id, scenario_id, **overrides) -> dict:
    payload = {
        "study_id": study_id,
        "scenario_id": scenario_id,
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "effective_school_year": DEFAULTS["EFFECTIVE_SCHOOL_YEAR"],
        "regime_years": DEFAULTS["REGIME_YEARS"],
        "transfer_deadline_date": DEFAULTS["TRANSFER_DEADLINE_DATE"],
        "transfer_cap_pct": DEFAULTS["TRANSFER_CAP_PCT"],
        "variance_tolerance_pct": DEFAULTS["VARIANCE_TOLERANCE_PCT"],
        "votes_for": DEFAULTS["VOTES_FOR"],
        "votes_against": DEFAULTS["VOTES_AGAINST"],
        "votes_abstain": DEFAULTS["VOTES_ABSTAIN"],
        "board_member_count": DEFAULTS["BOARD_MEMBER_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_phase_in_rule_payload(**overrides) -> dict:
    payload = {
        "rule_type": DEFAULTS["RULE_TYPE"],
        "grade_low": 4,
        "grade_high": 5,
        "sunset_school_year": DEFAULTS["SUNSET_SCHOOL_YEAR"],
    }
    payload.update(overrides)
    return payload


def create_transfer_request_payload(adoption_id, area_id, requested_school_id, **overrides) -> dict:
    payload = {
        "adoption_id": adoption_id,
        "area_id": area_id,
        "requested_school_id": requested_school_id,
        "student_reference": DEFAULTS["STUDENT_REFERENCE"],
        "student_grade": DEFAULTS["STUDENT_GRADE"],
        "reason": DEFAULTS["TRANSFER_REASON"],
    }
    payload.update(overrides)
    return payload


def create_variance_observation_payload(school_id, observed_enrollment, projected_enrollment, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "observed_on": "2027-10-01T00:00:00Z",
        "observed_enrollment": observed_enrollment,
        "projected_enrollment": projected_enrollment,
    }
    payload.update(overrides)
    return payload
