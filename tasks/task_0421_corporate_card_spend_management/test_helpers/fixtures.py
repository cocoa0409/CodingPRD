"""Composite setup helpers.

Most interesting claims require the system to be in a specific multi-step state
that takes several API calls to reach. These helpers encapsulate those preambles
so tests focus on assertions. All internal calls use get_success_data() (lenient)
so a setup misstep surfaces as a clear "Setup failed" rather than a confusing
assertion deep in a test.

The harness re-launches the server before every test, so every helper builds its
preconditions from scratch via PRD endpoints only. After creating an
entity-backed Employee, ownership-gated calls thread the real Employee.id through
make_<role>_headers(...).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_finance_admin_headers, make_approver_headers, make_cardholder_headers,
)
from . import factories as F

ADMIN = make_finance_admin_headers()


# ---------------------------------------------------------------------------
# Tier 0 — primitive creators
# ---------------------------------------------------------------------------
def create_company(**overrides):
    """Create a Company (also mints its RewardAccount + cycle-1 OPEN statement)."""
    return get_success_data(api_client.create_company(
        F.create_company_payload(**overrides), ADMIN))


def get_open_statement(company_id):
    """Fetch the company's earliest statement (cycle 1 OPEN at creation)."""
    data, _meta = _list(api_client.list_statements(ADMIN, params={"company_id": company_id}))
    # statements sorted by created_at ascending; cycle 1 is first.
    return data[0]


def get_reward_account(company_id):
    data, _meta = _list(api_client.list_reward_accounts(ADMIN, params={"company_id": company_id}))
    return data[0]


def set_clock(company_id, to_iso8601):
    return get_success_data(api_client.set_clock(
        F.set_clock_payload(company_id, to_iso8601), ADMIN))


def suspend_company(company_id, reason="ops freeze"):
    return get_success_data(api_client.suspend_company(
        company_id, F.suspend_company_payload(reason=reason), ADMIN))


def create_employee(company_id, email, full_name="Emp", employee_role="CARDHOLDER", **overrides):
    return get_success_data(api_client.create_employee(
        F.create_employee_payload(
            company_id, email=email, full_name=full_name,
            employee_role=employee_role, **overrides), ADMIN))


def create_gl_account(company_id, gl_code="6000", name="Travel"):
    return get_success_data(api_client.create_gl_account(
        F.create_gl_account_payload(company_id, gl_code=gl_code, name=name), ADMIN))


def create_spend_policy(company_id, **overrides):
    return get_success_data(api_client.create_spend_policy(
        F.create_spend_policy_payload(company_id, **overrides), ADMIN))


def create_card(company_id, employee_id, spend_policy_id, **overrides):
    return get_success_data(api_client.create_card(
        F.create_card_payload(company_id, employee_id, spend_policy_id, **overrides), ADMIN))


def _list(response):
    """Return (data_list, meta) from a 2xx list response, lenient on status."""
    get_success_data(response)
    body = response.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 1 — org graph baselines
# ---------------------------------------------------------------------------
def setup_company_with_card(
    company_overrides=None,
    policy_overrides=None,
    card_overrides=None,
    cardholder_email="holder@acme.com",
):
    """Active company + cardholder employee + policy + an ACTIVE VIRTUAL card.

    Returns dict: company, cardholder, policy, card, reward_account,
    open_statement, cardholder_headers.
    """
    company = create_company(**(company_overrides or {}))
    cardholder = create_employee(company["id"], cardholder_email, "Holder", "CARDHOLDER")
    policy = create_spend_policy(company["id"], **(policy_overrides or {}))
    card = create_card(
        company["id"], cardholder["id"], policy["id"], **(card_overrides or {}))
    return {
        "company": company,
        "cardholder": cardholder,
        "policy": policy,
        "card": card,
        "reward_account": get_reward_account(company["id"]),
        "open_statement": get_open_statement(company["id"]),
        "cardholder_headers": make_cardholder_headers(cardholder["id"]),
    }


def setup_company_with_card_and_approver(
    company_overrides=None,
    policy_overrides=None,
    card_overrides=None,
    with_gl=False,
    gl_code="6000",
):
    """Active company + cardholder + approver (+ optional GL account) + ACTIVE card.

    Returns dict: company, cardholder, approver, policy, card, reward_account,
    open_statement, gl (or None), cardholder_headers, approver_headers.
    """
    base = setup_company_with_card(
        company_overrides=company_overrides,
        policy_overrides=policy_overrides,
        card_overrides=card_overrides,
        cardholder_email="holder@acme.com",
    )
    approver = create_employee(base["company"]["id"], "approver@acme.com", "Approver", "APPROVER")
    gl = create_gl_account(base["company"]["id"], gl_code=gl_code) if with_gl else None
    base["approver"] = approver
    base["gl"] = gl
    base["approver_headers"] = make_approver_headers(approver["id"])
    return base


