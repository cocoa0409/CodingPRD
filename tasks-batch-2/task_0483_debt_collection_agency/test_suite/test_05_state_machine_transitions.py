"""State-machine transitions: invalid transitions, idempotency, guarded transitions,
terminal lockdown, and system bubble-up.

All tests translate corner-design (queue B) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    setup_placed_account,
    setup_validation_sent_account,
    setup_working_account,
    setup_working_account_with_open_accuracy_dispute,
    propose_arrangement,
    post_payment,
    refresh_account,
    TEST_USERS,
)

COLLECTOR = TEST_USERS["collector_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# state_machines / begin_work_from_placed_invalid_state
# ===========================================================================
def test_begin_work_from_placed_invalid_state():
    """PRD §3.3: "With the notice sent, the collector moves the account into active
    collection. Beginning work advances `work_status` from `VALIDATION_SENT` to
    `WORKING`."
    PRD §2.10: "After the body is accepted, state-transition endpoints confirm the
    target resource is in a state from which the requested transition is defined,
    rejecting otherwise with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/begin_work_from_placed_invalid_state
    """
    ctx = setup_placed_account(clock="2026-01-01T00:00:00Z",
                               account_overrides={"original_principal_cents": 50000})
    res = api_client.begin_work(ctx["account"]["id"], COLLECTOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines / send_validation_notice_twice_returns_already_sent
# ===========================================================================
def test_send_validation_notice_twice_returns_already_sent():
    """PRD §3.3: "This is permitted only while the account has not already had a
    notice sent — that is, while `validation_notice_sent_at` is null; a repeat
    attempt is rejected with `ERR_VALIDATION_ALREADY_SENT`."

    Design: Corner/state_machines/send_validation_notice_twice_returns_already_sent
    """
    ctx = setup_validation_sent_account(clock="2026-01-01T00:00:00Z",
                                        account_overrides={"original_principal_cents": 50000})
    res = api_client.send_validation_notice(ctx["account"]["id"], COLLECTOR)
    validate_error(res, ApiErrorId.ERR_VALIDATION_ALREADY_SENT.value)


# ===========================================================================
# state_machines / dispute_reopen_from_open_invalid_state
# ===========================================================================
def test_dispute_reopen_from_open_invalid_state():
    """PRD §3.4: "A `RESOLVED` dispute may be reopened by a compliance officer;
    reopening is permitted only from `RESOLVED` status and is otherwise rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dispute_reopen_from_open_invalid_state
    """
    ctx = setup_working_account_with_open_accuracy_dispute(
        clock="2026-01-01T00:00:00Z",
        account_overrides={"original_principal_cents": 50000},
    )
    res = api_client.reopen_dispute(ctx["dispute"]["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines / arrangement_accept_on_non_working_account_not_workable
# ===========================================================================
def test_arrangement_accept_on_non_working_account_not_workable():
    """PRD §3.6: "The account must be in `work_status` `WORKING`, or the accept is
    rejected with `ERR_ACCOUNT_NOT_WORKABLE`."

    Design: Corner/state_machines/arrangement_accept_on_non_working_account_not_workable
    """
    # Account in VALIDATION_SENT (notice sent, work NOT begun); a PROPOSED PLAN.
    ctx = setup_validation_sent_account(clock="2026-01-01T00:00:00Z",
                                        account_overrides={"original_principal_cents": 50000})
    arr = propose_arrangement(ctx["account"]["id"], "PLAN")
    res = api_client.accept_arrangement(arr["id"], COLLECTOR)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_WORKABLE.value)


# ===========================================================================
# state_machines / recall_terminal_account_invalid_state
# ===========================================================================
def test_recall_terminal_account_invalid_state():
    """PRD §3.8: "Recall is permitted only when the account's `work_status` is not
    already `CLOSED_PAID`, `CLOSED_UNCOLLECTIBLE`, or `RECALLED`; otherwise it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/recall_terminal_account_invalid_state
    """
    ctx = setup_placed_account(clock="2026-01-01T00:00:00Z",
                               account_overrides={"original_principal_cents": 50000})
    closed = get_success_data(
        api_client.close_uncollectible(ctx["account"]["id"], ctx["creditor_headers"])
    )
    res = api_client.recall_account(
        ctx["account"]["id"], {"expected_account_version": closed["version"]},
        ctx["creditor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines / account_auto_closes_paid_when_balance_zero
# ===========================================================================
def test_account_auto_closes_paid_when_balance_zero():
    """PRD §3.7: "Whenever the account's `balance_cents` reaches zero — whether
    through ordinary payment or through settlement fulfillment — the account
    auto-closes, its `work_status` moving from `WORKING` to `CLOSED_PAID`, and its
    commission is recomputed at closure."

    Design: Corner/state_machines/account_auto_closes_paid_when_balance_zero
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 50000})
    get_success_data(post_payment(ctx["account"]["id"], 50000))
    acct = refresh_account(ctx)
    assert acct["balance_cents"] == 0
    assert acct["work_status"] == "CLOSED_PAID"
