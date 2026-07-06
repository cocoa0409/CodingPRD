"""State-machine preconditions, terminal lockdown, and the two cyclic lifecycles —
the catering revision loop and the vendor-invoice dispute loop (PRD §3.1, §3.2, §3.6, §3.7).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_site, create_cycle, add_item, create_employee, create_pos,
    setup_session, setup_catering_order, setup_received_po, setup_matched_invoice, create_invoice,
    create_service_session_payload,
    make_coordinator_headers, make_approver_headers,
)

MANAGER = TEST_USERS["cafeteria_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


# ─── Corner: state_machines ──────────────────────────────────────────────────
def test_publish_empty_menu_cycle_rejected(api):
    """PRD §3.1: "Publishing a cycle transitions it from `DRAFT` to the terminal
    `PUBLISHED` state, and requires that at least one menu item already exists for that
    cycle — publishing an empty cycle is rejected with `ERR_EMPTY_MENU_CYCLE`."

    Design: Corner/state_machines/publish_empty_menu_cycle_returns_error
    """
    site = create_site()
    cycle = create_cycle(site["id"])
    res = api.publish_menu_cycle(cycle["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_EMPTY_MENU_CYCLE.value, expected_status=409)
    reread = validate_success(api.get_menu_cycle(cycle["id"], MANAGER), 200)
    assert reread["status"] == "DRAFT"


def test_open_session_with_unpublished_cycle_rejected(api):
    """PRD §3.2: "Opening the session then advances it from `FORECAST_LOCKED` to
    `IN_SERVICE`, and requires that the referenced menu cycle is `PUBLISHED`; opening
    against a non-published cycle is rejected with `ERR_MENU_CYCLE_NOT_PUBLISHED`."

    Design: Corner/state_machines/open_session_unpublished_cycle_rejected
    """
    site = create_site()
    cycle = create_cycle(site["id"])
    add_item(cycle["id"])  # cycle has an item but is never published
    session = validate_success(api.create_service_session(
        create_service_session_payload(site["id"], cycle["id"]), MANAGER), 201)
    validate_success(api.lock_forecast(session["id"], MANAGER), 200)
    res = api.open_session(session["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_MENU_CYCLE_NOT_PUBLISHED.value, expected_status=409)


def test_pay_unmatched_invoice_invalid_state(api):
    """PRD §3.7: "An `APPROVED` invoice is finally paid, advancing it from `APPROVED` to
    the terminal `PAID` state."
    PRD §2.8: "State — the target resource is in a state that permits the requested
    transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/pay_unmatched_invoice_invalid_state
    """
    base = setup_received_po()
    invoice = create_invoice(base["vendor"]["id"], base["po"]["id"], 2000)  # RECEIVED, not APPROVED
    res = api.pay_vendor_invoice(invoice["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_match_paid_invoice_terminal_lockdown(api):
    """PRD §3.7: "An `APPROVED` invoice is finally paid, advancing it from `APPROVED` to
    the terminal `PAID` state."
    PRD §2.8: "State — the target resource is in a state that permits the requested
    transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/match_paid_invoice_terminal_lockdown
    """
    ctx = setup_matched_invoice(2000)  # variance 0
    validate_success(api.resolve_vendor_invoice(ctx["invoice"]["id"], {"resolution": "APPROVE"}, FINANCE), 200)
    paid = validate_success(api.pay_vendor_invoice(ctx["invoice"]["id"], FINANCE), 200)
    assert paid["status"] == "PAID"
    res = api.match_vendor_invoice(ctx["invoice"]["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    reread = validate_success(api.get_vendor_invoice(ctx["invoice"]["id"], FINANCE), 200)
    assert reread["status"] == "PAID"


def test_cancel_in_service_session_with_sales_rejected(api):
    """PRD §3.2: "a session already carrying one or more `COMPLETED` transactions cannot be
    cancelled from `IN_SERVICE`, which is rejected with `ERR_SESSION_HAS_SALES`."

    Design: Corner/state_machines/cancel_session_with_sales_rejected
    """
    ctx = setup_session(stage="IN_SERVICE")
    create_pos(ctx["employee"]["id"], ctx["session"]["id"],
               [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}])
    res = api.cancel_session(ctx["session"]["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_SESSION_HAS_SALES.value, expected_status=409)


# ─── Difficulty: non_linear_state_machine — catering revision cycle ──────────
def test_catering_review_revision_pulls_order_back_to_draft(api):
    """PRD §3.6: "a `decision` of `REQUEST_REVISION` moves it from `SUBMITTED` to
    `REVISION_REQUESTED`."
    PRD §3.6: "From `REVISION_REQUESTED`, the coordinator may revise the order, pulling it
    back from `REVISION_REQUESTED` to `DRAFT`, where `lines` and `headcount` become
    editable again and pricing is recomputed on the next submit; the cycle
    `REVISION_REQUESTED → DRAFT → SUBMITTED` re-enters review."

    Design: Difficulty/non_linear_state_machine/catering_revision_cycle
    """
    ctx = setup_catering_order(target="SUBMITTED")
    coord = make_coordinator_headers(ctx["coordinator_id"])
    appr = make_approver_headers(ctx["approver_id"])

    reviewed = validate_success(api.review_catering_order(
        ctx["order"]["id"], {"decision": "REQUEST_REVISION"}, appr), 200)
    assert reviewed["status"] == "REVISION_REQUESTED"

    revised = validate_success(api.revise_catering_order(ctx["order"]["id"], coord), 200)
    assert revised["status"] == "DRAFT"


def test_catering_resubmit_after_revision_reenters_review(api):
    """PRD §3.6: "the cycle `REVISION_REQUESTED → DRAFT → SUBMITTED` re-enters review."

    Design: Difficulty/non_linear_state_machine/catering_revision_cycle
    """
    ctx = setup_catering_order(target="SUBMITTED")
    coord = make_coordinator_headers(ctx["coordinator_id"])
    appr = make_approver_headers(ctx["approver_id"])

    validate_success(api.review_catering_order(ctx["order"]["id"], {"decision": "REQUEST_REVISION"}, appr), 200)
    validate_success(api.revise_catering_order(ctx["order"]["id"], coord), 200)
    resubmitted = validate_success(api.submit_catering_order(ctx["order"]["id"], coord), 200)
    assert resubmitted["status"] == "SUBMITTED"


# ─── Difficulty: non_linear_state_machine — invoice dispute cycle ────────────
def test_invoice_dispute_resubmit_rematch_clears_variance(api):
    """PRD §3.7: "A `resolution` of `DISPUTE` moves the invoice from `MATCHED` to
    `DISPUTED` with no tolerance check. A disputed invoice may be resubmitted, moving it
    from `DISPUTED` back to `RECEIVED` with a corrected `invoiced_amount_cents` supplied in
    the request; on resubmit the stored amount is replaced and `matched_variance_cents` is
    cleared, so the cycle `MATCHED → DISPUTED → RECEIVED → MATCHED` can re-run the match."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle
    """
    ctx = setup_matched_invoice(3000, line=("FLOUR", 10, 200))  # PO total 2000, variance 1000
    inv_id = ctx["invoice"]["id"]
    validate_success(api.resolve_vendor_invoice(inv_id, {"resolution": "DISPUTE"}, FINANCE), 200)
    validate_success(api.resubmit_vendor_invoice(inv_id, {"invoiced_amount_cents": 2000}, FINANCE), 200)
    rematched = validate_success(api.match_vendor_invoice(inv_id, FINANCE), 200)
    assert rematched["matched_variance_cents"] == 0
    assert rematched["status"] == "MATCHED"


def test_invoice_dispute_cycle_second_match_approves(api):
    """PRD §3.7: "A `resolution` of `APPROVE` advances the invoice from `MATCHED` to
    `APPROVED`, but only when the absolute value of `matched_variance_cents` is within the
    match tolerance of 500 cents; a larger absolute variance is rejected with
    `ERR_VARIANCE_TOO_LARGE`."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle
    """
    ctx = setup_matched_invoice(3000, line=("FLOUR", 10, 200))
    inv_id = ctx["invoice"]["id"]
    validate_success(api.resolve_vendor_invoice(inv_id, {"resolution": "DISPUTE"}, FINANCE), 200)
    validate_success(api.resubmit_vendor_invoice(inv_id, {"invoiced_amount_cents": 2000}, FINANCE), 200)
    validate_success(api.match_vendor_invoice(inv_id, FINANCE), 200)
    approved = validate_success(api.resolve_vendor_invoice(inv_id, {"resolution": "APPROVE"}, FINANCE), 200)
    assert approved["status"] == "APPROVED"
