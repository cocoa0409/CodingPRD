"""Order and batch lifecycle: the two parallel order axes, the batch-run
cascade that bubbles the order into PROCESSING, and the compound READY gate."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, TEST_USERS,
    create_customer, create_order, authorize_payment, capture_payment,
    run_batch, qc_pass, get_order_admin, get_item_admin,
    make_customer_headers,
    setup_loaded_batch, setup_order_one_ready_one_pending,
)


# ===========================================================================
# non_linear_state_machine / order_parallel_payment_and_fulfillment_axes
# ===========================================================================
def test_capture_advances_payment_axis_only(api):
    """PRD §3.2: "Capture is permitted only when `payment_status` is
    `AUTHORIZED`; it advances `payment_status` from `AUTHORIZED` to `CAPTURED`
    and, at that moment, records `captured_total_cents` as equal to the order's
    `estimate_total_cents`. Capture is purely a payment-axis move and does not
    touch `fulfillment_status`."

    After authorize (fulfillment AWAITING_MEDIA) then capture, payment is
    CAPTURED while fulfillment remains AWAITING_MEDIA.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    cust = create_customer(api, email="sm-1@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    authorize_payment(api, order["id"], cust["id"])
    capture_payment(api, order["id"])
    got = get_order_admin(api, order["id"])
    assert got["payment_status"] == "CAPTURED", got
    assert got["fulfillment_status"] == "AWAITING_MEDIA", got


def test_authorize_advances_both_axes_together(api):
    """PRD §3.2: "Authorizing is permitted only when the order's
    `fulfillment_status` is `QUOTED` and its `payment_status` is `UNPAID`; in a
    single call it advances `payment_status` from `UNPAID` to `AUTHORIZED` and
    `fulfillment_status` from `QUOTED` to `AWAITING_MEDIA`."

    The single authorize call is the one transition moving both axes at once.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    cust = create_customer(api, email="sm-2@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    authorized = authorize_payment(api, order["id"], cust["id"])
    assert authorized["payment_status"] == "AUTHORIZED", authorized
    assert authorized["fulfillment_status"] == "AWAITING_MEDIA", authorized


# ===========================================================================
# transitive_cascade / batch_run_scan_processing_depth2
# ===========================================================================
def test_batch_run_scans_item_and_bubbles_order_to_processing(api):
    """PRD §3.4: "Running advances the batch from `LOADED` to `RUNNING` and, for
    each loaded media item, advances that item from `PREPPED` to `SCANNING`."
    PRD §3.4: "As a running batch drives its first item into `SCANNING`, the
    owning order bubbles up: any order whose `fulfillment_status` is `RECEIVED`
    advances to `PROCESSING`."

    Design: Difficulty/transitive_cascade/batch_run_scan_processing_depth2
    """
    base = setup_loaded_batch(api, customer_email="tc-run1@x.com")
    run_batch(api, base["batch"]["id"])
    item = get_item_admin(api, base["item_id"])
    order = get_order_admin(api, base["order_id"])
    assert item["status"] == "SCANNING", item
    assert order["fulfillment_status"] == "PROCESSING", order


def test_batch_run_advances_batch_to_running(api):
    """PRD §3.4: "Running advances the batch from `LOADED` to `RUNNING` and, for
    each loaded media item, advances that item from `PREPPED` to `SCANNING`."

    The batch that originates the cascade moves to RUNNING while its loaded item
    reaches SCANNING.

    Design: Difficulty/transitive_cascade/batch_run_scan_processing_depth2
    """
    base = setup_loaded_batch(api, customer_email="tc-run2@x.com")
    batch = run_batch(api, base["batch"]["id"])
    assert batch["status"] == "RUNNING", batch
    item = get_item_admin(api, base["item_id"])
    assert item["status"] == "SCANNING", item


# ===========================================================================
# cross_entity_state_dependency / order_ready_requires_all_media_output_ready
# ===========================================================================
def test_output_blocked_while_one_item_still_pending(api):
    """PRD §3.6: "The system advances an order from `PROCESSING` to `READY` when
    every media item belonging to that order is in either `OUTPUT_READY` or
    `WRITTEN_OFF` status and at least one of them is `OUTPUT_READY`."
    PRD §3.6: "First, the order's `fulfillment_status` must be `READY`;
    otherwise the request is rejected with `ERR_ORDER_NOT_READY` (HTTP 409)."

    One item OUTPUT_READY, one at QC_PENDING: the order stays PROCESSING and
    deliverable generation is refused.

    Design: Difficulty/cross_entity_state_dependency/order_ready_requires_all_media_output_ready
    """
    base = setup_order_one_ready_one_pending(api, customer_email="ce-r1@x.com")
    order = get_order_admin(api, base["order_id"])
    resp = api.create_output_artifact(
        base["order_id"],
        {"output_type": "CLOUD", "expected_order_version": order["version"]},
        make_customer_headers(base["customer_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_READY)
    assert get_order_admin(api, base["order_id"])["fulfillment_status"] == "PROCESSING"


def test_order_reaches_ready_once_all_items_output_ready(api):
    """PRD §3.6: "The system advances an order from `PROCESSING` to `READY` when
    every media item belonging to that order is in either `OUTPUT_READY` or
    `WRITTEN_OFF` status and at least one of them is `OUTPUT_READY`."

    Passing QC on the last pending item resolves every item, advancing the order
    to READY so a deliverable can be generated.

    Design: Difficulty/cross_entity_state_dependency/order_ready_requires_all_media_output_ready
    """
    base = setup_order_one_ready_one_pending(api, customer_email="ce-r2@x.com")
    qc_pass(api, base["mi2"])
    order = get_order_admin(api, base["order_id"])
    assert order["fulfillment_status"] == "READY", order
    resp = api.create_output_artifact(
        base["order_id"],
        {"output_type": "CLOUD", "expected_order_version": order["version"]},
        make_customer_headers(base["customer_id"]),
    )
    artifact = validate_success(resp, expected_status=201)
    assert artifact["status"] == "AVAILABLE", artifact


# ===========================================================================
# state_machines / capture_before_authorize_returns_invalid_state (corner)
# ===========================================================================
def test_capture_before_authorize_is_invalid_state(api):
    """PRD §3.2: "Capture is permitted only when `payment_status` is
    `AUTHORIZED`; it advances `payment_status` from `AUTHORIZED` to `CAPTURED`."
    PRD §2.9: "Within the state-and-business tier, a request that targets an
    entity in the wrong state for a requested transition is rejected with the
    generic `ERR_INVALID_STATE` (HTTP 409) unless a more specific rule below
    claims it."

    Capturing a still-UNPAID order (never authorized) is refused.

    Design: Corner/state_machines/capture_before_authorize_returns_invalid_state
    """
    cust = create_customer(api, email="cb@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    resp = api.capture_payment(order["id"], TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# state_machines / run_batch_twice_returns_invalid_state (corner)
# ===========================================================================
def test_run_batch_twice_is_invalid_state(api):
    """PRD §3.4: "A run is permitted only when the batch's `status` is `LOADED`
    and its `loaded_count` is at least 1."
    PRD §2.9: "Within the state-and-business tier, a request that targets an
    entity in the wrong state for a requested transition is rejected with the
    generic `ERR_INVALID_STATE` (HTTP 409) unless a more specific rule below
    claims it."

    A second run on an already-RUNNING (no longer LOADED) batch is refused.

    Design: Corner/state_machines/run_batch_twice_returns_invalid_state
    """
    base = setup_loaded_batch(api, customer_email="rb@x.com")
    run_batch(api, base["batch"]["id"])
    resp = api.run_batch(base["batch"]["id"], TEST_USERS["lab_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