# ---------------------------------------------------------------------------
# Tier 2 — transaction lifecycle shortcuts
# ---------------------------------------------------------------------------
def capture_transaction(card_id, headers=None, **payload_overrides):
    """Capture a PENDING transaction on an ACTIVE card. Defaults run as ADMIN."""
    return get_success_data(api_client.capture_transaction(
        card_id, F.capture_transaction_payload(**payload_overrides), headers or ADMIN))


def capture_cleared_transaction(card_id, headers=None, **payload_overrides):
    """Capture then clear -> auth_status CLEARED."""
    tx = capture_transaction(card_id, headers=headers, **payload_overrides)
    return get_success_data(api_client.clear_transaction(tx["id"], ADMIN))


def capture_settled_transaction(card_id, settled_amount_cents=None, headers=None,
                                **payload_overrides):
    """Capture -> clear -> settle. settled defaults to the authorized amount."""
    amount = payload_overrides.get("amount_cents", 5000)
    tx = capture_transaction(card_id, headers=headers, **payload_overrides)
    get_success_data(api_client.clear_transaction(tx["id"], ADMIN))
    settled = settled_amount_cents if settled_amount_cents is not None else amount
    return get_success_data(api_client.settle_transaction(
        tx["id"], F.settle_payload(settled), ADMIN))


# ---------------------------------------------------------------------------
# Tier 3 — statement / repayment lifecycle
# ---------------------------------------------------------------------------
def setup_due_statement_with_settled_spend(
    settled_amount_cents=40000,
    billing_model="CHARGE",
    minimum_payment_pct=None,
    clock="2026-06-30T00:00:00Z",
):
    """Active CHARGE/CREDIT company; one SETTLED tx; cycle-1 statement CLOSED then
    ISSUED (DUE). Returns dict: company, card, cardholder, policy, statement,
    open_statement(closed one), settled_tx, statement_version (post-issue).
    """
    company_overrides = {"billing_model": billing_model}
    if minimum_payment_pct is not None:
        company_overrides["minimum_payment_pct"] = minimum_payment_pct
    base = setup_company_with_card(company_overrides=company_overrides)
    stmt = base["open_statement"]
    settled_tx = capture_settled_transaction(
        base["card"]["id"], settled_amount_cents=settled_amount_cents,
        amount_cents=settled_amount_cents)
    set_clock(base["company"]["id"], clock)
    closed = get_success_data(api_client.close_statement(stmt["id"], ADMIN))
    issued = get_success_data(api_client.issue_statement(stmt["id"], ADMIN))
    base["statement"] = issued
    base["settled_tx"] = settled_tx
    base["statement_version"] = issued["version"]
    return base


def setup_closed_statement_with_settled_coded_spend(
    settled_amount_cents=5000,
    clock="2026-06-30T00:00:00Z",
    gl_code="7000",
):
    """Active CHARGE company; one SETTLED + GL-coded tx; cycle-1 statement CLOSED.

    Returns dict: company, card, cardholder, policy, gl, statement(closed),
    settled_tx.
    """
    base = setup_company_with_card()
    gl = create_gl_account(base["company"]["id"], gl_code=gl_code, name="Ops")
    stmt = base["open_statement"]
    settled_tx = capture_settled_transaction(
        base["card"]["id"], settled_amount_cents=settled_amount_cents,
        amount_cents=settled_amount_cents, gl_account_id=gl["id"])
    set_clock(base["company"]["id"], clock)
    closed = get_success_data(api_client.close_statement(stmt["id"], ADMIN))
    base["gl"] = gl
    base["statement"] = closed
    base["settled_tx"] = settled_tx
    return base


