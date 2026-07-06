"""Composite setup helpers.

Each helper builds the multi-step preconditions a test needs from scratch using
only PRD-declared endpoints, since the server's database is empty at the start of
every test. Setup calls use get_success_data() so a setup failure surfaces clearly.

Identity threading: ClientContact is entity-backed by the Client, so every
ownership-gated ClientContact call (dispute, catch-up reject/approve, pay) uses
make_client_contact_headers(client_id) with the real client id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_client_contact_headers
from . import factories as f

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: Client lifecycle progression
# ---------------------------------------------------------------------------
def create_client(retainer_tier="GROWTH", covenant_floor_cents=None,
                  legal_name="Test Co LLC", state_code="CA"):
    """Create a fresh client in LEAD / PROSPECT. Returns the client dict."""
    payload = f.create_client_payload(
        retainer_tier=retainer_tier, legal_name=legal_name, state_code=state_code)
    if covenant_floor_cents is not None:
        payload["covenant_floor_cents"] = covenant_floor_cents
    return get_success_data(api_client.create_client(payload, CFO))


def create_active_ledger_account(client_id, account_code="1000",
                                 account_type="ASSET", name="Cash",
                                 parent_account_id=None):
    """Create one ACTIVE ledger account for the client. Returns the account dict."""
    payload = f.create_ledger_account_payload(
        account_code=account_code, account_type=account_type, name=name)
    if parent_account_id is not None:
        payload["parent_account_id"] = parent_account_id
    return get_success_data(api_client.create_ledger_account(client_id, payload, BK))


def create_onboarded_client(retainer_tier="GROWTH", covenant_floor_cents=None):
    """Walk the onboarding axis LEAD -> ONBOARDED (creates a ledger account on
    the way so complete-onboarding passes). engagement_status stays PROSPECT.
    Returns the client dict re-fetched after onboarding."""
    client = create_client(retainer_tier, covenant_floor_cents)
    cid = client["id"]
    get_success_data(api_client.schedule_kickoff(cid, CFO))
    get_success_data(api_client.start_ledger_setup(cid, BK))
    create_active_ledger_account(cid)
    get_success_data(api_client.complete_onboarding(cid, CFO))
    return get_success_data(api_client.get_client(cid, CFO))


def create_active_client(retainer_tier="GROWTH", covenant_floor_cents=None):
    """Fully onboarded AND engagement ACTIVE client. Returns the client dict."""
    client = create_onboarded_client(retainer_tier, covenant_floor_cents)
    cid = client["id"]
    get_success_data(api_client.activate_engagement(cid, CFO))
    return get_success_data(api_client.get_client(cid, CFO))


# ---------------------------------------------------------------------------
# Tier 2 / 4: Monthly close + retainer setup
# ---------------------------------------------------------------------------
def create_client_with_close(retainer_tier="GROWTH", txn_count=100,
                             period_year=2026, period_month=1,
                             covenant_floor_cents=None):
    """Create a client (LEAD) plus one OPEN MonthlyClose with the given txn_count.
    Returns (client, close)."""
    client = create_client(retainer_tier, covenant_floor_cents)
    cid = client["id"]
    close = get_success_data(api_client.create_monthly_close(
        cid, f.create_monthly_close_payload(
            period_year=period_year, period_month=period_month, txn_count=txn_count),
        BK))
    return client, close


def current_client_version(client_id):
    """Read the client's current version (for OCC expected_client_version)."""
    return get_success_data(api_client.get_client(client_id, CFO))["version"]


def setup_scoped_catchup(client_id, months_behind=3, quoted_fee_cents=400000):
    """Create + scope a CatchupProject (catchup_active becomes true). Returns the
    project dict after scope."""
    cp = get_success_data(api_client.create_catchup_project(
        client_id, f.create_catchup_project_payload(
            months_behind=months_behind, quoted_fee_cents=quoted_fee_cents), CFO))
    get_success_data(api_client.scope_catchup_project(cp["id"], CFO))
    return get_success_data(api_client.get_catchup_project(cp["id"], CFO))


def issue_retainer_invoice(client_id, monthly_close_id):
    """Issue a retainer invoice with the current (fresh) client version. Returns
    the invoice dict."""
    cver = current_client_version(client_id)
    return get_success_data(api_client.issue_retainer_invoice(
        client_id,
        {"monthly_close_id": monthly_close_id, "expected_client_version": cver},
        CFO))


