"""Orders and shipments: creation, defaults, the OPEN->PLANNED bubble-up,
structural validation, foreign-key existence, and not-found envelopes.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    assert_order, assert_shipment,
    ApiErrorId, MISSING_UUID,
    create_order_payload, create_shipment_payload, create_claim_payload,
    setup_tendered_shipment,
)

SHIPPER = TEST_USERS["shipper_ops_headers"]


def test_get_order_returns_stored_entity(api):
    """PRD §3.3: "The order opens in the `OPEN` state."

    Design: Corner/entities/get_order_returns_stored_entity
    """
    order = validate_success(api.create_order(
        create_order_payload(weight_lbs=10000, declared_value_cents=200000), SHIPPER), 201)
    resp = api.get_order(order["id"], SHIPPER)
    data = validate_success(resp, 200)
    assert_order(data)
    assert data["status"] == "OPEN"
    assert data["weight_lbs"] == 10000
    assert data["declared_value_cents"] == 200000


def test_create_shipment_bubbles_order_to_planned(api):
    """PRD §2.5: "an order is born `OPEN`, advances to `PLANNED` the instant its
    first child shipment is created, and is automatically driven to `CLOSED` when
    that shipment reaches delivery."

    Design: Corner/entities/create_shipment_bubbles_order_to_planned
    """
    order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
    validate_success(api.create_shipment(
        create_shipment_payload(order_id=order["id"]), SHIPPER), 201)
    refreshed = validate_success(api.get_order(order["id"], SHIPPER), 200)
    assert refreshed["status"] == "PLANNED"


def test_shipment_starts_untendered_and_pending(api):
    """PRD §3.3: "A new shipment is created with two independent status
    dimensions: a `tender_status` that starts at `UNTENDERED` and a separate
    `execution_status` that starts at `PENDING`."
    PRD §3.3: "`quoted_cost_cents` (the provisional freight cost locked at
    acceptance)"

    Design: Corner/entities/shipment_system_fields_input_ignored
    """
    order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
    ship = validate_success(api.create_shipment(
        create_shipment_payload(order_id=order["id"]), SHIPPER), 201)
    assert_shipment(ship)
    assert ship["tender_status"] == "UNTENDERED"
    assert ship["execution_status"] == "PENDING"
    assert ship["quoted_cost_cents"] is None


def test_create_shipment_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "structural validity of the body — required fields present and
    well-typed, enum values within their allowed sets, and the positivity and
    ordering constraints described elsewhere in this document
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_shipment_missing_required_field_returns_invalid_request
    """
    order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
    payload = create_shipment_payload(order_id=order["id"])
    payload.pop("distance_miles")
    resp = api.create_shipment(payload, SHIPPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_shipment_nonpositive_weight_returns_invalid_request(api):
    """PRD §3.3: "The shipment weight must be greater than zero and must not
    exceed the parent order's own weight"
    PRD §2.8: "structural validity of the body — required fields present and
    well-typed, enum values within their allowed sets, and the positivity and
    ordering constraints described elsewhere in this document
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_shipment_nonpositive_weight_returns_invalid_request
    """
    order = validate_success(api.create_order(create_order_payload(weight_lbs=10000), SHIPPER), 201)
    resp = api.create_shipment(
        create_shipment_payload(order_id=order["id"], weight_lbs=0), SHIPPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_shipment_unknown_order_id_returns_not_found(api):
    """PRD §2.6: "Foreign-key identifiers supplied in a request body are subject
    to the same existence requirement: when a create call references another
    resource by id, a missing target yields that resource type's not-found error."

    Design: Corner/entities/create_shipment_unknown_order_id_returns_not_found
    """
    resp = api.create_shipment(create_shipment_payload(order_id=MISSING_UUID), SHIPPER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_get_shipment_nonexistent_returns_not_found(api):
    """PRD §2.6: "that identifier must resolve to an existing resource or the
    request is rejected with the not-found error for that resource type"

    Design: Corner/entities/get_shipment_nonexistent_returns_not_found
    """
    resp = api.get_shipment(MISSING_UUID, SHIPPER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value)


def test_shipment_weight_exceeds_order_weight_rejected(api):
    """PRD §3.3: "The shipment weight must be greater than zero and must not
    exceed the parent order's own weight; a shipment heavier than its order is
    rejected with `ERR_MODE_MISMATCH`."

    Design: Corner/validations/shipment_weight_exceeds_order_weight_rejected
    """
    order = validate_success(api.create_order(create_order_payload(weight_lbs=10000), SHIPPER), 201)
    resp = api.create_shipment(
        create_shipment_payload(order_id=order["id"], weight_lbs=12000), SHIPPER)
    validate_error(resp, ApiErrorId.ERR_MODE_MISMATCH.value)


def test_cancel_order_not_open_returns_not_cancellable(api):
    """PRD §3.3: "While it is still `OPEN`, the shipper may cancel it, which
    requires the order to be `OPEN` (otherwise `ERR_ORDER_NOT_CANCELLABLE`) and
    moves it to `CANCELLED`."

    Design: Corner/state_machines/cancel_order_not_open_returns_not_cancellable
    """
    order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
    validate_success(api.create_shipment(
        create_shipment_payload(order_id=order["id"]), SHIPPER), 201)  # -> PLANNED
    resp = api.cancel_order(order["id"], SHIPPER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)


def test_claim_open_against_nonexistent_shipment_returns_not_found(api):
    """PRD §2.6: "This referential check applies to the body-supplied ids on
    shipment creation, contract-rate creation, load creation, dock-appointment
    creation, freight-invoice creation, claim creation, and the consolidation of
    a shipment onto a load."

    Design: Corner/errors/claim_open_against_nonexistent_shipment_returns_not_found
    """
    resp = api.create_claim(
        create_claim_payload(shipment_id=MISSING_UUID, claim_type="DAMAGE", claimed_amount_cents=50000),
        SHIPPER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value)


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.6: "that identifier must resolve to an existing resource or the
    request is rejected with the not-found error for that resource type —
    `ERR_CARRIER_NOT_FOUND`"

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    resp = api.get_carrier(MISSING_UUID, SHIPPER)
    error_data = validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"
    assert "message" in error_data
