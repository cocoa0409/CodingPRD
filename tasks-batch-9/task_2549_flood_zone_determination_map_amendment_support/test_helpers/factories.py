"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMMUNITY_ID_CODE": "125129",
    "COMMUNITY_NAME": "Coastal County FL",
    "STATE_CODE": "FL",
    "LENDER_NAME": "First Coastal Bank",
    "LENDER_EMAIL": "ops@firstcoastal.example",
    "MAP_PANEL_NUMBER": "12086C0312K",
    "PANEL_ZONE_CODE": "AE",
    "PANEL_BFE_FT": 7.75,
    "PANEL_EFFECTIVE_DATE": "2020-06-05T00:00:00Z",
    "STREET_ADDRESS": "11 Bayfront Rd",
    "CITY": "Miami",
    "POSTAL_CODE": "33101",
    "LATITUDE": 25.761700,
    "LONGITUDE": -80.191800,
    "STRUCTURE_LABEL": "Main dwelling",
    "OCCUPANCY_TYPE": "SINGLE_FAMILY",
    "FOUNDATION_TYPE": "SLAB",
    "REPLACEMENT_COST_CENTS": 32_000_000,
    "SFHA_OFFSET_FT": -12.0,
    "LOAN_NUMBER": "LN-4401",
    "BORROWER_USER_ID": "borrower-a",
    "PRINCIPAL_BALANCE_CENTS": 28_000_000,
    "POLICY_ANNIVERSARY_DATE": "2027-03-15T00:00:00Z",
    "ESCROW_BALANCE_CENTS": 500_000,
    "SURVEYOR_LICENSE_NUMBER": "FL-PSM-8841",
    "SURVEY_DATE": "2026-07-01T00:00:00Z",
    "RAW_LOWEST_FLOOR_ELEVATION_FT": 8.94,
    "RAW_LOWEST_ADJACENT_GRADE_FT": 8.90,
    "MACHINERY_ELEVATION_FT": 9.50,
    "ANNUAL_PREMIUM_RATE_CENTS": 288_000,
    "BORROWER_STATEMENT": "The dwelling sits on the ridge, outside the mapped floodway.",
}


def create_community_payload(**overrides) -> dict:
    payload = {
        "community_id_code": DEFAULTS["COMMUNITY_ID_CODE"],
        "name": DEFAULTS["COMMUNITY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_lender_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["LENDER_NAME"],
        "contact_email": DEFAULTS["LENDER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_map_panel_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "map_panel_number": DEFAULTS["MAP_PANEL_NUMBER"],
        "revision_sequence": 1,
        "zone_code": DEFAULTS["PANEL_ZONE_CODE"],
        "base_flood_elevation_ft": DEFAULTS["PANEL_BFE_FT"],
        "effective_date": DEFAULTS["PANEL_EFFECTIVE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "street_address": DEFAULTS["STREET_ADDRESS"],
        "city": DEFAULTS["CITY"],
        "postal_code": DEFAULTS["POSTAL_CODE"],
        "map_panel_number": DEFAULTS["MAP_PANEL_NUMBER"],
        "latitude": DEFAULTS["LATITUDE"],
        "longitude": DEFAULTS["LONGITUDE"],
        "geocode_method": "ROOFTOP",
        "geocode_confidence_score": 0.95,
    }
    payload.update(overrides)
    return payload


def create_structure_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "structure_label": DEFAULTS["STRUCTURE_LABEL"],
        "occupancy_type": DEFAULTS["OCCUPANCY_TYPE"],
        "foundation_type": DEFAULTS["FOUNDATION_TYPE"],
        "replacement_cost_cents": DEFAULTS["REPLACEMENT_COST_CENTS"],
        "sfha_offset_ft": DEFAULTS["SFHA_OFFSET_FT"],
    }
    payload.update(overrides)
    return payload


def create_loan_folio_payload(lender_id, property_id, **overrides) -> dict:
    payload = {
        "lender_id": lender_id,
        "property_id": property_id,
        "loan_number": DEFAULTS["LOAN_NUMBER"],
        "borrower_user_id": DEFAULTS["BORROWER_USER_ID"],
        "principal_balance_cents": DEFAULTS["PRINCIPAL_BALANCE_CENTS"],
        "policy_anniversary_date": DEFAULTS["POLICY_ANNIVERSARY_DATE"],
        "escrow_balance_cents": DEFAULTS["ESCROW_BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_determination_payload(loan_folio_id, structure_id, expected_loan_folio_version,
                                 determination_type="ORIGINATION", **overrides) -> dict:
    payload = {
        "loan_folio_id": loan_folio_id,
        "structure_id": structure_id,
        "determination_type": determination_type,
        "expected_loan_folio_version": expected_loan_folio_version,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(determination_id, **overrides) -> dict:
    payload = {
        "determination_id": determination_id,
        "basis": "STRUCTURE_LOCATION",
        "borrower_statement": DEFAULTS["BORROWER_STATEMENT"],
        "asserted_sfha_offset_ft": 30.0,
    }
    payload.update(overrides)
    return payload


def create_elevation_certificate_payload(structure_id, **overrides) -> dict:
    payload = {
        "structure_id": structure_id,
        "surveyor_license_number": DEFAULTS["SURVEYOR_LICENSE_NUMBER"],
        "survey_date": DEFAULTS["SURVEY_DATE"],
        "datum": "NGVD29",
        "raw_lowest_floor_elevation_ft": DEFAULTS["RAW_LOWEST_FLOOR_ELEVATION_FT"],
        "raw_lowest_adjacent_grade_ft": DEFAULTS["RAW_LOWEST_ADJACENT_GRADE_FT"],
        "machinery_elevation_ft": DEFAULTS["MACHINERY_ELEVATION_FT"],
    }
    payload.update(overrides)
    return payload


def create_map_amendment_request_payload(determination_id, elevation_certificate_id,
                                         request_type="LOMA", **overrides) -> dict:
    payload = {
        "determination_id": determination_id,
        "elevation_certificate_id": elevation_certificate_id,
        "request_type": request_type,
    }
    payload.update(overrides)
    return payload


def create_compliance_notice_payload(loan_folio_id, determination_id,
                                     notice_type="MANDATORY_PURCHASE", **overrides) -> dict:
    payload = {
        "loan_folio_id": loan_folio_id,
        "determination_id": determination_id,
        "notice_type": notice_type,
        "annual_premium_rate_cents": DEFAULTS["ANNUAL_PREMIUM_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_geocode_correction_payload(**overrides) -> dict:
    payload = {
        "latitude": DEFAULTS["LATITUDE"],
        "longitude": DEFAULTS["LONGITUDE"],
        "geocode_method": "ROOFTOP",
        "geocode_confidence_score": 0.98,
    }
    payload.update(overrides)
    return payload