def create_cleared_repayment(statement_id, amount_cents, expected_statement_version):
    """Create a repayment then clear it -> CLEARED (allocates to the statement)."""
    rp = get_success_data(api_client.create_repayment(
        F.create_repayment_payload(statement_id, amount_cents, expected_statement_version),
        ADMIN))
    return get_success_data(api_client.clear_repayment(rp["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 4 — approval-request / review lifecycle
# ---------------------------------------------------------------------------
def setup_high_value_tx_with_pending_request(
    approval_threshold_cents=5000,
    amount_cents=20000,
    with_gl=True,
    matched=False,
):
    """High-value tx (amount > approval_threshold) on a low-threshold policy, with
    an open PENDING ApprovalRequest; optionally GL-coded and receipt-MATCHED.

    Returns dict from setup_company_with_card_and_approver plus tx, approval_request.
    """
    base = setup_company_with_card_and_approver(
        policy_overrides={"approval_threshold_cents": approval_threshold_cents},
        with_gl=with_gl,
    )
    capture_overrides = {"amount_cents": amount_cents}
    if with_gl:
        capture_overrides["gl_account_id"] = base["gl"]["id"]
    tx = capture_transaction(
        base["card"]["id"], headers=base["cardholder_headers"], **capture_overrides)
    if matched:
        get_success_data(api_client.upload_receipt(
            tx["id"], F.receipt_payload(amount_cents, "Merchant"),
            base["cardholder_headers"]))
    ar = get_success_data(api_client.open_approval_request(
        tx["id"], {}, base["cardholder_headers"]))
    base["tx"] = tx
    base["approval_request"] = ar
    return base


# ---------------------------------------------------------------------------
# Tier 5 — reimbursement lifecycle
# ---------------------------------------------------------------------------
def setup_submitted_reimbursement_claim(
    amount_cents=9000,
    receipt_amount_cents=9000,
    reward_rate_default_bps=None,
    claimant_role="CARDHOLDER",
    gl_code="8000",
):
    """Active company + claimant + approver + GL; a SUBMITTED ReimbursementClaim.

    Returns dict: company, claimant, approver, gl, reward_account, claim,
    claimant_headers, approver_headers.
    """
    company_overrides = {}
    if reward_rate_default_bps is not None:
        company_overrides["reward_rate_default_bps"] = reward_rate_default_bps
    company = create_company(**company_overrides)
    claimant = create_employee(company["id"], "claimant@acme.com", "Claimant", claimant_role)
    approver = create_employee(company["id"], "rb-approver@acme.com", "Approver", "APPROVER")
    gl = create_gl_account(company["id"], gl_code=gl_code, name="Meals")
    claimant_headers = make_cardholder_headers(claimant["id"])
    claim = get_success_data(api_client.create_reimbursement_claim(
        F.create_reimbursement_claim_payload(
            company["id"], claimant["id"], gl["id"],
            amount_cents=amount_cents, receipt_amount_cents=receipt_amount_cents),
        claimant_headers))
    get_success_data(api_client.submit_reimbursement_claim(claim["id"], claimant_headers))
    return {
        "company": company,
        "claimant": claimant,
        "approver": approver,
        "gl": gl,
        "reward_account": get_reward_account(company["id"]),
        "claim": claim,
        "claimant_headers": claimant_headers,
        "approver_headers": make_approver_headers(approver["id"]),
    }


def setup_paid_reimbursement_claim(
    amount_cents=12000,
    receipt_amount_cents=12000,
    reward_rate_default_bps=100,
):
    """Carry a claim all the way through to PAID (accruing reward).

    Returns the same dict as setup_submitted_reimbursement_claim with the claim
    updated to PAID and reward_account refreshed.
    """
    s = setup_submitted_reimbursement_claim(
        amount_cents=amount_cents,
        receipt_amount_cents=receipt_amount_cents,
        reward_rate_default_bps=reward_rate_default_bps,
    )
    get_success_data(api_client.approve_reimbursement_claim(
        s["claim"]["id"], s["approver_headers"]))
    s["claim"] = get_success_data(api_client.pay_reimbursement_claim(
        s["claim"]["id"], ADMIN))
    s["reward_account"] = get_reward_account(s["company"]["id"])
    return s


# ---------------------------------------------------------------------------
# Tier 6 — spend authorization windows
# ---------------------------------------------------------------------------
def setup_active_employee_authorization(window_start, window_end, budget_cents=50000):
    """Active company + employee + one ACTIVE EMPLOYEE-scope authorization.

    Returns dict: company, employee, auth.
    """
    company = create_company()
    employee = create_employee(company["id"], "auth-emp@acme.com", "AE", "CARDHOLDER")
    auth = get_success_data(api_client.create_spend_authorization(
        F.create_spend_authorization_payload(
            company["id"], employee["id"], window_start, window_end,
            scope="EMPLOYEE", budget_cents=budget_cents),
        ADMIN))
    return {"company": company, "employee": employee, "auth": auth}


def setup_active_card_authorization(window_start, window_end, budget_cents=50000):
    """Active company + employee + card + one ACTIVE CARD-scope authorization.

    Returns dict: company, employee, card, policy, auth.
    """
    base = setup_company_with_card(cardholder_email="card-auth@acme.com")
    auth = get_success_data(api_client.create_spend_authorization(
        F.create_spend_authorization_payload(
            base["company"]["id"], base["cardholder"]["id"], window_start, window_end,
            scope="CARD", card_id=base["card"]["id"], budget_cents=budget_cents),
        ADMIN))
    return {
        "company": base["company"],
        "employee": base["cardholder"],
        "card": base["card"],
        "policy": base["policy"],
        "auth": auth,
    }


# ---------------------------------------------------------------------------
# Tier 7 — ERP batch
# ---------------------------------------------------------------------------
def setup_built_erp_batch(settled_amount_cents=5000, gl_code="7000"):
    """Closed statement with one SETTLED + GL-coded tx, then a BUILT ErpSyncBatch.

    Returns dict: company, statement, settled_tx, gl, batch.
    """
    base = setup_closed_statement_with_settled_coded_spend(
        settled_amount_cents=settled_amount_cents, gl_code=gl_code)
    batch = get_success_data(api_client.create_erp_sync_batch(
        F.create_erp_sync_batch_payload(base["company"]["id"], base["statement"]["id"]),
        ADMIN))
    base["batch"] = batch
    return base
