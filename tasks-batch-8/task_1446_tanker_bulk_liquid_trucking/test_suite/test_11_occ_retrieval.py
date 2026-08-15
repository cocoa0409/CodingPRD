"""Optimistic concurrency, immediate consistency, retrieval, and envelope claims."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_agreement_payload,
    create_customer,
    create_product,
    create_shipment_payload,
    create_trailer,
    setup_draft_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_shipments_filtered_by_customer(api):
    """PRD section 4: "List endpoints accept the `limit` and `offset` pagination
    parameters of §2.3 plus resource-specific filters" — including "shipments by
    `customer_id`, `product_id`, `trailer_id`, `driver_id`, `rack_id`,
    `wash_cert_id`, and `status`".

    Design: Corner/endpoints/shipments_filtered_by_customer
    """
    cust_a = create_customer(name="A Co")
    cust_b = create_customer(name="B Co")
    prod = create_product()
    ship_a = validate_success(api.create_shipment(
        create_shipment_payload(cust_a["id"], prod["id"], ordered_gallons=100, route_miles=10),
        DISP), 201)
    validate_success(api.create_shipment(
        create_shipment_payload(cust_b["id"], prod["id"], ordered_gallons=200, route_miles=10),
        DISP), 201)

    data, meta = validate_paginated(api.list_shipments(DISP, params={"customer_id": cust_a["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == ship_a["id"]


def test_error_envelope_shape(api):
    """PRD 2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`.", "The `error_id` is a unique, machine-readable
    string that identifies the specific error.", and "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape
    """
    res = api.get_shipment(NON_EXISTENT_UUID, DISP)
    assert res.status_code == 404
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_SHIPMENT_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_meter_ticket_not_found_returns_404(api):
    """PRD 2.8 step 3: "The first unknown identifier yields that resource's dedicated
    404", and `ERR_METER_TICKET_NOT_FOUND` is one of the listed per-resource 404
    codes.

    Design: Corner/errors/meter_ticket_not_found_returns_404
    """
    res = api.get_meter_ticket(NON_EXISTENT_UUID, DISP)
    validate_error(res, "ERR_METER_TICKET_NOT_FOUND", expected_status=404)


def test_occ_shipment_patch_stale_version(api):
    """PRD 2.7: "Revising a DRAFT shipment's commercial terms requires the request to
    carry `expected_shipment_version` holding the shipment's `version` as the client
    last observed it; if another writer has advanced the shipment since that read —
    for example through a prior accepted revision — the versions no longer match and
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_shipment_patch_stale_version
    """
    scenario = setup_draft_shipment()
    ship = scenario["ship"]
    stale_version = ship["version"]

    revised = validate_success(api.patch_shipment(
        ship["id"], {"ordered_gallons": 1200, "expected_shipment_version": stale_version},
        DISP), 200)
    assert revised["version"] == stale_version + 1

    res = api.patch_shipment(
        ship["id"], {"ordered_gallons": 1300, "expected_shipment_version": stale_version}, DISP)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_occ_agreement_patch_stale_version(api):
    """PRD 2.7: "Revising a PENDING dedicated-trailer agreement's committed volume
    likewise requires `expected_agreement_version` matching the agreement's current
    `version`; a stale value means the client's base revision is out of date and the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_agreement_patch_stale_version
    """
    cust = create_customer(name="Dedicated Co", dedicated_program_enrolled=True)
    trl = create_trailer()
    agr = validate_success(
        api.create_agreement(create_agreement_payload(cust["id"], trl["id"]), ADMIN), 201)
    stale_version = agr["version"]

    revised = validate_success(api.patch_agreement(
        agr["id"], {"committed_loads_per_month": 6, "expected_agreement_version": stale_version},
        ADMIN), 200)
    assert revised["committed_loads_per_month"] == 6
    assert revised["version"] == stale_version + 1

    res = api.patch_agreement(
        agr["id"], {"committed_loads_per_month": 7, "expected_agreement_version": stale_version},
        ADMIN)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_immediate_visibility_after_patch(api):
    """PRD 3.3: "a `Dispatcher` may revise its commercial terms — any of
    `ordered_gallons`, `route_miles`, or `rate_per_gal_cents` — through the
    OCC-guarded revision endpoint of §2.7, which requires
    `expected_shipment_version` and increments the shipment's `version` by one on
    success." A successful revision is fully visible on the immediately following
    read.

    Design: Corner/consistency_model/immediate_visibility_after_patch
    """
    scenario = setup_draft_shipment()
    ship = scenario["ship"]
    observed_version = ship["version"]

    validate_success(api.patch_shipment(
        ship["id"], {"ordered_gallons": 1500, "expected_shipment_version": observed_version},
        DISP), 200)

    after = validate_success(api.get_shipment(ship["id"], DISP), 200)
    assert after["ordered_gallons"] == 1500
    assert after["version"] == observed_version + 1
