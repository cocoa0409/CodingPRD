"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_airport(data: dict):
    _assert_common(data)
    assert isinstance(data["icao_code"], str) and len(data["icao_code"]) == 4
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["current_hazard_level"] in ("LOW", "ELEVATED", "HIGH", "CRITICAL")
    assert isinstance(data["strikes_trailing_12m"], int)
    assert isinstance(data["strikes_trailing_12m_high_risk"], int)
    assert isinstance(data["annual_plan_cycle_year"], int)


def assert_species(data: dict):
    _assert_common(data)
    assert isinstance(data["common_name"], str) and len(data["common_name"]) > 0
    assert data["guild"] in (
        "RAPTOR", "WATERFOWL", "GULL", "SONGBIRD", "BAT", "MAMMAL", "REPTILE", "OTHER",
    )
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["body_mass_g"] > 0


def assert_biologist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["certification_id"], str)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert isinstance(data["is_senior"], bool)
    assert isinstance(data["active"], bool)


def assert_atc_controller(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["facility_id"], str)
    assert is_valid_uuid(data.get("airport_id", ""))


def assert_regulator(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["agency"] in ("USFWS", "USDA_WS", "STATE_DNR")
    assert isinstance(data["badge_number"], str)


def assert_strike_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert is_valid_uuid(data.get("reporter_biologist_id", ""))
    assert is_valid_uuid(data.get("species_id", ""))
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "CONFIRMED", "REJECTED", "AMENDED",
    )
    assert data["damage_class"] in (
        "NONE", "MINOR", "MEDIUM", "SUBSTANTIAL", "DESTROYED", "UNKNOWN",
    )
    assert data["phase_of_flight"] in (
        "TAKEOFF", "CLIMB", "CRUISE", "DESCENT", "APPROACH", "LANDING", "TAXI", "PARKED",
    )
    assert data["altitude_ft_agl"] >= 0
    assert data["strike_count_animals"] >= 1
    assert isinstance(data["carcass_present"], bool)


def assert_carcass_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("strike_report_id", ""))
    assert is_valid_uuid(data.get("species_id_at_collection", ""))
    assert data["identification_status"] in (
        "COLLECTED", "PENDING_ID", "IDENTIFIED", "DISPUTED", "RESOLVED",
    )


def assert_habitat_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert is_valid_uuid(data.get("assessed_by_biologist_id", ""))
    assert data["habitat_feature"] in (
        "STANDING_WATER", "VEGETATION_TALL", "GRASSLAND", "WASTE_SITE",
        "RODENT_PREY_BASE", "NESTING_STRUCTURE", "FOOD_SOURCE", "ROOSTING",
    )
    assert 1 <= data["attractiveness_score"] <= 10
    assert 1 <= data["severity_score"] <= 10
    assert isinstance(data["composite_score"], int)
    assert 1 <= data["composite_score"] <= 100


def assert_mitigation_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("habitat_assessment_id", ""))
    assert data["action_type"] in (
        "DRAINAGE", "MOWING", "FENCING", "HABITAT_REMOVAL", "DETERRENT",
        "EXCLUSION", "PREY_REDUCTION",
    )
    assert data["status"] in (
        "PROPOSED", "APPROVED", "IN_PROGRESS", "VERIFIED", "COMPLETED",
        "REJECTED", "CANCELLED",
    )
    assert is_valid_uuid(data.get("proposed_by_biologist_id", ""))


def assert_dispersal_activity(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert is_valid_uuid(data.get("performed_by_biologist_id", ""))
    assert is_valid_uuid(data.get("species_id", ""))
    assert data["method"] in (
        "PYROTECHNICS", "DISTRESS_CALLS", "VEHICULAR", "LASER", "DOG",
        "FALCONRY", "LETHAL_AMMO",
    )
    assert data["animals_dispersed"] >= 0
    assert data["animals_taken_lethal"] >= 0
    assert data["status"] in ("LOGGED", "REVIEWED", "FLAGGED", "CLOSED")


def assert_take_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert is_valid_uuid(data.get("species_id", ""))
    assert is_valid_uuid(data.get("issued_by_regulator_id", ""))
    assert isinstance(data["permit_number"], str)
    assert data["authorized_take_total"] >= 1
    assert isinstance(data["take_consumed"], int) and data["take_consumed"] >= 0
    assert data["status"] in ("ISSUED", "ACTIVE", "EXHAUSTED", "EXPIRED", "REVOKED", "CLOSED")
    assert isinstance(data["annual_report_submitted"], bool)


def assert_operational_advisory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert is_valid_uuid(data.get("issued_by_biologist_id", ""))
    assert data["hazard_level"] in ("LOW", "ELEVATED", "HIGH", "CRITICAL")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED", "CANCELLED")
    assert data["reason_code"] in (
        "STRIKE_SPIKE", "MIGRATION", "NESTING", "HABITAT_CHANGE", "WEATHER", "OTHER",
    )


def assert_runway_closure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert is_valid_uuid(data.get("requested_by_biologist_id", ""))
    assert data["status"] in (
        "REQUESTED", "AUTHORIZED", "ACTIVE", "RELEASED", "DENIED", "CANCELLED",
    )
    assert data["reason"] in (
        "CARCASS_RECOVERY", "HAZARD_SWEEP", "STRIKE_RESPONSE", "MITIGATION_WORK", "OTHER",
    )


def assert_annual_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("airport_id", ""))
    assert isinstance(data["plan_year"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED_FOR_REVIEW", "RETURNED", "APPROVED", "PUBLISHED", "SUPERSEDED",
    )


def assert_training_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("biologist_id", ""))
    assert isinstance(data["course_code"], str)
    assert data["status"] in ("VALID", "EXPIRING_SOON", "EXPIRED", "REVOKED")
