"""Corner queue / endpoints section — response envelope shape, success
status codes (201 for creation, 200 for reads/actions)."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID, is_iso8601_timestamp,
    TEST_USERS,
    create_bin, create_lot, create_contract,
    setup_bin_with_lot,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_bin_payload, create_loadout_payload

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


def test_response_envelope_shape_success_and_error(api):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."
    PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."
    PRD section 2.2: "All error API responses (4xx status codes) follow
    this standard envelope format: ... `data`: { `error_id`: ...,
    `message`: ... }".

    Success body carries meta + response_type + data; error body carries
    response_type "error" with data.error_id and data.message.

    Design: Corner/endpoints/response_envelope_shape_success_and_error
    """
    ok = api_client.create_bin(
        create_bin_payload(name="BIN-ENV", capacity_bu=5000.00, crop="CORN"),
        SM)
    assert ok.status_code == 201
    body = ok.json()
    assert "meta" in body and "data" in body
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert "id" in body["data"]

    bad = api_client.get_bin(NON_EXISTENT_UUID, SM)
    assert bad.status_code == 404
    err_body = bad.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)


def test_success_codes_created_vs_ok(api):
    """PRD section 4: "Operations that create a new resource return `201
    Created`; operations that modify an existing resource, and all reads,
    return `200 OK`."

    POST /grain/bins, /grain/lots, /grain/contracts, /grain/loadouts -> 201.
    GET /grain/bins/{id} and POST /grain/loadouts/{id}/dispatch -> 200.

    Design: Corner/endpoints/success_codes_created_vs_ok
    """
    b_resp = api_client.create_bin(
        create_bin_payload(name="BIN-SC", capacity_bu=5000.00, crop="CORN"),
        SM)
    assert b_resp.status_code == 201
    b = get_success_data(b_resp)

    l_resp = api_client.create_lot(
        {
            "bin_id": b["id"], "crop": "CORN", "grade": "GRADE_1",
            "fill_date": "2026-08-01T00:00:00Z", "original_bu": 500.00,
            "fill_moisture_pct": 15.0, "fill_basis_cents": -25,
            "reference_price_cents_per_bu": 430,
        }, SM)
    assert l_resp.status_code == 201

    c_resp = api_client.create_contract(
        {
            "crop": "CORN", "contracted_bu": 2000.00,
            "window_start": "2026-08-01T00:00:00Z",
            "window_end": "2026-12-31T23:59:59Z",
            "basis_cents_per_bu": -20, "futures_ref_cents_per_bu": 450,
        }, FO)
    assert c_resp.status_code == 201
    con = get_success_data(c_resp)

    lo_resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=100.00), SM)
    assert lo_resp.status_code == 201
    lo = get_success_data(lo_resp)

    get_resp = api_client.get_bin(b["id"], SM)
    assert get_resp.status_code == 200

    disp_resp = api_client.dispatch_loadout(lo["id"], SM)
    assert disp_resp.status_code == 200
