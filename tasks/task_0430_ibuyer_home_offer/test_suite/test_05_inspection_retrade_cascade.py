"""Inspection re-trade: the valuation cascade (revised AVM -> service fee ->
lease-back -> final proceeds), the re-trade cap boundary, single-re-trade rule,
and the cancellation compensation that unwinds a re-trade.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    setup_inspection_transaction,
    apply_retrade,
    cancel_transaction,
    STANDARD_REPAIR_LINES,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def test_retrade_cascade_revised_avm_and_final_proceeds(api):
    """PRD §3.6: "the property's `revised_avm_value` is set to `avm_value_snapshot`
    minus `retrade_amount`, rounded half-up to two decimal places; and because the
    effective AVM has now dropped, the effective service fee, the
    `leaseback_daily_rate`, the `leaseback_total`, and the `final_net_proceeds` are
    all recomputed on the revised figure within the same request."

    Design: Difficulty/transitive_cascade/retrade_cascade_depth3_avm_fee_proceeds
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=10,
        final_concession=7650.00,
    )
    updated = validate_success(
        api.retrade(txn["id"], {"retrade_amount": 12000}, _ANALYST)
    )
    # revised_avm = 510000 - 12000 = 498000.00 (on Property).
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["revised_avm_value"] == 498000.00, prop_after["revised_avm_value"]
    # leaseback recomputed on revised AVM: daily=round(498000*0.0004,2)=199.20.
    assert updated["leaseback_daily_rate"] == 199.20, updated["leaseback_daily_rate"]
    # final = 498000 - 24900 - 7650 - 6634.57 - 1992.00 = 456823.43.
    assert updated["final_net_proceeds"] == 456823.43, updated["final_net_proceeds"]


def test_retrade_final_proceeds_branch_on_effective_avm(api):
    """PRD §3.6: "From this point on, the effective AVM that feeds every proceeds and
    lease-back computation is the `revised_avm_value`."
    PRD §3.5: "The effective AVM used here is the property's `revised_avm_value` if an
    inspection re-trade has already been applied, and otherwise the offer's
    `avm_value_snapshot`."

    Design: Difficulty/combinatorial_formula/final_net_proceeds_nonlinear_effective_avm_branch_mode_a
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=10,
        final_concession=7650.00,
    )
    updated = validate_success(
        api.retrade(txn["id"], {"retrade_amount": 12000, "retrade_reason": "roof beyond estimate"}, _ANALYST)
    )
    assert updated["retrade_amount"] == 12000, updated["retrade_amount"]
    assert updated["leaseback_daily_rate"] == 199.20, updated["leaseback_daily_rate"]
    assert updated["leaseback_total"] == 1992.00, updated["leaseback_total"]
    assert updated["final_net_proceeds"] == 456823.43, updated["final_net_proceeds"]


def test_retrade_recomputes_leaseback_total_on_revised_avm(api):
    """PRD §3.6: "because the effective AVM has now dropped, the effective service
    fee, the `leaseback_daily_rate`, the `leaseback_total`, and the
    `final_net_proceeds` are all recomputed on the revised figure within the same
    request."

    Design: Difficulty/combinatorial_formula/final_net_proceeds_nonlinear_effective_avm_branch_mode_a
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=10,
        final_concession=7650.00,
    )
    # Before re-trade, leaseback is computed on avm_value_snapshot=510000: daily 204.00.
    assert txn["leaseback_daily_rate"] == 204.00, txn["leaseback_daily_rate"]
    updated = validate_success(
        api.retrade(txn["id"], {"retrade_amount": 12000}, _ANALYST)
    )
    # After re-trade the effective AVM is 498000 -> daily 199.20, total 1992.00.
    assert updated["leaseback_total"] == 1992.00, updated["leaseback_total"]
    assert updated["final_net_proceeds"] == 456823.43, updated["final_net_proceeds"]


def test_retrade_cascade_recomputes_final_net_proceeds_via_revised_avm(api):
    """PRD §2.6: "lowering a property's effective valuation flows through to the
    effective service fee, the lease-back daily rate and total, and the final net
    proceeds, all of which are recomputed in the same request."
    PRD §3.6: "the property's `revised_avm_value` is set to `avm_value_snapshot` minus
    `retrade_amount`, rounded half-up to two decimal places"

    Design: Difficulty/transitive_cascade/retrade_cascade_depth3_avm_fee_proceeds
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=10,
        final_concession=7650.00,
    )
    updated = validate_success(
        api.retrade(txn["id"], {"retrade_amount": 12000}, _ANALYST)
    )
    # The recomputed daily rate (199.20) is itself a downstream link of the revised AVM.
    assert updated["leaseback_daily_rate"] == 199.20, updated["leaseback_daily_rate"]
    assert updated["final_net_proceeds"] == 456823.43, updated["final_net_proceeds"]
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["revised_avm_value"] == 498000.00, prop_after["revised_avm_value"]


def test_retrade_self_loop_keeps_inspection_status(api):
    """PRD §3.6: "A successful re-trade leaves the transaction in `INSPECTION` and
    triggers the full valuation cascade: the transaction's `retrade_amount` is
    recorded; the property's `revised_avm_value` is set to `avm_value_snapshot` minus
    `retrade_amount`, rounded half-up to two decimal places"

    Design: Difficulty/non_linear_state_machine/transaction_branches_inspection_self_loop_retrade
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    updated = validate_success(
        api.retrade(txn["id"], {"retrade_amount": 5000}, _ANALYST)
    )
    assert updated["status"] == "INSPECTION", updated["status"]
    assert updated["retrade_amount"] == 5000, updated["retrade_amount"]
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["revised_avm_value"] == 505000.00, prop_after["revised_avm_value"]


