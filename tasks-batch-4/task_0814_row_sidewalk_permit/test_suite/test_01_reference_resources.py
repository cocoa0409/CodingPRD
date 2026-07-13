"""Foundational reference resources: applicants, segments, spans, and basic
permit creation validation."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_applicant_headers,
    create_applicant_payload,
    create_street_segment_payload,
    create_permit_payload,
    assert_applicant,
    assert_street_segment,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


def test_applicant_creation_echoes_fields(api):
    """PRD §3.1: "An applicant is registered with its `company_name` (the legal
    name of the contractor organization), its municipal `license_number`, and a
    primary `contact_email`."

    Design: Corner/entities/applicant_creation_returns_fields
    """
    resp = api.create_applicant(
        create_applicant_payload(company_name="Acme", license_number="L1"), ADMIN
    )
    data = validate_success(resp, 201)
    assert_applicant(data)
    assert data["company_name"] == "Acme"
    assert data["license_number"] == "L1"


def test_get_unknown_permit_returns_not_found(api):
    """PRD §2.8: "A request naming a permit that does not exist fails with
    `ERR_PERMIT_NOT_FOUND` (HTTP 404) before any child is considered."

    Design: Corner/entities/permit_not_found_on_get_returns_404
    """
    resp = api.get_permit(NON_EXISTENT, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_FOUND.value)


def test_permit_missing_required_field_rejected(api):
    """PRD §2.9: "Well-formedness of the request body — required fields present,
    correctly typed, and enum values in range — is checked last and surfaces as
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/permit_missing_required_field_returns_invalid_request
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(api)
    headers = make_applicant_headers(app["id"])
    payload = {
        "applicant_id": app["id"],
        "street_segment_id": seg["id"],
        "primary_obstruction_type": "LANE",
        "requested_start_date": "2026-04-01",
        # requested_end_date omitted
    }
    resp = api.create_permit(payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_arterial_segment_moratorium_end_computed(api):
    """PRD §3.1: "take the `last_repaved_date` and add a whole number of calendar
    years determined by the zone — 2 years for a `RESIDENTIAL` segment, 3 years
    for a `COMMERCIAL` segment, and 5 years for an `ARTERIAL` segment."

    Design: Corner/entities/street_segment_moratorium_end_computed
    """
    resp = api.create_street_segment(
        create_street_segment_payload(
            block_label="Grand 3", zone_class="ARTERIAL",
            last_repaved_date="2020-01-01", roadway_lane_count=4,
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_street_segment(data)
    assert data["moratorium_end_date"] == "2025-01-01"


def test_segment_invalid_zone_enum_rejected(api):
    """PRD §3.1: "The `zone_class` is one of `RESIDENTIAL`, `COMMERCIAL`, or
    `ARTERIAL`, and it drives both fee rates and the length of the utility-cut
    moratorium."

    Design: Corner/entities/street_segment_invalid_zone_enum_rejected
    """
    resp = api.create_street_segment(
        create_street_segment_payload(block_label="Bad 1", zone_class="INDUSTRIAL"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
