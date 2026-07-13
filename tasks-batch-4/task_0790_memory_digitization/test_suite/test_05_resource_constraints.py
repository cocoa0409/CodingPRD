"""Resource and precedence constraints: half-open machine reservations,
aggregate bin retention capacity, and the two validation-precedence pairs."""
from test_helpers import (
    ApiErrorId, validate_error, validate_success, TEST_USERS,
    create_customer, create_order, log_media_item, get_order_admin,
    authorize_payment, receive_order, create_bin, set_clock, make_customer_headers,
    setup_machine_with_batch, setup_bin_with_one_item,
)


# ===========================================================================
# resource_temporal_overlap / machine_pairwise_halfopen_double_book
# ===========================================================================
def test_overlapping_batch_on_same_machine_rejected(api):
    """PRD §3.4: "The reservation window is half-open: a new batch's window must
    not overlap any existing batch's window on the same machine, though two
    windows that merely touch at an endpoint (one ends exactly where the next
    begins) are allowed. An overlapping reservation is rejected with
    `ERR_MACHINE_DOUBLE_BOOKED` (HTTP 409)."

    A [09:30,10:30) window strictly overlaps an existing [09:00,10:00) on the
    same machine.

    Design: Difficulty/resource_temporal_overlap/machine_pairwise_halfopen_double_book
    """
    base = setup_machine_with_batch(api)
    resp = api.create_batch(
        {"machine_id": base["machine_id"],
         "scheduled_start": "2026-03-01T09:30:00Z",
         "scheduled_end": "2026-03-01T10:30:00Z"},
        TEST_USERS["lab_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_MACHINE_DOUBLE_BOOKED)


def test_adjacent_batch_on_same_machine_allowed(api):
    """PRD §3.4: "The reservation window is half-open: a new batch's window must
    not overlap any existing batch's window on the same machine, though two
    windows that merely touch at an endpoint (one ends exactly where the next
    begins) are allowed. An overlapping reservation is rejected with
    `ERR_MACHINE_DOUBLE_BOOKED` (HTTP 409)."

    A [10:00,11:00) window that begins exactly where the existing [09:00,10:00)
    ends is adjacency, not overlap, and is accepted.

    Design: Difficulty/resource_temporal_overlap/machine_pairwise_halfopen_double_book
    """
    base = setup_machine_with_batch(api)
    resp = api.create_batch(
        {"machine_id": base["machine_id"],
         "scheduled_start": "2026-03-01T10:00:00Z",
         "scheduled_end": "2026-03-01T11:00:00Z"},
        TEST_USERS["lab_headers"],
    )
    batch = validate_success(resp, expected_status=201)
    assert batch["status"] == "OPEN", batch


# ===========================================================================
# resource_temporal_overlap / bin_aggregate_capacity_overlap
# ===========================================================================
def test_bin_overflow_when_overlap_exceeds_capacity(api):
    """PRD §3.3: "Assigning a media item to a bin must not push the number of
    overlapping retention windows in that bin above its `capacity`: treating each
    item's occupancy as the half-open interval from its `stored_at` up to but not
    including its `retention_until`, if admitting the new item would make the
    count of mutually overlapping windows exceed the bin's capacity, the intake
    is rejected with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409)."

    A capacity-1 bin already holds one item whose 30-day window covers the clock;
    logging a second overlapping item exceeds capacity.

    Design: Difficulty/resource_temporal_overlap/bin_aggregate_capacity_overlap
    """
    base = setup_bin_with_one_item(api, capacity=1, customer_email="bin-of@x.com")
    resp = api.create_media_item(
        base["order_id"], {"media_type": "TAPE", "bin_id": base["bin_id"]},
        TEST_USERS["intake_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED)


def test_bin_admits_second_item_within_capacity(api):
    """PRD §3.3: "Assigning a media item to a bin must not push the number of
    overlapping retention windows in that bin above its `capacity`: treating each
    item's occupancy as the half-open interval from its `stored_at` up to but not
    including its `retention_until`, if admitting the new item would make the
    count of mutually overlapping windows exceed the bin's capacity, the intake
    is rejected with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409)."

    A capacity-2 bin holding one item admits a second overlapping item because
    the count (2) does not exceed capacity.

    Design: Difficulty/resource_temporal_overlap/bin_aggregate_capacity_overlap
    """
    base = setup_bin_with_one_item(api, capacity=2, customer_email="bin-ok@x.com")
    resp = api.create_media_item(
        base["order_id"], {"media_type": "TAPE", "bin_id": base["bin_id"]},
        TEST_USERS["intake_headers"],
    )
    item = validate_success(resp, expected_status=201)
    assert item["status"] == "LOGGED", item


# ===========================================================================
# priority_pair_validation_conflict / output_state_beats_fiscal
# ===========================================================================
def test_output_readiness_precedes_capture_check_when_quoted(api):
    """PRD §3.6: "First, the order's `fulfillment_status` must be `READY`;
    otherwise the request is rejected with `ERR_ORDER_NOT_READY` (HTTP 409).
    Second, the order's `payment_status` must be `CAPTURED`; otherwise the
    request is rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 402)."

    A freshly QUOTED, UNPAID order is neither READY nor CAPTURED; the readiness
    check fires first, so the state error (not the fiscal error) is returned.

    Design: Difficulty/priority_pair_validation_conflict/output_state_beats_fiscal
    """
    cust = create_customer(api, email="pc-of1@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    resp = api.create_output_artifact(
        order["id"],
        {"output_type": "CLOUD", "expected_order_version": order["version"]},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_READY)


def test_output_readiness_precedes_capture_check_when_authorized(api):
    """PRD §2.9: "Where several domain rules apply to one endpoint, the more
    foundational readiness checks are evaluated ahead of the more specific ones —
    for example, on deliverable generation the order-readiness check precedes the
    payment-capture check, which in turn precedes the stale-version check."

    An authorized-but-uncaptured order that is not READY still yields the
    readiness error ahead of the fiscal error.

    Design: Difficulty/priority_pair_validation_conflict/output_state_beats_fiscal
    """
    from test_helpers import authorize_payment
    cust = create_customer(api, email="pc-of2@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    authorize_payment(api, order["id"], cust["id"])
    current = get_order_admin(api, order["id"])
    resp = api.create_output_artifact(
        order["id"],
        {"output_type": "CLOUD", "expected_order_version": current["version"]},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_READY)


# ===========================================================================
# priority_pair_validation_conflict / claim_referential_beats_temporal
# ===========================================================================
def test_claim_media_not_in_order_after_window_advanced(api):
    """PRD §3.7: "A claim names the `order_id` it is filed against and the
    `media_item_id` of the affected item, and that media item must belong to the
    named order — its `order_id` must match the claim's `order_id`; a mismatch is
    rejected with `ERR_MEDIA_NOT_IN_ORDER` (HTTP 422)."

    A claim naming order A but a media item that belongs to order B is a
    membership mismatch. Order A never reached READY, so no claim-window anchor
    exists and only the referential error can fire.

    Design: Difficulty/priority_pair_validation_conflict/claim_referential_beats_temporal
    """
    cust = create_customer(api, email="pc-rt1@x.com")
    order_a = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    order_b = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    from test_helpers import authorize_payment, receive_order, create_bin
    authorize_payment(api, order_b["id"], cust["id"])
    receive_order(api, order_b["id"])
    bin_ = create_bin(api, capacity=10)
    mi_b = log_media_item(api, order_b["id"], bin_["id"], "TAPE")
    set_clock(api, "2026-12-01T00:00:00Z")
    resp = api.create_damage_claim(
        {"order_id": order_a["id"], "media_item_id": mi_b["id"], "claim_type": "LOST"},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEDIA_NOT_IN_ORDER)


def test_claim_media_not_in_order_without_window_advance(api):
    """PRD §3.7: "A claim names the `order_id` it is filed against and the
    `media_item_id` of the affected item, and that media item must belong to the
    named order — its `order_id` must match the claim's `order_id`; a mismatch is
    rejected with `ERR_MEDIA_NOT_IN_ORDER` (HTTP 422)."

    The membership check is independent of timing: even at the default clock
    (well inside any window), a media item from a different order is rejected.

    Design: Difficulty/priority_pair_validation_conflict/claim_referential_beats_temporal
    """
    cust = create_customer(api, email="pc-rt2@x.com")
    order_a = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    order_b = create_order(api, cust["id"], declared={"declared_tape_count": 1})
    from test_helpers import authorize_payment, receive_order, create_bin
    authorize_payment(api, order_b["id"], cust["id"])
    receive_order(api, order_b["id"])
    bin_ = create_bin(api, capacity=10)
    mi_b = log_media_item(api, order_b["id"], bin_["id"], "TAPE")
    resp = api.create_damage_claim(
        {"order_id": order_a["id"], "media_item_id": mi_b["id"], "claim_type": "LOST"},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEDIA_NOT_IN_ORDER)
