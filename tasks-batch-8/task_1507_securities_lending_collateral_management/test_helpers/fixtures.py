"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at exactly 2026-08-01T00:00:00Z). Setup
calls use get_success_data so failures surface as clear "Setup failed"
errors. Identity threading is mandatory: OwnerRep/BorrowerRep calls inside
fixtures use make_owner_rep_headers(entity_id) / make_borrower_rep_headers
(entity_id), never the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_beneficial_owner_payload,
    create_borrower_payload,
    create_borrow_request_payload,
    create_cash_pledge_payload,
    create_lendable_position_payload,
    create_loan_payload,
    create_recall_payload,
    create_regulatory_report_payload,
    create_reinvestment_payload,
    create_security_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_borrower_rep_headers,
    make_owner_rep_headers,
)

TRADER = TEST_USERS["desk_trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]
OPS = TEST_USERS["ops_settler_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


def _setup_error(step, resp):
    return AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Tier 1 — reference data and counterparties
# ---------------------------------------------------------------------------

def create_security(symbol="SEC1", asset_class="EQUITY", price_cents=1000):
    """Register a security (born LENDABLE). Returns the security dict."""
    resp = api_client.create_security(
        create_security_payload(symbol=symbol, asset_class=asset_class,
                                price_cents=price_cents), ADMIN)
    return _ok("create_security", resp)


def create_owner(display_name="Owner One", revenue_share_bps=6000,
                 indemnification_opt_in=False):
    """Onboard a beneficial owner (born ACTIVE). Returns the owner dict."""
    resp = api_client.create_beneficial_owner(
        create_beneficial_owner_payload(
            display_name=display_name,
            revenue_share_bps=revenue_share_bps,
            indemnification_opt_in=indemnification_opt_in), ADMIN)
    return _ok("create_beneficial_owner", resp)


def create_borrower(display_name="Borrower One",
                    credit_limit_cents=100_000_000):
    """Onboard a borrower (born ACTIVE). Returns the borrower dict."""
    resp = api_client.create_borrower(
        create_borrower_payload(display_name=display_name,
                                credit_limit_cents=credit_limit_cents), ADMIN)
    return _ok("create_borrower", resp)


def create_position(owner, security, quantity_total=100_000, min_fee_bps=25):
    """Make inventory lendable as the owning OwnerRep. Returns the position."""
    resp = api_client.create_lendable_position(
        create_lendable_position_payload(
            owner["id"], security["id"], quantity_total=quantity_total,
            min_fee_bps=min_fee_bps),
        make_owner_rep_headers(owner["id"]))
    return _ok("create_lendable_position", resp)


def create_borrow_request(borrower, security, quantity=1000, max_rate_bps=40,
                          collateral_type="SECURITIES",
                          needed_by_date="2026-08-20", term_days=None):
    """Submit borrow demand as the borrowing BorrowerRep (born SUBMITTED)."""
    payload = create_borrow_request_payload(
        borrower["id"], security["id"], quantity=quantity,
        max_rate_bps=max_rate_bps, collateral_type=collateral_type,
        needed_by_date=needed_by_date)
    if term_days is not None:
        payload["term_days"] = term_days
    resp = api_client.create_borrow_request(
        payload, make_borrower_rep_headers(borrower["id"]))
    return _ok("create_borrow_request", resp)


# ---------------------------------------------------------------------------
# Tier 2 — loan proposals and booking
# ---------------------------------------------------------------------------

def create_loan_proposal(owner, borrower, security, position, quantity=1000,
                         collateral_type="SECURITIES", rate_bps=25,
                         term_days=None):
    """Desk opens a direct loan proposal (born PROPOSED). Returns the loan."""
    payload = create_loan_payload(
        owner["id"], borrower["id"], security["id"], position["id"],
        quantity=quantity, collateral_type=collateral_type, rate_bps=rate_bps)
    if term_days is not None:
        payload["term_days"] = term_days
    resp = api_client.create_loan(payload, TRADER)
    return _ok("create_loan", resp)


def accept_loan(loan, borrower):
    """BorrowerRep accepts a PROPOSED loan -> BOOKED. Returns the loan."""
    resp = api_client.accept_loan(
        loan["id"], make_borrower_rep_headers(borrower["id"]))
    return _ok("accept_loan", resp)


def create_and_book_loan(owner, borrower, security, position, quantity=1000,
                         collateral_type="SECURITIES", rate_bps=25,
                         term_days=None):
    """Direct proposal + borrower accept. Returns the BOOKED loan."""
    loan = create_loan_proposal(
        owner, borrower, security, position, quantity=quantity,
        collateral_type=collateral_type, rate_bps=rate_bps,
        term_days=term_days)
    return accept_loan(loan, borrower)


def setup_desk(security_symbol="SEC1", asset_class="EQUITY", price_cents=1000,
               revenue_share_bps=6000, indemnification_opt_in=False,
               credit_limit_cents=100_000_000, quantity_total=100_000,
               min_fee_bps=25):
    """Security + owner + borrower + position. Returns the four dicts."""
    security = create_security(symbol=security_symbol, asset_class=asset_class,
                               price_cents=price_cents)
    owner = create_owner(revenue_share_bps=revenue_share_bps,
                         indemnification_opt_in=indemnification_opt_in)
    borrower = create_borrower(credit_limit_cents=credit_limit_cents)
    position = create_position(owner, security, quantity_total=quantity_total,
                               min_fee_bps=min_fee_bps)
    return security, owner, borrower, position


def setup_booked_loan(security_symbol="SEC1", price_cents=1000,
                      revenue_share_bps=6000, indemnification_opt_in=False,
                      credit_limit_cents=100_000_000,
                      quantity_total=100_000, min_fee_bps=25,
                      loan_quantity=1000, collateral_type="SECURITIES",
                      rate_bps=25, term_days=None):
    """Full desk plus one BOOKED loan. Returns a context dict."""
    security, owner, borrower, position = setup_desk(
        security_symbol=security_symbol, price_cents=price_cents,
        revenue_share_bps=revenue_share_bps,
        indemnification_opt_in=indemnification_opt_in,
        credit_limit_cents=credit_limit_cents, quantity_total=quantity_total,
        min_fee_bps=min_fee_bps)
    loan = create_and_book_loan(
        owner, borrower, security, position, quantity=loan_quantity,
        collateral_type=collateral_type, rate_bps=rate_bps,
        term_days=term_days)
    return {"security": security, "owner": owner, "borrower": borrower,
            "position": position, "loan": loan}


# ---------------------------------------------------------------------------
# Tier 3 — collateral, reinvestment, recall lifecycle shortcuts
# ---------------------------------------------------------------------------

def post_cash_pledge(loan, borrower, amount_cents):
    """BorrowerRep posts a CASH pledge (born ACTIVE). Returns the pledge."""
    resp = api_client.create_pledge(
        loan["id"], create_cash_pledge_payload(amount_cents),
        make_borrower_rep_headers(borrower["id"]))
    return _ok("create_pledge(cash)", resp)


def post_security_pledge(loan, borrower, pledge_security_id, quantity):
    """BorrowerRep posts a SECURITY pledge (born ACTIVE). Returns the pledge."""
    from .factories import create_security_pledge_payload
    resp = api_client.create_pledge(
        loan["id"],
        create_security_pledge_payload(pledge_security_id, quantity),
        make_borrower_rep_headers(borrower["id"]))
    return _ok("create_pledge(security)", resp)


def create_tranche(loan, principal_cents=100_000, instrument_type="MMF",
                   stated_yield_bps=360):
    """DeskTrader invests uninvested cash (born INVESTED). Returns tranche."""
    resp = api_client.create_reinvestment(
        loan["id"],
        create_reinvestment_payload(
            instrument_type=instrument_type, principal_cents=principal_cents,
            stated_yield_bps=stated_yield_bps), TRADER)
    return _ok("create_reinvestment", resp)


def issue_recall(loan, owner, quantity, reason="SALE",
                 deadline_date="2026-08-10"):
    """OwnerRep issues a full recall (born ISSUED; loan -> RECALLED)."""
    resp = api_client.create_recall(
        loan["id"],
        create_recall_payload(quantity, reason=reason,
                              deadline_date=deadline_date),
        make_owner_rep_headers(owner["id"]))
    return _ok("create_recall", resp)


def return_shares(loan, borrower, quantity):
    """BorrowerRep returns shares against a BOOKED/RECALLED loan."""
    resp = api_client.return_loan(
        loan["id"], {"quantity": quantity},
        make_borrower_rep_headers(borrower["id"]))
    return _ok("return_loan", resp)


# ---------------------------------------------------------------------------
# Tier 4 — clock and ops-run helpers (accumulation / epoch targeting)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """DeskAdmin moves the logical clock."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return _ok("set_clock", resp)


def run_mtm():
    """OpsSettler runs the daily mark-to-market batch for the clock date."""
    resp = api_client.run_mark_to_market(OPS)
    return _ok("run_mark_to_market", resp)


def run_mtm_on(date_iso):
    """Set the clock to YYYY-MM-DDT00:00:00Z then run the daily batch."""
    set_clock(f"{date_iso}T00:00:00Z")
    return run_mtm()


def run_month_end_close(period="2026-08"):
    """OpsSettler closes a period. Returns the PeriodClose record."""
    resp = api_client.run_month_end_close({"period": period}, OPS)
    return _ok("run_month_end_close", resp)


def run_mtm_for_dates(dates):
    """Run the daily batch once per YYYY-MM-DD date, advancing the clock."""
    summaries = []
    for d in dates:
        summaries.append(run_mtm_on(d))
    return summaries


def list_ledger_entries(headers, **params):
    """List ledger entries with equality filters; returns the data array."""
    resp = api_client.list_ledger_entries(headers, params=params or None)
    return _ok("list_ledger_entries", resp)


def get_loan(loan_id, headers=None):
    resp = api_client.get_loan(loan_id, headers or TRADER)
    return _ok("get_loan", resp)


def get_position(position_id, headers=None):
    resp = api_client.get_lendable_position(position_id, headers or TRADER)
    return _ok("get_lendable_position", resp)


def get_borrower(borrower_id, headers=None):
    resp = api_client.get_borrower(borrower_id, headers or TRADER)
    return _ok("get_borrower", resp)


def get_recall(recall_id, headers=None):
    resp = api_client.get_recall(recall_id, headers or TRADER)
    return _ok("get_recall", resp)


def get_pledge(pledge_id, headers=None):
    resp = api_client.get_pledge(pledge_id, headers or TRADER)
    return _ok("get_pledge", resp)


def get_tranche(tranche_id, headers=None):
    resp = api_client.get_reinvestment(tranche_id, headers or TRADER)
    return _ok("get_reinvestment", resp)


def get_borrow_request(request_id, headers=None):
    resp = api_client.get_borrow_request(request_id, headers or TRADER)
    return _ok("get_borrow_request", resp)


def get_margin_call(call_id, headers=None):
    resp = api_client.get_margin_call(call_id, headers or OPS)
    return _ok("get_margin_call", resp)


# ---------------------------------------------------------------------------
# Tier 5 — terminal states and reporting
# ---------------------------------------------------------------------------

def setup_closed_period(period="2026-08"):
    """Close a period with zero loan activity. Returns the PeriodClose."""
    return run_month_end_close(period)


def setup_finalized_report(period="2026-08",
                           report_type="MONTHLY_LOAN_ACTIVITY",
                           ops_user_id="ops-1"):
    """Period closed + DRAFT report + finalize. Returns the report dict."""
    from .factories import create_regulatory_report_payload
    from .test_users import make_ops_settler_headers
    run_month_end_close(period)
    resp = api_client.create_regulatory_report(
        create_regulatory_report_payload(period=period,
                                         report_type=report_type), OPS)
    report = _ok("create_regulatory_report", resp)
    resp = api_client.finalize_regulatory_report(
        report["id"], make_ops_settler_headers(ops_user_id))
    return _ok("finalize_regulatory_report", resp)


def setup_cash_loan_with_pledge(pledge_amount_cents=1_020_000,
                                loan_quantity=1000, price_cents=1000,
                                rate_bps=0, **desk_overrides):
    """BOOKED CASH-collateral loan plus one ACTIVE cash pledge.

    Returns the context dict extended with the pledge."""
    ctx = setup_booked_loan(loan_quantity=loan_quantity,
                            price_cents=price_cents,
                            collateral_type="CASH", rate_bps=rate_bps,
                            **desk_overrides)
    pledge = post_cash_pledge(ctx["loan"], ctx["borrower"],
                              pledge_amount_cents)
    ctx["pledge"] = pledge
    return ctx
