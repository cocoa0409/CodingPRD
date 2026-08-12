"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def strip_omitted(payload: dict) -> dict:
    """Drop keys an override explicitly set to None — the field is simply omitted."""
    return {k: v for k, v in payload.items() if v is not None}


def create_catalog_item_payload(**overrides) -> dict:
    defaults = {
        "nationality_code": TEST_DEFAULTS["NATIONALITY_CODE"],
        "destination_country": TEST_DEFAULTS["DESTINATION_COUNTRY"],
        "visa_type": "TOURIST",
        "government_fee_cents": TEST_DEFAULTS["GOVERNMENT_FEE_CENTS"],
        "government_fee_basis": "PER_APPLICANT",
        "base_service_fee_cents": TEST_DEFAULTS["BASE_SERVICE_FEE_CENTS"],
        "form_code": TEST_DEFAULTS["FORM_CODE"],
        "requires_appointment": False,
    }
    defaults.update(overrides)
    return strip_omitted(defaults)


def create_document_requirement_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "PASSPORT_BOOK",
        "is_required": True,
        "validity_rule": "VALID_BEYOND_RETURN_MONTHS",
        "validity_param": 6,
    }
    defaults.update(overrides)
    return strip_omitted(defaults)


def create_agency_form_payload(**overrides) -> dict:
    defaults = {
        "form_code": TEST_DEFAULTS["FORM_CODE"],
        "revision": 1,
        "required_field_count": TEST_DEFAULTS["REQUIRED_FIELD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_consulate_payload(**overrides) -> dict:
    defaults = {
        "name": "IN Consulate West",
        "destination_country": TEST_DEFAULTS["DESTINATION_COUNTRY"],
        "jurisdiction_region_codes": ["CA", "NV"],
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(**overrides) -> dict:
    defaults = {"starts_at": "2026-06-05T10:00:00Z", "capacity": 1}
    defaults.update(overrides)
    return defaults


def create_order_payload(catalog_item_id: str, **overrides) -> dict:
    defaults = {
        "catalog_item_id": catalog_item_id,
        "travel_date": TEST_DEFAULTS["TRAVEL_DATE"],
        "return_date": TEST_DEFAULTS["RETURN_DATE"],
        "delivery_region_code": TEST_DEFAULTS["DELIVERY_REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Traveller",
        "date_of_birth": "1990-03-04",
        "nationality_code": TEST_DEFAULTS["NATIONALITY_CODE"],
        "residence_region_code": TEST_DEFAULTS["RESIDENCE_REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def submit_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "PASSPORT_BOOK",
        "issue_date": "2020-01-15",
        "expiry_date": "2030-01-15",
    }
    defaults.update(overrides)
    return strip_omitted(defaults)


def upload_photo_payload(**overrides) -> dict:
    defaults = {
        "taken_on": "2026-05-20",
        "head_height_ratio": 0.60,
        "background_code": "WHITE",
        "resolution_px": 800,
    }
    defaults.update(overrides)
    return strip_omitted(defaults)


def create_courier_leg_payload(**overrides) -> dict:
    defaults = {
        "leg_index": 1,
        "from_holder": "APPLICANT",
        "to_holder": "SERVICE",
        "scheduled_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {"method": "GROUND", "address_region_code": "CA"}
    defaults.update(overrides)
    return defaults
