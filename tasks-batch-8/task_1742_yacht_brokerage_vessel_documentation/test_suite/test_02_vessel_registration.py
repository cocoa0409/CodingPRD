"""Vessel registration: documentation-mode coherence, HIN uniqueness, lien rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_vessel,
    create_lien_payload,
    create_state_vessel_payload,
    create_vessel,
    create_vessel_payload,
    setup_brokerage_desk,
    listing_headers,
    unique_hin,
    validate_error,
    validate_success,
)


def test_state_vessel_with_uscg_number_rejected(api, platform_admin_headers):
    """PRD §3.2: "A USCG vessel must carry its `uscg_official_no` — a
    six-to-seven-digit string — and must not carry a state title number in its
    place; a STATE vessel must carry its `state_title_no`" and "A submission
    whose numbers contradict its mode is rejected with `ERR_DOC_MODE_MISMATCH`
    (HTTP 422)."

    Design: Corner/entities/vessel_creation_requires_doc_mode_coherence
    """
    payload = create_vessel_payload(
        documentation_mode="STATE", uscg_official_no="1234567"
    )
    payload.pop("state_title_no", None)
    res = api.create_vessel(payload, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_DOC_MODE_MISMATCH)


def test_duplicate_hin_rejected(api, platform_admin_headers):
    """PRD §3.2: "A PlatformAdmin or ListingAgent registers each vessel with its
    `hin` — a Hull Identification Number of exactly twelve uppercase alphanumeric
    characters, globally unique across every vessel the desk has ever registered,
    so a duplicate submission is rejected with `ERR_DUPLICATE_RESOURCE`"

    Design: Corner/entities/vessel_hin_uniqueness_enforced
    """
    hin = unique_hin()
    first = validate_success(
        api.create_vessel(create_vessel_payload(hin=hin), platform_admin_headers), 201
    )
    assert_vessel(first)
    res = api.create_vessel(
        create_vessel_payload(hin=hin, make="Other", model="Boat"),
        platform_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_fresh_vessel_reports_liens_status_clean(api, platform_admin_headers):
    """PRD §3.2: "A freshly registered vessel starts with `liens_status` CLEAN."

    Design: Corner/entities/vessel_computed_liens_status_clean_on_create
    """
    created = validate_success(
        api.create_vessel(create_vessel_payload(), platform_admin_headers), 201
    )
    assert created["liens_status"] == "CLEAN"
    fetched = validate_success(
        api.get_vessel(created["id"], platform_admin_headers), 200
    )
    assert fetched["liens_status"] == "CLEAN"


def test_create_vessel_missing_hin_rejected(api, platform_admin_headers):
    """PRD §2.8: "a missing required field, an enum value outside its declared
    membership, or a field of the wrong type is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/errors/err_invalid_request_on_missing_required_field
    """
    payload = create_vessel_payload()
    del payload["hin"]
    res = api.create_vessel(payload, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_preferred_mortgage_on_state_titled_vessel_rejected(api):
    """PRD §3.2: "a PREFERRED_MORTGAGE may only be recorded on a USCG-documented
    vessel, and filing one against a state-titled boat is rejected with
    `ERR_LIEN_INSTRUMENT_MISMATCH` (HTTP 422)"

    Design: Corner/validations/preferred_mortgage_on_state_vessel_rejected
    """
    deal = setup_brokerage_desk()
    vessel = validate_success(
        api.create_vessel(
            create_state_vessel_payload(), TEST_USERS["platform_admin_headers"]
        ),
        201,
    )
    res = api.create_lien(
        vessel["id"],
        create_lien_payload(instrument_type="PREFERRED_MORTGAGE"),
        listing_headers(deal),
    )
    validate_error(res, ApiErrorId.ERR_LIEN_INSTRUMENT_MISMATCH)
