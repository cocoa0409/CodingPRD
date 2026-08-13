"""Payload factories — one per entity, input fields only (PRD section 3)."""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:8].upper()


def create_case_payload(**overrides) -> dict:
    defaults = {
        "case_code": f"ESM-{_suffix()}",
        "utility_district": "D1",
        "county": "King",
        "parcel_id": f"P-{_suffix()}",
        "easement_width_ft": 50,
        "easement_area_sqft": 10000,
        "fair_market_value_per_sqft": 10,
        "acquisition_budget_cents": 50000000,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "doc_kind": "DEED",
        "instrument_number": f"INST-{_suffix()}",
        "recording_date": "2026-07-01T00:00:00Z",
        "grantor_name": "Smith",
        "grantee_name": "CityUtil",
        "gis_polygon_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "width_ft": 50,
    }
    defaults.update(overrides)
    return defaults


def create_encroachment_payload(encroaches_document_id, **overrides) -> dict:
    defaults = {
        "discovered_via": "FIELD_INSPECTION",
        "encroachment_type": "FENCE",
        "encroachment_area_sqft": 100,
        "depth_into_easement_ft": 1,
        "encroaches_document_id": encroaches_document_id,
        "estimated_removal_cost_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "landowner_name": "Jones",
        "landowner_contact": "jones@example.com",
        "offered_area_sqft": 100,
        "severance_damages_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permittee_name": "Permittee",
        "permit_type": "DRIVEWAY",
        "requested_area_sqft": 100,
        "requested_start_date": "2026-09-01T00:00:00Z",
        "requested_end_date": "2027-09-01T00:00:00Z",
        "insurance_certificate_on_file": True,
    }
    defaults.update(overrides)
    return defaults


def create_vegetation_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_label": "North strip 0-200ft",
        "max_allowed_height_ft": 20,
        "prohibited_species": [],
        "wire_zone_width_ft": 25,
        "border_zone_width_ft": 25,
    }
    defaults.update(overrides)
    return defaults


def create_vegetation_violation_payload(**overrides) -> dict:
    defaults = {
        "species": "Oak",
        "observed_height_ft": 30,
        "location_within_zone": "BORDER_ZONE",
    }
    defaults.update(overrides)
    return defaults


def create_title_search_payload(**overrides) -> dict:
    defaults = {"search_scope": "FULL_CHAIN"}
    defaults.update(overrides)
    return defaults


def complete_title_search_payload(**overrides) -> dict:
    defaults = {
        "liens_found": 0,
        "defects_found": 0,
        "chain_of_title_json": {"links": []},
    }
    defaults.update(overrides)
    return defaults


def create_litigation_referral_payload(encroachment_id, **overrides) -> dict:
    defaults = {
        "encroachment_id": encroachment_id,
        "referral_reason": "NEGOTIATION_FAILED",
    }
    defaults.update(overrides)
    return defaults
