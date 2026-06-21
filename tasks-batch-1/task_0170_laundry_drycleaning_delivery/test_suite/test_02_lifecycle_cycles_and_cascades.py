"""Cyclic state machines and multi-hop cascades.

Covers the order rework loop, the claim appeal loop, the depth-3 cancel cascade,
and the depth-2 settle cascade. Side effects asserted are those PRD prose names.
"""
import test_helpers as th


def test_order_qc_rework_cycle_clears_final_total(api):
    """PRD §3.5: "Reopening requires the order to be in `QC_HOLD` (otherwise
    `ERR_INVALID_ORDER_STATE`) and either that at least one garment has been
    moved from `CLEANED` to `CLEANING` (a rewash) since the order entered
    `QC_HOLD`, or that the caller explicitly requests rework by setting
    `rework_requested`"
    PRD §3.5: "Reopening clears `final_total_cents` back to 0 - it will be
    recomputed the next time the order returns to `QC_HOLD`."

    Design: Difficulty/non_linear_state_machine/order_qc_rework_cycle
    """
    customer, pickup, delivery, order, garments = th.order_at_qc_hold(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}],
        actuals=[{"actual_weight_grams": 3000}],
    )
    # rewash one garment (CLEANED -> CLEANING) while order is in QC_HOLD
    th.validate_success(api.rewash(order["id"], garments[0]["id"], th.plant_headers()))
    reopened = th.validate_success(
        api.reopen_processing(order["id"], th.plant_headers(), {"rework_requested": True}))
    assert reopened["status"] == "IN_PROCESSING", \
        f"reopen returns to IN_PROCESSING, got {reopened['status']}"
    assert reopened["final_total_cents"] == 0, \
        f"reopen clears final_total to 0, got {reopened['final_total_cents']}"

    garment = th.validate_success(
        api.get_garment(order["id"], garments[0]["id"], th.plant_headers()))
    assert garment["status"] == "CLEANING", \
        f"rewashed garment is CLEANING, got {garment['status']}"


def test_order_qc_rework_cycle_loops_back_to_processing(api):
    """PRD §3.5: "This completes the order-level cyclic rework relationship
    `IN_PROCESSING -> QC_HOLD -> IN_PROCESSING`."

    Verifies the loop is genuinely cyclic: an order at QC_HOLD reopens to
    IN_PROCESSING and the rewashed garment returns to CLEANING.

    Design: Difficulty/non_linear_state_machine/order_qc_rework_cycle
    """
    customer, pickup, delivery, order, garments = th.order_at_qc_hold(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}],
        actuals=[{"actual_weight_grams": 3000}],
    )
    th.validate_success(api.rewash(order["id"], garments[0]["id"], th.plant_headers()))
    reopened = th.validate_success(
        api.reopen_processing(order["id"], th.plant_headers(), {"rework_requested": True}))
    assert reopened["status"] == "IN_PROCESSING"
    # re-finish then re-hold proves the loop is traversable a second time
    th.finish_clean(order, garments[0])
    held_again = th.validate_success(api.qc_hold(order["id"], th.plant_headers()))
    assert held_again["status"] == "QC_HOLD", \
        f"order re-enters QC_HOLD after rework, got {held_again['status']}"


def test_claim_reject_appeal_cycle_increments_appeal_count(api):
    """PRD §3.10: "Appealing ... moves the claim from `REJECTED` back to
    `INVESTIGATING`, requires it to be in `REJECTED` (otherwise
    `ERR_INVALID_CLAIM_STATE`), requires `appeal_count` to be strictly less than
    the maximum allowed appeals (otherwise `ERR_APPEAL_LIMIT_REACHED`), and
    increments `appeal_count` by one; this is the cyclic appeal relationship
    `REJECTED -> INVESTIGATING`."

    Design: Difficulty/non_linear_state_machine/claim_reject_appeal_cycle
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}])
    claim = th.file_claim(order, customer, subject_kind="ORDER", declared_value_cents=5000)
    th.investigate(claim)
    th.reject(claim)
    appealed = th.validate_success(
        api.appeal_claim(claim["id"], th.make_customer_headers(customer["id"])))
    assert appealed["status"] == "INVESTIGATING", \
        f"appeal returns to INVESTIGATING, got {appealed['status']}"
    assert appealed["appeal_count"] == 1, \
        f"appeal_count increments to 1, got {appealed['appeal_count']}"


def test_claim_appeal_count_starts_at_zero_then_one(api):
    """PRD §3.10: "A new claim begins in `SUBMITTED` status with
    `settlement_cents` 0 and `appeal_count` 0."
    PRD §3.10: "increments `appeal_count` by one; this is the cyclic appeal
    relationship `REJECTED -> INVESTIGATING`."

    Design: Difficulty/non_linear_state_machine/claim_reject_appeal_cycle
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}])
    claim = th.file_claim(order, customer, subject_kind="ORDER", declared_value_cents=5000)
    assert claim["appeal_count"] == 0, "new claim starts at appeal_count 0"
    th.investigate(claim)
    th.reject(claim)
    appealed = th.validate_success(
        api.appeal_claim(claim["id"], th.make_customer_headers(customer["id"])))
    assert appealed["appeal_count"] == 1, \
        f"first appeal moves appeal_count to 1, got {appealed['appeal_count']}"


