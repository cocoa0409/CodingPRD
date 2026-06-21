"""Escrow trust accounting: deposits, disbursements, wires, balances, compensating invariants.

Covers queue A: transitive_cascade (disbursement wire autoclose), boundary_precision
(amount == balance), compensating_invariant (deposit post/reverse), plus queue B
calculations / validations / consistency_model corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_order_clear_to_close,
    create_agency_and_order,
    add_posted_deposit,
    add_approved_disbursement,
    add_wired_disbursement,
    get_order,
    make_agency_headers,
    assert_escrow_invariants,
    UW,
)


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: wire drives balance to 0 then auto-closes order
# ---------------------------------------------------------------------------
def test_wire_drives_balance_to_zero_and_autocloses_order(api):
    """PRD §3.7: "A successful wire fires Cascade B: `escrow_disbursed_total_cents` grows
    by the wired `amount_cents`, `escrow_balance_cents` is recomputed, and if the balance
    reaches zero while the order is in `CLEAR_TO_CLOSE`, the order auto-transitions to
    `CLOSED` with `gap_open` set false, as described in §2.5."
    Deposit 300000 (balance 300000), wire exactly 300000.

    Design: Difficulty/transitive_cascade/disbursement_wire_cascade_depth2_balance_autoclose
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=300_000, source_ref="WIRE-IN-A")
    disb = add_approved_disbursement(order, amount_cents=300_000, purpose="SELLER_PROCEEDS")
    data = validate_success(api.transition_disbursement(disb["id"], {"to_status": "WIRED"}, UW))
    assert data["status"] == "WIRED"
    final_order = get_order(order["id"])
    assert final_order["escrow_balance_cents"] == 0, "balance must be 0 after the full wire"
    assert final_order["status"] == "CLOSED", "order must auto-close from CLEAR_TO_CLOSE on zero balance"


def test_wire_autoclose_sets_gap_open_false(api):
    """PRD §3.7: "if the balance reaches zero while the order is in `CLEAR_TO_CLOSE`, the
    order auto-transitions to `CLOSED` with `gap_open` set false, as described in §2.5."

    Design: Difficulty/transitive_cascade/disbursement_wire_cascade_depth2_balance_autoclose
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=300_000, source_ref="WIRE-IN-B")
    disb = add_approved_disbursement(order, amount_cents=300_000, purpose="SELLER_PROCEEDS")
    validate_success(api.transition_disbursement(disb["id"], {"to_status": "WIRED"}, UW))
    final_order = get_order(order["id"])
    assert final_order["status"] == "CLOSED"
    assert final_order["gap_open"] is False, "gap_open must be false after auto-close"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision: amount exactly equals balance (inclusive <=)
# ---------------------------------------------------------------------------
def test_wire_amount_exactly_equals_balance_allowed(api):
    """PRD §3.7: "The `amount_cents` must be less than or equal to the order's current
    `escrow_balance_cents` (otherwise `ERR_INSUFFICIENT_ESCROW`)".
    Amount 300000 == balance 300000 is allowed and drives the balance to 0.

    Design: Difficulty/boundary_precision_check/disbursement_amount_exactly_equals_balance
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=300_000, source_ref="WIRE-IN-C")
    disb = add_approved_disbursement(order, amount_cents=300_000, purpose="SELLER_PROCEEDS")
    data = validate_success(api.transition_disbursement(disb["id"], {"to_status": "WIRED"}, UW))
    assert data["status"] == "WIRED"
    assert get_order(order["id"])["escrow_balance_cents"] == 0