# ---------------------------------------------------------------------------
# Tier 3: MonthlyClose lifecycle shortcuts
# ---------------------------------------------------------------------------
def add_close_task(close_id, name="Reconcile", weight=1):
    """Add a PENDING CloseTask. Returns the task dict."""
    return get_success_data(api_client.create_close_task(
        close_id, f.create_close_task_payload(name=name, weight=weight), BK))


def transition_close_task(task_id, to_status):
    """Transition a CloseTask to to_status. Returns the task dict."""
    return get_success_data(api_client.transition_close_task(
        task_id, {"to_status": to_status}, BK))


def create_ready_for_review_close(client_id=None, retainer_tier="GROWTH",
                                  period_year=2026, period_month=2, txn_count=20):
    """Create a close with a single task driven to DONE so the close reaches
    READY_FOR_REVIEW with review_status UNDER_REVIEW. Returns (client_id, close_id,
    task_id). If client_id is None a fresh client is created."""
    if client_id is None:
        client = create_client(retainer_tier)
        client_id = client["id"]
    close = get_success_data(api_client.create_monthly_close(
        client_id, f.create_monthly_close_payload(
            period_year=period_year, period_month=period_month, txn_count=txn_count),
        BK))
    task = add_close_task(close["id"], name="Reconcile", weight=1)
    transition_close_task(task["id"], "DONE")
    return client_id, close["id"], task["id"]


def create_approved_review_close(client_id=None, retainer_tier="GROWTH",
                                 period_year=2026, period_month=2, txn_count=20):
    """READY_FOR_REVIEW close advanced to review_status APPROVED. Returns
    (client_id, close_id, task_id)."""
    client_id, close_id, task_id = create_ready_for_review_close(
        client_id, retainer_tier, period_year, period_month, txn_count)
    get_success_data(api_client.approve_review(close_id, CFO))
    return client_id, close_id, task_id


def create_finalized_close(client_id=None, retainer_tier="GROWTH",
                           period_year=2026, period_month=2, txn_count=20):
    """Walk a close all the way to FINALIZED. Returns (client_id, close_id)."""
    client_id, close_id, _ = create_approved_review_close(
        client_id, retainer_tier, period_year, period_month, txn_count)
    get_success_data(api_client.finalize_close(close_id, CFO))
    return client_id, close_id


# ---------------------------------------------------------------------------
# Tier 3/4: Payroll lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_payroll_run(client_id, monthly_close_id, total_employer_cost_cents=1000000,
                       pay_period_start="2026-03-01T00:00:00Z",
                       pay_period_end="2026-04-01T00:00:00Z",
                       pay_date="2026-03-31T00:00:00Z"):
    """Create a DRAFT PayrollRun. Returns the run dict."""
    return get_success_data(api_client.create_payroll_run(
        client_id,
        f.create_payroll_run_payload(
            monthly_close_id,
            total_employer_cost_cents=total_employer_cost_cents,
            pay_period_start=pay_period_start, pay_period_end=pay_period_end,
            pay_date=pay_date),
        BK))


def add_allocation(run_id, department_name, dept_gross_cents):
    """Add one PayrollAllocation line. Returns the allocation dict."""
    return get_success_data(api_client.create_payroll_allocation(
        run_id,
        f.create_payroll_allocation_payload(
            department_name=department_name, dept_gross_cents=dept_gross_cents),
        BK))


def setup_allocated_payroll_run(total_employer_cost_cents=1000000,
                                dept_gross_list=(("A", 500000), ("B", 500000), ("C", 500000)),
                                period_month=3):
    """Create client + close + DRAFT run + the given allocation lines (in order),
    then allocate. Returns (client_id, close_id, run_id, [allocation_ids])."""
    client, close = create_client_with_close(
        txn_count=100, period_month=period_month)
    cid = client["id"]
    run = create_payroll_run(
        cid, close["id"], total_employer_cost_cents=total_employer_cost_cents,
        pay_period_start=f"2026-{period_month:02d}-01T00:00:00Z",
        pay_period_end=f"2026-{period_month + 1:02d}-01T00:00:00Z",
        pay_date=f"2026-{period_month:02d}-28T00:00:00Z")
    alloc_ids = []
    for name, gross in dept_gross_list:
        alloc_ids.append(add_allocation(run["id"], name, gross)["id"])
    get_success_data(api_client.allocate_payroll_run(run["id"], BK))
    return cid, close["id"], run["id"], alloc_ids


