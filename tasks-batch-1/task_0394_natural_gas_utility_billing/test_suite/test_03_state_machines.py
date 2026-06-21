"""State-machine tests: valid transitions, precondition enforcement, invalid-from rejection,
terminal lockdown, and side effects across ServiceOrder, PremiseMeter, Bill, EmergencyTicket,
LowIncomeCredit, BudgetPlan, Deposit."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    fixtures as fx,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]


def test_dispatch_service_order_scheduled_to_dispatched(api):
    """PRD 3.3: "A FieldTech dispatches a scheduled order, advancing it
    SCHEDULED -> DISPATCHED".

    Design: Corner/state_machines/dispatch_service_order_scheduled_to_dispatched
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    order = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "METER_SET", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-02-01T00:00:00.000Z"}, headers=FT))
    resp = api.dispatch_service_order(order["id"], headers=FT)
    data = validate_success(resp, 200)
    assert data["status"] == "DISPATCHED", f"got {data['status']}"


def test_dispatch_before_scheduled_date_returns_order_not_due(api):
    """PRD 3.3: "a dispatch attempted before the order's scheduled_date has been reached
    relative to the clock is rejected with ERR_ORDER_NOT_DUE."

    Design: Corner/state_machines/dispatch_service_order_before_scheduled_date_returns_order_not_due
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    order = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "METER_SET", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-06-01T00:00:00.000Z"}, headers=FT))
    resp = api.dispatch_service_order(order["id"], headers=FT)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DUE.value)


def test_complete_meter_set_without_index_returns_missing_completion_index(api):
    """PRD 3.3: "For both METER_SET and SHUTOFF completions the completed_index is required;
    omitting it is rejected with ERR_MISSING_COMPLETION_INDEX."

    Design: Corner/state_machines/complete_meter_set_without_index_returns_missing_completion_index
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    order = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "METER_SET", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-02-01T00:00:00.000Z"}, headers=FT))
    fx.get_success_data(api.dispatch_service_order(order["id"], headers=FT))
    resp = api.complete_service_order(order["id"], {}, headers=FT)
    validate_error(resp, ApiErrorId.ERR_MISSING_COMPLETION_INDEX.value)


