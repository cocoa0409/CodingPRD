"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import TEST_DEFAULTS


def unique_email(prefix: str = "acct") -> str:
    """Account emails are unique across accounts (PRD §3.1)."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}@corp.example"


def unique_plan_code(prefix: str = "PLAN") -> str:
    """HostingPlan.plan_code is unique (PRD §3.6)."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_promo_code(prefix: str = "PROMO") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "company_name": TEST_DEFAULTS["COMPANY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def payment_method_payload(**overrides) -> dict:
    defaults = {"card_token": TEST_DEFAULTS["CARD_TOKEN"]}
    defaults.update(overrides)
    return defaults


def credit_grant_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": "welcome credit"}
    defaults.update(overrides)
    return defaults


def create_domain_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "domain_name": "example",
        "tld": "com",
        "term_years": 1,
        "registrant_name": TEST_DEFAULTS["REGISTRANT_NAME"],
        "registrant_email": TEST_DEFAULTS["REGISTRANT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def domain_settings_payload(**overrides) -> dict:
    """All three switches are optional (PRD §3.3); send only what the test needs."""
    payload: dict = {}
    payload.update(overrides)
    return payload


def renew_domain_payload(term_years: int, expected_domain_version: int, **overrides) -> dict:
    defaults = {
        "term_years": term_years,
        "expected_domain_version": expected_domain_version,
    }
    defaults.update(overrides)
    return defaults


def create_dns_record_payload(**overrides) -> dict:
    defaults = {"record_type": "A", "name": "@", "value": "203.0.113.10"}
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(account_id: str, direction: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "direction": direction,
        "domain_name": "acquired",
        "tld": "net",
        "epp_auth_code": "EPP-1",
    }
    defaults.update(overrides)
    return defaults


def create_hosting_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": unique_plan_code("DLX"),
        "tier": "DELUXE",
        "storage_quota_mb": TEST_DEFAULTS["PLAN_STORAGE_QUOTA_MB"],
        "bandwidth_quota_mb": TEST_DEFAULTS["PLAN_BANDWIDTH_QUOTA_MB"],
        "monthly_price_cents": TEST_DEFAULTS["PLAN_MONTHLY_PRICE_CENTS"],
        "included_mailboxes": 5,
        "included_ssl": True,
        "overage_rate_cents_per_gb": TEST_DEFAULTS["PLAN_OVERAGE_RATE_CENTS_PER_GB"],
    }
    defaults.update(overrides)
    return defaults


def create_hosting_subscription_payload(account_id: str, plan_id: str, **overrides) -> dict:
    defaults = {"account_id": account_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def usage_record_payload(amount_mb, recorded_at: str, **overrides) -> dict:
    defaults = {
        "metric": "BANDWIDTH_MB",
        "amount_mb": amount_mb,
        "recorded_at": recorded_at,
    }
    defaults.update(overrides)
    return defaults


def billing_period_payload(period_start: str, period_end: str, **overrides) -> dict:
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults


def create_mailbox_payload(subscription_id: str, domain_id: str, mailbox_address: str,
                           storage_mb_quota: int, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "domain_id": domain_id,
        "add_on_type": "EMAIL_MAILBOX",
        "term_days": 365,
        "mailbox_address": mailbox_address,
        "storage_mb_quota": storage_mb_quota,
    }
    defaults.update(overrides)
    return defaults


def create_ssl_payload(subscription_id: str, domain_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "domain_id": domain_id,
        "add_on_type": "SSL_CERT",
        "term_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_promo_code_payload(code: str, **overrides) -> dict:
    defaults = {
        "code": code,
        "discount_type": "PERCENT",
        "discount_value": 0.10,
        "applies_to_item_types": ["DOMAIN_REGISTRATION"],
        "min_subtotal_cents": 0,
        "max_discount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def apply_promo_payload(promo_code: str, expected_invoice_version: int, **overrides) -> dict:
    defaults = {
        "promo_code": promo_code,
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults


def pay_invoice_payload(use_credit: bool = False, **overrides) -> dict:
    defaults = {"use_credit": use_credit}
    defaults.update(overrides)
    return defaults


def refund_payload(amount_cents: int, destination: str = "CARD", **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "destination": destination,
        "reason": "customer cancelled",
    }
    defaults.update(overrides)
    return defaults


def create_abuse_report_payload(domain_id: str, severity: str = "HIGH",
                                category: str = "SPAM", **overrides) -> dict:
    defaults = {
        "domain_id": domain_id,
        "category": category,
        "severity": severity,
        "reporter_email": TEST_DEFAULTS["REPORTER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def decision_payload(note: str = "confirmed", **overrides) -> dict:
    defaults = {"decision_note": note}
    defaults.update(overrides)
    return defaults


def reason_payload(reason: str = "customer asked", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
