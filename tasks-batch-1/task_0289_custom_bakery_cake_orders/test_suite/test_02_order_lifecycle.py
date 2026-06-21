"""Order production lifecycle: the proof revision loop, the parallel payment and
production axes, and terminal-state lockdown."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    proof_payload,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine
# ---------------------------------------------------------------------------
def test_proof_revision_loop_reopens_review_with_next_revision(api):
    """PRD 3.8: "Posting a subsequent proof is allowed from `CHANGES_REQUESTED`
    only when the order has no proof currently `AWAITING_REVIEW`; it creates a new
    `DesignProof` whose `revision_number` is one greater than the highest revision
    number seen so far on the order, again `AWAITING_REVIEW`, and drives the order
    back to `PROOF_PENDING`."

    Design: Difficulty/non_linear_state_machine/order_proof_revision_cycle
    """
    order, customer, proof1, product, pday = fx.setup_proof_pending_order(units=1, image_ref="r1")
    headers = make_customer_headers(customer["id"])
    validate_success(api.request_changes(order["id"], proof1["id"], {"change_note": "fix color"}, headers), 200)

    proof2 = validate_success(api.post_proof(order["id"], proof_payload("r2"), fx.STAFF), 201)
    assert proof2["revision_number"] == 2, proof2
    assert proof2["proof_status"] == "AWAITING_REVIEW", proof2

    order_after = validate_success(api.get_order(order["id"], headers), 200)
    assert order_after["production_status"] == "PROOF_PENDING", order_after


def test_request_changes_rejects_proof_and_reopens_editing(api):
    """PRD 3.8: "This moves the named proof's `proof_status` to `REJECTED` and the
    order's production status from `PROOF_PENDING` to `CHANGES_REQUESTED`,
    reopening editing, and increments the order's `version`."

    Design: Difficulty/transitive_cascade/request_changes_rejects_proof_reopens_editing
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=1, image_ref="p1")
    headers = make_customer_headers(customer["id"])
    proof_after = validate_success(
        api.request_changes(order["id"], proof["id"], {"change_note": "wrong flavor"}, headers), 200)
    assert proof_after["proof_status"] == "REJECTED", proof_after

    order_after = validate_success(api.get_order(order["id"], headers), 200)
    assert order_after["production_status"] == "CHANGES_REQUESTED", order_after


def test_request_changes_reopens_editing_allows_line_add(api):
    """PRD 3.8: "This moves the named proof's `proof_status` to `REJECTED` and the
    order's production status from `PROOF_PENDING` to `CHANGES_REQUESTED`,
    reopening editing".
    PRD 3.3: "While an order is in an editable production state - `DRAFT`, `QUOTED`,
    or `CHANGES_REQUESTED` - the customer composes its **lines**."

    After request-changes the order is editable again: adding a line succeeds.

    Design: Difficulty/transitive_cascade/request_changes_rejects_proof_reopens_editing
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=1, image_ref="reopen")
    headers = make_customer_headers(customer["id"])
    validate_success(api.request_changes(order["id"], proof["id"], {"change_note": "more"}, headers), 200)
    added = validate_success(api.add_line(order["id"], {"units": 1, "selected_option_codes": [],
                                                        "requested_dietary_codes": []}, headers), 201)
    assert added["units"] == 1, added


def test_request_changes_then_revision_two(api):
    """PRD 3.8: "This forms a cyclic revision loop between `PROOF_PENDING` and
    `CHANGES_REQUESTED` that can repeat as many times as needed, each pass
    incrementing the order's `version`."

    A second pass through request-changes reaches a second AWAITING_REVIEW proof
    at revision_number 2.

    Design: Difficulty/non_linear_state_machine/order_proof_revision_cycle
    """
    order, customer, proof1, product, pday = fx.setup_proof_pending_order(units=1, image_ref="rev1")
    headers = make_customer_headers(customer["id"])
    validate_success(api.request_changes(order["id"], proof1["id"], {"change_note": "again"}, headers), 200)
    proof2 = validate_success(api.post_proof(order["id"], proof_payload("rev2"), fx.STAFF), 201)
    assert proof2["revision_number"] == 2, proof2
    assert proof2["proof_status"] == "AWAITING_REVIEW", proof2


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine — parallel axes
# ---------------------------------------------------------------------------
def test_deposit_advances_payment_axis_production_axis_stays_quoted(api):
    """PRD 2.9: "The two axes advance independently — for instance, an order can be
    `QUOTED` on the production axis while still `UNPAID`, or `PROOF_APPROVED` while
    `DEPOSIT_PAID`."
    PRD 3.7: "Recording a **deposit payment** carries a `kind` of `DEPOSIT` and
    advances the payment axis from `UNPAID` to `DEPOSIT_PAID`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_production_axes
    """
    order, customer, product, pday = fx.setup_quoted_order(units=1)
    headers = make_customer_headers(customer["id"])
    validate_success(api.post_payment(order["id"], {"kind": "DEPOSIT"}, headers), 201)
    data = validate_success(api.get_order(order["id"], headers), 200)
    assert data["payment_status"] == "DEPOSIT_PAID", data
    assert data["production_status"] == "QUOTED", data


def test_quoted_order_can_be_unpaid_before_deposit(api):
    """PRD 2.9: "The two axes advance independently — for instance, an order can be
    `QUOTED` on the production axis while still `UNPAID`, or `PROOF_APPROVED` while
    `DEPOSIT_PAID`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_production_axes
    """
    order, customer, product, pday = fx.setup_quoted_order(units=1)
    headers = make_customer_headers(customer["id"])
    data = validate_success(api.get_order(order["id"], headers), 200)
    assert data["production_status"] == "QUOTED", data
    assert data["payment_status"] == "UNPAID", data


# ---------------------------------------------------------------------------
# Queue B: state_machines — terminal lockdown and idempotency
# ---------------------------------------------------------------------------
def test_cancel_terminal_fulfilled_order_rejected(api):
    """PRD 2.9: "Any attempt to drive a transition that is not defined from an
    entity's current state (on any of the production, payment, proof, or
    reservation axes) is rejected with `ERR_INVALID_STATE`."
    PRD 2.9: "it begins at `DRAFT`, and `FULFILLED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/approve_proof_from_terminal_fulfilled_order_invalid_state
    """
    order, customer, reservation, product, pday = fx.setup_fulfilled_order(units=1)
    headers = make_customer_headers(customer["id"])
    validate_error(api.cancel_order(order["id"], {"cancel_reason": "too late"}, headers),
                   ApiErrorId.ERR_INVALID_STATE)
    data = validate_success(api.get_order(order["id"], headers), 200)
    assert data["production_status"] == "FULFILLED", data


def test_approve_already_approved_proof_rejected(api):
    """PRD 2.9: "Any attempt to drive a transition that is not defined from an
    entity's current state ... is rejected with `ERR_INVALID_STATE`."
    PRD 3.8: "Its `proof_status` is one of `AWAITING_REVIEW`, `APPROVED`,
    `SUPERSEDED`, or `REJECTED`, beginning at `AWAITING_REVIEW`, with `APPROVED`
    and `SUPERSEDED` terminal."

    Design: Corner/state_machines/approve_proof_twice_second_attempt_invalid_state
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=1)
    headers = make_customer_headers(customer["id"])
    validate_error(api.approve_proof(order["id"], proof["id"], {}, headers),
                   ApiErrorId.ERR_INVALID_STATE)
