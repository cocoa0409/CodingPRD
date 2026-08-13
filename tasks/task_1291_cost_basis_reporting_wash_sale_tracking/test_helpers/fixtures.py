"""Composite setup helpers.

Each function builds preconditions from scratch using only PRD-declared
endpoints (the server is restarted before every test, so every test starts
against an empty database). Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_firm_payload, create_customer_payload, create_account_payload,
    create_security_payload, create_tax_lot_payload, create_disposition_payload,
    create_corporate_action_payload, create_transfer_statement_payload,
    create_tax_form_payload, create_basis_change_request_payload,
)
from .test_users import (
    make_firm_admin_headers, make_tax_ops_headers, make_customer_headers,
    make_customer_service_headers,
)

FIRM_ADMIN = make_firm_admin_headers()
TAX_OPS = make_tax_ops_headers()


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def make_firm(legal_name="Test Brokerage Firm") -> dict:
    return get_success_data(api_client.create_firm(create_firm_payload(legal_name=legal_name), FIRM_ADMIN))


def make_customer(firm_id, tin="TIN-000-1", display_name="Customer") -> dict:
    return get_success_data(
        api_client.create_customer(firm_id, create_customer_payload(taxpayer_tin=tin, display_name=display_name), FIRM_ADMIN)
    )


def make_account(firm_id, customer_id, account_number="A1", method="FIFO", account_type="TAXABLE") -> dict:
    return get_success_data(
        api_client.create_account(
            firm_id, customer_id,
            create_account_payload(account_number=account_number, default_disposal_method=method, account_type=account_type),
            TAX_OPS,
        )
    )


def make_security(firm_id, cusip="123456789", ticker="TST", security_type="EQUITY",
                  covered_effective="2011-01-01T00:00:00Z") -> dict:
    return get_success_data(
        api_client.create_security(
            firm_id,
            create_security_payload(cusip=cusip, ticker=ticker, security_type=security_type,
                                    covered_security_effective_date=covered_effective),
            TAX_OPS,
        )
    )


def make_lot(firm_id, account_id, security_id, acquisition_date="2025-01-05T00:00:00Z",
             quantity=10, basis=10000, kind="PURCHASE", **extra) -> dict:
    payload = create_tax_lot_payload(
        security_id=security_id, acquisition_date=acquisition_date, quantity=quantity,
        original_cost_basis_cents=basis, acquisition_kind=kind,
    )
    payload.update(extra)
    return get_success_data(api_client.create_tax_lot(firm_id, account_id, payload, TAX_OPS))


def make_disposition(firm_id, account_id, security_id, quantity=10, proceeds=15000,
                     method="FIFO", trade_date="2025-06-10T00:00:00Z",
                     settlement_date="2025-06-11T00:00:00Z", lot_allocations=None) -> dict:
    payload = create_disposition_payload(
        security_id=security_id, trade_date=trade_date, settlement_date=settlement_date,
        quantity=quantity, proceeds_cents=proceeds, method=method,
    )
    if lot_allocations is not None:
        payload["lot_allocations"] = lot_allocations
    return get_success_data(api_client.create_disposition(firm_id, account_id, payload, TAX_OPS))


def settle(firm_id, disposition_id) -> dict:
    return get_success_data(api_client.settle_disposition(firm_id, disposition_id, TAX_OPS))


# ---------------------------------------------------------------------------
# Tier 2: hierarchy builders
# ---------------------------------------------------------------------------

def setup_book(tin="TIN-B-1", cusip="123456789", ticker="BK", method="FIFO",
               account_number="A1", display_name="Book"):
    """firm + customer + one account + one security. Returns dict of the four entities."""
    firm = make_firm()
    cust = make_customer(firm["id"], tin=tin, display_name=display_name)
    acct = make_account(firm["id"], cust["id"], account_number=account_number, method=method)
    sec = make_security(firm["id"], cusip=cusip, ticker=ticker)
    return {"firm": firm, "customer": cust, "account": acct, "security": sec}


def setup_two_account_book(tin="TIN-B-2", cusip="123456789", ticker="BK2"):
    """firm + customer + two TAXABLE accounts (A1, A2) + one security."""
    firm = make_firm()
    cust = make_customer(firm["id"], tin=tin, display_name="Two Accounts")
    acct1 = make_account(firm["id"], cust["id"], account_number="A1", method="FIFO")
    acct2 = make_account(firm["id"], cust["id"], account_number="A2", method="FIFO")
    sec = make_security(firm["id"], cusip=cusip, ticker=ticker)
    return {"firm": firm, "customer": cust, "account1": acct1, "account2": acct2, "security": sec}


def get_customer_version(firm_id, customer_id) -> int:
    return get_success_data(api_client.get_customer(firm_id, customer_id, TAX_OPS))["version"]


def get_account_version(firm_id, account_id) -> int:
    return get_success_data(api_client.get_account(firm_id, account_id, TAX_OPS))["version"]


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_settled_sale(proceeds=15000, basis=10000, qty=10, tin="TIN-S-1", cusip="121212121",
                       method="FIFO", trade_date="2025-06-10T00:00:00Z",
                       acq_date="2025-01-05T00:00:00Z", lot_allocations=None):
    """Book + settle one disposition against a single lot. Returns ids dict."""
    s = setup_book(tin=tin, cusip=cusip, ticker="STL", method=method)
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                   acquisition_date=acq_date, quantity=qty, basis=basis)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=qty if lot_allocations is None else sum(a["quantity"] for a in lot_allocations),
                            proceeds=proceeds, method=method if lot_allocations is None else "SPECIFIC_ID",
                            trade_date=trade_date, lot_allocations=lot_allocations)
    settled = settle(s["firm"]["id"], disp["id"])
    s.update({"lot": lot, "disposition": settled})
    return s


def setup_wash_sale_scenario(repl_qty=100, repl_basis=410000, repl_date="2025-06-20T00:00:00Z",
                             loss_qty=100, loss_basis=500000, proceeds=400000,
                             trade_date="2025-06-10T00:00:00Z",
                             tin="TIN-WS-1", cusip="343434343"):
    """Two accounts sharing one wash-sale scope: A1 holds the loss lot, A2 holds
    the replacement lot; a PENDING disposition sells the loss lot at a loss.
    Returns ids dict including the PENDING disposition (not yet settled)."""
    s = setup_two_account_book(tin=tin, cusip=cusip, ticker="WS")
    lot1 = make_lot(s["firm"]["id"], s["account1"]["id"], s["security"]["id"],
                    acquisition_date="2025-01-05T00:00:00Z", quantity=loss_qty, basis=loss_basis)
    lot2 = make_lot(s["firm"]["id"], s["account2"]["id"], s["security"]["id"],
                    acquisition_date=repl_date, quantity=repl_qty, basis=repl_basis)
    disp = make_disposition(s["firm"]["id"], s["account1"]["id"], s["security"]["id"],
                            quantity=loss_qty, proceeds=proceeds, method="FIFO", trade_date=trade_date)
    s.update({"lot1": lot1, "lot2": lot2, "disposition": disp})
    return s


def setup_draft_form(firm_id, customer_id, tax_year=2025) -> dict:
    return get_success_data(
        api_client.create_tax_form(firm_id, customer_id, create_tax_form_payload(tax_year=tax_year), TAX_OPS)
    )


def generate_form(firm_id, customer_id, form_id) -> dict:
    """Generate a DRAFT form, passing the customer's current version for OCC."""
    version = get_customer_version(firm_id, customer_id)
    return get_success_data(
        api_client.generate_tax_form(firm_id, customer_id, form_id, {"expected_customer_version": version}, TAX_OPS)
    )


