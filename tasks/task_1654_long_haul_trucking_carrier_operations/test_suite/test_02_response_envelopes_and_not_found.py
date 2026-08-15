"""Response envelope shapes (PRD §2.2) and per-family 404 resolution
(PRD §2.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_customer,
    is_iso8601_timestamp,
    make_dispatcher_headers,
    make_fleet_admin_headers,
    validate_error,
    validate_success,
)

FLEET_ADMIN = make_fleet_admin_headers()
DISPATCHER = make_dispatcher_headers()


def test_success_envelope_object_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/endpoints/success_envelope_object_shape
    """
    resp = api_client.create_customer({"name": "Acme Foods"}, FLEET_ADMIN)
    assert resp.status_code == 201, f"expected 201, got {resp.status_code}"
    body = resp.json()
    assert body["response_type"] == "object"
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert body["data"]["id"], "created resource must carry its id"


def test_error_envelope_shape(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape
    """
    resp = api_client.get_driver(NON_EXISTENT_UUID, DISPATCHER)
    err = validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND)
    assert err["message"].strip(), "error message must be non-empty"
    body = resp.json()
    assert body["response_type"] == "error"


def test_not_found_sweep_returns_domain_specific_404s(api):
    """PRD §2.10: "Each resource type has its own not-found error:
    `ERR_DRIVER_NOT_FOUND`, `ERR_TRACTOR_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_LANE_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`,
    `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_FUEL_RATE_NOT_FOUND`, and
    `ERR_SAFETY_EVENT_NOT_FOUND` (all HTTP 404)."

    Design: Corner/errors/not_found_sweep_returns_404s
    """
    customer = create_customer()
    assert customer["id"] != NON_EXISTENT_UUID
    cases = [
        (api_client.get_tractor, ApiErrorId.ERR_TRACTOR_NOT_FOUND),
        (api_client.get_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
        (api_client.get_lane, ApiErrorId.ERR_LANE_NOT_FOUND),
        (api_client.get_load, ApiErrorId.ERR_LOAD_NOT_FOUND),
        (api_client.get_trip, ApiErrorId.ERR_TRIP_NOT_FOUND),
        (api_client.get_accessorial, ApiErrorId.ERR_ACCESSORIAL_NOT_FOUND),
        (api_client.get_settlement, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
        (api_client.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
        (api_client.get_state_fuel_rate, ApiErrorId.ERR_FUEL_RATE_NOT_FOUND),
        (api_client.get_safety_event, ApiErrorId.ERR_SAFETY_EVENT_NOT_FOUND),
    ]
    for getter, error_id in cases:
        resp = getter(NON_EXISTENT_UUID, DISPATCHER)
        validate_error(resp, error_id)
