"""State-machine cycles (difficulty queue) and invalid/terminal transitions (corner queue)."""
from test_helpers import (
    validate_success, validate_error,
    create_compliance_report_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    new_customer, new_site, new_equipment, new_technician, new_work_order,
    dispatch_work_order, new_contract, new_active_contract, setup_issued_invoice,
    setup_draft_report,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─────────────── Difficulty: WorkOrder dispatch/recall cycle ───────────────
def _dispatched_grease_work_order():
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    tech = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"])
    dispatch_work_order(wo["id"], tech["id"])
    return wo, tech


def test_recall_clears_technician_and_returns_to_scheduled(api):
    """PRD §3.3: "A `Dispatcher` may recall a dispatched order by requesting `to_status`
    `SCHEDULED`, which moves it `DISPATCHED → SCHEDULED` and clears `technician_id` back to null."

    Design: Difficulty/non_linear_state_machine/work_order_dispatch_recall_cycle
    """
    wo, tech = _dispatched_grease_work_order()
    res = api.transition_work_order(wo["id"], {"to_status": "SCHEDULED"}, DISPATCHER)
    recalled = validate_success(res, 200)
    assert recalled["status"] == "SCHEDULED", "recall must return the order to SCHEDULED"
    assert recalled["technician_id"] is None, "recall must clear technician_id to null"


def test_recalled_order_can_be_redispatched(api):
    """PRD §3.3: "A `Dispatcher` routes a `SCHEDULED` order by supplying a target `to_status`
    of `DISPATCHED` together with a `technician_id`, which advances the order
    `SCHEDULED → DISPATCHED` and records the assignment."

    Design: Difficulty/non_linear_state_machine/work_order_dispatch_recall_cycle
    """
    wo, tech = _dispatched_grease_work_order()
    validate_success(api.transition_work_order(wo["id"], {"to_status": "SCHEDULED"}, DISPATCHER), 200)
    res = api.transition_work_order(
        wo["id"], {"to_status": "DISPATCHED", "technician_id": tech["id"]}, DISPATCHER)
    redispatched = validate_success(res, 200)
    assert redispatched["status"] == "DISPATCHED", "recalled order must be re-dispatchable"
    assert redispatched["technician_id"] == tech["id"]


# ─────────────── Difficulty: ComplianceReport reject/revise cycle ───────────────
def _rejected_report():
    ctx = setup_draft_report()
    validate_success(api_client.submit_compliance_report(ctx["rep_id"], COMPLIANCE), 200)
    validate_success(api_client.record_report_decision(
        ctx["rep_id"], {"decision": "REJECTED", "decision_note": "insufficient"}, COMPLIANCE), 200)
    return ctx


def test_revise_returns_rejected_report_to_draft(api):
    """PRD §3.6: "A `REJECTED` report can be reopened for revision, moving it
    `REJECTED → DRAFT`, from which it can be corrected and re-submitted — a cyclic revision loop."

    Design: Difficulty/non_linear_state_machine/compliance_report_reject_revise_cycle
    """
    ctx = _rejected_report()
    res = api.revise_compliance_report(ctx["rep_id"], COMPLIANCE)
    revised = validate_success(res, 200)
    assert revised["status"] == "DRAFT", "revise must move a REJECTED report back to DRAFT"


def test_revised_report_can_be_resubmitted(api):
    """PRD §3.6: "The officer submits a `DRAFT` report, advancing it `DRAFT → SUBMITTED`,
    at which point `pumped_gallons_total` and `included_manifest_count` are frozen."

    Design: Difficulty/non_linear_state_machine/compliance_report_reject_revise_cycle
    """
    ctx = _rejected_report()
    validate_success(api.revise_compliance_report(ctx["rep_id"], COMPLIANCE), 200)
    res = api.submit_compliance_report(ctx["rep_id"], COMPLIANCE)
    resubmitted = validate_success(res, 200)
    assert resubmitted["status"] == "SUBMITTED", "revised report must be re-submittable"


# ─────────────── Corner: invalid / terminal transitions & preconditions ───────────────
def test_revise_non_rejected_report_returns_invalid_state(api):
    """PRD §3.6: "A `REJECTED` report can be reopened for revision, moving it
    `REJECTED → DRAFT`, from which it can be corrected and re-submitted — a cyclic revision loop."
    PRD §2.11: "From-state — the target resource is in a legal state for the requested
    transition; otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/revise_non_rejected_report_returns_invalid_state
    """
    ctx = setup_draft_report()  # report is DRAFT, not REJECTED
    res = api.revise_compliance_report(ctx["rep_id"], COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE")


def test_transition_cancelled_contract_returns_invalid_state(api):
    """PRD §3.1: "and an `ACTIVE` contract may be cancelled to the terminal `CANCELLED` state."
    PRD §2.11: "From-state — the target resource is in a legal state for the requested
    transition; otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/transition_cancelled_contract_returns_invalid_state
    """
    cust = new_customer()
    contract = new_active_contract(cust["id"], base_rate_cents=1000, tax_rate_bps=0)
    validate_success(api.transition_service_contract(
        contract["id"], {"to_status": "CANCELLED"}, ADMIN), 200)
    res = api.transition_service_contract(contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_close_customer_with_open_balance_returns_invalid_state(api):
    """PRD §3.1: "a close attempt against a customer with any outstanding balance is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_customer_with_open_balance_returns_invalid_state
    """
    ctx = setup_issued_invoice(credit_limit_cents=1000000, base_rate_cents=12500, tax_rate_bps=0)
    res = api.close_customer(ctx["cust_id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
