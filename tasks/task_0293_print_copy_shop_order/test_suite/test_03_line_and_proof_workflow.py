"""Line lifecycle, preflight, and proofing state machines."""
import pytest
from test_helpers import (
    api_client, get_success_data,
    validate_success, validate_error,
    create_shop, create_customer, create_product, create_order, add_line,
    upload_and_pass_preflight, add_pickup_fulfillment, read_order_version, confirm_order,
    pin_clock, setup_proof_line, submit_proof, setup_confirmable_copies_order,
    drive_order_to_fulfilled,
    TEST_USERS, make_customer_headers, ApiErrorId,
)

STAFF = TEST_USERS["shop_staff_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


# ─── Difficulty: transitive_cascade (preflight bubble depth-2) ───────────────
def test_preflight_pass_bubbles_line_to_preflight_ok(api):
    """PRD §3.3: "When preflight passes, the line the artwork belongs to advances from
    `OPEN` to `PREFLIGHT_OK`." PRD §3.3: "Only when both minimums are met — resolution at
    least 150 and bleed at least 3 — does the file move to `PASSED` with a null
    `preflight_reason`."

    Design: Difficulty/transitive_cascade/preflight_pass_bubbles_line_open_to_preflight_ok_depth2
    """
    shop = create_shop(name="Bubble Shop")
    cust = create_customer(shop["id"], email="h@x.com")
    prod = create_product(shop["id"], name="BW Copy", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    assert line["status"] == "OPEN"
    cust_headers = make_customer_headers(cust["id"])
    art = get_success_data(api.create_artwork(
        {"order_line_id": line["id"], "file_name": "h.pdf", "page_count": 1,
         "dpi": 600, "bleed_mm": 3}, cust_headers))
    art_after = validate_success(api.run_preflight(art["id"], OPERATOR), 200)
    assert art_after["preflight_status"] == "PASSED"
    line_after = get_success_data(api.get_order_line(line["id"], cust_headers))
    assert line_after["status"] == "PREFLIGHT_OK"


def test_preflight_pass_clears_reason_and_line_advances(api):
    """PRD §3.3: "When preflight passes, the line the artwork belongs to advances from
    `OPEN` to `PREFLIGHT_OK`." PRD §3.3: "does the file move to `PASSED` with a null
    `preflight_reason`."

    Design: Difficulty/transitive_cascade/preflight_pass_bubbles_line_open_to_preflight_ok_depth2
    """
    shop = create_shop(name="Bubble Shop 2")
    cust = create_customer(shop["id"], email="h2@x.com")
    prod = create_product(shop["id"], name="BW Copy", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    art = upload_and_pass_preflight(line["id"], cust["id"], dpi=150, bleed_mm=3)
    assert art["preflight_status"] == "PASSED"
    assert art["preflight_reason"] is None
    line_after = get_success_data(api.get_order_line(line["id"], make_customer_headers(cust["id"])))
    assert line_after["status"] == "PREFLIGHT_OK"


# ─── Difficulty: non_linear_state_machine (proof cycle) ──────────────────────
def test_proof_cycle_request_changes_then_resubmit_round_two(api):
    """PRD §3.4: "A valid request-changes moves the proof from `SUBMITTED` to
    `CHANGES_REQUESTED` and reopens the line, reverting it from `PROOF_PENDING` back to
    `PREFLIGHT_OK` so a fresh round can begin." PRD §3.4: "the operator submits the next
    round against the same `PREFLIGHT_OK` line; this creates a new proof whose
    `round_number` is one greater than the prior proof's, in status `SUBMITTED`, and
    drives the line back to `PROOF_PENDING`."

    Design: Difficulty/non_linear_state_machine/proof_cycle_submitted_changes_requested_resubmit
    """
    ctx = setup_proof_line(shop_overrides={"name": "Proof Shop"})
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    proof1 = submit_proof(ctx["line"]["id"])
    assert proof1["round_number"] == 1
    get_success_data(api.request_changes(proof1["id"], {"change_note": "Logo too small"}, cust_headers))
    line_reopened = get_success_data(api.get_order_line(ctx["line"]["id"], cust_headers))
    assert line_reopened["status"] == "PREFLIGHT_OK"
    proof2 = submit_proof(ctx["line"]["id"])
    assert proof2["round_number"] == 2
    assert proof2["status"] == "SUBMITTED"
    line_after = get_success_data(api.get_order_line(ctx["line"]["id"], cust_headers))
    assert line_after["status"] == "PROOF_PENDING"


def test_proof_request_changes_reverts_line_to_preflight_ok(api):
    """PRD §3.4: "A valid request-changes moves the proof from `SUBMITTED` to
    `CHANGES_REQUESTED` and reopens the line, reverting it from `PROOF_PENDING` back to
    `PREFLIGHT_OK` so a fresh round can begin."

    Design: Difficulty/non_linear_state_machine/proof_cycle_submitted_changes_requested_resubmit
    """
    ctx = setup_proof_line(shop_overrides={"name": "Proof Shop 2"})
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    proof1 = submit_proof(ctx["line"]["id"])
    line_pending = get_success_data(api.get_order_line(ctx["line"]["id"], cust_headers))
    assert line_pending["status"] == "PROOF_PENDING"
    proof_after = validate_success(
        api.request_changes(proof1["id"], {"change_note": "Move logo"}, cust_headers), 200)
    assert proof_after["status"] == "CHANGES_REQUESTED"
    line_after = get_success_data(api.get_order_line(ctx["line"]["id"], cust_headers))
    assert line_after["status"] == "PREFLIGHT_OK"


# ─── Difficulty: non_linear_state_machine (parallel dimensions) ──────────────
def test_order_parallel_dimensions_paid_while_confirmed(api):
    """PRD §2.7: "The two dimensions are not slaved to one another — an order can be
    `CONFIRMED` while still `UNPAID`, or `IN_PRODUCTION` while `INVOICED`". PRD §3.7: "A
    successful payment moves `payment_status` from `INVOICED` to `PAID`".

    Design: Difficulty/non_linear_state_machine/order_parallel_production_and_payment_dimensions
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "Parallel Shop"}, quantity=10)
    cust = ctx["customer"]
    order_id = ctx["order"]["id"]
    confirmed = validate_success(confirm_order(order_id, cust["id"], ctx["version"]), 200)
    total = confirmed["total_cents"]
    get_success_data(api.invoice_order(order_id, STAFF))
    paid = validate_success(
        api.pay_order(order_id, {"amount_cents": total}, make_customer_headers(cust["id"])), 200)
    assert paid["payment_status"] == "PAID"
    assert paid["production_status"] == "CONFIRMED", "production unaffected by payment dimension"


def test_order_confirmed_starts_unpaid(api):
    """PRD §2.7: "The two dimensions are not slaved to one another — an order can be
    `CONFIRMED` while still `UNPAID`". PRD §3.2: "A fresh order begins with
    `production_status` `DRAFT` and `payment_status` `UNPAID`".

    Design: Difficulty/non_linear_state_machine/order_parallel_production_and_payment_dimensions
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "Parallel Shop 2"}, quantity=10)
    cust = ctx["customer"]
    confirmed = validate_success(confirm_order(ctx["order"]["id"], cust["id"], ctx["version"]), 200)
    assert confirmed["production_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "UNPAID", "confirm does not touch payment dimension"


# ─── State-machine preconditions and transitions ─────────────────────────────
def test_order_initial_state_is_draft_unpaid(api):
    """PRD §3.2: "A fresh order begins with `production_status` `DRAFT` and `payment_status`
    `UNPAID`".

    Design: Corner/state_machines/order_initial_state_is_draft_unpaid
    """
    shop = create_shop(name="S10")
    cust = create_customer(shop["id"], email="s10@x.com")
    order = create_order(shop["id"], cust["id"])
    assert order["production_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"


def test_cancel_fulfilled_order_returns_invalid_state(api):
    """PRD §3.8: "Cancellation is available to the owning customer while the order's
    `production_status` is `DRAFT` or `CONFIRMED`". PRD §3.9: "State validity comes fifth,
    yielding `ERR_INVALID_STATE` when a target is not in a state that permits the requested
    transition."

    Design: Corner/state_machines/cancel_already_fulfilled_order_returns_invalid_state
    """
    ctx = drive_order_to_fulfilled(quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    order_id = ctx["order"]["id"]
    fulfilled = get_success_data(api.get_order(order_id, cust_headers))
    assert fulfilled["production_status"] == "FULFILLED"
    res = api.cancel_order(order_id, {"expected_order_version": fulfilled["version"]}, cust_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_approve_already_approved_proof_returns_invalid_state(api):
    """PRD §3.4: "Approving the proof moves it from `SUBMITTED` to `APPROVED`". PRD §3.9:
    "State validity comes fifth, yielding `ERR_INVALID_STATE` when a target is not in a
    state that permits the requested transition."

    Design: Corner/state_machines/approve_already_approved_proof_returns_invalid_state
    """
    ctx = setup_proof_line(shop_overrides={"name": "S12"})
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    proof = submit_proof(ctx["line"]["id"])
    validate_success(api.approve_proof(proof["id"], cust_headers), 200)
    res = api.approve_proof(proof["id"], cust_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_submit_proof_for_non_proof_product_rejected(api):
    """PRD §3.4: "Submitting a proof for a line whose product does not require one is
    rejected with `ERR_PROOF_NOT_REQUIRED` (HTTP 409)".

    Design: Corner/state_machines/submit_proof_for_non_proof_product_rejected
    """
    shop = create_shop(name="S13")
    cust = create_customer(shop["id"], email="s13@x.com")
    prod = create_product(shop["id"], name="NoProof", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    upload_and_pass_preflight(line["id"], cust["id"])
    res = api.create_proof({"order_line_id": line["id"]}, OPERATOR)
    validate_error(res, ApiErrorId.ERR_PROOF_NOT_REQUIRED, expected_status=409)


def test_preflight_fail_low_dpi_sets_failed_with_reason(api):
    """PRD §3.3: "If the declared `dpi` is below 150, the file moves to `preflight_status`
    `FAILED` and `preflight_reason` records the DPI shortfall." PRD §3.3: "A failed file is
    not a dead end" (the line is not advanced).

    Design: Corner/state_machines/preflight_fail_sets_failed_with_reason
    """
    shop = create_shop(name="S14")
    cust = create_customer(shop["id"], email="s14@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    cust_headers = make_customer_headers(cust["id"])
    art = get_success_data(api.create_artwork(
        {"order_line_id": line["id"], "file_name": "s14.pdf", "page_count": 1,
         "dpi": 100, "bleed_mm": 3}, cust_headers))
    art_after = validate_success(api.run_preflight(art["id"], OPERATOR), 200)
    assert art_after["preflight_status"] == "FAILED"
    assert art_after["preflight_reason"] is not None
    line_after = get_success_data(api.get_order_line(line["id"], cust_headers))
    assert line_after["status"] == "OPEN", "failed preflight does not advance the line"


def test_produce_before_pricelock_returns_invalid_state(api):
    """PRD §3.7: "The operator marks each locked line produced once the order is in
    production and the line is `PRICE_LOCKED`, advancing that line from `PRICE_LOCKED` to
    `PRODUCED`." PRD §3.9: "State validity comes fifth, yielding `ERR_INVALID_STATE` when a
    target is not in a state that permits the requested transition."

    Design: Corner/state_machines/produce_before_pricelock_returns_invalid_state
    """
    shop = create_shop(name="S15")
    cust = create_customer(shop["id"], email="s15@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    res = api.produce_order_line(line["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