def test_retrade_records_revised_avm_on_property(api):
    """PRD §3.6: "the property's `revised_avm_value` is set to `avm_value_snapshot`
    minus `retrade_amount`, rounded half-up to two decimal places"

    Design: Difficulty/non_linear_state_machine/transaction_branches_inspection_self_loop_retrade
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    validate_success(api.retrade(txn["id"], {"retrade_amount": 5000}, _ANALYST))
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["revised_avm_value"] == 505000.00, prop_after["revised_avm_value"]


def test_retrade_above_cap_rejected(api):
    """PRD §3.6: "The re-trade amount may not exceed three percent of the offer's
    `avm_value_snapshot`; a larger reduction is rejected with
    `ERR_RETRADE_EXCEEDS_CAP`."

    Design: Difficulty/boundary_precision_check/retrade_at_cap_allowed_above_cap_rejected
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    # avm=510000 -> cap = 3% = 15300.00; 15300.01 is above the cap.
    validate_error(
        api.retrade(txn["id"], {"retrade_amount": 15300.01}, _ANALYST),
        ApiErrorId.ERR_RETRADE_EXCEEDS_CAP,
    )


def test_retrade_at_exactly_cap_allowed(api):
    """PRD §3.6: "The re-trade amount may not exceed three percent of the offer's
    `avm_value_snapshot`; a larger reduction is rejected with
    `ERR_RETRADE_EXCEEDS_CAP`."

    Design: Difficulty/boundary_precision_check/retrade_at_cap_allowed_above_cap_rejected
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    # 15300.00 == cap is allowed ("may not exceed" -> equal is permitted).
    updated = validate_success(
        api.retrade(txn["id"], {"retrade_amount": 15300.00}, _ANALYST)
    )
    assert updated["retrade_amount"] == 15300.00, updated["retrade_amount"]
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["revised_avm_value"] == 494700.00, prop_after["revised_avm_value"]


def test_retrade_twice_returns_already_applied(api):
    """PRD §3.6: "At most one re-trade is permitted per transaction — if
    `retrade_amount` is already nonzero on the transaction, a second attempt is
    rejected with `ERR_RETRADE_ALREADY_APPLIED`."

    Design: Corner/state_machines/retrade_twice_returns_already_applied
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    apply_retrade(txn["id"], 5000)
    validate_error(
        api.retrade(txn["id"], {"retrade_amount": 3000}, _ANALYST),
        ApiErrorId.ERR_RETRADE_ALREADY_APPLIED,
    )


def test_retrade_then_cancel_reverts_revised_avm(api):
    """PRD §3.7: "Cancellation also performs compensation: if a re-trade had been
    applied to the transaction, the property's `revised_avm_value` is reverted to
    null, unwinding the revised valuation so the property is priced from its original
    AVM again."

    Design: Difficulty/compensating_invariant/retrade_then_cancel_conserves_revised_avm_to_null
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    apply_retrade(txn["id"], 12000)
    cancelled = validate_success(
        api.cancel_transaction(
            txn["id"], {"cancel_reason": "seller backed out"}, make_seller_headers(seller["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["revised_avm_value"] is None, prop_after["revised_avm_value"]
    assert prop_after["status"] == "VALUED", prop_after["status"]


def test_retrade_then_cancel_returns_property_to_valued(api):
    """PRD §3.7: "Cancellation moves the transaction to the terminal `CANCELLED`
    status, moves the bound offer to `DECLINED`, returns the property to `VALUED`, and
    clears the property's `active_offer_id` to null."

    Design: Difficulty/compensating_invariant/retrade_then_cancel_conserves_revised_avm_to_null
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    apply_retrade(txn["id"], 12000)
    cancel_transaction(txn["id"], seller["id"], cancel_reason="changed mind")
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["status"] == "VALUED"
    assert prop_after["active_offer_id"] is None
    assert prop_after["revised_avm_value"] is None
    offer_after = validate_success(api.get_offer(offer["id"], _ANALYST))
    assert offer_after["status"] == "DECLINED", offer_after["status"]


def test_cancel_closed_transaction_returns_invalid_state(api):
    """PRD §3.7: "On close, the platform recomputes `final_net_proceeds` one last time
    from the prevailing inputs and locks it, moves the transaction
    `INSPECTION → CLOSED`"
    PRD §3.7: "A close attempted on a transaction that is not in `INSPECTION`, like
    any other transition attempted from an invalid state, is rejected with
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/cancel_closed_transaction_returns_invalid_state
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction()
    validate_success(api.close_transaction(txn["id"], {}, _ADMIN))
    # Transaction is CLOSED (terminal); cancel must be rejected.
    validate_error(
        api.cancel_transaction(txn["id"], {}, make_seller_headers(seller["id"])),
        ApiErrorId.ERR_INVALID_STATE,
    )
