"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims need the system walked through 5-15 API calls to reach a testable
state (a cleared pro, a booked window, an issued/paid invoice, a dispute under review, an
open warranty callback, ...). These helpers encapsulate those preambles. They use
get_success_data() (lenient validator) so a setup failure raises a clear "Setup step failed"
error instead of a confusing assertion failure deep in a test.

Identity threading: after creating an entity-backed Customer/Pro, every ownership-gated call
uses make_customer_headers(customer["id"]) / make_pro_headers(pro["id"]) — never the shared
TEST_USERS fallback — because X-User-ID is compared to the resource's owner foreign key.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_service_category_payload,
    create_customer_payload,
    create_pro_payload,
    create_background_check_payload,
    decide_background_check_payload,
    create_job_payload,
    submit_quote_payload,
    accept_quote_payload,
    create_dispatch_window_payload,
    book_window_payload,
    create_visit_payload,
    create_labor_line_payload,
    create_part_line_payload,
    pay_invoice_payload,
    create_dispute_payload,
    resolve_dispute_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_pro_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── primitive builders ───────────────────────────────────────

def set_clock(iso8601: str):
    """Pin the server's logical now (PRD §4 test-only clock)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), ADMIN))


def create_category(**overrides):
    """Create a ServiceCategory. Caller passes pricing/eligibility/skill overrides."""
    res = api_client.create_service_category(create_service_category_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_customer(**overrides):
    res = api_client.create_customer(create_customer_payload(**overrides), ANON)
    return get_success_data(res)


def create_pro(**overrides):
    res = api_client.create_pro(create_pro_payload(**overrides), ANON)
    return get_success_data(res)


def clear_pro(pro_id):
    """Run a CRIMINAL + IDENTITY background check, both PASS, to move the pro to CLEARED."""
    bc1 = get_success_data(api_client.create_background_check(
        pro_id, create_background_check_payload(check_type="CRIMINAL"), ADMIN))
    api_client.decide_background_check(bc1["id"], decide_background_check_payload(decision="PASS"), ADMIN)
    bc2 = get_success_data(api_client.create_background_check(
        pro_id, create_background_check_payload(check_type="IDENTITY"), ADMIN))
    api_client.decide_background_check(bc2["id"], decide_background_check_payload(decision="PASS"), ADMIN)
    return get_success_data(api_client.get_pro(pro_id, ADMIN))


def verify_license(pro_id, license_expires_on):
    """Run a LICENSE check that PASSes, setting license_status (VERIFIED if expiry future)."""
    bc = get_success_data(api_client.create_background_check(
        pro_id, create_background_check_payload(check_type="LICENSE", license_expires_on=license_expires_on), ADMIN))
    api_client.decide_background_check(bc["id"], decide_background_check_payload(decision="PASS"), ADMIN)
    return get_success_data(api_client.get_pro(pro_id, ADMIN))


def create_cleared_pro(skill_tags=None, home_zip_code="30301", truck_stock_markup_pct=None, **overrides):
    """Register a pro, clear background, and return the refreshed pro entity."""
    payload = dict(overrides)
    if skill_tags is not None:
        payload["skill_tags"] = skill_tags
    payload["home_zip_code"] = home_zip_code
    if truck_stock_markup_pct is not None:
        payload["truck_stock_markup_pct"] = truck_stock_markup_pct
    pro = create_pro(**payload)
    return clear_pro(pro["id"])


def create_window(pro_id, window_start, window_end, service_zip_code="30301"):
    res = api_client.create_dispatch_window(
        create_dispatch_window_payload(pro_id, window_start, window_end, service_zip_code),
        make_pro_headers(pro_id))
    return get_success_data(res)


def create_job(customer_id, category_id, address_zip_code="30301"):
    res = api_client.create_job(
        create_job_payload(customer_id, category_id, address_zip_code=address_zip_code),
        make_customer_headers(customer_id))
    return get_success_data(res)


# ─── Tier 2/3: job lifecycle shortcuts ────────────────────────

def instant_quoted_job(customer_id, category_id, address_zip_code="30301"):
    """Create a job and take the INSTANT path. Returns (job, quote)."""
    job = create_job(customer_id, category_id, address_zip_code)
    cust = make_customer_headers(customer_id)
    quote = get_success_data(api_client.instant_quote(job["id"], cust))
    return get_success_data(api_client.get_job(job["id"], cust)), quote


def accepted_instant_job(customer_id, category_id, address_zip_code="30301"):
    """Create job -> instant-quote -> accept. Returns (job, quote)."""
    job, quote = instant_quoted_job(customer_id, category_id, address_zip_code)
    cust = make_customer_headers(customer_id)
    api_client.accept_quote(job["id"], accept_quote_payload(quote["id"]), cust)
    return get_success_data(api_client.get_job(job["id"], cust)), quote


def estimate_requested_job(customer_id, category_id, address_zip_code="30301"):
    """Create job -> request-estimate. Returns the job in ESTIMATE_REQUESTED."""
    job = create_job(customer_id, category_id, address_zip_code)
    cust = make_customer_headers(customer_id)
    api_client.request_estimate(job["id"], cust)
    return get_success_data(api_client.get_job(job["id"], cust))


def book_accepted_job(window_id, expected_version, job_id, customer_id):
    """Book an accepted-quote job into a FREE window. Returns the booked window."""
    res = api_client.book_window(
        window_id,
        book_window_payload(job_id, expected_version),
        make_customer_headers(customer_id))
    return res  # raw response so callers can assert success or error


def scheduled_job(customer_id, category_id, pro, window_start, window_end,
                  address_zip_code="30301", service_zip_code="30301"):
    """Create job -> instant-quote -> accept -> book into a fresh window owned by `pro`.
    Returns (job, window, quote)."""
    window = create_window(pro["id"], window_start, window_end, service_zip_code)
    job, quote = accepted_instant_job(customer_id, category_id, address_zip_code)
    get_success_data(book_accepted_job(window["id"], window["version"], job["id"], customer_id))
    cust = make_customer_headers(customer_id)
    return (get_success_data(api_client.get_job(job["id"], cust)),
            get_success_data(api_client.get_dispatch_window(window["id"], ADMIN)),
            quote)


def in_progress_job(customer_id, category_id, pro, window_start, window_end,
                    arrived_at, address_zip_code="30301", service_zip_code="30301"):
    """Walk a job through to IN_PROGRESS (scheduled + visit logged). Returns (job, window)."""
    job, window, _ = scheduled_job(customer_id, category_id, pro, window_start, window_end,
                                   address_zip_code, service_zip_code)
    api_client.create_visit(
        job["id"], create_visit_payload(window["id"], arrived_at), make_pro_headers(pro["id"]))
    cust = make_customer_headers(customer_id)
    return (get_success_data(api_client.get_job(job["id"], cust)),
            get_success_data(api_client.get_dispatch_window(window["id"], ADMIN)))


def issued_invoice_for_in_progress_job(customer_id, category_id, pro, window_start, window_end,
                                       arrived_at, labor_hours=None, parts=None,
                                       address_zip_code="30301", service_zip_code="30301"):
    """IN_PROGRESS job -> optionally record labor/parts -> create+issue invoice.
    `parts` is a list of dicts with keys description/unit_cost_cents/quantity/from_truck_stock.
    Returns (job, window, invoice)."""
    job, window = in_progress_job(customer_id, category_id, pro, window_start, window_end,
                                  arrived_at, address_zip_code, service_zip_code)
    pro_h = make_pro_headers(pro["id"])
    if labor_hours:
        for h in labor_hours:
            api_client.create_labor_line(job["id"], create_labor_line_payload(h), pro_h)
    if parts:
        for p in parts:
            api_client.create_part_line(job["id"], create_part_line_payload(**p), pro_h)
    invoice = get_success_data(api_client.create_invoice(job["id"], pro_h))
    invoice = get_success_data(api_client.issue_invoice(invoice["id"], pro_h))
    return job, window, invoice


def completed_paid_job(customer_id, category_id, pro, window_start, window_end, arrived_at,
                       pay_amount, labor_hours=None, parts=None,
                       address_zip_code="30301", service_zip_code="30301"):
    """Full path to COMPLETED with a PAID invoice. Returns (job, window, invoice)."""
    job, window, invoice = issued_invoice_for_in_progress_job(
        customer_id, category_id, pro, window_start, window_end, arrived_at,
        labor_hours, parts, address_zip_code, service_zip_code)
    pro_h = make_pro_headers(pro["id"])
    cust_h = make_customer_headers(customer_id)
    api_client.complete_job(job["id"], pro_h)
    invoice = get_success_data(api_client.pay_invoice(invoice["id"], pay_invoice_payload(pay_amount), cust_h))
    return get_success_data(api_client.get_job(job["id"], cust_h)), window, invoice


def dispute_under_review(customer_id, invoice_id, job_id, reason, requested_refund_cents,
                         refund_destination=None):
    """File a dispute then move it to UNDER_REVIEW. Returns the dispute."""
    cust_h = make_customer_headers(customer_id)
    overrides = {}
    if refund_destination is not None:
        overrides["refund_destination"] = refund_destination
    disp = get_success_data(api_client.create_dispute(
        create_dispute_payload(job_id, invoice_id, reason, requested_refund_cents, **overrides), cust_h))
    disp = get_success_data(api_client.review_dispute(disp["id"], ADMIN))
    return disp
