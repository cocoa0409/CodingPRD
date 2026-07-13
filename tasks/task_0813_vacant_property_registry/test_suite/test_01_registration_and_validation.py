"""Registrant/property registration, body validation, consistency, pagination.

Covers corner-design instances from the `entities`, `validations`,
`consistency_model`, and `cross_cutting_complexity_layers` (pagination) sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_registrant_headers,
    create_registrant, create_property,
    create_registrant_payload, create_property_payload,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_abandoned_owner_property_computed_fee_and_initial_states(api):
    """PRD §3.1: "the base fee is 20000 cents for a `LENDER` registration and
    10000 cents for an `OWNER` registration; if the property's `occupancy_status`
    is `ABANDONED`, a surcharge equal to 50 percent of that base fee, rounded half
    up to whole cents, is added, and if the occupancy is `VACANT` no surcharge
    applies."
    PRD §3.1: "A newly registered property starts life on the `ACTIVE`
    registration axis and the `NONE` foreclosure axis."

    Design: Corner/entities/property_create_returns_computed_fee_and_initial_states
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, occupancy_status="ABANDONED",
                           registration_type="OWNER")
    assert prop["registration_fee_cents"] == 15000
    assert prop["registration_status"] == "ACTIVE"
    assert prop["foreclosure_status"] == "NONE"
    assert prop["outstanding_balance_cents"] == 15000
    assert prop["version"] == 1


def test_owner_registrant_license_number_defaults_null(api):
    """PRD §3.1: "When `party_type` is `OWNER`, `license_number` carries no value
    and is left null."

    Design: Corner/entities/owner_registrant_license_number_defaults_null
    """
    payload = create_registrant_payload(party_type="OWNER")
    data = validate_success(api.create_registrant(payload, ANON), expected_status=201)
    assert data["license_number"] is None
    assert data["party_type"] == "OWNER"


def test_get_nonexistent_property_returns_404(api):
    """PRD §2.10: "a missing property yields `ERR_PROPERTY_NOT_FOUND`".

    Design: Corner/entities/get_property_nonexistent_returns_404
    """
    resp = api.get_property(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_create_property_missing_parcel_id_returns_validation(api):
    """PRD §2.10: "body well-formedness — required fields present, enum values
    legal, and window fields well-typed (`ERR_VALIDATION`, HTTP 422)."

    Design: Corner/entities/property_missing_parcel_id_returns_validation
    """
    registrant = create_registrant(api, party_type="OWNER")
    payload = {
        "registrant_id": registrant["id"],
        "street_address": "2 Elm",
        "occupancy_status": "VACANT",
        "registration_type": "OWNER",
    }
    resp = api.create_property(payload, make_registrant_headers(registrant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_property_invalid_occupancy_enum_returns_validation(api):
    """PRD §2.10: "body well-formedness — required fields present, enum values
    legal, and window fields well-typed (`ERR_VALIDATION`, HTTP 422)."
    PRD §3.1: "the field-observed `occupancy_status` (either `VACANT` or
    `ABANDONED`)".

    Design: Corner/entities/property_invalid_occupancy_enum_returns_validation
    """
    registrant = create_registrant(api, party_type="OWNER")
    payload = create_property_payload(
        registrant_id=registrant["id"], occupancy_status="OCCUPIED",
        registration_type="OWNER",
    )
    resp = api.create_property(payload, make_registrant_headers(registrant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_property_unknown_registrant_returns_404(api):
    """PRD §3.1: "The `registrant_id` must resolve to an existing registrant, or
    the request fails with `ERR_REGISTRANT_NOT_FOUND`."

    Design: Corner/entities/create_property_unknown_registrant_returns_404
    """
    payload = create_property_payload(
        registrant_id=NON_EXISTENT_UUID, occupancy_status="VACANT",
        registration_type="OWNER",
    )
    resp = api.create_property(payload, make_registrant_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_REGISTRANT_NOT_FOUND.value)


def test_lender_registrant_without_license_returns_error(api):
    """PRD §3.1: "A lender is a licensed entity, so `license_number` (the state
    lender license number) must be present when `party_type` is `LENDER`; if it is
    omitted in that case the registration is rejected with `ERR_LICENSE_REQUIRED`."

    Design: Corner/validations/lender_registrant_without_license_returns_error
    """
    payload = create_registrant_payload(party_type="LENDER", legal_name="Bank Co")
    resp = api.create_registrant(payload, ANON)
    validate_error(resp, ApiErrorId.ERR_LICENSE_REQUIRED.value)


def test_property_registration_type_mismatch_returns_error(api):
    """PRD §3.1: "The `registration_type` must equal the referenced registrant's
    `party_type`; a filing that claims to be a lender registration against an owner
    party (or vice versa) is rejected with `ERR_TYPE_MISMATCH`."

    Design: Corner/validations/property_registration_type_mismatch_returns_error
    """
    registrant = create_registrant(api, party_type="OWNER")
    payload = create_property_payload(
        registrant_id=registrant["id"], occupancy_status="VACANT",
        registration_type="LENDER",
    )
    resp = api.create_property(payload, make_registrant_headers(registrant["id"]))
    validate_error(resp, ApiErrorId.ERR_TYPE_MISMATCH.value)


def test_duplicate_parcel_returns_error(api):
    """PRD §3.1: "The `parcel_id` must be unique across all properties; a second
    property claiming a parcel already on file is rejected with
    `ERR_DUPLICATE_PARCEL`."

    Design: Corner/validations/duplicate_parcel_returns_error
    """
    registrant = create_registrant(api, party_type="OWNER")
    create_property(api, registrant, parcel_id="C-DUP", registration_type="OWNER")
    payload = create_property_payload(
        registrant_id=registrant["id"], parcel_id="C-DUP",
        occupancy_status="VACANT", registration_type="OWNER",
    )
    resp = api.create_property(payload, make_registrant_headers(registrant["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARCEL.value)


def test_property_immediately_readable_after_create(api):
    """PRD §2.4: "Every persisted resource is assigned a server-minted `id` — a
    UUID string with no type prefix — at creation."
    PRD §3.1: "Fetching a single property returns its stored fields together with
    the three computed figures".

    Design: Corner/consistency_model/property_create_immediately_readable
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, parcel_id="C-IMM",
                           registration_type="OWNER")
    fetched = validate_success(api.get_property(prop["id"], ADMIN))
    assert fetched["parcel_id"] == "C-IMM"
    assert fetched["id"] == prop["id"]


def test_properties_list_pagination_reports_total_and_has_more(api):
    """PRD §2.3: "`total_count` is the number of records matching the query before
    pagination is applied, and `has_more` is true when records remain beyond the
    current page (that is, when `offset` plus the number of returned records is
    less than `total_count`)."

    Design: Corner/cross_cutting_complexity_layers/properties_list_pagination_has_more
    """
    registrant = create_registrant(api, party_type="OWNER")
    create_property(api, registrant, registration_type="OWNER")
    create_property(api, registrant, registration_type="OWNER")
    resp = api.list_properties(
        ADMIN, params={"registrant_id": registrant["id"], "limit": 1, "offset": 0}
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