def test_complete_meter_set_sets_meter_and_install_index(api):
    """PRD 3.2: "When the meter-set order is completed, the meter advances from PENDING_SET to
    SET, its install_index is overwritten with the order's captured completion index, and the
    meter's version is bumped."

    Design: Corner/state_machines/complete_meter_set_side_effect_sets_meter_and_install_index
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    order = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "METER_SET", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-02-01T00:00:00.000Z"}, headers=FT))
    fx.get_success_data(api.dispatch_service_order(order["id"], headers=FT))
    resp = api.complete_service_order(order["id"], {"completed_index": 1005}, headers=FT)
    data = validate_success(resp, 200)
    assert data["status"] == "COMPLETED"
    meter_after = fx.get_success_data(api.get_meter(meter["id"], headers=FT))
    assert meter_after["status"] == "SET", f"got {meter_after['status']}"
    assert meter_after["install_index"] == 1005, f"got {meter_after['install_index']}"


def test_dispatch_already_dispatched_returns_invalid_state(api):
    """PRD 2.10: "The target-state check for a transition then yields ERR_INVALID_STATE (409)
    when the resource is not in a state from which the requested transition is defined."

    Design: Corner/state_machines/dispatch_already_dispatched_order_returns_invalid_state
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    order = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "METER_SET", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-02-01T00:00:00.000Z"}, headers=FT))
    fx.get_success_data(api.dispatch_service_order(order["id"], headers=FT))
    resp = api.dispatch_service_order(order["id"], headers=FT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_resolve_ticket_from_open_returns_invalid_state(api):
    """PRD 3.13: "A FieldTech works the ticket through its lifecycle: dispatching it
    OPEN -> DISPATCHED, marking it DISPATCHED -> MADE_SAFE, and resolving it
    MADE_SAFE -> RESOLVED." PRD 2.10: "The target-state check for a transition then yields
    ERR_INVALID_STATE (409) when the resource is not in a state from which the requested
    transition is defined."

    Design: Corner/state_machines/resolve_ticket_from_open_returns_invalid_state
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    ticket = fx.open_ticket(meter["id"], account_id=acct["id"], kind="ODOR", reported_indoors=False)
    resp = api.resolve_ticket(ticket["id"], headers=FT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_void_issued_bill_returns_invalid_state(api):
    """PRD 3.5: "A draft bill may instead be voided by a BillingAdmin, moving it
    DRAFT -> VOID". PRD 2.10: "The target-state check for a transition then yields
    ERR_INVALID_STATE (409) when the resource is not in a state from which the requested
    transition is defined."

    Design: Corner/state_machines/void_issued_bill_from_issued_returns_invalid_state
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    resp = api.void_bill(acct["id"], issued["id"], headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_resolved_ticket_terminal_returns_invalid_state(api):
    """PRD 3.13: "A ticket may be cancelled as a false alarm by a CustomerService operator
    from either OPEN or DISPATCHED, moving it to CANCELLED." PRD 2.10: "The target-state check
    for a transition then yields ERR_INVALID_STATE (409) when the resource is not in a state
    from which the requested transition is defined."

    Design: Corner/state_machines/cancel_ticket_from_resolved_terminal_returns_invalid_state
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    ticket = fx.open_ticket(meter["id"], account_id=acct["id"], kind="ODOR", reported_indoors=False)
    fx.get_success_data(api.dispatch_ticket(ticket["id"], headers=FT))
    fx.get_success_data(api.make_safe_ticket(ticket["id"], headers=FT))
    fx.get_success_data(api.resolve_ticket(ticket["id"], headers=FT))
    resp = api.cancel_ticket(ticket["id"], headers=CS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_deny_low_income_credit_does_not_enroll(api):
    """PRD 3.8: "An application may instead be denied by a CustomerService operator, moving it
    SUBMITTED -> DENIED."

    Design: Corner/state_machines/deny_low_income_credit_side_effect_status_denied
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    credit = fx.submit_low_income_credit(acct["id"], household_size=1, annual_income_cents=1400000)
    resp = api.deny_low_income_credit(acct["id"], credit["id"], headers=CS)
    data = validate_success(resp, 200)
    assert data["status"] == "DENIED", f"got {data['status']}"
    acct_after = fx.get_account(acct["id"])
    assert acct_after["low_income_status"] == "NONE", f"got {acct_after['low_income_status']}"


def test_expire_low_income_credit_resets_account_tier(api):
    """PRD 3.8: "An APPROVED credit may later be expired by a BillingAdmin, moving it
    APPROVED -> EXPIRED; if no other approved credit remains on the account, expiry resets the
    account's low_income_status to NONE and low_income_tier to NONE."

    Design: Corner/state_machines/low_income_expire_resets_account_tier_side_effect
    """
    rs, acct, credit = fx.setup_enrolled_low_income_account(household_size=1,
                                                            annual_income_cents=1400000)
    resp = api.expire_low_income_credit(acct["id"], credit["id"], headers=ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "EXPIRED", f"got {data['status']}"
    acct_after = fx.get_account(acct["id"])
    assert acct_after["low_income_status"] == "NONE", f"got {acct_after['low_income_status']}"
    assert acct_after["low_income_tier"] == "NONE", f"got {acct_after['low_income_tier']}"


def test_approve_ineligible_credit_returns_not_eligible(api):
    """PRD 3.8: "A CustomerService operator approves the application, advancing it
    SUBMITTED -> APPROVED, but approval is rejected with ERR_NOT_ELIGIBLE when the computed
    tier is NONE."

    Design: Corner/state_machines/low_income_approve_ineligible_tier_returns_not_eligible
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    # household 1 income 5,000,000 -> ratio 3.31x FPL -> tier NONE
    credit = fx.submit_low_income_credit(acct["id"], household_size=1, annual_income_cents=5000000)
    resp = api.approve_low_income_credit(acct["id"], credit["id"], headers=CS)
    validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE.value)


def test_budget_trueup_no_bills_returns_no_bills_to_true_up(api):
    """PRD 3.7: "It requires that at least one bill has been issued under the plan; if none
    has, it is rejected with ERR_NO_BILLS_TO_TRUE_UP."

    Design: Corner/state_machines/budget_trueup_no_bills_returns_no_bills_to_true_up
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    plan = fx.enroll_budget_plan(acct["id"], anchor_month="2026-02", projected_annual_cents=96000)
    resp = api.true_up_budget_plan(acct["id"], plan["id"], headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_BILLS_TO_TRUE_UP.value)


def test_budget_plan_cancel_clears_budget_enrolled(api):
    """PRD 3.7: "A plan may alternatively be cancelled by a CustomerService operator, moving it
    ACTIVE -> CANCELLED and likewise clearing Account.budget_enrolled to false."

    Design: Corner/state_machines/budget_plan_cancel_clears_budget_enrolled_side_effect
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    plan = fx.enroll_budget_plan(acct["id"], anchor_month="2026-02", projected_annual_cents=96000)
    resp = api.cancel_budget_plan(acct["id"], plan["id"], headers=CS)
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELLED", f"got {data['status']}"
    acct_after = fx.get_account(acct["id"])
    assert acct_after["budget_enrolled"] is False, f"got {acct_after['budget_enrolled']}"


def test_collect_waived_deposit_returns_deposit_waived_not_payable(api):
    """PRD 3.11: "A collect attempt on a deposit whose amount is 0 is rejected with
    ERR_DEPOSIT_WAIVED_NOT_PAYABLE."

    Design: Corner/state_machines/deposit_collect_on_waived_returns_deposit_waived_not_payable
    """
    rs, acct, credit = fx.setup_enrolled_low_income_account(household_size=1,
                                                            annual_income_cents=1400000)
    dep = fx.get_success_data(api.create_deposit(acct["id"], {"reason": "NEW_SERVICE"}, headers=CS))
    assert dep["status"] == "WAIVED", f"got {dep['status']}"
    resp = api.collect_deposit(acct["id"], dep["id"], headers=CS)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_WAIVED_NOT_PAYABLE.value)


def test_refund_deposit_before_threshold_returns_refund_not_due(api):
    """PRD 3.11: "A held deposit is refunded by a BillingAdmin ... but the refund is permitted
    only once the account has at least twelve consecutive on-time payments; an earlier attempt
    is rejected with ERR_DEPOSIT_REFUND_NOT_DUE."

    Design: Corner/state_machines/deposit_refund_before_threshold_returns_refund_not_due
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    dep = fx.create_held_deposit(acct["id"], reason="NEW_SERVICE")
    assert dep["status"] == "HELD"
    resp = api.refund_deposit(acct["id"], dep["id"], headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_REFUND_NOT_DUE.value)


def test_meter_remove_set_to_removed(api):
    """PRD 3.2: "A FieldTech may retire a meter, driving it to the terminal REMOVED status and
    bumping its version. ... A meter in SET status may be removed only when no DRAFT bill
    references an unconsumed read on that meter".

    Design: Corner/state_machines/meter_remove_set_to_removed_valid_transition
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    resp = api.remove_meter(meter["id"], headers=FT)
    data = validate_success(resp, 200)
    assert data["status"] == "REMOVED", f"got {data['status']}"
