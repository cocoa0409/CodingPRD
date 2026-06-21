"""Transitive cascades, compensating invariants, the two-dimensional transaction
state machine, the approval-request cycle, and cross-entity state gates.

Difficulty queue: transitive_cascade, compensating_invariant,
non_linear_state_machine, cross_entity_state_dependency.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiClient, ApiErrorId,
    setup_company_with_card, setup_company_with_card_and_approver,
    setup_due_statement_with_settled_spend, capture_transaction,
    capture_settled_transaction, create_cleared_repayment, get_reward_account,
    create_company, create_employee, create_spend_policy, create_card,
    create_gl_account, suspend_company,
)
from test_helpers import factories as F
from test_helpers.test_users import (
    make_finance_admin_headers, make_approver_headers, make_cardholder_headers,
)

ADMIN = make_finance_admin_headers()


# ===========================================================================
# Difficulty: transitive_cascade / tc_repayment_clear_depth3_pays_statement
# ===========================================================================
def test_repayment_clear_lifts_repaid_total(api: ApiClient):
    """PRD §3.6: "Clearing it moves INITIATED -> CLEARED and cascades: the statement's
    amount_repaid_cents increases by the repayment's amount_cents; because that
    changed, the company's available_credit_cents increases by the same amount (the
    posted-unpaid component shrinks); and if the statement's amount_repaid_cents has
    reached or exceeded its minimum_due_cents, the statement (whether DUE or PAST_DUE)
    transitions to PAID."

    Clearing a 40000 repayment lifts amount_repaid_cents to 40000 and PAYs the
    (DUE, min_due 40000) statement.

    Design: Difficulty/transitive_cascade/tc_repayment_clear_depth3_pays_statement
    """
    s = setup_due_statement_with_settled_spend(settled_amount_cents=40000,
                                               billing_model="CHARGE")
    stmt = s["statement"]
    create_cleared_repayment(stmt["id"], 40000, s["statement_version"])
    after = validate_success(api.get_statement(stmt["id"], ADMIN))
    assert after["amount_repaid_cents"] == 40000, (
        f"repaid total expected 40000, got {after['amount_repaid_cents']}")
    assert after["status"] == "PAID", f"statement should be PAID, got {after['status']}"


def test_repayment_clear_restores_available_credit(api: ApiClient):
    """PRD §2.6: "When a repayment clears, the unpaid portion of its statement shrinks
    and available_credit_cents rises by the repaid amount"

    A full 40000 repayment clear restores the company's available_credit_cents to
    its 1,000,000 credit limit.

    Design: Difficulty/transitive_cascade/tc_repayment_clear_depth3_pays_statement
    """
    s = setup_due_statement_with_settled_spend(settled_amount_cents=40000,
                                               billing_model="CHARGE")
    create_cleared_repayment(s["statement"]["id"], 40000, s["statement_version"])
    company = validate_success(api.get_company(s["company"]["id"], ADMIN))
    assert company["available_credit_cents"] == 1_000_000, (
        f"available_credit restored to 1,000,000, got {company['available_credit_cents']}")


# ===========================================================================
# Difficulty: transitive_cascade / tc_settle_depth2_release_hold_and_accrue
# ===========================================================================
def test_settle_releases_hold_and_restores_credit(api: ApiClient):
    """PRD §3.3: "the hold of amount_cents is released from held_cents, which in turn
    lowers the open-holds component and triggers recomputation of available_credit_cents"
    PRD §2.6: "When a transaction settles, its hold leaves the first subtraction (the
    hold is released) but its settled amount joins a statement balance only once that
    statement closes"

    Settling a fully-held 10000 tx drops held_cents to 0 and (with the statement
    still OPEN) restores available_credit_cents to the 1,000,000 limit.

    Design: Difficulty/transitive_cascade/tc_settle_depth2_release_hold_and_accrue
    """
    base = setup_company_with_card(company_overrides={"credit_limit_cents": 1_000_000,
                                                      "reward_rate_default_bps": 100})
    capture_settled_transaction(base["card"]["id"], settled_amount_cents=10000,
                                amount_cents=10000)
    card = validate_success(api.get_card(base["card"]["id"], ADMIN))
    assert card["held_cents"] == 0, f"held_cents released, expected 0, got {card['held_cents']}"
    company = validate_success(api.get_company(base["company"]["id"], ADMIN))
    assert company["available_credit_cents"] == 1_000_000, (
        f"available_credit restored, got {company['available_credit_cents']}")


def test_settle_accrues_reward_into_account(api: ApiClient):
    """PRD §3.3: "the transaction's reward_points_cents is computed by the reward rule
    (§3.4) and that same amount is added to the reward account's accrued_points_cents
    and balance_points_cents"

    A 10000 settle at 100 bps accrues 100 into the RewardAccount (parallel hop).

    Design: Difficulty/transitive_cascade/tc_settle_depth2_release_hold_and_accrue
    """
    base = setup_company_with_card(company_overrides={"credit_limit_cents": 1_000_000,
                                                      "reward_rate_default_bps": 100})
    capture_settled_transaction(base["card"]["id"], settled_amount_cents=10000,
                                amount_cents=10000)
    ra = get_reward_account(base["company"]["id"])
    assert ra["accrued_points_cents"] == 100, (
        f"reward accrued expected 100, got {ra['accrued_points_cents']}")


# ===========================================================================
# Difficulty: compensating_invariant / ci_transaction_reverse_restores_available_credit
# ===========================================================================
def test_reverse_pending_restores_available_credit(api: ApiClient):
    """PRD §2.6: "When a transaction is reversed, its hold leaves the first subtraction
    and available_credit_cents returns to its pre-authorization value."
    PRD §3.3: "The reversal drops the card's held_cents by amount_cents and raises the
    company's available_credit_cents by the same amount_cents, so the credit pool
    returns exactly to its pre-authorization value."

    Reversing a 25000 PENDING tx restores available_credit to 1,000,000 and held to 0.

    Design: Difficulty/compensating_invariant/ci_transaction_reverse_restores_available_credit
    """
    base = setup_company_with_card(company_overrides={"credit_limit_cents": 1_000_000})
    tx = capture_transaction(base["card"]["id"], amount_cents=25000)
    reversed_tx = validate_success(api.reverse_transaction(tx["id"], ADMIN))
    assert reversed_tx["auth_status"] == "REVERSED"
    company = validate_success(api.get_company(base["company"]["id"], ADMIN))
    assert company["available_credit_cents"] == 1_000_000, (
        f"available_credit restored, got {company['available_credit_cents']}")
    card = validate_success(api.get_card(base["card"]["id"], ADMIN))
    assert card["held_cents"] == 0, f"held_cents restored to 0, got {card['held_cents']}"


def test_reverse_sets_auth_status_reversed(api: ApiClient):
    """PRD §3.3: "Reversing a transaction from PENDING or CLEARED moves auth_status to
    REVERSED (any other state yields ERR_INVALID_STATE)."

    A PENDING tx that is reversed reports auth_status REVERSED.

    Design: Difficulty/compensating_invariant/ci_transaction_reverse_restores_available_credit
    """
    base = setup_company_with_card(company_overrides={"credit_limit_cents": 1_000_000})
    tx = capture_transaction(base["card"]["id"], amount_cents=25000)
    reversed_tx = validate_success(api.reverse_transaction(tx["id"], ADMIN))
    assert reversed_tx["auth_status"] == "REVERSED", (
        f"reversed tx auth_status REVERSED, got {reversed_tx['auth_status']}")


# ===========================================================================
# Difficulty: compensating_invariant / ci_repayment_reverse_restores_repaid_and_unpays_statement
# ===========================================================================
def test_repayment_reverse_unpays_statement(api: ApiClient):
    """PRD §3.6: "Reversing a CLEARED repayment moves it to REVERSED and runs the
    compensating cascade: the statement's amount_repaid_cents decreases by amount_cents,
    the company's available_credit_cents decreases by the same amount, and if the
    statement had been PAID and its amount_repaid_cents now falls below minimum_due_cents,
    the statement reverts PAID -> DUE."

    A 40000 repayment that PAID the statement, when reversed, drives
    amount_repaid_cents to 0 and the statement back to DUE.

    Design: Difficulty/compensating_invariant/ci_repayment_reverse_restores_repaid_and_unpays_statement
    """
    s = setup_due_statement_with_settled_spend(settled_amount_cents=40000,
                                               billing_model="CHARGE")
    stmt = s["statement"]
    rp = create_cleared_repayment(stmt["id"], 40000, s["statement_version"])
    reversed_rp = validate_success(api.reverse_repayment(rp["id"], ADMIN))
    assert reversed_rp["status"] == "REVERSED"
    after = validate_success(api.get_statement(stmt["id"], ADMIN))
    assert after["amount_repaid_cents"] == 0, (
        f"repaid total restored to 0, got {after['amount_repaid_cents']}")
    assert after["status"] == "DUE", f"statement reverts to DUE, got {after['status']}"


def test_repayment_reverse_is_terminal_reversed(api: ApiClient):
    """PRD §3.6: "Both versions increment. FAILED and REVERSED are terminal for a
    repayment; clearing is defined only from INITIATED, failing only from INITIATED,
    and reversing only from CLEARED (each otherwise ERR_INVALID_STATE)."

    A reversed (terminal) repayment cannot be reversed again — ERR_INVALID_STATE.

    Design: Difficulty/compensating_invariant/ci_repayment_reverse_restores_repaid_and_unpays_statement
    """
    s = setup_due_statement_with_settled_spend(settled_amount_cents=40000,
                                               billing_model="CHARGE")
    rp = create_cleared_repayment(s["statement"]["id"], 40000, s["statement_version"])
    validate_success(api.reverse_repayment(rp["id"], ADMIN))
    resp = api.reverse_repayment(rp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty: non_linear_state_machine / nlsm_transaction_parallel_auth_and_review
# ===========================================================================
def test_transaction_auth_and_review_advance_independently(api: ApiClient):
    """PRD §3.3: "The two dimensions do not wait for each other: a transaction may be
    SETTLED while still UNREVIEWED, or MATCHED while still PENDING."
    PRD §3.4: "On a MATCH, the transaction advances along the compliance dimension to
    MATCHED and its version increments: from NEEDS_RECEIPT -> MATCHED for a transaction
    that required a receipt"

    A 10000 tx cleared on the auth dimension, then receipt-matched on the review
    dimension, ends CLEARED + MATCHED.

    Design: Difficulty/non_linear_state_machine/nlsm_transaction_parallel_auth_and_review
    """
    base = setup_company_with_card()
    ch = base["cardholder_headers"]
    tx = capture_transaction(base["card"]["id"], headers=ch, amount_cents=10000)
    assert tx["review_status"] == "NEEDS_RECEIPT"
    get_success_data(api.clear_transaction(tx["id"], ADMIN))
    get_success_data(api.upload_receipt(tx["id"], F.receipt_payload(10000, "Merchant"), ch))
    after = validate_success(api.get_transaction(tx["id"], ADMIN))
    assert after["auth_status"] == "CLEARED", f"auth stays CLEARED, got {after['auth_status']}"
    assert after["review_status"] == "MATCHED", (
        f"review independently advances to MATCHED, got {after['review_status']}")


def test_clearing_does_not_change_review_status(api: ApiClient):
    """PRD §3.3: "Clearing moves auth_status PENDING -> CLEARED (defined only from
    PENDING, else ERR_INVALID_STATE); the hold remains counted in both held_cents and
    available_credit_cents, because cleared money is still held, not yet posted."
    PRD §3.3: "The two dimensions do not wait for each other: a transaction may be
    SETTLED while still UNREVIEWED, or MATCHED while still PENDING."

    Clearing the auth dimension leaves a NEEDS_RECEIPT transaction's review_status
    untouched.

    Design: Difficulty/non_linear_state_machine/nlsm_transaction_parallel_auth_and_review
    """
    base = setup_company_with_card()
    tx = capture_transaction(base["card"]["id"], amount_cents=10000)
    assert tx["review_status"] == "NEEDS_RECEIPT"
    cleared = validate_success(api.clear_transaction(tx["id"], ADMIN))
    assert cleared["auth_status"] == "CLEARED"
    assert cleared["review_status"] == "NEEDS_RECEIPT", (
        f"review unchanged by clear, got {cleared['review_status']}")


# ===========================================================================
# Difficulty: non_linear_state_machine / nlsm_approval_request_reject_resubmit_cycle
# ===========================================================================
def _setup_rejected_request(amount_cents=20000, approval_threshold_cents=5000):
    """Cardholder + approver; high-value tx; PENDING request then REJECTED."""
    base = setup_company_with_card_and_approver(
        policy_overrides={"approval_threshold_cents": approval_threshold_cents})
    ch = base["cardholder_headers"]
    tx = capture_transaction(base["card"]["id"], headers=ch, amount_cents=amount_cents)
    ar = get_success_data(api_open_request(tx["id"], ch))
    get_success_data(reject_request(ar["id"], base["approver_headers"]))
    base["tx"] = tx
    base["approval_request"] = ar
    return base


def api_open_request(tx_id, headers):
    from test_helpers import api_client
    return api_client.open_approval_request(tx_id, {}, headers)


def reject_request(ar_id, headers):
    from test_helpers import api_client
    return api_client.reject_approval_request(ar_id, F.approval_decision_payload(decision_note="more info"), headers)


def test_resubmit_returns_request_to_pending(api: ApiClient):
    """PRD §3.5: "A rejected request is not dead: the original requester may resubmit
    it, moving it REJECTED -> PENDING, which increases revision_count by one and clears
    approver_employee_id back to null."

    Resubmitting a REJECTED request returns it to PENDING with revision_count 1.

    Design: Difficulty/non_linear_state_machine/nlsm_approval_request_reject_resubmit_cycle
    """
    base = _setup_rejected_request()
    ar = base["approval_request"]
    resubmitted = validate_success(api.resubmit_approval_request(ar["id"], base["cardholder_headers"]))
    assert resubmitted["status"] == "PENDING", f"resubmit -> PENDING, got {resubmitted['status']}"
    assert resubmitted["revision_count"] == 1, (
        f"revision_count -> 1, got {resubmitted['revision_count']}")


def test_resubmit_clears_approver_employee_id(api: ApiClient):
    """PRD §3.5: "the original requester may resubmit it, moving it REJECTED -> PENDING,
    which increases revision_count by one and clears approver_employee_id back to null."

    Resubmit clears the previously-recorded approver_employee_id back to null.

    Design: Difficulty/non_linear_state_machine/nlsm_approval_request_reject_resubmit_cycle
    """
    base = _setup_rejected_request()
    ar = base["approval_request"]
    resubmitted = validate_success(api.resubmit_approval_request(ar["id"], base["cardholder_headers"]))
    assert resubmitted["approver_employee_id"] is None, (
        f"approver_employee_id cleared to null, got {resubmitted['approver_employee_id']!r}")


# ===========================================================================
# Difficulty: cross_entity_state_dependency / cesd_approve_review_requires_approved_request
# ===========================================================================
def test_approve_review_blocked_by_pending_approval_request(api: ApiClient):
    """PRD §3.5: "Third, if the transaction's amount_cents exceeds the policy's
    approval_threshold_cents, there must exist an approval request for this transaction
    in status APPROVED, else ERR_APPROVAL_REQUIRED."

    A high-value (20000 > threshold 5000), GL-coded, MATCHED transaction whose
    ApprovalRequest is still PENDING is rejected with ERR_APPROVAL_REQUIRED.

    Design: Difficulty/cross_entity_state_dependency/cesd_approve_review_requires_approved_request
    """
    base = setup_company_with_card_and_approver(
        policy_overrides={"approval_threshold_cents": 5000}, with_gl=True)
    ch = base["cardholder_headers"]
    tx = capture_transaction(base["card"]["id"], headers=ch, amount_cents=20000,
                             gl_account_id=base["gl"]["id"])
    get_success_data(api.upload_receipt(tx["id"], F.receipt_payload(20000, "Merchant"), ch))
    get_success_data(api.open_approval_request(tx["id"], {}, ch))  # stays PENDING
    resp = api.approve_review(tx["id"], base["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_APPROVAL_REQUIRED.value)


def test_approve_review_succeeds_after_approved_request(api: ApiClient):
    """PRD §3.5: "Third, if the transaction's amount_cents exceeds the policy's
    approval_threshold_cents, there must exist an approval request for this transaction
    in status APPROVED, else ERR_APPROVAL_REQUIRED. ... On success the review moves to
    APPROVED and the transaction's version increments."

    Once the ApprovalRequest is APPROVED, the high-value MATCHED+GL-coded transaction's
    review advances to APPROVED.

    Design: Difficulty/cross_entity_state_dependency/cesd_approve_review_requires_approved_request
    """
    base = setup_company_with_card_and_approver(
        policy_overrides={"approval_threshold_cents": 5000}, with_gl=True)
    ch = base["cardholder_headers"]
    tx = capture_transaction(base["card"]["id"], headers=ch, amount_cents=20000,
                             gl_account_id=base["gl"]["id"])
    get_success_data(api.upload_receipt(tx["id"], F.receipt_payload(20000, "Merchant"), ch))
    ar = get_success_data(api.open_approval_request(tx["id"], {}, ch))
    get_success_data(api.approve_approval_request(ar["id"], {}, base["approver_headers"]))
    approved = validate_success(api.approve_review(tx["id"], base["approver_headers"]))
    assert approved["review_status"] == "APPROVED", (
        f"review advances to APPROVED, got {approved['review_status']}")


# ===========================================================================
# Difficulty: cross_entity_state_dependency / cesd_card_activate_requires_company_active
# ===========================================================================
def test_activate_physical_card_blocked_on_suspended_company(api: ApiClient):
    """PRD §3.2: "Activating a physical card moves it REQUESTED -> ACTIVE; this is
    defined only for a physical card ... and is blocked while the company is suspended
    with ERR_COMPANY_SUSPENDED."

    Activating a REQUESTED physical card on a SUSPENDED company is rejected with
    ERR_COMPANY_SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/cesd_card_activate_requires_company_active
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=1_000_000)
    emp = create_employee(company["id"], "ce2@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"])
    card = create_card(company["id"], emp["id"], pol["id"], form_factor="PHYSICAL")
    suspend_company(company["id"])
    resp = api.activate_card(card["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COMPANY_SUSPENDED.value)


def test_activate_physical_card_succeeds_on_active_company(api: ApiClient):
    """PRD §3.2: "A virtual card is born ready to spend, in status ACTIVE; a physical
    card is born in status REQUESTED and must be activated before it can be used."
    PRD §3.2: "Activating a physical card moves it REQUESTED -> ACTIVE"

    On an ACTIVE company, a REQUESTED physical card activates to ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/cesd_card_activate_requires_company_active
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=1_000_000)
    emp = create_employee(company["id"], "ce2b@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"])
    card = create_card(company["id"], emp["id"], pol["id"], form_factor="PHYSICAL")
    assert card["status"] == "REQUESTED"
    activated = validate_success(api.activate_card(card["id"], ADMIN))
    assert activated["status"] == "ACTIVE", (
        f"physical card activates to ACTIVE, got {activated['status']}")
