"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared endpoints:
the API server is restarted (and the database emptied) before every individual test.
Setup calls use the lenient validator so a broken precondition surfaces as
"Setup step failed" rather than as a confusing assertion deep inside a test.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    apply_promo_payload,
    billing_period_payload,
    clock_payload,
    create_abuse_report_payload,
    create_account_payload,
    create_dns_record_payload,
    create_domain_payload,
    create_hosting_plan_payload,
    create_hosting_subscription_payload,
    create_mailbox_payload,
    create_promo_code_payload,
    create_ssl_payload,
    create_transfer_request_payload,
    credit_grant_payload,
    decision_payload,
    pay_invoice_payload,
    payment_method_payload,
    unique_promo_code,
    usage_record_payload,
)
from .test_users import (
    ANALYST_1,
    ANONYMOUS,
    BILLING,
    PLATFORM,
    make_abuse_analyst_headers,
    make_registrant_headers,
)


# ─── Logical-clock helpers (PRD §2.5) ──────────────────────────────────────

def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")


def days_after(iso_value: str, days: int) -> str:
    return iso(parse_iso(iso_value) + timedelta(days=days))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), PLATFORM))


def run_sweep() -> dict:
    return get_success_data(api_client.run_expiry_sweep(PLATFORM))


# ─── Tier 1: accounts, credit and cards (PRD §3.1) ─────────────────────────

def create_account(with_card: bool = True, credit_cents: int = 0, **overrides) -> dict:
    """Open an account, optionally attaching a card and granting store credit."""
    account = get_success_data(
        api_client.create_account(create_account_payload(**overrides), ANONYMOUS)
    )
    headers = make_registrant_headers(account["id"])
    if with_card:
        get_success_data(
            api_client.set_payment_method(account["id"], payment_method_payload(), headers)
        )
    if credit_cents:
        get_success_data(
            api_client.grant_credit(
                account["id"], credit_grant_payload(credit_cents), BILLING
            )
        )
    return get_success_data(api_client.get_account(account["id"], headers))


def registrant_of(account: dict) -> dict:
    """Ownership-gated calls must carry the acting Account's own id (PRD §2.1)."""
    return make_registrant_headers(account["id"])


# ─── Tier 1: invoices ──────────────────────────────────────────────────────

def issued_invoices(account_id: str, headers: dict = None) -> list:
    resp = api_client.list_invoices(
        headers or BILLING, {"account_id": account_id, "status": "ISSUED"}
    )
    return get_success_data(resp)


def first_issued_invoice(account_id: str, headers: dict = None) -> dict:
    """The account's oldest still-ISSUED invoice (list endpoints order created_at ASC)."""
    invoices = issued_invoices(account_id, headers)
    assert invoices, f"Setup step failed: account {account_id} has no ISSUED invoice"
    return invoices[0]


def pay_invoice(invoice_id: str, account: dict, use_credit: bool = False) -> dict:
    return get_success_data(
        api_client.pay_invoice(
            invoice_id, pay_invoice_payload(use_credit), registrant_of(account)
        )
    )


# ─── Tier 2: domains (PRD §3.2) ────────────────────────────────────────────

def register_domain(account: dict, domain_name: str = "example", tld: str = "com",
                    **overrides) -> dict:
    """Register a domain; it lands in PENDING_PAYMENT with an ISSUED invoice."""
    payload = create_domain_payload(
        account["id"], domain_name=domain_name, tld=tld, **overrides
    )
    return get_success_data(
        api_client.create_domain(payload, registrant_of(account))
    )


def register_and_activate_domain(account: dict, domain_name: str = "example",
                                 tld: str = "com", auto_renew: bool = False,
                                 **overrides) -> dict:
    """Register a domain and pay its invoice, so it reaches ACTIVE (PRD §3.2)."""
    domain = register_domain(
        account, domain_name=domain_name, tld=tld, auto_renew=auto_renew, **overrides
    )
    invoice = first_issued_invoice(account["id"], registrant_of(account))
    pay_invoice(invoice["id"], account)
    return get_domain(domain["id"], account)


