"""Organization onboarding, authentication/authorization, and envelope shape."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_generator,
    create_generator_payload,
    create_stream_payload,
    create_generator,
    create_stream,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_generator_headers,
    make_offtaker_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_ops_headers"]
CO_FILE = TEST_USERS["compliance_officer_file_headers"]


def test_create_generator_returns_201_with_defaults(api):
    """PRD §3.1: "Registering a **Generator** requires its `legal_name`, the
    two-letter `hq_state_code` of its headquarters, and a `contact_email`; a new
    generator begins with `total_credits` of 0.0 and a `credit_tier` of
    `STANDARD`."
    PRD §4: "Operations that create new resources return a `201 Created` status
    code, while operations that act on or modify an existing resource return
    `200 OK`."

    Design: Corner/entities/create_generator_returns_201_with_defaults
    """
    resp = api.create_generator(create_generator_payload(), BROKER)
    data = validate_success(resp, 201)
    assert_generator(data)
    assert data["total_credits"] == pytest.approx(
        0.0
    ), f"new generator total_credits must be 0.0, got {data['total_credits']}"
    assert (
        data["credit_tier"] == "STANDARD"
    ), f"new generator credit_tier must be STANDARD, got {data['credit_tier']}"


def test_create_generator_with_computed_field_input_ignored(api):
    """PRD §2.10: "Fourth, body well-formedness: required fields present, enum
    values within their declared sets, numeric ranges respected, dates in ISO
    format — violations yield `ERR_INVALID_REQUEST`, while unknown computed or
    system-managed fields supplied in the input are ignored rather than
    rejected."

    Design: Corner/entities/create_generator_with_computed_field_input_ignored
    """
    payload = create_generator_payload(total_credits=999)
    resp = api.create_generator(payload, BROKER)
    data = validate_success(resp, 201)
    assert data["total_credits"] == pytest.approx(
        0.0
    ), "client-supplied total_credits must be ignored; new generator starts at 0.0"


def test_create_generator_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request with a missing header, or whose declared role is not
    one of these five, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/create_generator_missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_generator(create_generator_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_offtaker_cannot_create_stream_returns_forbidden(api):
    """PRD §2.1: "A well-authenticated request whose role is not authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §4: POST /api/streams is authorized for Generator only.

    Design: Corner/rbac/offtaker_cannot_create_stream_returns_forbidden
    """
    resp = api.create_stream(
        create_stream_payload(NON_EXISTENT_UUID),
        make_offtaker_headers("off_x"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_compliance_officer_cannot_publish_price_index_returns_forbidden(api):
    """PRD §2.1: "A well-authenticated request whose role is not authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §4: POST /api/price-index-entries is authorized for BrokerOps only.

    Design: Corner/rbac/compliance_officer_cannot_publish_price_index_returns_forbidden
    """
    resp = api.create_price_index_entry(
        {
            "material_type": "FLY_ASH",
            "region_code": "PA",
            "effective_from": "2026-01-01",
            "price_cents_per_ton": 300,
        },
        CO_FILE,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_error_envelope_shape_on_failure_and_success(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/errors/error_envelope_shape_on_failure_and_success
    """
    # Error envelope
    err_resp = api.get_shipment(NON_EXISTENT_UUID, BROKER)
    err_body = err_resp.json()
    assert err_resp.status_code == 404
    assert err_body["response_type"] == "error"
    assert set(err_body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert err_body["meta"]["api_request_id"].startswith("req_")
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]

    # Success envelope
    ok_resp = api.create_generator(create_generator_payload(), BROKER)
    ok_body = ok_resp.json()
    assert ok_resp.status_code == 201
    assert ok_body["response_type"] == "object"
    assert ok_body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(ok_body["meta"]["api_request_timestamp"])
    assert is_valid_uuid(ok_body["data"]["id"])


def test_get_shipment_not_found_returns_404(api):
    """PRD §2.10: "Fifth, every resource referenced by a path parameter must
    exist, else `ERR_NOT_FOUND`."

    Design: Corner/entities/get_shipment_not_found_returns_404
    """
    resp = api.get_shipment(NON_EXISTENT_UUID, BROKER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_stream_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "The creation payload carries `generator_id` — which must equal
    the acting Generator's own id, or the request fails ownership with
    `ERR_OWNERSHIP_MISMATCH` — along with the stream's `material_type`, one of
    `FLY_ASH`, `SLAG`, `GYPSUM`, `FOUNDRY_SAND`, or `BIOSOLIDS`; the
    generator-declared typical `declared_moisture_pct`; and the
    `expected_tons_per_month` production forecast."
    PRD §2.10: "Fourth, body well-formedness: required fields present, enum
    values within their declared sets, numeric ranges respected, dates in ISO
    format — violations yield `ERR_INVALID_REQUEST`"

    Design: Corner/entities/create_stream_missing_required_field_returns_invalid_request
    """
    generator = create_generator()
    payload = create_stream_payload(generator["id"])
    del payload["material_type"]
    resp = api.create_stream(payload, make_generator_headers(generator["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_stream_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: "The creation payload carries `generator_id` — which must equal
    the acting Generator's own id, or the request fails ownership with
    `ERR_OWNERSHIP_MISMATCH` — along with the stream's `material_type`, one of
    `FLY_ASH`, `SLAG`, `GYPSUM`, `FOUNDRY_SAND`, or `BIOSOLIDS`; the
    generator-declared typical `declared_moisture_pct`; and the
    `expected_tons_per_month` production forecast."
    PRD §2.10: "Fourth, body well-formedness: required fields present, enum
    values within their declared sets, numeric ranges respected, dates in ISO
    format — violations yield `ERR_INVALID_REQUEST`"

    Design: Corner/entities/create_stream_invalid_enum_returns_invalid_request
    """
    generator = create_generator()
    resp = api.create_stream(
        create_stream_payload(generator["id"], material_type="UNOBTANIUM"),
        make_generator_headers(generator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_filtered_list_streams_by_generator(api):
    """PRD §3.1: "The stream catalogue can be listed with optional
    `generator_id`, `status`, and `material_type` filters."

    Design: Corner/endpoints/filtered_list_streams_by_generator
    """
    gen_a = create_generator(legal_name="GenA", contact_email="a@x.com")
    gen_b = create_generator(legal_name="GenB", hq_state_code="MI", contact_email="b@x.com")
    stream_a = create_stream(gen_a["id"])
    create_stream(gen_b["id"], material_type="SLAG", declared_moisture_pct=5.0,
                  expected_tons_per_month=300)

    resp = api.list_streams(BROKER, params={"generator_id": gen_a["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly 1 stream, got {meta['total_count']}"
    assert len(data) == 1
    assert data[0]["id"] == stream_a["id"]
    assert data[0]["generator_id"] == gen_a["id"]
