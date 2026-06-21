"""Statements of work and milestone deliverables: activation preconditions, the
sequence gate, invoice bubble-up to COMPLETED, and conserved invoiced value
(§3.10).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    get_success_data, make_supplier_headers, TEST_USERS,
    create_program, create_supplier,
    setup_draft_sow, add_milestone, setup_active_sow, setup_accepted_milestone,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_headers"]


# ===========================================================================
# Queue A: transitive_cascade / milestone_invoice_bubbles_sow_to_completed
# ===========================================================================

def test_invoicing_last_milestone_increments_invoiced_value(api):
    """PRD §3.10: "Invoicing increments the SOW's `invoiced_value_cents` by that
    milestone's `milestone_amount_cents`."

    Single ACCEPTED milestone amount 50000; after invoice the SOW's
    invoiced_value_cents == 50000.

    Design: Difficulty/transitive_cascade/milestone_invoice_bubbles_sow_to_completed
    """
    base = setup_accepted_milestone(amount_cents=50000, total_value_cents=100000)
    m = base["milestones"][0]
    get_success_data(api.invoice_milestone(m["id"], FIN))
    sow = get_success_data(api.get_sow(base["sow"]["id"], PM))
    assert sow["invoiced_value_cents"] == 50000, f"got {sow['invoiced_value_cents']}"


def test_invoicing_last_milestone_bubbles_sow_to_completed(api):
    """PRD §3.10: "If, after that increment, every milestone under the SOW is
    `INVOICED`, the system drives the SOW from `ACTIVE` to `COMPLETED` — a parent
    state that the system derives automatically from its children rather than
    from any direct request."

    Invoicing the only (last) milestone drives the SOW ACTIVE -> COMPLETED.

    Design: Difficulty/transitive_cascade/milestone_invoice_bubbles_sow_to_completed
    """
    base = setup_accepted_milestone(amount_cents=50000, total_value_cents=100000)
    m = base["milestones"][0]
    get_success_data(api.invoice_milestone(m["id"], FIN))
    sow = get_success_data(api.get_sow(base["sow"]["id"], PM))
    assert sow["status"] == "COMPLETED", f"got {sow['status']}"


# ===========================================================================
# Queue A: compensating_invariant / sow_invoiced_value_conserved_across_milestone_reject_restart
# ===========================================================================

def test_reject_leaves_invoiced_value_unchanged(api):
    """PRD §3.10: "Rejection moves the milestone from `SUBMITTED` to `REJECTED`"
    PRD §3.10: "A new SOW starts in `DRAFT` with `invoiced_value_cents` of 0."

    Rejecting a SUBMITTED milestone touches no INVOICED milestone, so the SOW's
    invoiced_value_cents stays 0 (the conserved money quantity is unchanged).

    Design: Difficulty/compensating_invariant/sow_invoiced_value_conserved_across_milestone_reject_restart
    """
    base = setup_active_sow([("M1", 40000, 1)], total_value_cents=100000)
    m = base["milestones"][0]
    sh = base["supplier_headers"]
    get_success_data(api.start_milestone(m["id"], sh))
    get_success_data(api.submit_milestone(m["id"], sh))
    get_success_data(api.reject_milestone(m["id"], HM))
    sow = get_success_data(api.get_sow(base["sow"]["id"], PM))
    assert sow["invoiced_value_cents"] == 0, f"got {sow['invoiced_value_cents']}"


def test_invoiced_value_counts_once_after_reject_restart_invoice(api):
    """PRD §3.10: "Invoicing increments the SOW's `invoiced_value_cents` by that
    milestone's `milestone_amount_cents`."
    PRD §3.10: "If, after that increment, every milestone under the SOW is
    `INVOICED`, the system drives the SOW from `ACTIVE` to `COMPLETED`"

    After a reject->restart->resubmit->accept->invoice lap, invoiced_value_cents
    equals exactly the one invoiced amount 40000 (no double count) and the SOW is
    COMPLETED.

    Design: Difficulty/compensating_invariant/sow_invoiced_value_conserved_across_milestone_reject_restart
    """
    base = setup_active_sow([("M1", 40000, 1)], total_value_cents=100000)
    m = base["milestones"][0]
    sh = base["supplier_headers"]
    get_success_data(api.start_milestone(m["id"], sh))
    get_success_data(api.submit_milestone(m["id"], sh))
    get_success_data(api.reject_milestone(m["id"], HM))
    get_success_data(api.start_milestone(m["id"], sh))
    get_success_data(api.submit_milestone(m["id"], sh))
    get_success_data(api.accept_milestone(m["id"], HM))
    get_success_data(api.invoice_milestone(m["id"], FIN))
    sow = get_success_data(api.get_sow(base["sow"]["id"], PM))
    assert sow["invoiced_value_cents"] == 40000, f"got {sow['invoiced_value_cents']}"
    assert sow["status"] == "COMPLETED", f"got {sow['status']}"


# ===========================================================================
# Queue B: validations / sow_value_exceeded_on_activate
# ===========================================================================

def test_activate_sow_milestones_exceeding_total_value_rejected(api):
    """PRD §3.10: "the sum of `milestone_amount_cents` over all milestones must
    not exceed `total_value_cents`, or it fails with `ERR_SOW_VALUE_EXCEEDED`."

    total 100000 with milestones 60000 + 50000 = 110000 -> ERR_SOW_VALUE_EXCEEDED.

    Design: Corner/validations/sow_value_exceeded_on_activate
    """
    base = setup_draft_sow(total_value_cents=100000)
    add_milestone(base["sow"]["id"], "M1", 60000, 1)
    add_milestone(base["sow"]["id"], "M2", 50000, 2)
    validate_error(api.activate_sow(base["sow"]["id"], PM),
                   ApiErrorId.ERR_SOW_VALUE_EXCEEDED.value)


# ===========================================================================
# Queue B: validations / activate_sow_with_no_milestones_rejected
# ===========================================================================

def test_activate_sow_with_no_milestones_rejected(api):
    """PRD §3.10: "at least one milestone must exist under the SOW, or it fails
    with `ERR_SOW_NO_MILESTONES`"

    Design: Corner/validations/activate_sow_with_no_milestones_rejected
    """
    base = setup_draft_sow(total_value_cents=100000)
    validate_error(api.activate_sow(base["sow"]["id"], PM),
                   ApiErrorId.ERR_SOW_NO_MILESTONES.value)


# ===========================================================================
# Queue B: state_machines / milestone_initial_state_is_pending
# ===========================================================================

def test_new_milestone_starts_pending(api):
    """PRD §3.10: "Milestones begin in `PENDING`."

    Design: Corner/state_machines/milestone_initial_state_is_pending
    """
    base = setup_draft_sow(total_value_cents=100000)
    data = validate_success(api.create_milestone(
        F.create_milestone_payload(base["sow"]["id"], name="M1",
                                   milestone_amount_cents=40000, sequence=1),
        PM,
    ), expected_status=201)
    assert data["status"] == "PENDING", f"got {data['status']}"


# ===========================================================================
# Queue B: state_machines / milestone_sequence_violation_blocks_out_of_order_submit
# ===========================================================================

def test_out_of_order_milestone_submit_rejected(api):
    """PRD §3.10: "submission enforces ordering — every lower-`sequence` milestone
    in the same SOW must already be `ACCEPTED` or `INVOICED`, or the submit is
    rejected with `ERR_MILESTONE_SEQUENCE_VIOLATION`."

    Submitting sequence 2 while sequence 1 is still IN_PROGRESS ->
    ERR_MILESTONE_SEQUENCE_VIOLATION.

    Design: Corner/state_machines/milestone_sequence_violation_blocks_out_of_order_submit
    """
    base = setup_active_sow([("M1", 30000, 1), ("M2", 30000, 2)], total_value_cents=100000)
    m1, m2 = base["milestones"]
    sh = base["supplier_headers"]
    get_success_data(api.start_milestone(m1["id"], sh))
    get_success_data(api.start_milestone(m2["id"], sh))
    validate_error(api.submit_milestone(m2["id"], sh),
                   ApiErrorId.ERR_MILESTONE_SEQUENCE_VIOLATION.value)


# ===========================================================================
# Queue B: state_machines / invoice_milestone_from_terminal_invoiced_returns_invalid_state
# ===========================================================================

def test_reinvoice_invoiced_milestone_returns_invalid_state(api):
    """PRD §3.10: "`Finance` invoices an `ACCEPTED` milestone, moving it from
    `ACCEPTED` to `INVOICED`; invoicing a milestone that is not `ACCEPTED` is
    rejected with `ERR_INVALID_STATE`. ... `INVOICED` is the terminal milestone
    state."

    Re-invoicing an already-INVOICED milestone -> ERR_INVALID_STATE.

    Design: Corner/state_machines/invoice_milestone_from_terminal_invoiced_returns_invalid_state
    """
    base = setup_accepted_milestone(amount_cents=40000, total_value_cents=100000)
    m = base["milestones"][0]
    get_success_data(api.invoice_milestone(m["id"], FIN))
    validate_error(api.invoice_milestone(m["id"], FIN), ApiErrorId.ERR_INVALID_STATE.value)
