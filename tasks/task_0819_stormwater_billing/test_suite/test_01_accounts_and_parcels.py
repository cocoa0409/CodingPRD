"""Account and parcel registration: creation, defaults, required fields,
not-found, immediate read-after-write, pagination, uniqueness."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS,
    create_account_payload, create_parcel_payload,
    assert_account, assert_parcel,
)

ASSESSOR = TEST_USERS["assessor_headers"]


def test_account_create_returns_all_fields(api):
    """PRD §3.1: "An `Assessor` or a `StormwaterAdmin` opens a property account
    by supplying the owner's details: `owner_name`, `contact_email`, an optional
    `billing_method`, and an optional `mailing_address`."
    PRD §3.1: "A newly opened account carries no debt — its
    `outstanding_balance_cents` starts at 0 and its `delinquency_status` starts
    at `CURRENT`."
    PRD §2.4: "an integer `version` that begins at 1 and increments by one on
    each mutation."

    Design: Corner/entities/account_create_returns_all_fields
    """
    resp = api.create_account(
        create_account_payload(owner_name="Rivera", contact_email="r@x.com"), ASSESSOR)
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["owner_name"] == "Rivera"
    assert data["version"] == 1
    assert data["outstanding_balance_cents"] == 0


def test_account_billing_method_default_applied(api):
    """PRD §3.1: "The `billing_method` records where the stormwater charge is
    placed and must be either `TAX_ROLL` or `UTILITY_BILL`; when it is omitted,
    the account defaults to `UTILITY_BILL`."

    Design: Corner/entities/account_billing_method_default_applied
    """
    resp = api.create_account(
        create_account_payload(owner_name="Rivera", contact_email="r@x.com"), ASSESSOR)
    data = validate_success(resp, expected_status=201)
    assert data["billing_method"] == "UTILITY_BILL"


def test_account_missing_owner_name_returns_missing_field(api):
    """PRD §2.8: "Only after those pass does the system check that all required
    body fields are present (`ERR_MISSING_FIELD`)."
    PRD §3.1: "An `Assessor` or a `StormwaterAdmin` opens a property account by
    supplying the owner's details: `owner_name`, `contact_email`, an optional
    `billing_method`, and an optional `mailing_address`."

    Design: Corner/entities/account_missing_owner_name_returns_missing_field
    """
    resp = api.create_account({"contact_email": "r@x.com"}, ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD.value)


def test_parcel_not_found_returns_404(api):
    """PRD §2.8: "Existence is then verified — every path identifier and every
    foreign-key field in the body must reference a resource that exists,
    validated from left to right along the path, and the first missing reference
    yields `ERR_NOT_FOUND`."

    Design: Corner/entities/parcel_not_found_returns_404
    """
    resp = api.get_parcel(NON_EXISTENT_UUID, ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_immediate_read_after_write_visible(api):
    """PRD §1: "Every mutation that changes a parcel's size, credit, or exemption
    re-derives the downstream fee so that a read of any resource always reflects
    the current state of the world."
    PRD §3.1: "A freshly registered parcel begins in the `DRAFT` state with a
    `billable_eru` of 0."

    Design: Corner/consistency_model/immediate_read_after_write_visible
    """
    acct = validate_success(api.create_account(create_account_payload(), ASSESSOR),
                            expected_status=201)
    created = validate_success(
        api.create_parcel(
            create_parcel_payload(acct["id"], parcel_number="P-CM1",
                                  land_use="COMMERCIAL"), ASSESSOR),
        expected_status=201)
    fetched = validate_success(api.get_parcel(created["id"], ASSESSOR))
    assert fetched["status"] == "DRAFT"
    assert fetched["parcel_number"] == "P-CM1"


def test_parcels_list_pagination_envelope(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object, where `total_count` is the number
    of records matching the filter before pagination and `has_more` is true when
    records remain beyond the returned page."
    PRD §2.3: "`limit` defaults to 10 when omitted, may be no smaller than 1, and
    may be no larger than 100."

    Design: Corner/endpoints/parcels_list_pagination_envelope
    """
    acct = validate_success(api.create_account(create_account_payload(), ASSESSOR),
                            expected_status=201)
    validate_success(
        api.create_parcel(create_parcel_payload(acct["id"], parcel_number="P-EP2"),
                          ASSESSOR),
        expected_status=201)
    data, meta = validate_paginated(
        api.list_parcels(ASSESSOR, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_duplicate_parcel_number_rejected(api):
    """PRD §3.1: "The `parcel_number` must be unique across every parcel in the
    system; an attempt to register a second parcel with an existing
    `parcel_number` is rejected with `ERR_DUPLICATE_PARCEL`."

    Design: Corner/validations/duplicate_parcel_number_rejected
    """
    acct = validate_success(api.create_account(create_account_payload(), ASSESSOR),
                            expected_status=201)
    validate_success(
        api.create_parcel(
            create_parcel_payload(acct["id"], parcel_number="P-DUP",
                                  land_use="COMMERCIAL"), ASSESSOR),
        expected_status=201)
    resp = api.create_parcel(
        create_parcel_payload(acct["id"], parcel_number="P-DUP",
                              land_use="INDUSTRIAL"), ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARCEL.value)