def setup_posted_payroll_run(total_employer_cost_cents=1000000,
                             dept_gross_list=(("A", 500000), ("B", 500000), ("C", 500000)),
                             period_month=3):
    """As setup_allocated_payroll_run, then post (close is not finalized).
    Returns (client_id, close_id, run_id, [allocation_ids])."""
    cid, close_id, run_id, alloc_ids = setup_allocated_payroll_run(
        total_employer_cost_cents, dept_gross_list, period_month)
    get_success_data(api_client.post_payroll_run(run_id, CFO))
    return cid, close_id, run_id, alloc_ids


def allocation_sum(run_id):
    """Sum of allocated_cents over all allocation lines on the run."""
    data, _ = _paginate_all(api_client.list_payroll_allocations, run_id)
    return sum(a["allocated_cents"] for a in data)


def _paginate_all(list_fn, *args):
    """Fetch all pages of a list endpoint. Returns (rows, last_meta)."""
    import json
    rows = []
    offset = 0
    meta = {}
    while True:
        resp = list_fn(*args, headers=CFO, params={"limit": 100, "offset": offset})
        body = resp.json()
        meta = body.get("meta", {})
        page = body.get("data", [])
        rows.extend(page)
        if not meta.get("has_more"):
            break
        offset += len(page)
        if len(page) == 0:
            break
    return rows, meta


# ---------------------------------------------------------------------------
# Tier 3/4: Forecast lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_forecast(client_id, opening_balance_cents=1000000):
    """Create a DRAFT CashFlowForecast. Returns the forecast dict."""
    return get_success_data(api_client.create_forecast(
        client_id, f.create_forecast_payload(opening_balance_cents=opening_balance_cents),
        CFO))


def add_forecast_line(forecast_id, effective_date, direction, amount_cents):
    """Add a ForecastLine; recomputes the forecast balances. Returns the line dict."""
    return get_success_data(api_client.create_forecast_line(
        forecast_id,
        f.create_forecast_line_payload(
            effective_date=effective_date, direction=direction, amount_cents=amount_cents),
        CFO))


def setup_forecast_with_min_balance(covenant_floor_cents, opening_balance_cents,
                                    outflow_cents):
    """Client with the given covenant floor and a DRAFT forecast whose single
    OUTFLOW makes min_projected_balance_cents == opening - outflow.
    Returns (client_id, forecast_id)."""
    client = create_client(covenant_floor_cents=covenant_floor_cents)
    cid = client["id"]
    fc = create_forecast(cid, opening_balance_cents=opening_balance_cents)
    add_forecast_line(fc["id"], "2026-04-05T00:00:00Z", "OUTFLOW", outflow_cents)
    return cid, fc["id"]


def approve_forecast(forecast_id, client_id):
    """Approve a forecast with the current client version. Returns the forecast dict."""
    cver = current_client_version(client_id)
    return get_success_data(api_client.approve_forecast(
        forecast_id, {"expected_client_version": cver}, CFO))


# ---------------------------------------------------------------------------
# Tier 5: Tax handoff lifecycle
# ---------------------------------------------------------------------------
def create_handoff_in_books_review(tax_year=2025):
    """Create a client whose (tax_year, 12) close is FINALIZED, then a TaxHandoff
    driven through start-reviews to BOOKS_REVIEW. Returns (client_id, handoff_id)."""
    client = create_client()
    cid = client["id"]
    _, _ = create_finalized_close(
        client_id=cid, period_year=tax_year, period_month=12, txn_count=40)
    th = get_success_data(api_client.create_tax_handoff(
        cid, f.create_tax_handoff_payload(tax_year=tax_year), CFO))
    get_success_data(api_client.start_tax_reviews(th["id"], CFO))
    return cid, th["id"]


# ---------------------------------------------------------------------------
# Tier 2: AR setup
# ---------------------------------------------------------------------------
def create_ar_invoice(client_id, amount_cents=100000, counterparty_name="Customer",
                      issue_date="2026-03-01T00:00:00Z", due_date="2026-03-31T00:00:00Z"):
    """Create an OPEN AR invoice. Returns the invoice dict."""
    return get_success_data(api_client.create_ar_invoice(
        client_id,
        f.create_ar_invoice_payload(
            amount_cents=amount_cents, counterparty_name=counterparty_name,
            issue_date=issue_date, due_date=due_date),
        BK))


def dispute_ar_invoice(client_id, invoice_id):
    """Dispute an AR invoice as the owning ClientContact (ownership-gated)."""
    return get_success_data(api_client.dispute_ar_invoice(
        invoice_id, make_client_contact_headers(client_id)))