def get_domain(domain_id: str, account: dict) -> dict:
    return get_success_data(
        api_client.get_domain(domain_id, registrant_of(account))
    )


def domain_version(domain_id: str, account: dict) -> int:
    return get_domain(domain_id, account)["version"]


def setup_account_with_active_domain(domain_name: str = "example", tld: str = "com",
                                     with_card: bool = True, auto_renew: bool = False,
                                     **domain_overrides):
    """Account (card on file) + one ACTIVE domain. Returns (account, domain)."""
    account = create_account(with_card=with_card)
    domain = register_and_activate_domain(
        account, domain_name=domain_name, tld=tld, auto_renew=auto_renew,
        **domain_overrides
    )
    return account, domain


# ─── Tier 2: DNS records (PRD §3.5) ────────────────────────────────────────

def create_dns_record(domain: dict, account: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_dns_record(
            domain["id"], create_dns_record_payload(**overrides), registrant_of(account)
        )
    )


def publish_acme_challenge(domain: dict, account: dict, token: str) -> dict:
    """Publish the DNS-01 TXT record an SSL certificate validates against."""
    return create_dns_record(
        domain, account, record_type="TXT", name="_acme-challenge",
        value=token, ttl=300,
    )


# ─── Tier 3: hosting plans and subscriptions (PRD §3.6) ────────────────────

def create_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_hosting_plan(create_hosting_plan_payload(**overrides), BILLING)
    )


def create_subscription(account: dict, plan: dict, primary_domain_id: str = None) -> dict:
    payload = create_hosting_subscription_payload(account["id"], plan["id"])
    if primary_domain_id is not None:
        payload["primary_domain_id"] = primary_domain_id
    return get_success_data(
        api_client.create_hosting_subscription(payload, registrant_of(account))
    )


def activate_subscription(account: dict, subscription: dict) -> dict:
    """Pay the HOSTING_PLAN invoice: PROVISIONING -> ACTIVE, first period opened."""
    invoice = first_issued_invoice(account["id"], registrant_of(account))
    pay_invoice(invoice["id"], account)
    return get_success_data(
        api_client.get_hosting_subscription(subscription["id"], registrant_of(account))
    )


def create_and_activate_subscription(account: dict, plan: dict,
                                     primary_domain_id: str = None) -> dict:
    subscription = create_subscription(account, plan, primary_domain_id)
    return activate_subscription(account, subscription)


def get_subscription(subscription_id: str, account: dict) -> dict:
    return get_success_data(
        api_client.get_hosting_subscription(subscription_id, registrant_of(account))
    )


def setup_hosting_stack(plan_overrides: dict = None, bind_primary_domain: bool = True,
                        domain_name: str = "example", tld: str = "com"):
    """Account (card) + ACTIVE domain + HostingPlan + ACTIVE subscription.

    Returns (account, domain, plan, subscription). The subscription's
    primary_domain_id is bound to the domain unless bind_primary_domain is False.
    """
    plan = create_plan(**(plan_overrides or {}))
    account, domain = setup_account_with_active_domain(domain_name=domain_name, tld=tld)
    subscription = create_and_activate_subscription(
        account, plan, primary_domain_id=domain["id"] if bind_primary_domain else None
    )
    return account, domain, plan, subscription


def setup_subscription_without_domain(plan_overrides: dict = None):
    """Account (card) + HostingPlan + ACTIVE subscription with no domain bound.

    Returns (account, plan, subscription).
    """
    plan = create_plan(**(plan_overrides or {}))
    account = create_account()
    subscription = create_and_activate_subscription(account, plan)
    return account, plan, subscription


# ─── Tier 3: metering (PRD §3.6) ───────────────────────────────────────────

def billing_periods(subscription_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_billing_periods(subscription_id, BILLING, params)
    )


def first_billing_period(subscription_id: str) -> dict:
    periods = billing_periods(subscription_id)
    assert periods, f"Setup step failed: subscription {subscription_id} has no BillingPeriod"
    return periods[0]


def get_billing_period(subscription_id: str, period_id: str) -> dict:
    for period in billing_periods(subscription_id):
        if period["id"] == period_id:
            return period
    raise AssertionError(f"BillingPeriod {period_id} not found on {subscription_id}")


