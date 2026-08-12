"""Composite setup helpers.

Most interesting PRD claims require the system to be in a state that takes
5-15 API calls to reach (an account with a paid order, a job with scheduled
deliveries, a spec sheet through approval). These helpers encapsulate the
multi-step preambles so tests can focus on assertions.

All helpers use get_success_data() internally so a setup failure surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_color_match_request_payload,
    create_contractor_account_payload,
    create_delivery_payload,
    create_job_account_payload,
    create_jurisdiction_payload,
    create_match_proposal_payload,
    create_mistint_listing_payload,
    create_order_payload,
    create_product_bulletin_payload,
    create_product_payload,
    create_rebate_statement_payload,
    create_spec_sheet_payload,
    create_tint_formula_payload,
    create_voc_rule_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
WRITER = TEST_USERS["spec_writer_headers"]


def set_logical_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4). Returns the raw response."""
    return api_client.set_clock(to_iso8601, ADMIN)


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_account(company_name="Test Co", credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"]):
    """Create a contractor account. Returns the account dict (status ACTIVE,
    tier STANDARD, zero balances, version 1)."""
    resp = api_client.create_contractor_account(
        create_contractor_account_payload(
            company_name=company_name, credit_limit_cents=credit_limit_cents),
        ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create account -> {resp.status_code} {resp.text}"
    return data


def create_jurisdiction(code="TX-OPEN", name="Texas Open"):
    resp = api_client.create_jurisdiction(
        create_jurisdiction_payload(code=code, name=name), ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create jurisdiction -> {resp.status_code} {resp.text}"
    return data


def create_product(sku="P-1", name="Paint", category="FLAT", voc_gpl=100,
                   list_price_cents=TEST_DEFAULTS["LIST_PRICE_CENTS"], tintable=False):
    resp = api_client.create_product(
        create_product_payload(sku=sku, name=name, category=category, voc_gpl=voc_gpl,
                               list_price_cents=list_price_cents, tintable=tintable),
        ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create product -> {resp.status_code} {resp.text}"
    return data


def create_voc_rule(jurisdiction_id, category="FLAT", max_voc_gpl=250,
                    effective_from="2026-01-01T00:00:00Z", effective_to=None):
    payload = create_voc_rule_payload(
        jurisdiction_id, category=category, max_voc_gpl=max_voc_gpl,
        effective_from=effective_from)
    if effective_to is not None:
        payload["effective_to"] = effective_to
    resp = api_client.create_voc_rule(payload, ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create VOC rule -> {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — account + jurisdiction + job (+ product)
# ---------------------------------------------------------------------------

def create_job_for_account(account_id, jurisdiction_id, job_name="Job",
                           site_address="1 Main St", budget_cap_cents=None):
    payload = create_job_account_payload(
        account_id, jurisdiction_id, job_name=job_name, site_address=site_address)
    if budget_cap_cents is not None:
        payload["budget_cap_cents"] = budget_cap_cents
    resp = api_client.create_job_account(payload, ASSOCIATE)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create job -> {resp.status_code} {resp.text}"
    return data


def setup_account_with_job(company_name="Test Co",
                           credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
                           jurisdiction_code="TX-OPEN", jurisdiction_name="Texas Open",
                           job_name="Job", budget_cap_cents=None):
    """Account + jurisdiction + OPEN job. Returns (account, jurisdiction, job)."""
    account = create_account(company_name=company_name, credit_limit_cents=credit_limit_cents)
    jurisdiction = create_jurisdiction(code=jurisdiction_code, name=jurisdiction_name)
    job = create_job_for_account(account["id"], jurisdiction["id"], job_name=job_name,
                                 budget_cap_cents=budget_cap_cents)
    return account, jurisdiction, job


def setup_account_job_product(company_name="Test Co",
                              credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
                              jurisdiction_code="TX-OPEN", jurisdiction_name="Texas Open",
                              job_name="Job", budget_cap_cents=None,
                              sku="P-1", product_name="Paint", category="FLAT", voc_gpl=100,
                              list_price_cents=TEST_DEFAULTS["LIST_PRICE_CENTS"],
                              tintable=False):
    """Account + jurisdiction + job + product. Returns (account, jurisdiction, job, product)."""
    account, jurisdiction, job = setup_account_with_job(
        company_name=company_name, credit_limit_cents=credit_limit_cents,
        jurisdiction_code=jurisdiction_code, jurisdiction_name=jurisdiction_name,
        job_name=job_name, budget_cap_cents=budget_cap_cents)
    product = create_product(sku=sku, name=product_name, category=category,
                             voc_gpl=voc_gpl, list_price_cents=list_price_cents,
                             tintable=tintable)
    return account, jurisdiction, job, product


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle shortcuts
# ---------------------------------------------------------------------------

def get_account_version(account_id) -> int:
    """Re-read the account and return its current version (OCC token for the
    next write, PRD §2.7)."""
    resp = api_client.get_contractor_account(account_id, ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: read account -> {resp.status_code} {resp.text}"
    return data["version"]


def place_order(account_id, job_id, lines, headers=None):
    """Create an order, reading the account version fresh for the OCC token.
    Returns the created order dict."""
    version = get_account_version(account_id)
    resp = api_client.create_order(
        create_order_payload(account_id, job_id, version, lines),
        headers or ASSOCIATE)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create order -> {resp.status_code} {resp.text}"
    return data


def place_and_pay_order(account_id, job_id, lines, headers=None):
    """Create + pay an order. Returns the paid order dict."""
    order = place_order(account_id, job_id, lines, headers=headers)
    resp = api_client.pay_order(order["id"], headers or ASSOCIATE)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: pay order -> {resp.status_code} {resp.text}"
    return data


def get_first_order_line(order_id):
    """Return the first (and typically only) order line of an order."""
    resp = api_client.list_order_lines(ASSOCIATE, params={"order_id": order_id})
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: list order lines -> {resp.status_code} {resp.text}"
    assert isinstance(data, list) and data, "Setup failed: order has no lines"
    return data[0]


def schedule_delivery(order_id, job_id,
                      window_start=TEST_DEFAULTS["WINDOW_START"],
                      window_end=TEST_DEFAULTS["WINDOW_END"]):
    resp = api_client.create_delivery(
        create_delivery_payload(order_id, job_id,
                                window_start=window_start, window_end=window_end),
        MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: schedule delivery -> {resp.status_code} {resp.text}"
    return data


def dispatch_delivery(delivery_id):
    resp = api_client.dispatch_delivery(delivery_id, MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: dispatch delivery -> {resp.status_code} {resp.text}"
    return data


def deliver_delivery(delivery_id):
    resp = api_client.mark_delivery_delivered(delivery_id, MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: mark delivered -> {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 3: spec sheet lifecycle
# ---------------------------------------------------------------------------

def create_spec_sheet_with_line(product_id, project_code="PRJ-1", specified_qty=5,
                                architect_name="A A", title="Spec"):
    resp = api_client.create_spec_sheet(
        create_spec_sheet_payload(
            [{"product_id": product_id, "specified_qty": specified_qty}],
            project_code=project_code, architect_name=architect_name, title=title),
        WRITER)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create spec sheet -> {resp.status_code} {resp.text}"
    return data


def get_first_spec_line(sheet_id):
    resp = api_client.list_spec_lines(WRITER, params={"spec_sheet_id": sheet_id})
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: list spec lines -> {resp.status_code} {resp.text}"
    assert isinstance(data, list) and data, "Setup failed: sheet has no lines"
    return data[0]


def submit_spec_sheet(sheet_id):
    resp = api_client.submit_spec_sheet(sheet_id, WRITER)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: submit sheet -> {resp.status_code} {resp.text}"
    return data


def approve_spec_sheet(sheet_id):
    resp = api_client.approve_spec_sheet(sheet_id, ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: approve sheet -> {resp.status_code} {resp.text}"
    return data


def setup_approved_spec_with_line(product_id, project_code="PRJ-1", specified_qty=5):
    """DRAFT -> SUBMITTED -> APPROVED sheet with one line. Returns (sheet, line)."""
    sheet = create_spec_sheet_with_line(product_id, project_code=project_code,
                                        specified_qty=specified_qty)
    line = get_first_spec_line(sheet["id"])
    submit_spec_sheet(sheet["id"])
    sheet = approve_spec_sheet(sheet["id"])
    return sheet, line


# ---------------------------------------------------------------------------
# Tier 3: bulletin lifecycle
# ---------------------------------------------------------------------------

def create_publish_bulletin(product_id, replacement_id, effective_date="2026-06-01T00:00:00Z",
                            title="Discontinuation"):
    """Create a bulletin and publish it. Returns the published bulletin dict."""
    resp = api_client.create_product_bulletin(
        create_product_bulletin_payload(product_id, replacement_id,
                                        effective_date=effective_date, title=title),
        ADMIN)
    bulletin = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create bulletin -> {resp.status_code} {resp.text}"
    resp = api_client.publish_product_bulletin(bulletin["id"], ADMIN)
    bulletin = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: publish bulletin -> {resp.status_code} {resp.text}"
    return bulletin


# ---------------------------------------------------------------------------
# Tier 3: color match lifecycle
# ---------------------------------------------------------------------------

def create_match_request(account_id, product_id, sample_reference="S-1"):
    resp = api_client.create_color_match_request(
        create_color_match_request_payload(account_id, product_id,
                                           sample_reference=sample_reference),
        ASSOCIATE)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create match request -> {resp.status_code} {resp.text}"
    return data


def propose_match(request_id, color_code="SW 7008", name="Proposal",
                  ounces_128ths=8):
    resp = api_client.create_match_proposal(
        request_id,
        create_match_proposal_payload(color_code=color_code, name=name,
                                      shots=[{"colorant_code": "B1",
                                              "ounces_128ths": ounces_128ths}]),
        ASSOCIATE)
    data = get_success_data(resp)
    assert resp.status_code in (200, 201), \
        f"Setup failed: propose match -> {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_account_at_tier(company_name, target_subtotal_cents,
                          jurisdiction_code="TX-TIER", sku_prefix="P-TIER"):
    """Drive an account to a chosen year-to-date net volume with a single paid
    order, then evaluate tier. Returns (account, job, tiered_order)."""
    account, _, job, product = setup_account_job_product(
        company_name=company_name, jurisdiction_code=jurisdiction_code,
        sku=f"{sku_prefix}", list_price_cents=target_subtotal_cents)
    order = place_and_pay_order(account["id"], job["id"],
                                [{"product_id": product["id"], "quantity": 1}])
    resp = api_client.evaluate_tier(account["id"], ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: evaluate tier -> {resp.status_code} {resp.text}"
    account = data
    return account, job, order


# ---------------------------------------------------------------------------
# Tier 5: composite workflow states
# ---------------------------------------------------------------------------

def setup_paid_order_with_delivery(window_start=TEST_DEFAULTS["WINDOW_START"],
                                   window_end=TEST_DEFAULTS["WINDOW_END"],
                                   list_price_cents=TEST_DEFAULTS["LIST_PRICE_CENTS"],
                                   quantity=1, jurisdiction_code="NV-OPEN"):
    """Paid order with one SCHEDULED delivery. Returns (account, job, product,
    order, delivery)."""
    account, _, job, product = setup_account_job_product(
        company_name="Delivery Co", jurisdiction_code=jurisdiction_code,
        list_price_cents=list_price_cents)
    order = place_and_pay_order(account["id"], job["id"],
                                [{"product_id": product["id"], "quantity": quantity}])
    delivery = schedule_delivery(order["id"], job["id"],
                                 window_start=window_start, window_end=window_end)
    return account, job, product, order, delivery


def setup_mistint_listing(cost_basis_cents=10_000, quantity=1, sku="P-MT"):
    product = create_product(sku=sku, tintable=True)
    resp = api_client.create_mistint_listing(
        create_mistint_listing_payload(product["id"], quantity=quantity,
                                       cost_basis_cents=cost_basis_cents),
        ASSOCIATE)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create mistint listing -> {resp.status_code} {resp.text}"
    return product, data
