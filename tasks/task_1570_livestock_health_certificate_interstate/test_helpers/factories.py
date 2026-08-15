"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "PREMISES_NAME": "Test Ranch",
    "COUNTY": "Yolo",
    "STATE_CODE": "CA",
    "SPECIES": "CATTLE",
    "INITIAL_HEAD_COUNT": 30,
    "VET_NAME": "Dr. Ada",
    "VET_ACCREDITATION_NUMBER": "ACCRED-1",
    "VET_EXPIRES": "2027-01-01T00:00:00Z",
    "DESTINATION_STATE": "KS",
    "TEST_TYPE": "BRUCELLOSIS",
    "TEST_VALIDITY_DAYS": 30,
    "EFFECTIVE_FROM": "2026-06-01T00:00:00Z",
    "TEST_DATE": "2026-07-12T00:00:00Z",
    "LAB_REFERENCE": "LAB-1",
    "INSPECTION_DATE": "2026-08-10T00:00:00Z",
    "VACCINATION_DATE": "2026-07-12T00:00:00Z",
    "CERT_HEAD_COUNT": 10,
    "PERMIT_VALID_FROM": "2026-08-11T00:00:00Z",
    "PERMIT_VALID_UNTIL": "2026-09-08T00:00:00Z",
    "SHIP_DATE": "2026-08-21T00:00:00Z",
    "DESTINATION_NAME": "KS Feedlot",
    "ZONE_DISEASE": "VESICULAR_STOMATITIS",
    "ZONE_SEVERITY": "HIGH",
    "ZONE_EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
}


def create_premises_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PREMISES_NAME"],
        "county": DEFAULTS["COUNTY"],
        "state_code": DEFAULTS["STATE_CODE"],
        "species_code": DEFAULTS["SPECIES"],
        "initial_head_count": DEFAULTS["INITIAL_HEAD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_veterinarian_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["VET_NAME"],
        "accreditation_number": DEFAULTS["VET_ACCREDITATION_NUMBER"],
        "accreditation_expires_at": DEFAULTS["VET_EXPIRES"],
    }
    defaults.update(overrides)
    return defaults


def create_entry_requirement_payload(**overrides) -> dict:
    defaults = {
        "destination_state_code": DEFAULTS["DESTINATION_STATE"],
        "species_code": DEFAULTS["SPECIES"],
        "test_type": DEFAULTS["TEST_TYPE"],
        "test_validity_days": DEFAULTS["TEST_VALIDITY_DAYS"],
        "vaccination_required": True,
        "vaccination_min_days_before_inspection": 14,
        "permit_required": True,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_none_entry_requirement_payload(**overrides) -> dict:
    """Matrix row with test_type NONE and no vaccination requirement — the
    lightweight row used when the test/vaccination battery is not under test."""
    defaults = {
        "destination_state_code": DEFAULTS["DESTINATION_STATE"],
        "species_code": DEFAULTS["SPECIES"],
        "test_type": "NONE",
        "test_validity_days": DEFAULTS["TEST_VALIDITY_DAYS"],
        "vaccination_required": False,
        "permit_required": True,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_test_record_payload(**overrides) -> dict:
    defaults = {
        "species_code": DEFAULTS["SPECIES"],
        "test_type": DEFAULTS["TEST_TYPE"],
        "test_date": DEFAULTS["TEST_DATE"],
        "lab_reference": DEFAULTS["LAB_REFERENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "destination_state_code": DEFAULTS["DESTINATION_STATE"],
        "species_code": DEFAULTS["SPECIES"],
        "head_count": DEFAULTS["CERT_HEAD_COUNT"],
        "inspection_date": DEFAULTS["INSPECTION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_movement_permit_payload(**overrides) -> dict:
    defaults = {
        "allocated_head_count": DEFAULTS["CERT_HEAD_COUNT"],
        "valid_from": DEFAULTS["PERMIT_VALID_FROM"],
        "valid_until": DEFAULTS["PERMIT_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_movement_record_payload(**overrides) -> dict:
    defaults = {
        "head_count": 5,
        "destination_name": DEFAULTS["DESTINATION_NAME"],
        "planned_ship_date": DEFAULTS["SHIP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_outbreak_zone_payload(**overrides) -> dict:
    defaults = {
        "county": DEFAULTS["COUNTY"],
        "state_code": DEFAULTS["STATE_CODE"],
        "disease_code": DEFAULTS["ZONE_DISEASE"],
        "species_code": DEFAULTS["SPECIES"],
        "severity": DEFAULTS["ZONE_SEVERITY"],
        "effective_from": DEFAULTS["ZONE_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_quarantine_order_payload(**overrides) -> dict:
    defaults = {
        "species_code": DEFAULTS["SPECIES"],
        "disease_code": "BRUCELLOSIS",
        "start_at": "2026-08-10T00:00:00Z",
        "end_at": "2026-08-24T00:00:00Z",
        "reason": "TRACE_EXPOSURE",
    }
    defaults.update(overrides)
    return defaults
