"""Application origination state machine: initial state, transitions, preconditions,
form-package branching, and independent status axes.

Covers corner-design section: state_machines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_application_payload, create_form_package_payload, create_credit_memo_payload,
    create_lender, create_borrower, create_application,
    create_draft_application, create_underwriting_application,
    reach_pending_approval, reach_fully_disbursed,
    file_and_accept_servicing_report, offer_guaranty_sale, settle_guaranty_sale,
    add_collateral, cleared_form_package, author_credit_memo,
    TEST_USERS,
)
from test_helpers.api_client import api_client

OFFICER = TEST_USERS["loan_officer_headers"]
APPROVER = TEST_USERS["credit_approver_headers"]
SBA = TEST_USERS["sba_officer_headers"]
INVESTOR = TEST_USERS["investor_servicer_headers"]


def test_new_application_initial_state_is_draft(api, loan_officer_headers):
    """PRD §3.1: "the application starts in `DRAFT` status with `servicing_status` of `NOT_SERVICING` and `guaranty_status` of `RETAINED`."

    Design: Corner/state_machines/new_application_initial_state_is_draft
    """
    lender = create_lender(name="Init CDC")
    borrower = create_borrower(lender["id"], legal_name="Init LLC")
    res = api.create_application(create_application_payload(borrower["id"]), loan_officer_headers)
    app = validate_success(res, 201)
    assert app["status"] == "DRAFT"
    assert app["servicing_status"] == "NOT_SERVICING"
    assert app["guaranty_status"] == "RETAINED"


def test_authorize_from_draft_returns_invalid_state(api, sba_officer_headers):
    """PRD §2.10: "for a state-transition endpoint, the target resource must currently be in a state from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409)."
    PRD §3.6: "an `SbaOfficer` authorizes it, advancing `status` from `APPROVED` to `AUTHORIZED`."

    Design: Corner/state_machines/authorize_from_draft_returns_invalid_state
    """
    lender = create_lender(name="Is CDC")
    borrower = create_borrower(lender["id"], legal_name="Is LLC")
    app = create_application(borrower["id"])
    res = api.authorize_application(app["id"], sba_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_application(app["id"], sba_officer_headers), 200)
    assert after["status"] == "DRAFT"
    assert after["guaranteed_amount_cents"] == 0


def test_withdrawn_application_is_terminal(api, loan_officer_headers):
    """PRD §3.5: "a `LoanOfficer` may withdraw it, moving `status` to `WITHDRAWN`. `WITHDRAWN` is terminal on the origination axis and carries no other side effects."
    PRD §2.10: "the target resource must currently be in a state from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/withdrawn_application_is_terminal
    """
    ctx = create_draft_application()
    aid = ctx["application"]["id"]
    validate_success(api.withdraw_application(aid, loan_officer_headers), 200)
    res = api.submit_application(aid, loan_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_application(aid, loan_officer_headers), 200)
    assert after["status"] == "WITHDRAWN"


def test_submit_with_no_proceeds_returns_no_proceeds(api, loan_officer_headers):
    """PRD §3.4: "at least one proceeds line item must exist, or the submit is rejected with `ERR_NO_PROCEEDS`."

    Design: Corner/state_machines/submit_with_no_proceeds_returns_no_proceeds
    """
    lender = create_lender(name="Np CDC")
    borrower = create_borrower(lender["id"], legal_name="Np LLC")
    app = create_application(borrower["id"])
    res = api.submit_application(app["id"], loan_officer_headers)
    validate_error(res, ApiErrorId.ERR_NO_PROCEEDS.value)
    after = validate_success(api.get_application(app["id"], loan_officer_headers), 200)
    assert after["status"] == "DRAFT"


def test_submit_proceeds_sum_mismatch_returns_proceeds_mismatch(api, loan_officer_headers):
    """PRD §3.4: "the sum of the `amount_cents` across all proceeds line items must equal the application's `requested_amount_cents`, or the submit is rejected with `ERR_PROCEEDS_MISMATCH`."

    Design: Corner/state_machines/submit_proceeds_sum_mismatch_returns_proceeds_mismatch
    """
    # requested 50000000 but a single proceeds line of 40000000.
    ctx = create_draft_application(proceeds=False)
    aid = ctx["application"]["id"]
    api.create_proceeds(
        {"application_id": aid, "use_category": "WORKING_CAPITAL", "amount_cents": 40_000_000},
        loan_officer_headers)
    res = api.submit_application(aid, loan_officer_headers)
    validate_error(res, ApiErrorId.ERR_PROCEEDS_MISMATCH.value)


def test_form_package_submit_incomplete_returns_form_incomplete(api, loan_officer_headers):
    """PRD §3.3: "Submission is permitted only when both `form_1919_complete` and `form_1920_complete` are true; if either form is not yet marked complete, the submit is rejected with `ERR_FORM_INCOMPLETE`."

    Design: Corner/state_machines/form_package_submit_incomplete_returns_form_incomplete
    """
    lender = create_lender(name="Fi CDC")
    borrower = create_borrower(lender["id"], legal_name="Fi LLC")
    app = create_application(borrower["id"])
    fp = validate_success(api.create_form_package(
        create_form_package_payload(app["id"], form_1919_complete=True,
                                    form_1920_complete=False, character_cleared=True),
        loan_officer_headers), 201)
    res = api.submit_form_package(fp["id"], loan_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORM_INCOMPLETE.value)
    after = validate_success(api.list_form_packages(app["id"], loan_officer_headers), 200)


def test_approve_declined_recommendation_returns_memo_not_approvable(api):
    """PRD §3.5: "the submitted memo's `recommendation` must be `APPROVE`, or the approval is rejected with `ERR_MEMO_NOT_APPROVABLE`."

    Design: Corner/state_machines/approve_declined_recommendation_returns_memo_not_approvable
    """
    ctx = reach_pending_approval(recommendation="DECLINE")
    aid = ctx["application"]["id"]
    res = api_client.approve_application(aid, APPROVER)
    validate_error(res, ApiErrorId.ERR_MEMO_NOT_APPROVABLE.value)
    after = validate_success(api_client.get_application(aid, SBA), 200)
    assert after["status"] == "PENDING_APPROVAL"


def test_declare_default_not_delinquent_enough_returns_error(api):
    """PRD §3.10: "Default may be declared only when the most-recent accepted servicing report shows `days_past_due` of at least 90; otherwise the declaration is rejected with `ERR_NOT_DELINQUENT_ENOUGH`."

    Design: Corner/state_machines/declare_default_not_delinquent_enough_returns_error
    """
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    # Accepted report with days_past_due 75 -> DELINQUENT (>=60) but not default-eligible (<90).
    file_and_accept_servicing_report(aid, 0, 0, principal_paid_cents=0, days_past_due=75)
    res = api_client.declare_default(aid, OFFICER)
    validate_error(res, ApiErrorId.ERR_NOT_DELINQUENT_ENOUGH.value)
    after = validate_success(api_client.get_application(aid, SBA), 200)
    assert after["servicing_status"] == "DELINQUENT"


def test_open_liquidation_when_not_defaulted_returns_not_defaulted(api):
    """PRD §3.10: "Opening is permitted only when `servicing_status` is `DEFAULTED`, or it is rejected with `ERR_NOT_DEFAULTED`."

    Design: Corner/state_machines/liquidation_open_when_not_defaulted_returns_not_defaulted
    """
    ctx = reach_fully_disbursed()  # servicing_status CURRENT, never defaulted
    aid = ctx["application"]["id"]
    res = api_client.create_liquidation(
        {"application_id": aid, "recovery_cents": 1_000_000, "expense_cents": 0}, OFFICER)
    validate_error(res, ApiErrorId.ERR_NOT_DEFAULTED.value)


def test_form_package_cleared_branch_unblocks_credit_memo(api):
    """PRD §3.3: "When `character_cleared` is true, the package moves to `CLEARED`, which unblocks credit-memo submission downstream."
    PRD §3.4: "Submitting the credit memo advances the memo from `DRAFT` to `SUBMITTED` and the application's `status` from `UNDERWRITING` to `PENDING_APPROVAL`."

    Design: Corner/state_machines/form_package_branch_cleared_unblocks_credit_memo
    """
    ctx = create_underwriting_application()
    aid = ctx["application"]["id"]
    add_collateral(aid, asset_type="REAL_ESTATE", appraised_value_cents=70_000_000)
    cleared_form_package(aid, character_cleared=True)
    memo = author_credit_memo(aid, recommendation="APPROVE")
    res = api_client.submit_credit_memo(memo["id"], OFFICER)
    submitted = validate_success(res, 200)
    assert submitted["status"] == "SUBMITTED"
    after = validate_success(api_client.get_application(aid, SBA), 200)
    assert after["status"] == "PENDING_APPROVAL"


def test_parallel_axes_independent_sold_while_delinquent(api):
    """PRD §2.8: "These last two axes are genuinely independent: a loan may be `SOLD` on the guaranty axis while simultaneously `DELINQUENT` on the servicing axis, and an operation that advances one axis does not move the other unless §3 explicitly says so."
    PRD §3.9: "an accepted report whose `days_past_due` is at least 60 moves `servicing_status` from `CURRENT` to `DELINQUENT`".

    Design: Corner/state_machines/parallel_axes_independent_sold_while_delinquent
    """
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    app = validate_success(api_client.get_application(aid, SBA), 200)
    # Sell the guaranteed portion: guaranty_status RETAINED -> SOLD.
    sale = offer_guaranty_sale(aid, app["guaranteed_amount_cents"], premium_bps=350)
    settle_guaranty_sale(sale["id"], app["version"])
    # Accept a report with days_past_due 95: servicing_status CURRENT -> DELINQUENT.
    file_and_accept_servicing_report(aid, 0, 0, principal_paid_cents=0, days_past_due=95)
    after = validate_success(api_client.get_application(aid, SBA), 200)
    assert after["servicing_status"] == "DELINQUENT"
    assert after["guaranty_status"] == "SOLD"