def test_wire_amount_one_cent_over_balance_rejected(api):
    """PRD §3.7: "The `amount_cents` must be less than or equal to the order's current
    `escrow_balance_cents` (otherwise `ERR_INSUFFICIENT_ESCROW`)".
    Amount balance+1 (300001 over 300000) is rejected.

    Design: Difficulty/boundary_precision_check/disbursement_amount_exactly_equals_balance
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=300_000, source_ref="WIRE-IN-D")
    disb = add_approved_disbursement(order, amount_cents=300_001, purpose="SELLER_PROCEEDS")
    validate_error(
        api.transition_disbursement(disb["id"], {"to_status": "WIRED"}, UW),
        ApiErrorId.ERR_INSUFFICIENT_ESCROW.value,
    )
    assert get_order(order["id"])["escrow_balance_cents"] == 300_000, "balance unchanged after rejection"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant: deposit post then reverse returns to prior value
# ---------------------------------------------------------------------------
def test_deposit_post_then_reverse_returns_balance_to_zero(api):
    """PRD §3.7: "a posted deposit may later be reversed to `REVERSED` as a compensating
    action, but a reversal is refused if it would drive `escrow_balance_cents` below zero
    (`ERR_ESCROW_WOULD_GO_NEGATIVE`). ... Posting or reversing a deposit recomputes the
    order's escrow totals."
    Post 500000 (balance 500000), then reverse it -> balance back to 0.

    Design: Difficulty/compensating_invariant/escrow_cash_invariant_deposit_post_then_reverse
    """
    agency, order = create_agency_and_order()
    deposit = add_posted_deposit(order, agency, amount_cents=500_000, source_ref="WIRE-IN-E")
    after_post = get_order(order["id"])
    assert after_post["escrow_balance_cents"] == 500_000, "balance 500000 after POST"
    validate_success(api.transition_deposit(deposit["id"], {"to_status": "REVERSED"}, UW))
    after_reverse = get_order(order["id"])
    assert after_reverse["escrow_deposit_total_cents"] == 0, "deposit total back to 0 after reversal"
    assert after_reverse["escrow_balance_cents"] == 0, "balance back to 0 after reversal"
    assert_escrow_invariants(after_reverse)


def test_only_posted_deposits_count_toward_escrow_total(api):
    """PRD §3.7: "`escrow_deposit_total_cents` is the sum of `amount_cents` across the
    order's deposits in `POSTED`."
    A still-RECEIVED deposit contributes 0; the escrow total reflects only the POSTED one.

    Design: Difficulty/compensating_invariant/escrow_cash_invariant_deposit_post_then_reverse
    """
    agency, order = create_agency_and_order()
    # One RECEIVED-only deposit (never posted) must not count.
    validate_success(
        api.create_deposit(order["id"], {"amount_cents": 700_000, "source_ref": "WIRE-IN-RX"},
                           make_agency_headers(agency["id"])),
        expected_status=201,
    )
    add_posted_deposit(order, agency, amount_cents=400_000, source_ref="WIRE-IN-RP")
    data = get_order(order["id"])
    assert data["escrow_deposit_total_cents"] == 400_000, (
        f"Only POSTED deposits count; expected 400000, got {data['escrow_deposit_total_cents']}"
    )
    assert data["escrow_balance_cents"] == 400_000
    assert_escrow_invariants(data)


# ---------------------------------------------------------------------------
# Queue B — calculations: partial disbursement balance
# ---------------------------------------------------------------------------
def test_escrow_balance_after_partial_disbursement(api):
    """PRD §3.7: "`escrow_balance_cents` is the deposit total minus the disbursed total,
    in exact integer cents — the live trust balance the close, cancel, reversal, and wire
    checks all read."
    Posted 500000 minus wired 300000 -> balance 200000, disbursed_total 300000.

    Design: Corner/calculations/escrow_balance_after_partial_disbursement
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=500_000, source_ref="WIRE-IN-F")
    add_wired_disbursement(order, amount_cents=300_000, purpose="PAYOFF", payee="Payoff Bank")
    final_order = get_order(order["id"])
    assert final_order["escrow_disbursed_total_cents"] == 300_000, (
        f"Expected disbursed_total 300000, got {final_order['escrow_disbursed_total_cents']}"
    )
    assert final_order["escrow_balance_cents"] == 200_000, (
        f"Expected balance 200000, got {final_order['escrow_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# Queue B — validations: deposit reversal would go negative
# ---------------------------------------------------------------------------
def test_deposit_reversal_that_would_go_negative_rejected(api):
    """PRD §3.7: "a posted deposit may later be reversed to `REVERSED` as a compensating
    action, but a reversal is refused if it would drive `escrow_balance_cents` below zero
    (`ERR_ESCROW_WOULD_GO_NEGATIVE`)."
    Deposit 300000 posted, 300000 wired out (balance 0); reversing the deposit would
    make balance -300000.

    Design: Corner/validations/deposit_reversal_would_go_negative_rejected
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    deposit = add_posted_deposit(order, agency, amount_cents=300_000, source_ref="WIRE-IN-G")
    # Wire the full balance out (this also auto-closes the order, which is fine).
    add_wired_disbursement(order, amount_cents=300_000, purpose="SELLER_PROCEEDS")
    validate_error(
        api.transition_deposit(deposit["id"], {"to_status": "REVERSED"}, UW),
        ApiErrorId.ERR_ESCROW_WOULD_GO_NEGATIVE.value,
    )
    refetched = validate_success(api.get_deposit(deposit["id"], UW))
    assert refetched["status"] == "POSTED", "deposit must remain POSTED after refused reversal"


# ---------------------------------------------------------------------------
# Queue B — consistency_model: immediate escrow visibility
# ---------------------------------------------------------------------------
def test_posted_deposit_immediately_visible_in_next_get(api):
    """PRD §3.7: "An underwriter posts it to `POSTED`, and only at that point does it count
    toward the trust balance".

    Design: Corner/consistency_model/immediate_escrow_visible_same_request
    """
    agency, order = create_agency_and_order()
    add_posted_deposit(order, agency, amount_cents=250_000, source_ref="WIRE-IN-H")
    data = get_order(order["id"])
    assert data["escrow_balance_cents"] == 250_000, (
        f"Expected immediate balance 250000, got {data['escrow_balance_cents']}"
    )
