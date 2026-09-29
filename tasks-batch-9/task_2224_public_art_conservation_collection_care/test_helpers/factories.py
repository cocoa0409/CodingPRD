"""Payload factories — one per entity, request-input fields only."""

from .constants import TEST_DEFAULTS


def artist_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["ARTIST_NAME"],
        "is_living": True,
        "contact_email": TEST_DEFAULTS["ARTIST_EMAIL"],
    }
    payload.update(overrides)
    return payload


def site_payload(**overrides) -> dict:
    payload = {
        "site_code": TEST_DEFAULTS["SITE_CODE"],
        "name": TEST_DEFAULTS["SITE_NAME"],
        "address_ref": TEST_DEFAULTS["SITE_ADDRESS"],
        "exposure_class": "URBAN",
        "capacity_units": 20,
        "concurrent_work_capacity": 1,
    }
    payload.update(overrides)
    return payload


def artwork_payload(artist_id: str, site_id: str, **overrides) -> dict:
    payload = {
        "accession_number": TEST_DEFAULTS["ACCESSION_NUMBER"],
        "title": TEST_DEFAULTS["ARTWORK_TITLE"],
        "artist_id": artist_id,
        "site_id": site_id,
        "material_class": "BRONZE",
        "significance_tier": "LANDMARK",
        "footprint_units": TEST_DEFAULTS["FOOTPRINT_UNITS"],
        "insured_value_cents": TEST_DEFAULTS["INSURED_VALUE_CENTS"],
        "acquisition_date": TEST_DEFAULTS["ACQUISITION_DATE"],
        "acquisition_document_ref": TEST_DEFAULTS["ACQUISITION_DOCUMENT_REF"],
        "recognized_stature": False,
    }
    payload.update(overrides)
    return payload


def maintenance_protocol_payload(**overrides) -> dict:
    payload = {
        "protocol_code": TEST_DEFAULTS["PROTOCOL_CODE"],
        "material_class": "BRONZE",
        "method": "WASH",
        "cycle_days": TEST_DEFAULTS["PROTOCOL_CYCLE_DAYS"],
        "requires_conservator": False,
    }
    payload.update(overrides)
    return payload


def conservator_payload(**overrides) -> dict:
    payload = {
        "firm_name": TEST_DEFAULTS["CONSERVATOR_FIRM"],
        "accreditation": "AIC_PA",
        "material_specialties": ["BRONZE", "STONE"],
        "hourly_rate_cents": TEST_DEFAULTS["CONSERVATOR_HOURLY_RATE_CENTS"],
        "insurance_expires_on": TEST_DEFAULTS["CONSERVATOR_INSURANCE_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def condition_assessment_payload(artwork_id: str, **overrides) -> dict:
    payload = {
        "artwork_id": artwork_id,
        "cycle_year": 2026,
        "assessed_on": "2026-08-01",
        "surface_score": 3,
        "structural_score": 2,
        "coating_score": 2,
        "mount_score": 1,
        "graffiti_score": 2,
    }
    payload.update(overrides)
    return payload


def assessment_photo_payload(view_code: str = "FRONT", **overrides) -> dict:
    payload = {
        "view_code": view_code,
        "media_ref": f"media/2024.001/{view_code.lower()}.jpg",
    }
    payload.update(overrides)
    return payload


def maintenance_visit_payload(artwork_id: str, protocol_id: str, **overrides) -> dict:
    payload = {
        "artwork_id": artwork_id,
        "protocol_id": protocol_id,
        "window_start": "2026-08-10T08:00:00Z",
        "window_end": "2026-08-12T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def treatment_proposal_payload(
    artwork_id: str,
    conservator_id: str,
    assessment_id: str,
    expected_artwork_version: int,
    **overrides,
) -> dict:
    payload = {
        "artwork_id": artwork_id,
        "conservator_id": conservator_id,
        "assessment_id": assessment_id,
        "treatment_scope": "COATING",
        "engagement_start": "2026-09-01T00:00:00Z",
        "engagement_end": "2026-09-05T00:00:00Z",
        "expected_artwork_version": expected_artwork_version,
        "alters_appearance": False,
    }
    payload.update(overrides)
    return payload


def line_item_payload(**overrides) -> dict:
    payload = {
        "labor_hours": 12.5,
        "complexity_class": "COATING",
        "materials_cents": 82_500,
        "description": "recoat and wax",
    }
    payload.update(overrides)
    return payload


def artist_consultation_payload(artwork_id: str, artist_id: str, **overrides) -> dict:
    payload = {
        "artwork_id": artwork_id,
        "artist_id": artist_id,
        "subject": "TREATMENT",
    }
    payload.update(overrides)
    return payload


def moral_rights_notice_payload(artwork_id: str, artist_id: str, **overrides) -> dict:
    payload = {
        "artwork_id": artwork_id,
        "artist_id": artist_id,
        "action_type": "RELOCATION",
    }
    payload.update(overrides)
    return payload


def deaccession_case_payload(artwork_id: str, **overrides) -> dict:
    payload = {
        "artwork_id": artwork_id,
        "criteria": ["DETERIORATION_BEYOND_REPAIR"],
        "disposition": "TRANSFER",
        "disposition_target_ref": "State Museum of Art",
        "comment_days": 45,
    }
    payload.update(overrides)
    return payload


def funding_pool_payload(**overrides) -> dict:
    payload = {
        "pool_code": TEST_DEFAULTS["POOL_CODE"],
        "pool_type": "ENDOWMENT",
        "fiscal_year": 2026,
        "principal_cents": TEST_DEFAULTS["POOL_PRINCIPAL_CENTS"],
        "draw_rate_bps": TEST_DEFAULTS["POOL_DRAW_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def funding_allocation_payload(
    pool_id: str, expected_pool_version: int, **overrides
) -> dict:
    payload = {
        "pool_id": pool_id,
        "purpose": "TREATMENT",
        "amount_cents": TEST_DEFAULTS["TREATMENT_ALLOCATION_CENTS"],
        "expected_pool_version": expected_pool_version,
    }
    payload.update(overrides)
    return payload


def damage_incident_payload(artwork_id: str, **overrides) -> dict:
    payload = {
        "artwork_id": artwork_id,
        "incident_type": "VANDALISM",
        "damage_extent_pct": 0.35,
        "narrative": "Gouging and paint loss on torso",
    }
    payload.update(overrides)
    return payload