def open_billing_period(subscription_id: str, period_start: str, period_end: str) -> dict:
    return get_success_data(
        api_client.create_billing_period(
            subscription_id, billing_period_payload(period_start, period_end), BILLING
        )
    )


def ingest_usage(subscription_id: str, amount_mb, recorded_at: str) -> dict:
    return get_success_data(
        api_client.create_usage_record(
            subscription_id, usage_record_payload(amount_mb, recorded_at), PLATFORM
        )
    )


def close_period(period_id: str) -> dict:
    return get_success_data(api_client.close_billing_period(period_id, BILLING))


def setup_period_with_usage(amounts_and_dates, plan_overrides: dict = None):
    """ACTIVE subscription whose first OPEN period already carries usage records.

    `amounts_and_dates` is a list of (amount_mb, recorded_at) pairs, ingested in order.
    Returns (account, plan, subscription, period).
    """
    account, plan, subscription = setup_subscription_without_domain(plan_overrides)
    period = first_billing_period(subscription["id"])
    for amount_mb, recorded_at in amounts_and_dates:
        ingest_usage(subscription["id"], amount_mb, recorded_at)
    return account, plan, subscription, period


# ─── Tier 3: add-ons (PRD §3.5) ────────────────────────────────────────────

def create_mailbox(account: dict, subscription: dict, domain: dict, mailbox_address: str,
                   storage_mb_quota: int, **overrides) -> dict:
    payload = create_mailbox_payload(
        subscription["id"], domain["id"], mailbox_address, storage_mb_quota, **overrides
    )
    return get_success_data(
        api_client.create_add_on(payload, registrant_of(account))
    )


def create_ssl_cert(account: dict, subscription: dict, domain: dict, **overrides) -> dict:
    payload = create_ssl_payload(subscription["id"], domain["id"], **overrides)
    return get_success_data(
        api_client.create_add_on(payload, registrant_of(account))
    )


def create_and_validate_ssl_cert(account: dict, subscription: dict, domain: dict,
                                 **overrides):
    """SSL certificate driven all the way to ACTIVE via DNS-01 validation.

    Returns (add_on, txt_record) with the add-on re-read after validation.
    """
    cert = create_ssl_cert(account, subscription, domain, **overrides)
    txt = publish_acme_challenge(domain, account, cert["validation_token"])
    get_success_data(
        api_client.validate_add_on(cert["id"], registrant_of(account))
    )
    cert = get_add_on(cert["id"], account)
    return cert, txt


def get_add_on(add_on_id: str, account: dict) -> dict:
    return get_success_data(
        api_client.get_add_on(add_on_id, registrant_of(account))
    )


# ─── Tier 4: abuse workflow and risk accumulation (PRD §3.9) ───────────────

def file_report(domain: dict, severity: str = "HIGH", category: str = "SPAM") -> dict:
    return get_success_data(
        api_client.create_abuse_report(
            create_abuse_report_payload(domain["id"], severity=severity, category=category),
            ANONYMOUS,
        )
    )


def report_under_review(domain: dict, severity: str = "HIGH", category: str = "SPAM",
                        reviewer: str = "analyst-1") -> dict:
    """File a report and take it into review (records reviewer_user_id)."""
    report = file_report(domain, severity=severity, category=category)
    get_success_data(
        api_client.review_abuse_report(report["id"], make_abuse_analyst_headers(reviewer))
    )
    return report


def uphold_report(report_id: str, decider: str = "analyst-2", note: str = "confirmed") -> dict:
    return get_success_data(
        api_client.uphold_abuse_report(
            report_id, decision_payload(note), make_abuse_analyst_headers(decider)
        )
    )


def dismiss_report(report_id: str, decider: str = "analyst-2",
                   note: str = "not abusive") -> dict:
    return get_success_data(
        api_client.dismiss_abuse_report(
            report_id, decision_payload(note), make_abuse_analyst_headers(decider)
        )
    )


