"""Composite setup helpers for the Fund Sales and Clearing test suite.

The PRD's lifecycles are deeply interlocking:

  Fund: DRAFT -> UNDER_REVIEW -> ON_SHELF  (with SoD between submitter/approver,
                                            PRD §3.2)
  Order: SUBMITTED -> ACCEPTED -> CONFIRMED  (or LARGE_REDEMPTION_DEFERRED ->
                                              CONFIRMED, PRD §3.3 / §3.4)
  NavSnapshot: PROVISIONAL -> PUBLISHED  (gated on T+1 + SoD vs shelf reviewer,
                                          PRD §3.4)
  DividendPlan: ANNOUNCED -> EX_DIVIDEND -> PAID  (gated on payment_date and
                                                   NAV PUBLISHED, PRD §3.6)
  ReconciliationRun: OPEN -> EXCEPTIONS_FOUND -> RESOLVED -> CLOSED
                                                         (PRD §3.7)

Most tests need the system in a non-initial state (e.g., 'fund on shelf with
known total_outstanding_shares', 'investor with confirmed holdings',
'reconciliation run with one AMOUNT_MISMATCH exception'). The helpers below
encapsulate the API-call sequences required to reach those states so that
each test can focus on its single assertion.

Identity threading (PRD §2.1):

  - PlatformAdmin / ProductOperator / ComplianceReviewer / NavOperator /
    ClearingOperator are opaque, so their TEST_USERS shared headers are
    canonical.

  - Investor is entity-backed: when a fixture creates an Investor and then
    issues an Investor-scoped call (POST /orders, POST /orders/{id}/cancel,
    set-option) on its behalf, the fixture MUST mint headers via
    make_investor_headers(investor['id']). Falling back to the shared
    TEST_USERS['investor_headers_fallback'] would only succeed if the
    implementation skipped the §2.1 ownership check.

  - SoD pairs (shelf creator vs approver, NAV publisher vs shelf reviewer,
    reconciliation creator vs closer) require DISTINCT operator IDs.
    The fixtures use TEST_USERS '_alt' headers wherever needed.

Setup calls use get_success_data (lenient validator) so broken
preconditions surface as obvious 'Setup failed' errors rather than
masquerading as confusing assertion failures.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjust_exception_payload,
    advance_clock_payload,
    create_dividend_plan_payload,
    create_fund_payload,
    create_investor_payload,
    create_redeem_order_payload,
    create_reconciliation_payload,
    create_subscribe_order_payload,
    credit_cash_payload,
    external_record,
    fee_tier,
    holding_period_tier,
    publish_nav_payload,
    set_distribution_option_payload,
    unique_idempotency_key,
)
from .test_users import (
    TEST_USERS,
    make_compliance_reviewer_headers,
    make_clearing_operator_headers,
    make_investor_headers,
    make_nav_operator_headers,
    make_product_operator_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4: ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


def date_str(dt: datetime) -> str:
    """Pure calendar date as YYYY-MM-DD (used for nav_date paths and dividend
    date inputs)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def at_utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> str:
    return iso_z(datetime(year, month, day, hour, minute, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Clock control (PRD §2.12)
# ---------------------------------------------------------------------------
def get_current_clock() -> str:
    """Return the server's current Clock.now ISO string."""
    res = api_client.get_clock(TEST_USERS["platform_admin_headers"])
    data = get_success_data(res)
    return data["now"]


def advance_clock_to(target_iso: str) -> str:
    """Advance Clock.now to target_iso, monotonicity-safe.

    PRD §2.12 enforces strict monotonic advances at the API layer. Test
    sessions share a single global clock across tests, so two tests that
    both want "set clock to T" can collide whenever an earlier test has
    already advanced past T. This helper therefore reads the current clock
    first and no-ops when target_iso is at or before it. Tests that want
    to assert monotonicity rejection should call ``api.advance_clock``
    directly rather than via this helper (see test_99_clock).
    """
    cur = get_current_clock()
    if parse_iso(cur) >= parse_iso(target_iso):
        return cur
    res = api_client.advance_clock(
        advance_clock_payload(target_iso),
        TEST_USERS["platform_admin_headers"],
    )
    data = get_success_data(res)
    return data["now"]


def advance_clock_by_days(days: int, *, current: Optional[str] = None) -> str:
    """Advance Clock.now by N calendar days from current (or read it first)."""
    base = current or get_current_clock()
    return advance_clock_to(add_days(base, days))


def ensure_clock_at_least(target_iso: str) -> str:
    """If current clock < target_iso, advance to target_iso; else return
    current. Tests sometimes need 'clock at or after T'."""
    cur = get_current_clock()
    if parse_iso(cur) < parse_iso(target_iso):
        return advance_clock_to(target_iso)
    return cur


# ===========================================================================
# Investor setup (PRD §3.1)
# ===========================================================================
def create_investor_pending_kyc(**overrides: Any) -> Dict[str, Any]:
    """Create an Investor in the default kyc_status=PENDING state."""
    payload = create_investor_payload(**overrides)
    res = api_client.create_investor(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def create_kyc_approved_investor(
    *,
    cash_cents: int = 100_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create + KYC-approve + credit cash. Returns the latest Investor body
    (which carries cash_balance_cents reflecting the credit).

    PRD §3.1: KYC approval flips kyc_status PENDING -> APPROVED; cash
    crediting via /investors/{id}/credit-cash is the only path through
    which cash_balance_cents grows outside redemption/dividend payouts."""
    investor = create_investor_pending_kyc(**overrides)
    api_client.approve_kyc(
        investor["id"], TEST_USERS["compliance_reviewer_headers"]
    )
    if cash_cents > 0:
        res = api_client.credit_cash(
            investor["id"],
            credit_cash_payload(cash_cents),
            TEST_USERS["platform_admin_headers"],
        )
        return get_success_data(res)
    # Refresh investor after KYC flip
    res = api_client.get_investor(
        investor["id"], TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Fund setup (PRD §3.2)
# ===========================================================================
def create_draft_fund(**overrides: Any) -> Dict[str, Any]:
    """Create a fund in DRAFT state (the initial state)."""
    payload = create_fund_payload(**overrides)
    res = api_client.create_fund(
        payload, TEST_USERS["product_operator_headers"]
    )
    return get_success_data(res)


def create_on_shelf_fund(
    *,
    creator_headers: Optional[Dict[str, str]] = None,
    approver_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a fund and walk it DRAFT -> UNDER_REVIEW -> ON_SHELF.

    PRD §3.2: the approver's X-User-ID must differ from the
    Fund.shelf_creator_actor_id captured at submit-for-review. The default
    SoD pair uses product_operator_headers (creator) and
    compliance_reviewer_headers (approver).
    """
    creator = creator_headers or TEST_USERS["product_operator_headers"]
    approver = approver_headers or TEST_USERS["compliance_reviewer_headers"]

    fund = create_draft_fund(**overrides)
    submitted = get_success_data(
        api_client.submit_fund_for_review(fund["id"], creator)
    )
    assert submitted["status"] == "UNDER_REVIEW", (
        f"Setup failed: expected UNDER_REVIEW, got {submitted['status']!r}"
    )
    approved = get_success_data(
        api_client.approve_fund_shelf(fund["id"], approver)
    )
    assert approved["status"] == "ON_SHELF", (
        f"Setup failed: expected ON_SHELF, got {approved['status']!r}"
    )
    return approved


def get_fund_fresh(fund_id: str) -> Dict[str, Any]:
    """Re-read fund body to capture latest computed fields (e.g.,
    total_outstanding_shares after a confirmation cascade)."""
    res = api_client.get_fund(
        fund_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# NAV publication (PRD §3.4)
# ===========================================================================
def publish_nav_for_date(
    fund_id: str,
    nav_date: str,
    *,
    portfolio_market_value_cents: int = 0,
    portfolio_accrued_income_cents: int = 0,
    nav_operator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Publish the T+1 NAV for (fund_id, nav_date).

    PRD §3.4 preconditions are the responsibility of the caller -- this
    helper assumes:
      - Clock has already advanced to >= nav_date + 1 day (T+1 rule).
      - The supplied nav_operator_headers' X-User-ID differs from the fund's
        shelf_review_actor_id.
      - The fund is ON_SHELF or SUSPENDED at NAV time (PRD §3.4 / §3.2).
    """
    headers = nav_operator_headers or TEST_USERS["nav_operator_headers"]
    res = api_client.publish_nav(
        fund_id,
        publish_nav_payload(
            nav_date=nav_date,
            portfolio_market_value_cents=portfolio_market_value_cents,
            portfolio_accrued_income_cents=portfolio_accrued_income_cents,
        ),
        headers,
    )
    return get_success_data(res)


# ===========================================================================
# Order helpers (PRD §3.3 / §3.4)
# ===========================================================================
def submit_subscribe_order(
    investor: Dict[str, Any],
    fund: Dict[str, Any],
    gross_amount_cents: int,
    *,
    idempotency_key: Optional[str] = None,
    extra_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit a SUBSCRIBE order on behalf of `investor`.

    Uses make_investor_headers(investor['id']) as required by PRD §2.1
    -- the call is ownership-gated."""
    payload = create_subscribe_order_payload(
        fund_id=fund["id"],
        gross_amount_cents=gross_amount_cents,
        idempotency_key=idempotency_key,
        **(extra_overrides or {}),
    )
    res = api_client.create_order(
        payload, make_investor_headers(investor["id"])
    )
    return get_success_data(res)


def submit_redeem_order(
    investor: Dict[str, Any],
    fund: Dict[str, Any],
    requested_shares: int,
    *,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_redeem_order_payload(
        fund_id=fund["id"],
        requested_shares=requested_shares,
        idempotency_key=idempotency_key,
    )
    res = api_client.create_order(
        payload, make_investor_headers(investor["id"])
    )
    return get_success_data(res)


def get_order_fresh(order_id: str) -> Dict[str, Any]:
    res = api_client.get_order(
        order_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def cancel_order_by_owner(
    investor: Dict[str, Any], order_id: str
) -> Dict[str, Any]:
    res = api_client.cancel_order(
        order_id, make_investor_headers(investor["id"])
    )
    return get_success_data(res)


# ===========================================================================
# Combined: subscribe -> NAV publish -> CONFIRMED
# ===========================================================================
def subscribe_confirm(
    investor: Dict[str, Any],
    fund: Dict[str, Any],
    gross_amount_cents: int,
    *,
    submit_at: Optional[str] = None,
    nav_date_str: Optional[str] = None,
    portfolio_market_value_cents: Optional[int] = None,
    portfolio_accrued_income_cents: int = 0,
    nav_operator_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """End-to-end: advance clock to ``submit_at`` (if supplied), submit a
    SUBSCRIBE order, advance to T+1, publish NAV. Returns (order, nav).

    The portfolio_market_value defaults so that with shares_outstanding == 0
    the snapshot's nav_per_share_micros is 1_000_000 (PRD §3.4 initial-NAV
    constant) for predictable per-share arithmetic. When the fund already
    has outstanding shares, the caller must supply portfolio_market_value
    sized to keep nav at the expected level.

    Note: BOND fund (default) has confirmation_cycle_days = 1, EQUITY = 2,
    QDII = 3 (PRD §3.2). After NAV publish, the deferred confirmation
    pass runs over orders whose confirm_date has been reached -- that
    requires Clock.now >= confirm_date.
    """
    if submit_at is not None:
        # 'ensure' rather than 'advance' so the helper is safe to call in
        # any chronological order across the test session: if the clock
        # is already past `submit_at`, we simply submit at the current
        # clock value (still pre-cutoff for that calendar date if the
        # caller chose a 10:00 timestamp and tests increment dates).
        ensure_clock_at_least(submit_at)

    # Submit the order
    order = submit_subscribe_order(investor, fund, gross_amount_cents)

    # Determine the order's trade_date (server-assigned per acceptance window)
    # by re-reading the order. PRD §3.3: trade_date is set on acceptance.
    trade_date = order.get("trade_date")
    confirm_date = order.get("confirm_date")
    assert trade_date and confirm_date, (
        f"Setup failed: order missing trade_date/confirm_date: {order!r}"
    )

    # nav_date defaults to the order's trade_date (date portion).
    if nav_date_str is None:
        nav_date_str = trade_date.split("T")[0]

    # PRD §3.4: NAV publish requires Clock.now >= nav_date + 1 day. Also
    # the confirmation pass requires Clock.now >= confirm_date.
    target = max(
        parse_iso(nav_date_str + "T00:00:00.000Z") + timedelta(days=1),
        parse_iso(confirm_date) if "T" in confirm_date else parse_iso(confirm_date + "T00:00:00.000Z"),
    )
    # nudge a little past midnight to avoid boundary equality questions
    target = target + timedelta(seconds=1)
    ensure_clock_at_least(iso_z(target))

    # Sensible default for portfolio_market_value if not supplied:
    # if no shares yet outstanding, value can be zero (initial NAV path),
    # so the same call works for the very first confirmation.
    if portfolio_market_value_cents is None:
        # The NAV per share for fund WITH outstanding shares would need
        # custom valuation; callers needing that should pass it explicitly.
        portfolio_market_value_cents = 0

    nav = publish_nav_for_date(
        fund["id"],
        nav_date_str,
        portfolio_market_value_cents=portfolio_market_value_cents,
        portfolio_accrued_income_cents=portfolio_accrued_income_cents,
        nav_operator_headers=nav_operator_headers,
    )

    # The order should now be CONFIRMED (or REJECTED if validation failed
    # downstream). Re-read.
    order = get_order_fresh(order["id"])
    return order, nav


# ===========================================================================
# Convenience: end-to-end "investor with confirmed holdings"
# ===========================================================================
def setup_basic_investor_and_fund(
    *,
    cash_cents: int = 100_000_000,
    fund_overrides: Optional[Dict[str, Any]] = None,
    investor_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (investor, fund) with KYC approved, cash credited, and fund
    on shelf. The default fund is BOND / R3 / [CN] / 0-bps fees so the
    investor (default C5/CN/DOMESTIC) passes every validation."""
    investor = create_kyc_approved_investor(
        cash_cents=cash_cents, **(investor_overrides or {})
    )
    fund = create_on_shelf_fund(**(fund_overrides or {}))
    return investor, fund


def setup_investor_with_confirmed_subscribe(
    *,
    gross_amount_cents: int = 100_000,
    submit_at: str = "2026-05-01T10:00:00.000Z",
    cash_cents: int = 100_000_000,
    fund_overrides: Optional[Dict[str, Any]] = None,
    investor_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (investor, fund, order, nav) where the order is CONFIRMED.

    With the default 0-bps fund and gross_amount = 100_000 cents at NAV=1.0
    (initial-NAV path, shares_outstanding starts at 0), the resulting
    confirmed_shares is 10_000_000 (== 1000 whole shares).
    """
    investor, fund = setup_basic_investor_and_fund(
        cash_cents=cash_cents,
        fund_overrides=fund_overrides,
        investor_overrides=investor_overrides,
    )
    # 'ensure' rather than 'advance' so the helper is monotonicity-safe
    # across a session that has already advanced the clock past
    # `submit_at`. PRD §2.12 enforces strict monotonic clock advances.
    ensure_clock_at_least(submit_at)
    order, nav = subscribe_confirm(
        investor, fund, gross_amount_cents,
    )
    return investor, fund, order, nav


# ===========================================================================
# Setup a fund with a known total_outstanding_shares
# ===========================================================================
def setup_fund_with_outstanding_shares(
    *,
    target_outstanding_shares: int,
    seed_investor_cash_cents: int = 1_000_000_000,
    submit_at: str = "2026-05-01T10:00:00.000Z",
    fund_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Establish a Fund whose total_outstanding_shares == target_outstanding_shares.

    Approach: create one seed Investor, kyc-approve, credit cash, submit a
    SUBSCRIBE order whose gross_amount produces exactly target_outstanding_shares
    at the initial NAV (which is 1.0 CNY/share = 1_000_000 micros).

    Specifically: at NAV=1.0 with 0-bps subscription fee, confirmed_shares =
    gross_amount_cents * 1e8 / 1_000_000 = gross_amount_cents * 100. To
    obtain N shares (in 1e-4 units), we need gross_amount_cents = N / 100.

    Since N must be a multiple of 100 for clean integer cents, callers
    should pick target_outstanding_shares that is a multiple of 100.

    Returns (seed_investor, fund) where seed_investor still owns
    target_outstanding_shares.
    """
    assert target_outstanding_shares % 100 == 0, (
        "target_outstanding_shares must be a multiple of 100 to match "
        "integer-cent gross_amount at NAV=1.0"
    )
    overrides = dict(fund_overrides or {})
    # Force 0-bps subscription fees for clean math
    overrides.setdefault("subscription_fee_tiers", [fee_tier(0, None, 0)])
    overrides.setdefault("redemption_fee_tiers", [holding_period_tier(0, None, 0)])
    overrides.setdefault("management_fee_bps_annual", 0)
    overrides.setdefault("custodian_fee_bps_annual", 0)
    overrides.setdefault("sales_service_fee_bps_annual", 0)

    investor, fund = setup_basic_investor_and_fund(
        cash_cents=seed_investor_cash_cents,
        fund_overrides=overrides,
    )
    gross = target_outstanding_shares // 100
    ensure_clock_at_least(submit_at)
    order, _ = subscribe_confirm(investor, fund, gross)
    assert order["status"] == "CONFIRMED", (
        f"Setup failed: seed subscribe did not confirm: {order!r}"
    )
    fund_fresh = get_fund_fresh(fund["id"])
    assert fund_fresh["total_outstanding_shares"] == target_outstanding_shares, (
        f"Setup failed: expected total_outstanding_shares == "
        f"{target_outstanding_shares}, got {fund_fresh['total_outstanding_shares']}"
    )
    return investor, fund_fresh


# ===========================================================================
# Reconciliation setup (PRD §3.7)
# ===========================================================================
def open_reconciliation_run(
    *,
    as_of_date: str,
    scope: str = "TA_VS_CUSTODIAN",
    external_records: Optional[List[Dict[str, Any]]] = None,
    creator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    res = api_client.create_reconciliation(
        create_reconciliation_payload(
            as_of_date=as_of_date,
            scope=scope,
            external_records=external_records or [],
        ),
        creator_headers or TEST_USERS["clearing_operator_headers"],
    )
    return get_success_data(res)


def setup_reconciliation_with_amount_mismatch(
    *,
    as_of_date: str,
    internal_order_id: str,
    internal_amount_cents: int,
    external_amount_cents: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Open a run + run-match where the single external record disagrees
    with the SETTLED internal ledger by (external - internal) cents.

    Returns (run_after_match, the_single_AMOUNT_MISMATCH_exception).
    """
    run = open_reconciliation_run(
        as_of_date=as_of_date,
        external_records=[
            external_record(
                ref_id=internal_order_id,
                side="DEBIT",
                amount_cents=external_amount_cents,
            )
        ],
    )
    matched = get_success_data(
        api_client.run_match(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
    )
    # Re-read run to capture exceptions list path; tests will then pull
    # exceptions from the GET endpoint.
    detail = get_success_data(
        api_client.get_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
    )
    # PRD §3.7: detail returns run + exceptions + instructions; exceptions
    # may be exposed under a key the test must inspect. We return both so
    # tests can assert on whatever shape the implementation chose.
    return matched, detail


# ===========================================================================
# Generic helpers used by tests
# ===========================================================================
def list_audit_logs_for(
    subject_entity: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch audit-log rows filtered by PRD §3.8 query parameters."""
    params: Dict[str, Any] = {}
    if action:
        params["action"] = action
    if subject_entity:
        params["subject_entity"] = subject_entity
    if subject_id:
        params["subject_id"] = subject_id
    params["limit"] = 100
    res = api_client.list_audit_logs(
        TEST_USERS["compliance_reviewer_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    # Some implementations may return {"items": [...]} -- be tolerant.
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return []


__all__ = [
    "iso_z",
    "parse_iso",
    "add_days",
    "date_str",
    "at_utc",
    "get_current_clock",
    "advance_clock_to",
    "advance_clock_by_days",
    "ensure_clock_at_least",
    "create_investor_pending_kyc",
    "create_kyc_approved_investor",
    "create_draft_fund",
    "create_on_shelf_fund",
    "get_fund_fresh",
    "publish_nav_for_date",
    "submit_subscribe_order",
    "submit_redeem_order",
    "get_order_fresh",
    "cancel_order_by_owner",
    "subscribe_confirm",
    "setup_basic_investor_and_fund",
    "setup_investor_with_confirmed_subscribe",
    "setup_fund_with_outstanding_shares",
    "open_reconciliation_run",
    "setup_reconciliation_with_amount_mismatch",
    "list_audit_logs_for",
]
