"""Corner coverage: property creation defaults, not-found / bad-payload / bad-enum
rejections, the append-only PaymentRecord shape, and list pagination envelope.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, assert_property,
    create_property_payload, create_payment_payload,
    setup_quoted_job, pay, NON_EXISTENT_UUID, TEST_USERS, ApiErrorId,
)

CLIENT = TEST_USERS["client_contact_headers"]


def test_create_property_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created property has its posture at `OPEN`, an
    `open_test_count` of 0, and a null `latest_result_pci_l`."
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    and increments by one on every mutation."

    Design: Corner/entities/entity_property_creation_returns_201_with_defaults
    """
    res = api.create_property(
        create_property_payload(address_line="C1", foundation_type="SLAB",
                                floor_area_sqft=1400), CLIENT)
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["posture"] == "OPEN"
    assert prop["open_test_count"] == 0
    assert prop["latest_result_pci_l"] is None
    assert prop["version"] == 1


def test_get_property_nonexistent_returns_404(api):
    """PRD §2.5: "every resource named in the URL path must exist, validated left
    to right — the property first, then the radon test or mitigation job, then
    any permit, warranty, or retest schedule — with a missing path resource
    yielding `ERR_NOT_FOUND`."

    Design: Corner/entities/entity_property_get_not_found_returns_404
    """
    res = api.get_property(NON_EXISTENT_UUID, CLIENT)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_property_missing_foundation_rejected(api):
    """PRD §2.5: "the final, lowest-priority gate is request-body well-formedness,
    which yields `ERR_INVALID_REQUEST` when a required field is absent, an enum
    value is invalid, a numeric is negative where it must not be, or the
    retrieval payload is inconsistent with the test kind."

    Design: Corner/entities/entity_property_missing_required_field_rejected
    """
    res = api.create_property({"address_line": "C2", "floor_area_sqft": 1400}, CLIENT)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_property_invalid_foundation_enum_rejected(api):
    """PRD §3.1: "its `foundation_type` (one of `SLAB`, `BASEMENT`, or
    `CRAWLSPACE`, which later drives both the quote base price and the
    suction-point geometry)."
    PRD §2.5: "the final, lowest-priority gate is request-body well-formedness,
    which yields `ERR_INVALID_REQUEST` when a required field is absent, an enum
    value is invalid."

    Design: Corner/entities/entity_property_invalid_foundation_enum_rejected
    """
    res = api.create_property(
        {"address_line": "C3", "foundation_type": "PIER", "floor_area_sqft": 1400},
        CLIENT)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_payment_record_is_append_only_no_version(api):
    """PRD §2.4: "A `PaymentRecord` is an append-only ledger entry: it carries
    only `id` and `created_at`, and has no `updated_at` and no `version` because
    it is never modified after it is written."

    Design: Corner/entities/entity_paymentrecord_immutable_no_version_field
    """
    _, _, _, job = setup_quoted_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    pay(job["id"], "DEPOSIT", 45000)
    records = api.list_payment_records(
        CLIENT, params={"mitigation_job_id": job["id"]}).json()["data"]
    assert len(records) == 1
    rec = records[0]
    assert rec["kind"] == "DEPOSIT"
    assert rec["amount_cents"] == 45000
    assert "version" not in rec


def test_property_list_pagination_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/entity_property_list_pagination_envelope
    """
    api.create_property(create_property_payload(address_line="C5a"), CLIENT)
    api.create_property(create_property_payload(address_line="C5b"), CLIENT)
    data, meta = validate_paginated(
        api.list_properties(CLIENT, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
