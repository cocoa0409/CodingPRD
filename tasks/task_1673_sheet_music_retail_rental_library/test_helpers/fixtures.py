"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. They use get_success_data() so a setup failure
surfaces as a clear "Setup step failed" error rather than a confusing assert.

Identity threading: Customer calls are entity-backed by CustomerAccount, so
ownership-gated transitions (confirm-receipt, dispute) always build headers
from the real account id via make_customer_headers — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_customer_account_payload,
    create_damage_invoice_payload,
    create_perusal_request_payload,
    create_publisher_payload,
    create_purchase_order_payload,
    create_rental_order_payload,
    create_rental_set_payload,
    create_rights_case_payload,
    create_work_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_returns_clerk_headers

ADMIN = TEST_USERS["library_admin_headers"]
CLERK = TEST_USERS["library_clerk_headers"]
RETURNS = TEST_USERS["returns_clerk_headers"]
BILLING = TEST_USERS["billing_manager_headers"]
ADVISOR = TEST_USERS["rights_advisor_headers"]

BASE_CLOCK = "2026-08-05T00:00:00Z"
DEFAULT_CHECKOUT = "2026-08-05"
DEFAULT_DUE = "2026-09-04"


# ---------------------------------------------------------------------------
# Tier 0: logical clock and daily sweep
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601: str = BASE_CLOCK) -> dict:
    """Move the logical clock; returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweep() -> dict:
    """Run the daily batch; returns the sweep tallies."""
    return get_success_data(api_client.run_daily_sweep(ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_publisher(name="Test Publisher", **overrides):
    payload = create_publisher_payload(name=name, **overrides)
    return get_success_data(api_client.create_publisher(payload, ADMIN))


def create_work(publisher_id, **overrides):
    payload = create_work_payload(publisher_id, **overrides)
    return get_success_data(api_client.create_work(payload, ADMIN))


def create_rental_set(work_id, set_code="SET-001", copy_count=30,
                      replacement_value_cents=240000, **overrides):
    payload = create_rental_set_payload(
        work_id, set_code=set_code, copy_count=copy_count,
        replacement_value_cents=replacement_value_cents, **overrides,
    )
    return get_success_data(api_client.create_rental_set(payload, ADMIN))


def create_account(account_name="Test School", account_kind="SCHOOL", **overrides):
    payload = create_customer_account_payload(
        account_name=account_name, account_kind=account_kind, **overrides,
    )
    return get_success_data(api_client.create_customer_account(payload, ADMIN))


def create_purchase_order(account_id, po_number="PO-0001",
                          authorized_amount_cents=500000,
                          valid_from="2026-08-01", valid_until="2027-06-30",
                          **overrides):
    payload = create_purchase_order_payload(
        account_id, po_number=po_number,
        authorized_amount_cents=authorized_amount_cents,
        valid_from=valid_from, valid_until=valid_until, **overrides,
    )
    return get_success_data(api_client.create_purchase_order(payload, BILLING))


def create_approved_po(account_id, **kwargs):
    """SUBMITTED purchase order approved by the BillingManager. Returns the PO."""
    po = create_purchase_order(account_id, **kwargs)
    return get_success_data(api_client.approve_purchase_order(po["id"], BILLING))


def create_order(account_id, rental_set_id, copies=1,
                 checkout_date=DEFAULT_CHECKOUT, due_date=DEFAULT_DUE, **overrides):
    payload = create_rental_order_payload(
        account_id, rental_set_id, copies_requested=copies,
        checkout_date=checkout_date, due_date=due_date, **overrides,
    )
    return get_success_data(api_client.create_rental_order(payload, CLERK))


def create_perusal_request(account_id, work_id, format="PHYSICAL", **overrides):
    payload = create_perusal_request_payload(
        account_id, work_id, format=format, **overrides,
    )
    return get_success_data(api_client.create_perusal_request(payload, CLERK))


def create_rights_case(account_id, work_id, venue_kind="EDUCATIONAL",
                       question="Cleared for our concert?", headers=None, **overrides):
    payload = create_rights_case_payload(
        account_id, work_id, venue_kind=venue_kind, question=question, **overrides,
    )
    return get_success_data(api_client.create_rights_case(payload, headers or ADVISOR))


# ---------------------------------------------------------------------------
# Tier 1.5: single transitions (validated)
# ---------------------------------------------------------------------------

def reserve_order(order_id):
    return get_success_data(api_client.reserve_rental_order(order_id, CLERK))


def dispatch_order(order_id):
    return get_success_data(api_client.dispatch_rental_order(order_id, CLERK))


def confirm_order(order_id, account_id):
    """DISPATCHED -> ON_LOAN by the owning Customer (ownership-gated call)."""
    return get_success_data(
        api_client.confirm_receipt(order_id, make_customer_headers(account_id))
    )


def check_in_order(order_id, line_grades, headers=None):
    """ON_LOAN/OVERDUE -> RETURNED. line_grades is the per-line grade record
    (e.g. "A,A" for a two-copy order)."""
    return get_success_data(
        api_client.check_in_rental_order(order_id, line_grades, headers or RETURNS)
    )


def renew_order(order_id, expected_version):
    return get_success_data(
        api_client.renew_rental_order(order_id, expected_version, CLERK)
    )


def cancel_order(order_id):
    return get_success_data(api_client.cancel_rental_order(order_id, CLERK))


def settle_order(order_id, topup_cents=None):
    return get_success_data(
        api_client.settle_rental_order(order_id, BILLING, topup_cents=topup_cents)
    )


def dispute_order(order_id, account_id):
    return get_success_data(
        api_client.dispute_rental_order(order_id, make_customer_headers(account_id))
    )


def record_prepayment(order_id, amount_cents):
    return get_success_data(api_client.record_prepayment(order_id, amount_cents, BILLING))


# ---------------------------------------------------------------------------
# Tier 1.6: reads used across many setups
# ---------------------------------------------------------------------------

def fetch_account(account_id):
    return get_success_data(api_client.get_customer_account(account_id, BILLING))


def fetch_order(order_id):
    return get_success_data(api_client.get_rental_order(order_id, CLERK))


def fetch_set(rental_set_id):
    return get_success_data(api_client.get_rental_set(rental_set_id, CLERK))


def fetch_po(po_id):
    return get_success_data(api_client.get_purchase_order(po_id, BILLING))


def fetch_invoice(invoice_id):
    return get_success_data(api_client.get_damage_invoice(invoice_id, BILLING))


def fetch_report(report_id):
    return get_success_data(api_client.get_condition_report(report_id, BILLING))


def order_lines(order_id):
    """All rental lines of an order, in list order (created_at ascending)."""
    data, _meta = validate_paginated(
        api_client.list_rental_lines(CLERK, params={"rental_order_id": order_id})
    )
    return data


def reports_for_line(line_id):
    data, _meta = validate_paginated(
        api_client.list_condition_reports(BILLING, params={"rental_line_id": line_id})
    )
    return data


def first_degraded_line(lines):
    """First line whose recorded return condition degraded from its A checkout."""
    for line in lines:
        if line.get("return_condition") not in (None, "A"):
            return line
    raise AssertionError("Setup failed: no degraded line found")


# ---------------------------------------------------------------------------
# Tier 2: catalog + account composites
# ---------------------------------------------------------------------------

def setup_catalog(publisher_name="Test Publisher", publisher_overrides=None,
                  work_title="Test Work", catalog_number="CAT-001",
                  ensemble_tier="CHAMBER", base_rate=10000, sale_price=2000,
                  license_format="PRINT_ONLY", work_overrides=None,
                  set_code="SET-001", copies=30, replacement=240000,
                  with_set=True):
    """Publisher + work (+ one rental set). Returns a dict of the created rows."""
    publisher = create_publisher(publisher_name, **(publisher_overrides or {}))
    work_kwargs = dict(
        title=work_title, catalog_number=catalog_number,
        ensemble_tier=ensemble_tier, base_rental_rate_cents=base_rate,
        sale_price_cents=sale_price, license_format=license_format,
    )
    work_kwargs.update(work_overrides or {})
    work = create_work(publisher["id"], **work_kwargs)
    result = {"publisher": publisher, "work": work, "rental_set": None}
    if with_set:
        result["rental_set"] = create_rental_set(
            work["id"], set_code=set_code, copy_count=copies, replacement_value_cents=replacement,
        )
    return result


# ---------------------------------------------------------------------------
# Tier 3: rental-order lifecycle composites
# ---------------------------------------------------------------------------

def setup_order_on_loan(order_copies=1, account_overrides=None,
                        checkout_date=DEFAULT_CHECKOUT, due_date=DEFAULT_DUE,
                        order_overrides=None, **catalog_kwargs):
    """Full chain to ON_LOAN: catalog -> account -> clock -> order -> reserve ->
    dispatch -> customer confirm. Returns the workspace dict.
    `order_copies` is the order's copies_requested; the set's copy_count is a
    catalog kwarg (`copies`)."""
    catalog = setup_catalog(**catalog_kwargs)
    account = create_account(**(account_overrides or {}))
    advance_clock(BASE_CLOCK)
    order = create_order(account["id"], catalog["rental_set"]["id"],
                         copies=order_copies,
                         checkout_date=checkout_date, due_date=due_date,
                         **(order_overrides or {}))
    order = reserve_order(order["id"])
    order = dispatch_order(order["id"])
    order = confirm_order(order["id"], account["id"])
    assert order["status"] == "ON_LOAN", f"Setup failed: order is {order['status']}"
    return {**catalog, "account": account, "order": order}


def setup_returned_order(grades="C", copies=1, return_clock=None, **kwargs):
    """Order walked to RETURNED via check-in with the given per-line grades.
    return_clock=None keeps the loan on time (checked in at BASE_CLOCK).
    Returns the workspace dict with the post-check-in order."""
    ws = setup_order_on_loan(order_copies=copies, **kwargs)
    if return_clock is not None:
        advance_clock(return_clock)
    ws["order"] = check_in_order(ws["order"]["id"], grades)
    assert ws["order"]["status"] == "RETURNED", \
        f"Setup failed: order is {ws['order']['status']}"
    ws["lines"] = order_lines(ws["order"]["id"])
    return ws


def setup_draft_invoice(grades="C", copies=1, **kwargs):
    """RETURNED order with a degraded line plus a DRAFT damage invoice.
    Returns the workspace dict with line, report, and invoice. When a pinned
    assessor identity is required (segregation-of-duties tests), use
    setup_draft_invoice_with_assessor instead."""
    ws = setup_returned_order(grades=grades, copies=copies, **kwargs)
    line = first_degraded_line(ws["lines"])
    report = reports_for_line(line["id"])[0]
    invoice = get_success_data(api_client.create_damage_invoice(
        create_damage_invoice_payload(line["id"], report["id"]), BILLING,
    ))
    assert invoice["status"] == "DRAFT", f"Setup failed: invoice is {invoice['status']}"
    ws.update({"line": line, "report": report, "invoice": invoice})
    return ws


def setup_draft_invoice_with_assessor(assessor_user_id, grades="C", copies=1, **kwargs):
    """Like setup_draft_invoice, but the check-in assessment is performed by a
    ReturnsClerk with a pinned X-User-ID so the segregation-of-duties rule can
    key on it."""
    ws = setup_order_on_loan(order_copies=copies, **kwargs)
    ws["order"] = check_in_order(
        ws["order"]["id"], grades,
        headers=make_returns_clerk_headers(assessor_user_id),
    )
    ws["lines"] = order_lines(ws["order"]["id"])
    line = first_degraded_line(ws["lines"])
    report = reports_for_line(line["id"])[0]
    invoice = get_success_data(api_client.create_damage_invoice(
        create_damage_invoice_payload(line["id"], report["id"]), BILLING,
    ))
    ws.update({"line": line, "report": report, "invoice": invoice})
    return ws


def setup_issued_invoice(**kwargs):
    """DRAFT invoice issued by the BillingManager. Returns the workspace dict."""
    ws = setup_draft_invoice(**kwargs)
    ws["invoice"] = get_success_data(
        api_client.issue_damage_invoice(ws["invoice"]["id"], BILLING)
    )
    assert ws["invoice"]["status"] == "ISSUED", \
        f"Setup failed: invoice is {ws['invoice']['status']}"
    return ws


# ---------------------------------------------------------------------------
# Tier 4: perusal composites
# ---------------------------------------------------------------------------

def setup_shipped_perusal(format="PHYSICAL", publisher_overrides=None,
                          work_overrides=None, account_overrides=None,
                          ship_clock=BASE_CLOCK):
    """Perusal request approved and shipped. Returns the workspace dict."""
    pub_over = {"allows_digital_perusal": True}
    pub_over.update(publisher_overrides or {})
    work_over = {"perusal_allowed": True, "license_format": "PRINT_AND_DIGITAL"}
    work_over.update(work_overrides or {})
    publisher = create_publisher("Perusal Pub", **pub_over)
    work_kwargs = {"title": "Perusal Work", "catalog_number": "PER-001",
                   "base_rental_rate_cents": 5000, "sale_price_cents": 900}
    work_kwargs.update(work_over)
    work = create_work(publisher["id"], **work_kwargs)
    account = create_account(**(account_overrides or {}))
    advance_clock(ship_clock)
    perusal = create_perusal_request(account["id"], work["id"], format=format)
    perusal = get_success_data(api_client.approve_perusal_request(perusal["id"], CLERK))
    perusal = get_success_data(api_client.ship_perusal_request(perusal["id"], CLERK))
    assert perusal["status"] == "SHIPPED", \
        f"Setup failed: perusal is {perusal['status']}"
    return {"publisher": publisher, "work": work, "account": account,
            "perusal": perusal}
