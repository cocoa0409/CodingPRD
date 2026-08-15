"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "AIRPORT_NAME": "Test Airport",
    "PLAN_CYCLE_YEAR": 2026,
    "BODY_MASS_G": 500,
    "STRIKE_AT": "2026-07-15T10:00:00Z",
    "RUNWAY": "09L",
    "AIRCRAFT_REGISTRATION": "N100TST",
    "PERMIT_VALID_FROM": "2026-01-01",
    "PERMIT_VALID_TO": "2026-12-31",
    "ADVISORY_FROM": "2026-08-01T00:00:00Z",
    "ADVISORY_TO": "2026-09-01T00:00:00Z",
}


def create_airport_payload(**overrides) -> dict:
    defaults = {
        "icao_code": "KTST",
        "name": DEFAULTS["AIRPORT_NAME"],
        "annual_plan_cycle_year": DEFAULTS["PLAN_CYCLE_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_species_payload(**overrides) -> dict:
    defaults = {
        "common_name": "Test Sparrow",
        "scientific_name": "Passer testus",
        "guild": "SONGBIRD",
        "risk_tier": "LOW",
        "body_mass_g": DEFAULTS["BODY_MASS_G"],
        "is_protected_federally": False,
    }
    defaults.update(overrides)
    return defaults


def create_biologist_payload(airport_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Biologist",
        "certification_id": "CERT-0001",
        "airport_id": airport_id,
        "is_senior": False,
    }
    defaults.update(overrides)
    return defaults


def create_atc_controller_payload(airport_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Controller",
        "facility_id": "TWR-TST",
        "airport_id": airport_id,
    }
    defaults.update(overrides)
    return defaults


def create_regulator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Regulator",
        "agency": "USFWS",
        "badge_number": "USFWS-0001",
    }
    defaults.update(overrides)
    return defaults


def create_strike_report_payload(airport_id: str, reporter_biologist_id: str,
                                 species_id: str, **overrides) -> dict:
    defaults = {
        "airport_id": airport_id,
        "reporter_biologist_id": reporter_biologist_id,
        "strike_at": DEFAULTS["STRIKE_AT"],
        "runway_designator": DEFAULTS["RUNWAY"],
        "aircraft_registration": DEFAULTS["AIRCRAFT_REGISTRATION"],
        "species_id": species_id,
        "damage_class": "NONE",
        "phase_of_flight": "LANDING",
        "altitude_ft_agl": 50,
        "strike_count_animals": 1,
        "carcass_present": False,
    }
    defaults.update(overrides)
    return defaults


def create_carcass_record_payload(species_id_at_collection: str, **overrides) -> dict:
    defaults = {
        "species_id_at_collection": species_id_at_collection,
        "identification_method": "VISUAL",
        "disposal_method": "INCINERATED",
    }
    defaults.update(overrides)
    return defaults


def create_habitat_assessment_payload(airport_id: str, biologist_id: str, **overrides) -> dict:
    defaults = {
        "airport_id": airport_id,
        "assessed_by_biologist_id": biologist_id,
        "assessed_at": "2026-07-15T10:00:00Z",
        "habitat_feature": "STANDING_WATER",
        "attractiveness_score": 5,
        "severity_score": 5,
    }
    defaults.update(overrides)
    return defaults


def create_mitigation_action_payload(proposed_by_biologist_id: str, **overrides) -> dict:
    defaults = {
        "action_type": "DRAINAGE",
        "proposed_by_biologist_id": proposed_by_biologist_id,
        "target_completion_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_dispersal_activity_payload(airport_id: str, performed_by_biologist_id: str,
                                      species_id: str, **overrides) -> dict:
    defaults = {
        "airport_id": airport_id,
        "performed_by_biologist_id": performed_by_biologist_id,
        "performed_at": "2026-07-15T10:00:00Z",
        "method": "PYROTECHNICS",
        "species_id": species_id,
        "animals_dispersed": 5,
        "animals_taken_lethal": 0,
    }
    defaults.update(overrides)
    return defaults


def create_take_permit_payload(airport_id: str, species_id: str,
                               issued_by_regulator_id: str, **overrides) -> dict:
    defaults = {
        "airport_id": airport_id,
        "species_id": species_id,
        "issued_by_regulator_id": issued_by_regulator_id,
        "permit_number": "MB000000-00",
        "authorized_take_total": 10,
        "valid_from": DEFAULTS["PERMIT_VALID_FROM"],
        "valid_to": DEFAULTS["PERMIT_VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_advisory_payload(airport_id: str, issued_by_biologist_id: str, **overrides) -> dict:
    defaults = {
        "airport_id": airport_id,
        "issued_by_biologist_id": issued_by_biologist_id,
        "issued_at": "2026-07-15T10:00:00Z",
        "effective_from": DEFAULTS["ADVISORY_FROM"],
        "effective_to": DEFAULTS["ADVISORY_TO"],
        "hazard_level": "ELEVATED",
        "reason_code": "OTHER",
    }
    defaults.update(overrides)
    return defaults


def create_runway_closure_payload(airport_id: str, requested_by_biologist_id: str,
                                  **overrides) -> dict:
    defaults = {
        "airport_id": airport_id,
        "runway_designator": DEFAULTS["RUNWAY"],
        "requested_by_biologist_id": requested_by_biologist_id,
        "closure_start": "2026-08-01T09:00:00Z",
        "closure_end": "2026-08-01T10:00:00Z",
        "reason": "HAZARD_SWEEP",
    }
    defaults.update(overrides)
    return defaults


def create_annual_plan_payload(airport_id: str, **overrides) -> dict:
    defaults = {
        "airport_id": airport_id,
        "plan_year": 2027,
        "version_note": "v1",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(biologist_id: str, **overrides) -> dict:
    defaults = {
        "biologist_id": biologist_id,
        "course_code": "WHA-101",
        "completed_at": "2026-01-01",
        "expires_at": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults
