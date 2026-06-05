"""Payload factories — one per entity, input fields only."""
import itertools

_vin_counter = itertools.count(1)


def unique_vin() -> str:
    """Generate a unique 17-character VIN for test isolation."""
    n = next(_vin_counter)
    base = "1HGCM82633A"  # 11 chars
    return f"{base}{n:06d}"  # 11 + 6 = 17 chars


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Owner",
        "residence_county_code": "KING",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(owner_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "vin": unique_vin(),
        "model_year": 2024,
        "purchase_price_cents": 3000000,
        "msrp_cents": 3200000,
        "vehicle_class": "PASSENGER",
    }
    defaults.update(overrides)
    return defaults


def create_vin_verification_payload(vehicle_id, submitted_vin, outcome="MATCH", **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "submitted_vin": submitted_vin,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def create_title_application_payload(vehicle_id, applicant_owner_id, application_type="INITIAL", **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "applicant_owner_id": applicant_owner_id,
        "application_type": application_type,
    }
    defaults.update(overrides)
    return defaults


def create_salvage_inspection_payload(title_application_id, result="PASS", **overrides) -> dict:
    defaults = {
        "title_application_id": title_application_id,
        "result": result,
    }
    defaults.update(overrides)
    return defaults


def create_emissions_inspection_payload(vehicle_id, result="PASS", **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "result": result,
    }
    defaults.update(overrides)
    return defaults


def create_lien_payload(vehicle_id, lien_holder_name="Test Bank", principal_cents=1000000, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "lien_holder_name": lien_holder_name,
        "principal_cents": principal_cents,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(vehicle_id, owner_id, registration_type="INITIAL", **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "owner_id": owner_id,
        "registration_type": registration_type,
    }
    defaults.update(overrides)
    return defaults


def create_fee_assessment_payload(registration_id, **overrides) -> dict:
    defaults = {"registration_id": registration_id}
    defaults.update(overrides)
    return defaults


def create_license_plate_payload(registration_id, plate_number, plate_type, expected_registration_version, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "plate_number": plate_number,
        "plate_type": plate_type,
        "expected_registration_version": expected_registration_version,
    }
    defaults.update(overrides)
    return defaults


def create_real_id_application_payload(owner_id, documents_complete=False, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "documents_complete": documents_complete,
    }
    defaults.update(overrides)
    return defaults