def uphold_new_report(domain: dict, severity: str = "HIGH", category: str = "SPAM",
                      reviewer: str = "analyst-1", decider: str = "analyst-2") -> dict:
    """File → review → uphold, the full three-step abuse fork."""
    report = report_under_review(domain, severity=severity, category=category,
                                 reviewer=reviewer)
    return uphold_report(report["id"], decider=decider)


def get_account_state(account_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_account(account_id, headers or ANALYST_1)
    )


def setup_auto_suspended_account():
    """Account driven to risk_score 90 (CRITICAL 60 + HIGH 30) and auto-SUSPENDED.

    Returns (account, domain_critical, domain_high) with both domains SUSPENDED.
    """
    account = create_account()
    d1 = register_and_activate_domain(account, "example", "com")
    d2 = register_and_activate_domain(account, "shop", "net")
    uphold_new_report(d1, severity="CRITICAL", category="PHISHING")
    uphold_new_report(d2, severity="HIGH", category="MALWARE")
    return account, d1, d2


# ─── Tier 4: transfers (PRD §3.7) ──────────────────────────────────────────

def create_transfer_request(account: dict, direction: str, **overrides) -> dict:
    payload = create_transfer_request_payload(account["id"], direction, **overrides)
    return get_success_data(
        api_client.create_transfer_request(payload, registrant_of(account))
    )


def get_transfer_request(transfer_id: str, account: dict) -> dict:
    return get_success_data(
        api_client.get_transfer_request(transfer_id, registrant_of(account))
    )


def setup_outbound_transfer(clock_at: str = "2026-07-15T00:00:00Z",
                            unlock: bool = False,
                            epp_auth_code: str = None):
    """Account (card) + ACTIVE example.com + an INITIATED outbound TransferRequest.

    The clock is moved to `clock_at` (past the 60-day post-registration lock by
    default). When `unlock` is true the domain's lock dimension is moved to
    UNLOCKED first. `epp_auth_code` defaults to the domain's real code.
    Returns (account, domain, transfer_request).
    """
    account, domain = setup_account_with_active_domain()
    set_clock(clock_at)
    if unlock:
        get_success_data(
            api_client.update_domain_settings(
                domain["id"], {"locked": False}, registrant_of(account)
            )
        )
        domain = get_domain(domain["id"], account)
    code = epp_auth_code if epp_auth_code is not None else domain["epp_auth_code"]
    transfer = create_transfer_request(
        account, "OUT", domain_name=domain["domain_name"], tld=domain["tld"],
        epp_auth_code=code, domain_id=domain["id"],
    )
    return account, domain, transfer


def setup_inbound_transfer(domain_name: str = "acquired", tld: str = "net",
                           epp_auth_code: str = "EPP-1"):
    """Account + an INITIATED inbound TransferRequest. Returns (account, transfer)."""
    account = create_account(with_card=False)
    transfer = create_transfer_request(
        account, "IN", domain_name=domain_name, tld=tld, epp_auth_code=epp_auth_code
    )
    return account, transfer


# ─── Tier 5: promotions (PRD §3.8) ─────────────────────────────────────────

def create_promo(code: str = None, **overrides) -> dict:
    code = code or unique_promo_code()
    return get_success_data(
        api_client.create_promo_code(create_promo_code_payload(code, **overrides), BILLING)
    )


def apply_promo(invoice: dict, account: dict, promo_code: str,
                expected_invoice_version: int = None) -> dict:
    version = (
        expected_invoice_version
        if expected_invoice_version is not None
        else invoice["version"]
    )
    return get_success_data(
        api_client.apply_promo(
            invoice["id"], apply_promo_payload(promo_code, version), registrant_of(account)
        )
    )


def get_invoice(invoice_id: str, account: dict = None) -> dict:
    return get_success_data(
        api_client.get_invoice(invoice_id, registrant_of(account) if account else BILLING)
    )


def invoice_lines(invoice_id: str, account: dict = None) -> list:
    return get_success_data(
        api_client.list_invoice_line_items(
            invoice_id, registrant_of(account) if account else BILLING
        )
    )


def ledger_entries(account_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_ledger_entries(account_id, BILLING, params)
    )
