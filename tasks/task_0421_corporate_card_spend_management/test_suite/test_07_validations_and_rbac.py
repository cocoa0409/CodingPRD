"""Amount and capture-gate validations, duplicate constraints, and role-based
access control (segregation of duties, read-only Auditor, missing user context).

Corner queue: validations, errors, rbac.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiClient, ApiErrorId,
    setup_company_with_card, capture_transaction, capture_cleared_transaction,
    setup_submitted_reimbursement_claim, suspend_company,
    create_company, create_employee, create_spend_policy, create_card,
    create_gl_account, NO_CONTEXT_HEADERS,
)
from test_helpers import factories as F
from test_helpers.test_users import (
    make_finance_admin_headers, make_cardholder_headers, make_approver_headers,
    make_auditor_headers,
)

ADMIN = make_finance_admin_headers()
AUDITOR = make_auditor_headers()


# ===========================================================================
# Corner: validations / capture_zero_amount_returns_invalid_amount
# ===========================================================================
def test_capture_zero_amount_rejected(api: ApiClient):
    """PRD §2.10: "every monetary amount supplied by a client must be strictly greater
    than zero. This covers a transaction's amount_cents ... A non-positive value ... is
    rejected with ERR_INVALID_AMOUNT (HTTP 422)."

    Capturing a transaction with amount_cents=0 is rejected with ERR_INVALID_AMOUNT.

    Design: Corner/validations/capture_zero_amount_returns_invalid_amount
    """
    base = setup_company_with_card()
    resp = api.capture_transaction(
        base["card"]["id"], F.capture_transaction_payload(amount_cents=0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


# ===========================================================================
# Corner: validations / capture_over_per_transaction_limit_rejected
# ===========================================================================
def test_capture_over_per_transaction_limit_rejected(api: ApiClient):
    """PRD §2.9: "third, the per-transaction policy ceiling — if amount_cents exceeds
    the policy's per_transaction_limit_cents, the capture is rejected with
    ERR_PER_TXN_LIMIT_EXCEEDED"

    Capture 60000 under a policy with per_transaction_limit_cents=50000 is rejected.

    Design: Corner/validations/capture_over_per_transaction_limit_rejected
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=10_000_000)
    emp = create_employee(company["id"], "pl@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"], name="Lim", per_transaction_limit_cents=50000)
    card = create_card(company["id"], emp["id"], pol["id"], card_limit_cents=5_000_000)
    resp = api.capture_transaction(
        card["id"], F.capture_transaction_payload(merchant_name="Big", amount_cents=60000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_PER_TXN_LIMIT_EXCEEDED.value)


# ===========================================================================
# Corner: validations / capture_over_card_headroom_rejected
# ===========================================================================
def test_capture_over_card_headroom_rejected(api: ApiClient):
    """PRD §2.9: "fourth, the card's remaining headroom — if amount_cents exceeds
    card_limit_cents minus the card's current held_cents, the capture is rejected with
    ERR_CARD_LIMIT_EXCEEDED"

    With card_limit 50000 and a 40000 PENDING hold, a 20000 capture exceeds the
    remaining 10000 headroom and is rejected.

    Design: Corner/validations/capture_over_card_headroom_rejected
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=10_000_000)
    emp = create_employee(company["id"], "hr@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"])
    card = create_card(company["id"], emp["id"], pol["id"], card_limit_cents=50000)
    capture_transaction(card["id"], merchant_name="First", amount_cents=40000)
    resp = api.capture_transaction(
        card["id"], F.capture_transaction_payload(merchant_name="Second", amount_cents=20000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CARD_LIMIT_EXCEEDED.value)


# ===========================================================================
# Corner: validations / capture_over_company_credit_returns_402
# ===========================================================================
def test_capture_over_company_credit_returns_402(api: ApiClient):
    """PRD §2.9: "and fifth, the company credit pool — if amount_cents exceeds the
    company's available_credit_cents, the capture is rejected with ERR_INSUFFICIENT_CREDIT
    and HTTP status 402."

    Company credit_limit 30000, card_limit 100000: a 40000 capture exceeds available
    credit and returns ERR_INSUFFICIENT_CREDIT (402).

    Design: Corner/validations/capture_over_company_credit_returns_402
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=30000)
    emp = create_employee(company["id"], "cc@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"])
    card = create_card(company["id"], emp["id"], pol["id"], card_limit_cents=100000)
    resp = api.capture_transaction(
        card["id"], F.capture_transaction_payload(merchant_name="Over", amount_cents=40000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value)


# ===========================================================================
# Corner: validations / settle_over_authorized_amount_rejected
# ===========================================================================
def test_settle_over_authorized_amount_rejected(api: ApiClient):
    """PRD §3.3: "The settle request supplies settled_amount_cents, the final cleared
    amount, which must be greater than zero and no greater than the authorized
    amount_cents (a partial capture is allowed; a value outside that range yields
    ERR_INVALID_AMOUNT)."

    Settling 6000 on a tx authorized at 5000 is rejected with ERR_INVALID_AMOUNT.

    Design: Corner/validations/settle_over_authorized_amount_rejected
    """
    base = setup_company_with_card()
    tx = capture_cleared_transaction(base["card"]["id"], amount_cents=5000)
    resp = api.settle_transaction(tx["id"], F.settle_payload(6000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


# ===========================================================================
# Corner: validations / open_approval_request_not_needed_below_threshold
# ===========================================================================
def test_open_approval_request_below_threshold_rejected(api: ApiClient):
    """PRD §3.5: "An approval request is only meaningful for a transaction whose
    amount_cents exceeds the governing policy's approval_threshold_cents; opening one
    for a transaction at or below that threshold is rejected with ERR_APPROVAL_NOT_NEEDED."

    A tx of 5000 (<= threshold 10000) cannot open an approval request.

    Design: Corner/validations/open_approval_request_not_needed_below_threshold
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=1_000_000)
    emp = create_employee(company["id"], "an@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"], name="Thr", approval_threshold_cents=10000)
    card = create_card(company["id"], emp["id"], pol["id"])
    ch = make_cardholder_headers(emp["id"])
    tx = capture_transaction(card["id"], headers=ch, amount_cents=5000)
    resp = api.open_approval_request(tx["id"], {}, ch)
    validate_error(resp, ApiErrorId.ERR_APPROVAL_NOT_NEEDED.value)


# ===========================================================================
# Corner: validations / settle_on_suspended_company_rejected
# ===========================================================================
def test_settle_on_suspended_company_rejected(api: ApiClient):
    """PRD §3.1: "A suspended company blocks three money-forward operations — card
    activation, card unfreeze, and transaction settlement — each of which is rejected
    with ERR_COMPANY_SUSPENDED while the company is not ACTIVE."

    Settling a CLEARED transaction on a SUSPENDED company is rejected with
    ERR_COMPANY_SUSPENDED.

    Design: Corner/validations/settle_on_suspended_company_rejected
    """
    base = setup_company_with_card()
    tx = capture_cleared_transaction(base["card"]["id"], amount_cents=5000)
    suspend_company(base["company"]["id"], reason="compliance hold")
    resp = api.settle_transaction(tx["id"], F.settle_payload(5000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_COMPANY_SUSPENDED.value)


# ===========================================================================
# Corner: errors / duplicate_gl_code_rejected
# ===========================================================================
def test_duplicate_gl_code_rejected(api: ApiClient):
    """PRD §3.1: "the gl_code must be unique among the company's ACTIVE GL accounts,
    and a duplicate is rejected with ERR_DUPLICATE_GL_CODE."

    A second ACTIVE GL account reusing gl_code 9000 in the same company is rejected.

    Design: Corner/errors/duplicate_gl_code_rejected
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=1_000_000)
    create_gl_account(company["id"], gl_code="9000", name="First")
    resp = api.create_gl_account(
        F.create_gl_account_payload(company["id"], gl_code="9000", name="Second"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_GL_CODE.value)


# ===========================================================================
# Corner: rbac / cardholder_cannot_settle_transaction_forbidden
# ===========================================================================
def test_cardholder_cannot_settle_transaction_forbidden(api: ApiClient):
    """PRD §4 (endpoint table): "POST /transactions/{txId}/settle ... FinanceAdmin"
    PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_FOR_ROLE."

    A CardholderEmployee calling the FinanceAdmin-only settle endpoint is rejected
    with ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/cardholder_cannot_settle_transaction_forbidden
    """
    base = setup_company_with_card()
    tx = capture_cleared_transaction(base["card"]["id"], amount_cents=5000)
    resp = api.settle_transaction(tx["id"], F.settle_payload(5000), base["cardholder_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# Corner: rbac / auditor_cannot_create_company_forbidden
# ===========================================================================
def test_auditor_cannot_create_company_forbidden(api: ApiClient):
    """PRD §2.1: "the Auditor role is read-only and may invoke only the listing and
    retrieval (GET) endpoints across all resources."

    An Auditor calling POST /companies (a write) is rejected with ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/auditor_cannot_create_company_forbidden
    """
    resp = api.create_company(
        F.create_company_payload(legal_name="Aud Co", billing_model="CHARGE"), AUDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# Corner: rbac / approver_self_approval_on_own_reimbursement_forbidden
# ===========================================================================
def test_approver_cannot_approve_own_reimbursement(api: ApiClient):
    """PRD §3.7: "Approving moves it SUBMITTED -> APPROVED; it is defined only from
    SUBMITTED (else ERR_INVALID_STATE), forbidden when the approver's X-User-ID equals
    the claimant's employee_id (ERR_SELF_APPROVAL)"

    An approver whose X-User-ID equals the claimant's employee_id is rejected with
    ERR_SELF_APPROVAL when approving their own submitted claim.

    Design: Corner/rbac/approver_self_approval_on_own_reimbursement_forbidden
    """
    s = setup_submitted_reimbursement_claim(amount_cents=5000, receipt_amount_cents=5000,
                                            claimant_role="APPROVER")
    # The claimant employee approves their own claim using their own id as approver.
    self_approver_headers = make_approver_headers(s["claimant"]["id"])
    resp = api.approve_reimbursement_claim(s["claim"]["id"], self_approver_headers)
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL.value)


# ===========================================================================
# Corner: rbac / missing_user_context_header_rejected
# ===========================================================================
def test_missing_user_context_header_rejected(api: ApiClient):
    """PRD §2.1: "Every request to the API must carry two mandatory HTTP headers:
    X-User-ID, identifying the acting user, and X-User-Role, declaring the operational
    capacity under which the request is made. A request missing either header, or
    carrying a malformed value, is rejected with ERR_MISSING_USER_CONTEXT."

    A request with neither X-User-ID nor X-User-Role is rejected with
    ERR_MISSING_USER_CONTEXT (400).

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api.list_companies(NO_CONTEXT_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)
