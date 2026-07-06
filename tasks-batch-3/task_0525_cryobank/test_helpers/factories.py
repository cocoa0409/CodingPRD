"""Payload factories — one per entity, input fields only."""


def create_donor_payload(**overrides) -> dict:
    defaults = {
        "display_code": "D-TEST",
        "full_name": "Test Donor",
        "donor_type": "SPERM",
        "blood_type": "O_POS",
        "family_limit": 10,
    }
    defaults.update(overrides)
    return defaults


def create_screening_application_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "fda_risk_flag": False,
        "genetic_carrier_count": 0,
        "partner_screening_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_specimen_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": 5,
        "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": True,
    }
    defaults.update(overrides)
    return defaults


def create_recipient_payload(**overrides) -> dict:
    defaults = {
        "family_name": "Test Family",
        "contact_email": "test@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_recipient_consent_payload(**overrides) -> dict:
    defaults = {
        "recipient_id": None,
        "donor_id": None,
        "acknowledges_open_id": True,
    }
    defaults.update(overrides)
    return defaults


def create_vial_reservation_payload(**overrides) -> dict:
    defaults = {
        "recipient_id": None,
        "inventory_id": None,
        "vial_count": 1,
        "expected_inventory_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "reservation_id": None,
        "clinic_address": "1 Clinic Way",
        "ln2_dewar_serial": "DS-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_sibling_registry_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "recipient_id": None,
        "birth_reported_date": "2026-06-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_collection_appointment_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "room_code": "ROOM-A",
        "window_start": "2026-05-02T09:00:00Z",
        "window_end": "2026-05-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_dewar_maintenance_window_payload(**overrides) -> dict:
    defaults = {
        "dewar_code": "TANK-1",
        "service_start": "2026-05-03T00:00:00Z",
        "service_end": "2026-05-03T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_report_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "report_type": "FDA_ANNUAL",
        "as_of": "2026-06-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
