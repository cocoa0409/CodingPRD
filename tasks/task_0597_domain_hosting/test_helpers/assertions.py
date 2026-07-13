"""Entity assertions and domain invariant checkers for the registrar API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import RISK_SCORE_CAP


# ─── Generic shape helpers ─────────────────────────────────────────────────

def assert_audit_triple(data: dict, entity: str = "entity"):
    """PRD §2.4: id + created_at + updated_at + version on a full resource."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an int >= 1, got {data.get('version')!r}"


def assert_write_once_shape(data: dict, entity: str = "entity"):
    """PRD §2.4: write-once records carry id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"


# ─── Per-entity assertions ─────────────────────────────────────────────────

def assert_account(data: dict):
    assert_audit_triple(data, "Account")
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["company_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED"), \
        f"Account.status out of range: {data['status']!r}"
    assert isinstance(data["payment_method_on_file"], bool)
    assert isinstance(data["auto_renew_default"], bool)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["net_cash_cents"], int)
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= RISK_SCORE_CAP, \
        f"Account.risk_score must lie between 0 and 100, got {data['risk_score']}"


def assert_domain(data: dict):
    assert_audit_triple(data, "Domain")
    assert isinstance(data["account_id"], str)
    assert isinstance(data["domain_name"], str)
    assert data["tld"] in ("com", "net", "io", "xyz"), f"Domain.tld out of range: {data['tld']!r}"
    assert data["lifecycle_status"] in (
        "PENDING_PAYMENT", "ACTIVE", "SUSPENDED", "EXPIRED",
        "REDEMPTION", "PENDING_DELETE", "DELETED", "TRANSFERRED_OUT",
    ), f"Domain.lifecycle_status out of range: {data['lifecycle_status']!r}"
    assert data["lock_status"] in ("LOCKED", "UNLOCKED"), \
        f"Domain.lock_status out of range: {data['lock_status']!r}"
    assert isinstance(data["whois_privacy_enabled"], bool)
    assert isinstance(data["auto_renew_enabled"], bool)
    assert isinstance(data["term_years"], int) and 1 <= data["term_years"] <= 10


def assert_dns_record(data: dict):
    assert_audit_triple(data, "DnsRecord")
    assert data["record_type"] in ("A", "AAAA", "CNAME", "MX", "TXT", "NS")
    assert isinstance(data["name"], str)
    assert isinstance(data["value"], str)
    assert isinstance(data["ttl"], int) and 60 <= data["ttl"] <= 86400, \
        f"DnsRecord.ttl must lie between 60 and 86400, got {data.get('ttl')!r}"
    assert isinstance(data["serving_enabled"], bool)


def assert_hosting_plan(data: dict):
    assert_write_once_shape(data, "HostingPlan")
    assert data["tier"] in ("STARTER", "DELUXE", "ULTIMATE")
    for field in ("storage_quota_mb", "bandwidth_quota_mb", "monthly_price_cents",
                  "included_mailboxes", "overage_rate_cents_per_gb"):
        assert isinstance(data[field], int), f"HostingPlan.{field} must be an int"
    assert isinstance(data["included_ssl"], bool)


def assert_hosting_subscription(data: dict):
    assert_audit_triple(data, "HostingSubscription")
    assert data["status"] in (
        "PROVISIONING", "ACTIVE", "OVER_QUOTA", "SUSPENDED", "CANCELLED"
    ), f"HostingSubscription.status out of range: {data['status']!r}"
    assert isinstance(data["storage_committed_mb"], int)
    assert data["storage_committed_mb"] >= 0, "storage_committed_mb must never go negative"
    assert isinstance(data["bandwidth_used_mb"], (int, float))
    assert data["bandwidth_used_mb"] >= 0


def assert_add_on(data: dict):
    assert_audit_triple(data, "AddOn")
    assert data["add_on_type"] in ("SSL_CERT", "EMAIL_MAILBOX")
    assert data["status"] in (
        "PENDING_VALIDATION", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED", "CANCELLED"
    ), f"AddOn.status out of range: {data['status']!r}"
    assert isinstance(data["term_days"], int) and 1 <= data["term_days"] <= 730
    assert is_iso8601_timestamp(data["starts_at"]), "AddOn.starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data["ends_at"]), "AddOn.ends_at must be ISO 8601"
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0


def assert_transfer_request(data: dict):
    assert_audit_triple(data, "TransferRequest")
    assert data["direction"] in ("IN", "OUT")
    assert data["status"] in (
        "INITIATED", "PENDING_ACK", "REJECTED", "COMPLETED", "FAILED"
    ), f"TransferRequest.status out of range: {data['status']!r}"
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_invoice(data: dict):
    assert_audit_triple(data, "Invoice")
    assert data["status"] in ("ISSUED", "PAID", "PARTIALLY_REFUNDED", "REFUNDED"), \
        f"Invoice.status out of range: {data['status']!r}"
    for field in ("subtotal_cents", "discount_cents", "service_fee_cents",
                  "tax_cents", "total_cents", "amount_paid_cents",
                  "amount_refunded_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"
    assert_invoice_money_invariants(data)


def assert_invoice_line_item(data: dict):
    assert_write_once_shape(data, "InvoiceLineItem")
    assert data["item_type"] in (
        "DOMAIN_REGISTRATION", "DOMAIN_RENEWAL", "REDEMPTION_FEE", "PRIVACY_FEE",
        "HOSTING_PLAN", "SSL_CERT", "EMAIL_MAILBOX", "BANDWIDTH_OVERAGE",
    ), f"InvoiceLineItem.item_type out of range: {data['item_type']!r}"
    for field in ("quantity", "unit_price_cents", "line_subtotal_cents",
                  "line_discount_cents", "line_tax_cents", "line_total_cents"):
        assert isinstance(data[field], int), f"InvoiceLineItem.{field} must be an int"
    assert_line_item_money_invariants(data)


def assert_ledger_entry(data: dict):
    assert_write_once_shape(data, "LedgerEntry")
    assert data["entry_type"] in ("PAYMENT", "REFUND", "CREDIT_GRANT", "CREDIT_APPLIED")
    assert isinstance(data["amount_cents"], int)
    assert data["reference_type"] in ("INVOICE", "ADJUSTMENT")
    assert isinstance(data["balance_after_cents"], int)
    # PRD §2.7 sign convention.
    if data["entry_type"] in ("PAYMENT", "CREDIT_GRANT"):
        assert data["amount_cents"] > 0, \
            f"{data['entry_type']} must be positive, got {data['amount_cents']}"
    else:
        assert data["amount_cents"] < 0, \
            f"{data['entry_type']} must be negative, got {data['amount_cents']}"


def assert_billing_period(data: dict):
    assert_audit_triple(data, "BillingPeriod")
    assert data["status"] in ("OPEN", "CLOSED")
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["provisional_overage_cents"], int)
    if data["status"] == "OPEN":
        assert data["final_overage_cents"] is None, \
            "final_overage_cents is null for as long as the period stays OPEN"
    else:
        assert isinstance(data["final_overage_cents"], int)


def assert_usage_record(data: dict):
    assert_write_once_shape(data, "UsageRecord")
    assert data["metric"] == "BANDWIDTH_MB"
    assert isinstance(data["amount_mb"], (int, float)) and data["amount_mb"] >= 0
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_abuse_report(data: dict):
    assert_audit_triple(data, "AbuseReport")
    assert data["category"] in ("PHISHING", "MALWARE", "SPAM", "COPYRIGHT")
    assert data["severity"] in ("LOW", "HIGH", "CRITICAL")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "UPHELD", "DISMISSED"), \
        f"AbuseReport.status out of range: {data['status']!r}"


def assert_promo_code(data: dict):
    assert_write_once_shape(data, "PromoCode")
    assert data["discount_type"] in ("PERCENT", "FLAT")
    assert isinstance(data["applies_to_item_types"], list)
    assert len(data["applies_to_item_types"]) > 0


# ─── Domain invariant checkers ─────────────────────────────────────────────

def assert_invoice_money_invariants(invoice: dict):
    """PRD §3.8: total = subtotal - discount + service_fee + tax."""
    expected = (
        invoice["subtotal_cents"]
        - invoice["discount_cents"]
        + invoice["service_fee_cents"]
        + invoice["tax_cents"]
    )
    assert invoice["total_cents"] == expected, (
        f"Invoice total_cents must be subtotal - discount + service_fee + tax "
        f"({expected}), got {invoice['total_cents']}"
    )
    assert invoice["amount_refunded_cents"] <= invoice["amount_paid_cents"], (
        "amount_refunded_cents may never exceed amount_paid_cents"
    )


def assert_line_item_money_invariants(line: dict):
    """PRD §3.8: line_total = line_subtotal - line_discount + line_tax, and
    line_subtotal is the exact integer product of quantity and unit price."""
    assert line["line_subtotal_cents"] == line["quantity"] * line["unit_price_cents"], (
        f"line_subtotal_cents must be quantity * unit_price_cents exactly, got "
        f"{line['line_subtotal_cents']} for {line['quantity']} x {line['unit_price_cents']}"
    )
    expected_total = (
        line["line_subtotal_cents"] - line["line_discount_cents"] + line["line_tax_cents"]
    )
    assert line["line_total_cents"] == expected_total, (
        f"line_total_cents must be subtotal - discount + tax ({expected_total}), "
        f"got {line['line_total_cents']}"
    )


def line_of_type(lines: list, item_type: str) -> dict:
    """Return the single line item of the given item_type."""
    matches = [line for line in lines if line["item_type"] == item_type]
    assert len(matches) == 1, (
        f"Expected exactly one {item_type} line, found {len(matches)} in "
        f"{[line['item_type'] for line in lines]}"
    )
    return matches[0]


def lines_of_type(lines: list, item_type: str) -> list:
    return [line for line in lines if line["item_type"] == item_type]


def entries_of_type(entries: list, entry_type: str) -> list:
    return [entry for entry in entries if entry["entry_type"] == entry_type]
