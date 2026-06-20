"""Invalid transitions, precondition enforcement, terminal lockdown, automatic
side-effect transitions, the reimbursement revision cycle, and ERP-batch build.

Corner queue: state_machines.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiClient, ApiErrorId,
    setup_company_with_card, setup_closed_statement_with_settled_coded_spend,
    setup_due_statement_with_settled_spend, setup_built_erp_batch,
    setup_submitted_reimbursement_claim, capture_transaction, capture_settled_transaction,
    set_clock,
)
from test_helpers import factories as F
from test_helpers.test_users import make_finance_admin_headers

ADMIN = make_finance_admin_headers()


# ===========================================================================
# Corner: state_machines / clear_already_cleared_transaction_returns_invalid_state
# ===========================================================================
def test_clear_already_cleared_returns_invalid_state(api: ApiClient):
    """PRD §3.3: "Clearing moves auth_status PENDING -> CLEARED (defined only from
    PENDING, else ERR_INVALID_STATE)"

    Re-clearing an already-CLEARED transaction is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/clear_already_cleared_transaction_returns_invalid_state
    """
    base = setup_company_with_card()
    tx = capture_transaction(base["card"]["id"], amount_cents=5000)
    get_success_data(api.clear_transaction(tx["id"], ADMIN))
    resp = api.clear_transaction(tx["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / activate_virtual_card_returns_invalid_state
# ===========================================================================
def test_activate_virtual_card_returns_invalid_state(api: ApiClient):
    """PRD §3.2: "this is defined only for a physical card (a virtual card is already
    ACTIVE, and attempting to activate one is rejected with ERR_INVALID_STATE)"

    Activating a VIRTUAL card (already ACTIVE) is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/activate_virtual_card_returns_invalid_state
    """
    base = setup_company_with_card()  # VIRTUAL card -> already ACTIVE
    resp = api.activate_card(base["card"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / terminate_card_with_pending_auth_rejected
# ===========================================================================
def test_terminate_card_with_pending_auth_rejected(api: ApiClient):
    """PRD §3.2: "termination is refused with ERR_CARD_HAS_OPEN_AUTH if the card still
    has any transaction whose auth_status is PENDING."

    Terminating an ACTIVE card that has a PENDING transaction is rejected with
    ERR_CARD_HAS_OPEN_AUTH.

    Design: Corner/state_machines/terminate_card_with_pending_auth_rejected
    """
    base = setup_company_with_card()
    capture_transaction(base["card"]["id"], amount_cents=5000)  # PENDING
    resp = api.terminate_card(base["card"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CARD_HAS_OPEN_AUTH.value)


# ===========================================================================
# Corner: state_machines / statement_close_without_clock_returns_clock_not_set
# ===========================================================================
def test_statement_close_without_clock_rejected(api: ApiClient):
    """PRD §3.6: "closing requires the company's clock_utc to be set, otherwise
    ERR_CLOCK_NOT_SET, and is defined only from OPEN, otherwise ERR_INVALID_STATE."

    Closing the OPEN statement before the company clock is set returns ERR_CLOCK_NOT_SET.

    Design: Corner/state_machines/statement_close_without_clock_returns_clock_not_set
    """
    base = setup_company_with_card()  # clock never set
    resp = api.close_statement(base["open_statement"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOCK_NOT_SET.value)


# ===========================================================================
# Corner: state_machines / settle_without_clear_returns_invalid_state
# ===========================================================================
def test_settle_pending_transaction_returns_invalid_state(api: ApiClient):
    """PRD §3.3: "Settling moves auth_status CLEARED -> SETTLED (defined only from
    CLEARED, else ERR_INVALID_STATE)"

    Settling a PENDING (never-cleared) transaction is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/settle_without_clear_returns_invalid_state
    """
    base = setup_company_with_card()
    tx = capture_transaction(base["card"]["id"], amount_cents=5000)  # PENDING
    resp = api.settle_transaction(tx["id"], F.settle_payload(5000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / erp_batch_post_twice_returns_invalid_state
# ===========================================================================
def test_erp_batch_post_twice_returns_invalid_state(api: ApiClient):
    """PRD §3.10: "The administrator then either posts it (BUILT -> POSTED) or discards
    it (BUILT -> DISCARDED); each is defined only from BUILT (else ERR_INVALID_STATE)
    and increments the batch's version. POSTED and DISCARDED are terminal."

    Posting an already-POSTED (terminal) ERP batch is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/erp_batch_post_twice_returns_invalid_state
    """
    base = setup_built_erp_batch(settled_amount_cents=5000, gl_code="7000")
    get_success_data(api.post_erp_sync_batch(base["batch"]["id"], ADMIN))
    resp = api.post_erp_sync_batch(base["batch"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / erp_batch_entry_count_and_debits_computed
# ===========================================================================
def test_erp_batch_captures_entry_count_and_debits(api: ApiClient):
    """PRD §3.10: "it captures, at build time, the company's SETTLED transactions whose
    statement_id is this statement and whose gl_account_id is non-null: the batch
    records the count of those rows in entry_count and the sum of their
    settled_amount_cents in total_debits_cents."

    One SETTLED tx settled at 5000 with a GL code yields entry_count=1,
    total_debits_cents=5000.

    Design: Corner/state_machines/erp_batch_entry_count_and_debits_computed
    """
    base = setup_closed_statement_with_settled_coded_spend(settled_amount_cents=5000,
                                                           gl_code="7100")
    batch = validate_success(api.create_erp_sync_batch(
        F.create_erp_sync_batch_payload(base["company"]["id"], base["statement"]["id"]),
        ADMIN), expected_status=201)
    assert batch["entry_count"] == 1, f"entry_count expected 1, got {batch['entry_count']}"
    assert batch["total_debits_cents"] == 5000, (
        f"total_debits_cents expected 5000, got {batch['total_debits_cents']}")


# ===========================================================================
# Corner: state_machines / reimbursement_reject_revise_returns_to_draft
# ===========================================================================
def test_reimbursement_reject_then_revise_returns_to_draft(api: ApiClient):
    """PRD §3.7: "Rejecting a submitted claim moves it SUBMITTED -> REJECTED (same state
    and self-approval guards) and increments version. A rejected claim returns to DRAFT
    through a revise action"

    A SUBMITTED claim rejected by the approver and then revised by the claimant returns
    to DRAFT.

    Design: Corner/state_machines/reimbursement_reject_revise_returns_to_draft
    """
    s = setup_submitted_reimbursement_claim(amount_cents=9000, receipt_amount_cents=9000)
    get_success_data(api.reject_reimbursement_claim(
        s["claim"]["id"], F.approval_decision_payload(decision_note="missing detail"),
        s["approver_headers"]))
    revised = validate_success(api.revise_reimbursement_claim(
        s["claim"]["id"], s["claimant_headers"]))
    assert revised["status"] == "DRAFT", f"revise returns to DRAFT, got {revised['status']}"


# ===========================================================================
# Corner: state_machines / due_statement_becomes_past_due_after_clock_advance
# ===========================================================================
def test_due_statement_becomes_past_due_on_clock_advance(api: ApiClient):
    """PRD §3.6: "when the clock is advanced and a DUE statement's due_at is now earlier
    than the new clock_utc while its amount_repaid_cents is still below its
    minimum_due_cents, the system automatically transitions that statement DUE ->
    PAST_DUE and increments its version."

    A DUE statement (closed 2026-06-30, due 2026-07-21, unpaid), after the clock
    advances to 2026-08-01, auto-transitions to PAST_DUE.

    Design: Corner/state_machines/due_statement_becomes_past_due_after_clock_advance
    """
    s = setup_due_statement_with_settled_spend(settled_amount_cents=30000,
                                               billing_model="CHARGE",
                                               clock="2026-06-30T00:00:00Z")
    set_clock(s["company"]["id"], "2026-08-01T00:00:00Z")
    after = validate_success(api.get_statement(s["statement"]["id"], ADMIN))
    assert after["status"] == "PAST_DUE", (
        f"DUE statement past due_at becomes PAST_DUE, got {after['status']}")
