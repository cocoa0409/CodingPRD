"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "BASE_NAME": "Base Alpha",
    "REGION": "SW-US",
    "TAIL_NUMBER": "N100AA",
    "AIRCRAFT_CLASS": "ROTOR_WING",
    "MEDICAL_CONFIG": "CCT_CAPABLE",
    "PATIENT_DOB": "1980-04-12",
    "PATIENT_WEIGHT_KG": 80,
    "ONSET_ISO": "2026-07-31T14:00:00Z",
    "PLANNED_LAUNCH_ISO": "2026-08-01T06:00:00Z",
    "HOLD_UNTIL_ISO": "2026-08-01T18:00:00Z",
    "GROUND_PICKUP_ISO": "2026-08-01T09:00:00Z",
}


def create_base_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["BASE_NAME"], "region": DEFAULTS["REGION"]}
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "base_id": None,
        "tail_number": DEFAULTS["TAIL_NUMBER"],
        "aircraft_class": DEFAULTS["AIRCRAFT_CLASS"],
        "medical_config": DEFAULTS["MEDICAL_CONFIG"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "base_id": None,
        "full_name": "Pat Pilot",
        "crew_role": "PILOT",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_crew_shift_payload(**overrides) -> dict:
    defaults = {
        "crew_member_id": None,
        "planned_start_iso": "2026-08-01T00:00:00Z",
        "planned_end_iso": "2026-08-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Paul Patient",
        "date_of_birth": DEFAULTS["PATIENT_DOB"],
        "weight_kg": DEFAULTS["PATIENT_WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "tier": "STANDARD",
        "effective_from": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_mission_request_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "transport_class": "EMERGENCY_INTERFACILITY",
        "origin_facility": "St Mary",
        "destination_facility": "County General",
        "reported_cardio": 8,
        "reported_resp": 6,
        "reported_neuro": 5,
        "reported_interventions": 3,
        "onset_iso": DEFAULTS["ONSET_ISO"],
    }
    defaults.update(overrides)
    return defaults


def create_triage_payload(**overrides) -> dict:
    defaults = {
        "verified_cardio": 8,
        "verified_resp": 6,
        "verified_neuro": 5,
        "verified_interventions": 3,
    }
    defaults.update(overrides)
    return defaults


def create_accept_payload(**overrides) -> dict:
    defaults = {
        "aircraft_id": None,
        "crew": [],
        "estimated_loaded_miles": 40,
        "planned_launch_iso": DEFAULTS["PLANNED_LAUNCH_ISO"],
        "planned_duration_min": 120,
    }
    defaults.update(overrides)
    return defaults


def create_weather_assessment_payload(**overrides) -> dict:
    defaults = {
        "mission_id": None,
        "ceiling_ft": 1000,
        "visibility_sm": 5.0,
        "wind_kt": 10,
        "precip": "NONE",
        "day_night": "DAY",
        "terrain": "FLAT",
        "expected_mission_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_ground_leg_payload(**overrides) -> dict:
    defaults = {
        "mission_id": None,
        "leg_type": "DESTINATION",
        "provider_name": "City EMS",
        "scheduled_pickup_iso": DEFAULTS["GROUND_PICKUP_ISO"],
    }
    defaults.update(overrides)
    return defaults


def create_bed_reservation_payload(**overrides) -> dict:
    defaults = {
        "mission_id": None,
        "facility_name": "County General",
        "bed_type": "ICU",
        "hold_until_iso": DEFAULTS["HOLD_UNTIL_ISO"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_authorization_payload(**overrides) -> dict:
    defaults = {
        "mission_id": None,
        "payer_name": "Acme Health",
        "policy_number": "POL-1",
    }
    defaults.update(overrides)
    return defaults


def create_repatriation_case_payload(**overrides) -> dict:
    defaults = {
        "mission_id": None,
        "destination_country": "MX",
        "receiving_facility": "County General",
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    """Repatriation document entry. expires_iso is optional; pass
    expires_iso=None to omit it (FIT_TO_FLY and CUSTOMS_PRECLEARANCE carry
    none in practice)."""
    defaults = {
        "doc_type": "PASSPORT",
        "document_number": "P123",
        "issued_iso": "2020-01-01T00:00:00Z",
        "expires_iso": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_pcr_payload(**overrides) -> dict:
    defaults = {
        "mission_id": None,
        "author_crew_id": None,
        "vitals_summary": "stable",
        "interventions_summary": "none",
        "meds_summary": "none",
    }
    defaults.update(overrides)
    return defaults
