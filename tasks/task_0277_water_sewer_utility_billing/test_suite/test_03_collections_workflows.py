"""Collections cascades and parallel state machines: cycle-close late fees,
payment waterfall clearing shutoffs, the dual billing/service axes, the cyclic
shutoff lifecycle, and compensating post/void & enroll/revoke invariants.

Translates Difficulty queue: transitive_cascade, non_linear_state_machine,
compensating_invariant.
"""
from test_helpers import (
    validate_success,
    setup_past_due_account, setup_scheduled_shutoff, setup_executed_shutoff,
    setup_canonical_posted_bill,
    fixtures, factories, TEST_USERS,
)

CLERK = TEST_USERS["billing_clerk_headers"]
FIELDOPS = TEST_USERS["field_ops_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# ===========================================================================
# Depth-3 cascade: cycle close -> late fee -> PAST_DUE -> balance reconcile
# ===========================================================================
def test_cycle_close_assesses_late_fee_and_flips_past_due(api):
    """PRD §3.3: "the bill's `late_fee_cents` becomes the unpaid principal
    multiplied by the schedule's `late_fee_pct`, divided by 100, rounded half up to
    whole cents."
    PRD §3.3: "Each affected account whose closing cycle leaves an unpaid posted
    bill moves its `billing_status` from `CURRENT` to `PAST_DUE`, and that account's
    `past_due_cents` and `balance_due_cents` are recomputed."

    Design: Difficulty/transitive_cascade/cycle_close_to_late_fee_to_balance_reconcile_depth3
    """
    account, bill, rs, cycle = setup_past_due_account(potable=12000, irrigation=8000)
    bill_after = validate_success(api.get_bill(bill["id"], CLERK))
    # late fee = round_half_up(18980 * 5 / 100) = 949
    assert bill_after["late_fee_cents"] == 949
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["billing_status"] == "PAST_DUE"


def test_cycle_close_reconciles_past_due_and_balance(api):
    """PRD §2.5: "take every bill of the account whose status is `POSTED` and whose
    owning billing cycle has reached `CLOSED`, sum each such bill's `total_cents`
    together with its `late_fee_cents`, subtract the payments already absorbed by
    those specific bills, and floor the result at zero."

    Design: Difficulty/transitive_cascade/cycle_close_to_late_fee_to_balance_reconcile_depth3
    """
    account, bill, rs, cycle = setup_past_due_account(potable=12000, irrigation=8000)
    acct = validate_success(api.get_account(account["id"], CLERK))
    # total_cents 18980 + late_fee 949 = 19929
    assert acct["past_due_cents"] == 19929
    assert acct["balance_due_cents"] == 19929


# ===========================================================================
# Depth-2 cascade: payment clears past due -> cancels scheduled shutoff
# ===========================================================================
def test_payment_clears_past_due_cancels_scheduled_shutoff(api):
    """PRD §3.6: "if the account is in `SHUTOFF_PENDING` and the payment drives
    `past_due_cents` to zero while every shutoff order on the account is still merely
    `SCHEDULED` (none has been `EXECUTED`), then all of those `SCHEDULED` shutoff
    orders are cancelled as a cascade and the account returns to `CURRENT`."

    Design: Difficulty/transitive_cascade/payment_clears_pastdue_cancels_shutoff_depth2
    """
    account, bill, order, rs, cycle = setup_scheduled_shutoff(potable=12000, irrigation=8000)
    validate_success(api.create_payment(account["id"], factories.payment_payload(19929, method="ACH"), CLERK), 201)
    bill_after = validate_success(api.get_bill(bill["id"], CLERK))
    assert bill_after["status"] == "PAID"
    order_after = validate_success(api.get_shutoff_order(order["id"], FIELDOPS))
    assert order_after["status"] == "CANCELLED"


def test_payment_clears_past_due_returns_account_current(api):
    """PRD §3.6: "If, after the waterfall runs, the account's resulting
    `past_due_cents` is zero, the account's `billing_status` returns to `CURRENT`."

    Design: Difficulty/transitive_cascade/payment_clears_pastdue_cancels_shutoff_depth2
    """
    account, bill, order, rs, cycle = setup_scheduled_shutoff(potable=12000, irrigation=8000)
    validate_success(api.create_payment(account["id"], factories.payment_payload(19929, method="ACH"), CLERK), 201)
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["billing_status"] == "CURRENT"
    assert acct["past_due_cents"] == 0


# ===========================================================================
# Parallel axes: billing_status vs service_status (non_linear_state_machine)
# ===========================================================================
def test_schedule_shutoff_moves_billing_axis_only(api):
    """PRD §3.9: "When scheduling succeeds, the order is created in `SCHEDULED`
    status and the account's `billing_status` advances to `SHUTOFF_PENDING`."

    Design: Difficulty/non_linear_state_machine/account_parallel_billing_and_service_axes
    """
    account, bill, order, rs, cycle = setup_scheduled_shutoff(potable=12000, irrigation=8000)
    acct = validate_success(api.get_account(account["id"], CLERK))
    # billing axis moved, service axis untouched
    assert acct["billing_status"] == "SHUTOFF_PENDING"
    assert acct["service_status"] == "ACTIVE"


def test_execute_shutoff_moves_service_axis_to_suspended(api):
    """PRD §3.9: "Execution advances the order from `SCHEDULED` to `EXECUTED` and,
    as a cross-axis effect, moves the account's `service_status` from `ACTIVE` to
    `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/account_parallel_billing_and_service_axes
    """
    account, bill, order, rs, cycle = setup_executed_shutoff(potable=12000, irrigation=8000)
    order_after = validate_success(api.get_shutoff_order(order["id"], FIELDOPS))
    assert order_after["status"] == "EXECUTED"
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["service_status"] == "SUSPENDED"
    # billing axis remains SHUTOFF_PENDING (independent of service axis)
    assert acct["billing_status"] == "SHUTOFF_PENDING"


# ===========================================================================
# Cyclic shutoff lifecycle: SCHEDULED -> EXECUTED -> RECONNECTED
# ===========================================================================
def test_reconnect_sets_fee_and_restores_service(api):
    """PRD §3.9: "On reconnection the order's `reconnect_fee_charged_cents` is set
    to the schedule's `reconnect_fee_cents`, the account's `balance_due_cents`
    increases by that reconnect fee as a posted charge, and the account's
    `service_status` moves from `SUSPENDED` to `RESTORED`."

    Design: Difficulty/non_linear_state_machine/shutoff_order_cyclic_schedule_execute_reconnect
    """
    account, bill, order, rs, cycle = setup_executed_shutoff(potable=12000, irrigation=8000)
    reconnected = validate_success(api.reconnect_shutoff_order(order["id"], FIELDOPS))
    assert reconnected["status"] == "RECONNECTED"
    assert reconnected["reconnect_fee_charged_cents"] == 5000
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["service_status"] == "RESTORED"


def test_reconnect_fee_posts_to_account_balance(api):
    """PRD §3.9: "the account's `balance_due_cents` increases by that reconnect fee
    as a posted charge"

    Design: Difficulty/non_linear_state_machine/shutoff_order_cyclic_schedule_execute_reconnect
    """
    account, bill, order, rs, cycle = setup_executed_shutoff(potable=12000, irrigation=8000)
    before = validate_success(api.get_account(account["id"], CLERK))["balance_due_cents"]
    validate_success(api.reconnect_shutoff_order(order["id"], FIELDOPS))
    after = validate_success(api.get_account(account["id"], CLERK))["balance_due_cents"]
    assert after - before == 5000


# ===========================================================================
# Compensating invariant: post then void leaves balance unchanged
# ===========================================================================
def test_post_then_void_conserves_balance(api):
    """PRD §3.5: "Voiding a `POSTED` bill is a compensation: the account's
    `balance_due_cents` is decreased by the bill's `total_cents`, reversing the
    original posting"

    Design: Difficulty/compensating_invariant/bill_post_then_void_leaves_balance_unchanged
    """
    account, bill, rs, cycle = setup_canonical_posted_bill(potable=12000, irrigation=8000)
    # posting moved balance to 18980
    assert validate_success(api.get_account(account["id"], CLERK))["balance_due_cents"] == 18980
    voided = validate_success(api.void_bill(bill["id"], CLERK))
    assert voided["status"] == "VOID"
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["balance_due_cents"] == 0


def test_void_draft_bill_has_no_ledger_effect(api):
    """PRD §3.5: "Voiding a `DRAFT` bill simply marks it `VOID` with no ledger
    effect."

    Design: Difficulty/compensating_invariant/bill_post_then_void_leaves_balance_unchanged
    """
    account, bill, rs, cycle, _, _ = fixtures.setup_canonical_draft_bill(potable=12000, irrigation=8000)
    voided = validate_success(api.void_bill(bill["id"], CLERK))
    assert voided["status"] == "VOID"
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["balance_due_cents"] == 0


# ===========================================================================
# Compensating invariant: assistance enroll then revoke restores standing
# ===========================================================================
def _past_due_account_high_arrears():
    """Past-due canonical account (arrears 19929) for protection tests."""
    account, bill, rs, cycle = setup_past_due_account(potable=12000, irrigation=8000)
    return account, bill


def test_assistance_enroll_protects_then_revoke_restores_past_due(api):
    """PRD §3.10: "When the enrollment grants shutoff protection and the account is
    currently `PAST_DUE`, the account's `billing_status` advances to
    `DELINQUENT_PROTECTED`"
    PRD §3.10: "Revocation moves the enrollment to `REVOKED` and clears the
    account's `assistance_enrolled` flag; if the account was `DELINQUENT_PROTECTED`
    and still carries arrears (its `past_due_cents` is greater than zero), its
    `billing_status` falls back to `PAST_DUE` as a cascade."

    Design: Difficulty/compensating_invariant/assistance_enroll_then_revoke_restores_billing_status
    """
    account, bill = _past_due_account_high_arrears()
    enr = validate_success(
        api.create_assistance_enrollment(
            account["id"],
            factories.assistance_enrollment_payload(grants_shutoff_protection=True),
            CASEWORKER), 201)
    protected = validate_success(api.get_account(account["id"], CLERK))
    assert protected["billing_status"] == "DELINQUENT_PROTECTED"
    assert protected["assistance_enrolled"] is True

    revoked = validate_success(api.revoke_assistance_enrollment(enr["id"], CASEWORKER))
    assert revoked["status"] == "REVOKED"
    after = validate_success(api.get_account(account["id"], CLERK))
    assert after["assistance_enrolled"] is False
    assert after["billing_status"] == "PAST_DUE"


def test_assistance_enroll_sets_enrolled_flag_true(api):
    """PRD §3.10: "Enrollment creates an `AssistanceEnrollment` in `ACTIVE` status
    and sets the account's `assistance_enrolled` true."

    Design: Difficulty/compensating_invariant/assistance_enroll_then_revoke_restores_billing_status
    """
    account, bill = _past_due_account_high_arrears()
    validate_success(
        api.create_assistance_enrollment(
            account["id"],
            factories.assistance_enrollment_payload(grants_shutoff_protection=True),
            CASEWORKER), 201)
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["assistance_enrolled"] is True
