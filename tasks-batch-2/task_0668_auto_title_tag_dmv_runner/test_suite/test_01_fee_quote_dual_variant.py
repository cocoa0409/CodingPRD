"""Dual-variant fee calculations: ESTIMATE vs FINAL divergence, and the
postpaid vs prepaid account-balance reconciliation variant.

Queue A (Difficulty) — rule dual_variant_calc.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_fee_schedule_payload,
    setup_schedule_and_account, create_account,
    create_transaction_verified_and_quoted, submit_transaction,
    create_planned_trip, attach_leg, record_decision, complete_transaction,
    publish_fee_schedule, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]


def _drive_to_approved(account_id, transaction_type, **txn_overrides):
    """Verify+quote+submit+attach+dispatch+return+ACCEPTED. Returns (txn, est_quote)."""
    txn, est_quote = create_transaction_verified_and_quoted(
        account_id, transaction_type, txn_overrides=txn_overrides)
    submission = submit_transaction(txn["id"])
    trip = create_planned_trip()
    attach_leg(trip["id"], submission["id"], trip["version"])
    api_client.dispatch_trip(trip["id"], DISPATCHER)
    api_client.return_trip(trip["id"], DISPATCHER)
    record_decision(submission["id"], "ACCEPTED")
    return txn, est_quote


def test_final_quote_repins_schedule_diverges_from_estimate(api):
    """PRD §3.6: "The final quote also re-pins the governing fee schedule by re-reading
    the ACTIVE schedule at completion time, which may differ from the schedule the
    estimate froze if a newer schedule was published in between; consequently the same
    transaction can yield a different final total than its estimate."
    PRD §3.6: "The final quote has variant of FINAL and status of SETTLED."

    Design: Difficulty/dual_variant_calc/feequote_estimate_vs_final_diverge_on_schedule_republish
    """
    schedule, account = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625})

    txn, est_quote = _drive_to_approved(
        account["id"], "TRANSFER",
        declared_price_cents=1000000, trade_in_allowance_cents=0, expedite=False)
    assert est_quote["total_cents"] == 68500
    assert est_quote["variant"] == "ESTIMATE"

    # Republish CA with a higher tax rate BEFORE completion.
    publish_fee_schedule(state_code="CA", use_tax_rate_bps=700)

    completed = validate_success(api.complete_transaction(txn["id"], ANALYST), 200)

    # The ESTIMATE quote is now SUPERSEDED.
    est_after = get_success_data(api.get_fee_quote(est_quote["id"], ANALYST))
    assert est_after["total_cents"] == 68500
    assert est_after["variant"] == "ESTIMATE"
    assert est_after["status"] == "SUPERSEDED"

    # The FINAL settled quote re-pins the 700 bps schedule -> 76000.
    final_quote = get_success_data(api.get_fee_quote(completed["active_quote_id"], ANALYST))
    assert final_quote["variant"] == "FINAL"
    assert final_quote["status"] == "SETTLED"
    assert final_quote["total_cents"] == 76000
    assert final_quote["total_cents"] != est_after["total_cents"]


def test_final_quote_repin_uses_current_active_schedule(api):
    """PRD §3.6: "The final quote also re-pins the governing fee schedule by re-reading
    the ACTIVE schedule at completion time, which may differ from the schedule the
    estimate froze if a newer schedule was published in between; consequently the same
    transaction can yield a different final total than its estimate."

    Design: Difficulty/dual_variant_calc/feequote_estimate_vs_final_diverge_on_schedule_republish
    """
    schedule, account = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625})
    txn, est_quote = _drive_to_approved(
        account["id"], "TRANSFER",
        declared_price_cents=1000000, trade_in_allowance_cents=0, expedite=False)

    new_sched = publish_fee_schedule(state_code="CA", use_tax_rate_bps=700)
    completed = validate_success(api.complete_transaction(txn["id"], ANALYST), 200)
    final_quote = get_success_data(api.get_fee_quote(completed["active_quote_id"], ANALYST))

    # FINAL re-pins the now-ACTIVE 700bps schedule, not the estimate's frozen one.
    assert final_quote["schedule_id"] == new_sched["id"]
    assert final_quote["tax_cents"] == 70000
    assert final_quote["total_cents"] == 76000


def test_postpaid_fleet_balance_equals_settled_total_after_completion(api):
    """PRD §3.7: "For a postpaid fleet account (one whose credit_terms is true),
    completion adds the settled total to the outstanding balance directly, and a
    later charge payment draws it back down."

    Design: Difficulty/dual_variant_calc/account_balance_postpaid_vs_prepaid_variant
    """
    schedule, fleet = setup_schedule_and_account(
        account_type="FLEET", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625},
        account_overrides={"credit_terms": True, "credit_limit_cents": 100000})

    txn, _est = _drive_to_approved(fleet["id"], "REGISTRATION", declared_price_cents=0)
    complete_transaction(txn["id"])

    account_after = validate_success(api.get_account(fleet["id"], ADMIN), 200)
    # Postpaid: completion adds the SETTLED total (13000) with NO prior CHARGE.
    assert account_after["outstanding_balance_cents"] == 13000
    assert account_after["status"] == "ACTIVE"  # 13000 <= credit_limit 100000
    assert account_after["ytd_completed_count"] == 1


def test_prepaid_retail_balance_nets_to_zero_with_charge(api):
    """PRD §3.7: "For a prepaid retail account (one whose credit_terms is false), a
    charge payment equal to the settled total must be recorded in the same exchange
    so that the outstanding balance nets back to zero immediately at completion."

    Design: Difficulty/dual_variant_calc/account_balance_postpaid_vs_prepaid_variant
    """
    schedule, retail = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625})

    txn, _est = _drive_to_approved(retail["id"], "REGISTRATION", declared_price_cents=0)
    completed = complete_transaction(txn["id"])
    settled = get_success_data(api.get_fee_quote(completed["active_quote_id"], ANALYST))
    assert settled["total_cents"] == 13000

    # RETAIL prepaid: record a CHARGE equal to the SETTLED total -> balance nets to 0.
    from test_helpers import make_account_holder_headers, create_payment_payload
    holder = make_account_holder_headers(retail["id"])
    validate_success(api.create_payment(
        retail["id"], create_payment_payload(txn["id"], 13000, "CHARGE"), holder), 201)

    account_after = validate_success(api.get_account(retail["id"], ADMIN), 200)
    assert account_after["outstanding_balance_cents"] == 0
