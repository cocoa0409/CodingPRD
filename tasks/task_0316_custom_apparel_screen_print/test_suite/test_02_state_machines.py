"""State-machine tests: the cyclic ArtProof revision loop, the Order's two independent
status axes (fulfillment x billing), proof initial state, invalid transitions, and the
billing-axis gates (invoice/pay).
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_shop_catalog,
    setup_confirmed_order,
    setup_fulfilled_order,
    setup_invoiced_order,
    create_draft_order,
    create_proof,
    submit_proof,
    get_order,
    api_client,
    TEST_USERS,
    make_customer_headers,
)

SM = TEST_USERS["shop_manager_headers"]
ART = TEST_USERS["art_staff_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# non_linear_state_machine — ArtProof revision loop (cyclic)
# ═══════════════════════════════════════════════════════════════════════════

def test_artproof_revision_loop_increments_round(api):
    """PRD §3.3: "When `ArtStaff` resubmits a proof that was in `CHANGES_REQUESTED`,
    it returns to `SUBMITTED` and its `revision_round` increments by one — this is the
    cyclic revision loop, `SUBMITTED → CHANGES_REQUESTED → SUBMITTED`".

    Design: Difficulty/non_linear_state_machine/artproof_revision_loop_cyclic
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    cust_headers = make_customer_headers(cat["customer"]["id"])
    validate_success(api.request_changes_proof(order["id"], proof["id"], cust_headers), 200)

    resubmitted = validate_success(api.submit_proof(order["id"], proof["id"], ART), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1


def test_artproof_request_changes_moves_to_changes_requested(api):
    """PRD §3.3: "A `Customer` who owns the order may then either request changes,
    sending the proof from `SUBMITTED` to `CHANGES_REQUESTED`, or approve it."

    Design: Difficulty/non_linear_state_machine/artproof_revision_loop_cyclic
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    cust_headers = make_customer_headers(cat["customer"]["id"])
    changed = validate_success(
        api.request_changes_proof(order["id"], proof["id"], cust_headers), 200
    )
    assert changed["status"] == "CHANGES_REQUESTED"


# ═══════════════════════════════════════════════════════════════════════════
# non_linear_state_machine — Order parallel fulfillment x billing axes
# ═══════════════════════════════════════════════════════════════════════════

def test_order_fulfilled_while_billing_still_unbilled(api):
    """PRD §3.9: "The billing dimension evolves independently of fulfillment beyond a
    single gate: an order may be invoiced only after it is `FULFILLED`."
    PRD §3.7: "the run moves from `RUNNING` to `COMPLETED` and cascades the order to
    `FULFILLED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_billing_dimensions
    """
    cat = setup_shop_catalog(stock_qty=200)
    parts = setup_fulfilled_order(cat, size_run={"L": 72}, good_units=72, spoiled_units=0)
    order = parts["order"]
    assert order["fulfillment_status"] == "FULFILLED"
    assert order["billing_status"] == "UNBILLED"


def test_invoice_advances_billing_axis_only(api):
    """PRD §3.9: "A `ShopManager` invoices a fulfilled order, advancing `billing_status`
    from `UNBILLED` to `INVOICED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_billing_dimensions
    """
    cat = setup_shop_catalog(stock_qty=200)
    parts = setup_invoiced_order(cat, size_run={"L": 72}, good_units=72, spoiled_units=0)
    order = parts["order"]
    assert order["billing_status"] == "INVOICED"
    assert order["fulfillment_status"] == "FULFILLED"


# ═══════════════════════════════════════════════════════════════════════════
# state_machines (corner) — initial state, invalid transition
# ═══════════════════════════════════════════════════════════════════════════

def test_new_artproof_is_draft_round_zero(api):
    """PRD §3.3: "A proof carries a `revision_round` counter that starts at 0 and a
    `status` that starts at `DRAFT`."

    Design: Corner/state_machines/artproof_initial_state_is_draft
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    proof = validate_success(
        api.create_art_proof(order["id"], {"title": "Front", "art_hash": "h1"}, ART), 201
    )
    assert proof["status"] == "DRAFT"
    assert proof["revision_round"] == 0


def test_approve_proof_from_draft_rejected(api):
    """PRD §3.3: "an attempt to drive a transition from a state that does not permit
    it fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/artproof_approve_from_draft_returns_invalid_state
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    order_v = order["version"]
    proof = create_proof(order["id"])  # still DRAFT, never submitted
    cust_headers = make_customer_headers(cat["customer"]["id"])
    res = api.approve_proof(
        order["id"], proof["id"], {"expected_order_version": order_v}, cust_headers
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    proof_now = validate_success(api.get_art_proof(order["id"], proof["id"], SM), 200)
    assert proof_now["status"] == "DRAFT"


# ═══════════════════════════════════════════════════════════════════════════
# state_machines (corner) — invoice / cancel gates
# ═══════════════════════════════════════════════════════════════════════════

def test_invoice_before_fulfilled_rejected(api):
    """PRD §3.9: "Invoicing while the order is not yet `FULFILLED` is rejected with
    `ERR_ORDER_NOT_FULFILLED`".

    Design: Corner/state_machines/order_invoice_before_fulfilled_returns_not_fulfilled
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(cat, size_run={"L": 30})
    res = api.invoice_order(parts["order"]["id"], SM)
    validate_error(res, "ERR_ORDER_NOT_FULFILLED", expected_status=409)


def test_cancel_in_production_order_rejected(api):
    """PRD §3.8: "A `ShopManager` or the owning `Customer` may cancel an order while its
    `fulfillment_status` is `DRAFT` or `CONFIRMED`; a cancel attempted from any other
    status is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_fulfilled_order_returns_not_cancellable
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(cat, size_run={"L": 30})
    order_id = parts["order"]["id"]
    # Schedule a run -> Order advances to IN_PRODUCTION (no longer cancellable).
    from test_helpers import create_press, create_production_run_payload
    press_id = create_press(cat["shop"]["id"])["id"]
    validate_success(
        api.create_production_run(
            order_id, create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z", press_id=press_id
            ), SM,
        ), 201
    )
    assert get_order(order_id)["fulfillment_status"] == "IN_PRODUCTION"
    res = api.cancel_order(order_id, SM)
    validate_error(res, "ERR_ORDER_NOT_CANCELLABLE", expected_status=409)


# ═══════════════════════════════════════════════════════════════════════════
# endpoints (corner) — pay marks an invoiced order PAID
# ═══════════════════════════════════════════════════════════════════════════

def test_pay_invoiced_order_marks_paid(api):
    """PRD §3.9: "Once invoiced, the owning `Customer` pays, advancing `billing_status`
    from `INVOICED` to `PAID`."

    Design: Corner/endpoints/pay_invoiced_order_marks_paid
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_invoiced_order(cat, size_run={"L": 30}, good_units=30, spoiled_units=0)
    cust_headers = make_customer_headers(cat["customer"]["id"])
    paid = validate_success(api.pay_order(parts["order"]["id"], cust_headers), 200)
    assert paid["billing_status"] == "PAID"
    assert paid["fulfillment_status"] == "FULFILLED"