def test_cancel_ready_order_depth3_cascade(api):
    """PRD §3.7: "Any `DRAFT` invoice for this order is voided, moving to `VOID`:
    voiding restores the reserved `wallet_applied_cents` back to the customer's
    `wallet_credit_cents`"
    PRD §3.7: "Any locker assignment for this order that is `RESERVED` or
    `OCCUPIED` is moved to `RELEASED`, freeing its compartment."
    PRD §3.7: "A successful cancel moves the order to `CANCELLED`, its terminal
    cancelled state, and increments the order's `version` by one."

    Wallet seeded to 500; LOCKER order to READY (DRAFT invoice). Cancel -> order
    CANCELLED -> invoice VOID -> wallet restored to 500 -> assignment RELEASED.

    Design: Difficulty/transitive_cascade/cancel_order_depth3_cascade
    """
    customer, pickup, delivery = th.create_zone_setup()
    locker = th.create_locker(zone_code="Z1", compartment_count=4, hold_buffer_minutes=30)
    # seed wallet 500 via a settled GARMENT claim (declared 625 -> 500 after 20% depreciation)
    th.seed_wallet_via_settled_claim(customer, pickup, delivery, declared_value_cents=625)

    _, _, _, order, garments = th.order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        order_overrides={"handoff_method": "LOCKER"},
    )
    assignment = th.create_locker_assignment(order, locker, compartment_index=1)

    ov = th.get_order(order["id"], customer["id"])["version"]
    cancelled = th.validate_success(
        api.cancel_order(order["id"], {"expected_order_version": ov},
                         th.make_customer_headers(customer["id"])))
    assert cancelled["status"] == "CANCELLED", \
        f"order should be CANCELLED, got {cancelled['status']}"

    invoices, _ = th.validate_paginated(
        api.get_order_invoice(order["id"], th.make_customer_headers(customer["id"])))
    assert invoices[0]["status"] == "VOID", \
        f"DRAFT invoice should VOID on cancel, got {invoices[0]['status']}"

    refreshed = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert refreshed["wallet_credit_cents"] == 500, \
        f"wallet restored to 500, got {refreshed['wallet_credit_cents']}"

    refreshed_la = th.validate_success(
        api.get_locker_assignment(assignment["id"], th.dispatch_headers()))
    assert refreshed_la["status"] == "RELEASED", \
        f"assignment should be RELEASED, got {refreshed_la['status']}"


def test_cancel_ready_order_releases_locker_compartment(api):
    """PRD §3.7: "Any locker assignment for this order that is `RESERVED` or
    `OCCUPIED` is moved to `RELEASED`, freeing its compartment."
    PRD §3.7: "A successful cancel moves the order to `CANCELLED`, its terminal
    cancelled state, and increments the order's `version` by one."

    Focuses the cascade's locker hop: a RESERVED assignment on a cancelled READY
    order moves to RELEASED, and the order version increments.

    Design: Difficulty/transitive_cascade/cancel_order_depth3_cascade
    """
    customer, pickup, delivery, order, garments, locker, assignment = \
        th.ready_locker_order_with_assignment()
    ov = th.get_order(order["id"], customer["id"])["version"]
    cancelled = th.validate_success(
        api.cancel_order(order["id"], {"expected_order_version": ov},
                         th.make_customer_headers(customer["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == ov + 1, \
        f"cancel increments order version: {ov}->{cancelled['version']}"
    refreshed_la = th.validate_success(
        api.get_locker_assignment(assignment["id"], th.dispatch_headers()))
    assert refreshed_la["status"] == "RELEASED", \
        f"assignment freed on cancel, got {refreshed_la['status']}"


def test_settle_claim_depth2_cascade_wallet_and_risk(api):
    """PRD §3.10: "Settling credits the computed `settlement_cents` to the owning
    customer's `wallet_credit_cents` and adds 25 points to that customer's
    `risk_score`."
    PRD §3.8: "Marking a garment lost adds a fixed 15 points for the lost garment."

    DRY_CLEAN garment lost (+15 risk), claim declared 10000 -> settle 8000 (wallet
    +8000) and +25 risk => risk 40, wallet 8000.

    Design: Difficulty/transitive_cascade/mark_lost_then_settle_depth2_cascade
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        actuals=[{"actual_piece_count": 1}],
    )
    th.mark_lost(order, garments[0])
    settled = th.settle_garment_claim(order, customer, garments[0], declared_value_cents=10000)
    assert settled["status"] == "SETTLED", f"claim should be SETTLED, got {settled['status']}"
    assert settled["settlement_cents"] == 8000, \
        f"settlement should be 8000, got {settled['settlement_cents']}"

    refreshed = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert refreshed["wallet_credit_cents"] == 8000, \
        f"wallet should be 8000, got {refreshed['wallet_credit_cents']}"
    assert refreshed["risk_score"] == 40, \
        f"risk should be 15(lost)+25(settle)=40, got {refreshed['risk_score']}"


def test_settle_claim_credits_wallet_hop(api):
    """PRD §3.10: "Settling credits the computed `settlement_cents` to the owning
    customer's `wallet_credit_cents` and adds 25 points to that customer's
    `risk_score`."

    Isolates the wallet-credit hop of the settle cascade: a DRY_CLEAN garment
    LOST then claim declared 10000 settled credits exactly 8000 to the wallet
    that began at 0.

    Design: Difficulty/transitive_cascade/mark_lost_then_settle_depth2_cascade
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        actuals=[{"actual_piece_count": 1}],
    )
    before = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert before["wallet_credit_cents"] == 0, "wallet starts at 0"
    th.mark_lost(order, garments[0])
    th.settle_garment_claim(order, customer, garments[0], declared_value_cents=10000)
    after = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert after["wallet_credit_cents"] == 8000, \
        f"settle credits wallet by settlement 8000, got {after['wallet_credit_cents']}"
