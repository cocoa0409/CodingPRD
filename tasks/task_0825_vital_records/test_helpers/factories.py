"""Payload factories — one per entity, input fields only (Vital Records PRD §3)."""

DEFAULTS = {
    "EVENT_DATE": "2026-02-25T00:00:00Z",
    "DEATH_EVENT_DATE": "2026-03-01T00:00:00Z",
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "General Hospital",
        "facility_type": "HOSPITAL",
        "jurisdiction_code": "CTY-01",
        "npi": "NPI-0001",
    }
    defaults.update(overrides)
    return defaults


def create_certifier_payload(**overrides) -> dict:
    defaults = {
        "name": "Dr Certifier",
        "certifier_type": "PHYSICIAN",
        "license_number": "LIC-0001",
        "jurisdiction_code": "CTY-01",
    }
    defaults.update(overrides)
    return defaults


def create_vital_event_payload(facility_id, **overrides) -> dict:
    defaults = {
        "event_type": "BIRTH",
        "event_date": DEFAULTS["EVENT_DATE"],
        "subject_last_name": "Roe",
        "subject_first_name": "Baby",
        "sex": "FEMALE",
        "jurisdiction_code": "CTY-01",
        "facility_id": facility_id,
        "place_of_event": "General Hospital",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(vital_event_id, certifier_id, **overrides) -> dict:
    defaults = {
        "vital_event_id": vital_event_id,
        "certifier_id": certifier_id,
        "cause_of_death": "Myocardial infarction",
        "manner_of_death": "NATURAL",
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(vital_event_id, **overrides) -> dict:
    defaults = {
        "vital_event_id": vital_event_id,
        "amendment_type": "DEMOGRAPHIC",
        "field_name": "subject_last_name",
        "new_value": "Corrected",
        "reason": "typo",
    }
    defaults.update(overrides)
    return defaults


def create_paternity_payload(vital_event_id, **overrides) -> dict:
    defaults = {
        "vital_event_id": vital_event_id,
        "father_last_name": "Vale",
        "father_first_name": "Max",
        "mother_consent": True,
    }
    defaults.update(overrides)
    return defaults


def create_copy_request_payload(vital_event_id, **overrides) -> dict:
    defaults = {
        "vital_event_id": vital_event_id,
        "requester_name": "Requester",
        "requester_relationship": "SELF",
        "id_document_type": "DRIVERS_LICENSE",
        "copy_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_apostille_payload(certified_copy_request_id, **overrides) -> dict:
    defaults = {
        "certified_copy_request_id": certified_copy_request_id,
        "destination_country": "FR",
        "apostille_type": "APOSTILLE",
    }
    defaults.update(overrides)
    return defaults


def create_packet_payload(vital_event_id, **overrides) -> dict:
    defaults = {
        "vital_event_id": vital_event_id,
        "packet_type": "DELAYED",
        "documentary_evidence_count": 2,
        "hearing_start": "2026-03-10T09:00:00Z",
        "hearing_end": "2026-03-10T10:00:00Z",
        "hearing_jurisdiction_code": "HRG-01",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction_code": "CTY-01",
        "period_start": "2026-02-01T00:00:00Z",
        "period_end": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