def setup_generated_form(firm_id, customer_id, tax_year=2025) -> dict:
    form = setup_draft_form(firm_id, customer_id, tax_year)
    return generate_form(firm_id, customer_id, form["id"])


def setup_filed_form(firm_id, customer_id, tax_year=2025) -> dict:
    form = setup_generated_form(firm_id, customer_id, tax_year)
    return get_success_data(api_client.file_tax_form(firm_id, customer_id, form["id"], FIRM_ADMIN))


def setup_settled_sale_with_filed_form(proceeds=15000, basis=10000, tin="TIN-F-1", cusip="454545454"):
    """One settled covered disposition + a FILED 2025 form for the customer."""
    s = setup_settled_sale(proceeds=proceeds, basis=basis, tin=tin, cusip=cusip)
    form = setup_filed_form(s["firm"]["id"], s["customer"]["id"], 2025)
    s["form"] = form
    return s


# ---------------------------------------------------------------------------
# Tier 4: basis change request ladder
# ---------------------------------------------------------------------------

def make_basis_request(firm_id, customer_id, lot_id, kind="BASIS_AMOUNT_CORRECTION",
                       submitter="customer", **overrides) -> dict:
    """Submit a basis change request. submitter='customer' uses the owning
    Customer's entity-backed headers; 'customer_service' uses CustomerService."""
    payload = create_basis_change_request_payload(tax_lot_id=lot_id, request_kind=kind, **overrides)
    if submitter == "customer":
        headers = make_customer_headers(customer_id)
    else:
        headers = make_customer_service_headers()
    return get_success_data(api_client.create_basis_change_request(firm_id, customer_id, payload, headers))


def setup_under_review_request(firm_id, customer_id, lot_id, **overrides) -> dict:
    req = make_basis_request(firm_id, customer_id, lot_id, **overrides)
    return get_success_data(api_client.start_review_basis_request(firm_id, req["id"], TAX_OPS))


def setup_approved_request(firm_id, customer_id, lot_id, reviewer="taxops-reviewer-1", **overrides) -> dict:
    req = setup_under_review_request(firm_id, customer_id, lot_id, **overrides)
    return get_success_data(
        api_client.approve_basis_request(firm_id, req["id"], make_tax_ops_headers(reviewer))
    )


# ---------------------------------------------------------------------------
# Tier 5: transfer statement helpers
# ---------------------------------------------------------------------------

def make_transfer_statement(firm_id, account_id, security_id, direction="INBOUND",
                            quantity=10, lots_payload=None, transfer_date="2025-04-01T00:00:00Z",
                            counterparty="Other Broker", replaces_statement_id=None) -> dict:
    payload = create_transfer_statement_payload(
        direction=direction, counterparty_firm_name=counterparty, security_id=security_id,
        quantity=quantity, transfer_date=transfer_date,
    )
    if lots_payload is not None:
        payload["lots_payload"] = lots_payload
    if replaces_statement_id is not None:
        payload["replaces_statement_id"] = replaces_statement_id
    return get_success_data(api_client.create_transfer_statement(firm_id, account_id, payload, TAX_OPS))


def deliver_statement(firm_id, account_id, stmt_id) -> dict:
    """Deliver a statement, passing the account's current version for OCC."""
    version = get_account_version(firm_id, account_id)
    return get_success_data(
        api_client.deliver_transfer_statement(firm_id, stmt_id, {"expected_account_version": version}, TAX_OPS)
    )


def lot_payload_entry(acquisition_date="2025-01-05T00:00:00Z", quantity=10, basis=10000) -> dict:
    return {"acquisition_date": acquisition_date, "quantity": quantity, "original_cost_basis_cents": basis}
