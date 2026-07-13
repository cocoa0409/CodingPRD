"""Resource representations."""

import config
import db
from services import money


def account_out(account):
    return {
        "id": account["id"],
        "email": account["email"],
        "company_name": account["company_name"],
        "status": account["status"],
        "payment_method_token": account["payment_method_token"],
        "payment_method_on_file": account["payment_method_token"] is not None,
        "auto_renew_default": account["auto_renew_default"],
        "credit_balance_cents": money.credit_balance(account),
        "net_cash_cents": money.net_cash(account),
        "risk_score": account["risk_score"],
        "created_at": account["created_at"],
        "updated_at": account["updated_at"],
        "version": account["version"],
    }


def domain_out(domain, role=None, user_id=None):
    registrant_name = domain["registrant_name"]
    registrant_email = domain["registrant_email"]
    epp = domain["epp_auth_code"]

    if role == "Anonymous":
        if domain["whois_privacy_enabled"]:
            registrant_name = config.WHOIS_REDACTED_NAME
            registrant_email = config.WHOIS_REDACTED_EMAIL

    sees_epp = role in ("SupportAgent", "PlatformAdmin") or (
        role == "Registrant" and user_id == domain["account_id"]
    )
    if not sees_epp:
        epp = None

    return {
        "id": domain["id"],
        "account_id": domain["account_id"],
        "domain_name": domain["domain_name"],
        "tld": domain["tld"],
        "fqdn": domain["fqdn"],
        "is_premium": domain["is_premium"],
        "lifecycle_status": domain["lifecycle_status"],
        "lock_status": domain["lock_status"],
        "suspension_reason": domain["suspension_reason"],
        "whois_privacy_enabled": domain["whois_privacy_enabled"],
        "auto_renew_enabled": domain["auto_renew_enabled"],
        "registrant_name": registrant_name,
        "registrant_email": registrant_email,
        "term_years": domain["term_years"],
        "registered_at": db.fmt_dt(domain["_registered_at"]),
        "expires_at": db.fmt_dt(domain["_expires_at"]),
        "epp_auth_code": epp,
        "created_at": domain["created_at"],
        "updated_at": domain["updated_at"],
        "version": domain["version"],
    }


def dns_record_out(record):
    domain = db.domains.get(record["domain_id"])
    serving = True
    if domain is not None:
        serving = domain["lifecycle_status"] not in config.SERVING_DOWN_STATES
    return {
        "id": record["id"],
        "domain_id": record["domain_id"],
        "record_type": record["record_type"],
        "name": record["name"],
        "value": record["value"],
        "ttl": record["ttl"],
        "priority": record["priority"],
        "serving_enabled": serving,
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def plan_out(plan):
    return {
        "id": plan["id"],
        "plan_code": plan["plan_code"],
        "tier": plan["tier"],
        "storage_quota_mb": plan["storage_quota_mb"],
        "bandwidth_quota_mb": plan["bandwidth_quota_mb"],
        "monthly_price_cents": plan["monthly_price_cents"],
        "included_mailboxes": plan["included_mailboxes"],
        "included_ssl": plan["included_ssl"],
        "overage_rate_cents_per_gb": plan["overage_rate_cents_per_gb"],
        "created_at": plan["created_at"],
    }


def subscription_out(subscription):
    return {
        "id": subscription["id"],
        "account_id": subscription["account_id"],
        "plan_id": subscription["plan_id"],
        "primary_domain_id": subscription["primary_domain_id"],
        "status": subscription["status"],
        "storage_committed_mb": subscription["storage_committed_mb"],
        "bandwidth_used_mb": subscription["bandwidth_used_mb"],
        "auto_renew": subscription["auto_renew"],
        "created_at": subscription["created_at"],
        "updated_at": subscription["updated_at"],
        "version": subscription["version"],
    }


def add_on_out(add_on):
    return {
        "id": add_on["id"],
        "subscription_id": add_on["subscription_id"],
        "domain_id": add_on["domain_id"],
        "add_on_type": add_on["add_on_type"],
        "status": add_on["status"],
        "validation_token": add_on["validation_token"],
        "mailbox_address": add_on["mailbox_address"],
        "storage_mb_quota": add_on["storage_mb_quota"],
        "term_days": add_on["term_days"],
        "starts_at": db.fmt_dt(add_on["_starts_at"]),
        "ends_at": db.fmt_dt(add_on["_ends_at"]),
        "unit_price_cents": add_on["unit_price_cents"],
        "created_at": add_on["created_at"],
        "updated_at": add_on["updated_at"],
        "version": add_on["version"],
    }


def transfer_out(transfer):
    return {
        "id": transfer["id"],
        "account_id": transfer["account_id"],
        "domain_id": transfer["domain_id"],
        "direction": transfer["direction"],
        "domain_name": transfer["domain_name"],
        "tld": transfer["tld"],
        "epp_auth_code": transfer["epp_auth_code"],
        "status": transfer["status"],
        "attempt_count": transfer["attempt_count"],
        "rejection_reason": transfer["rejection_reason"],
        "created_at": transfer["created_at"],
        "updated_at": transfer["updated_at"],
        "version": transfer["version"],
    }


def invoice_out(invoice):
    return {
        "id": invoice["id"],
        "account_id": invoice["account_id"],
        "billing_period_id": invoice["billing_period_id"],
        "status": invoice["status"],
        "applied_promo_code": invoice["applied_promo_code"],
        "subtotal_cents": invoice["subtotal_cents"],
        "discount_cents": invoice["discount_cents"],
        "service_fee_cents": invoice["service_fee_cents"],
        "tax_cents": invoice["tax_cents"],
        "total_cents": invoice["total_cents"],
        "amount_paid_cents": invoice["amount_paid_cents"],
        "amount_refunded_cents": invoice["amount_refunded_cents"],
        "created_at": invoice["created_at"],
        "updated_at": invoice["updated_at"],
        "version": invoice["version"],
    }


def line_item_out(line):
    return {
        "id": line["id"],
        "invoice_id": line["invoice_id"],
        "item_type": line["item_type"],
        "reference_id": line["reference_id"],
        "description": line["description"],
        "quantity": line["quantity"],
        "unit_price_cents": line["unit_price_cents"],
        "line_subtotal_cents": line["line_subtotal_cents"],
        "line_discount_cents": line["line_discount_cents"],
        "line_tax_cents": line["line_tax_cents"],
        "line_total_cents": line["line_total_cents"],
        "created_at": line["created_at"],
    }


def ledger_out(entry):
    return {
        "id": entry["id"],
        "account_id": entry["account_id"],
        "entry_type": entry["entry_type"],
        "amount_cents": entry["amount_cents"],
        "reference_type": entry["reference_type"],
        "reference_id": entry["reference_id"],
        "reason": entry["reason"],
        "balance_after_cents": entry["balance_after_cents"],
        "created_at": entry["created_at"],
    }


def billing_period_out(period):
    return {
        "id": period["id"],
        "subscription_id": period["subscription_id"],
        "period_start": db.fmt_dt(period["_period_start"]),
        "period_end": db.fmt_dt(period["_period_end"]),
        "status": period["status"],
        "provisional_overage_cents": period["provisional_overage_cents"],
        "final_overage_cents": period["final_overage_cents"],
        "created_at": period["created_at"],
        "updated_at": period["updated_at"],
        "version": period["version"],
    }


def usage_record_out(record):
    return {
        "id": record["id"],
        "subscription_id": record["subscription_id"],
        "metric": record["metric"],
        "amount_mb": record["amount_mb"],
        "recorded_at": db.fmt_dt(record["_recorded_at"]),
        "created_at": record["created_at"],
    }


def abuse_report_out(report):
    return {
        "id": report["id"],
        "domain_id": report["domain_id"],
        "category": report["category"],
        "severity": report["severity"],
        "status": report["status"],
        "reporter_email": report["reporter_email"],
        "evidence_url": report["evidence_url"],
        "reviewer_user_id": report["reviewer_user_id"],
        "decider_user_id": report["decider_user_id"],
        "decision_note": report["decision_note"],
        "decided_at": db.fmt_dt(report["_decided_at"]),
        "created_at": report["created_at"],
        "updated_at": report["updated_at"],
        "version": report["version"],
    }


def promo_out(promo):
    return {
        "id": promo["id"],
        "code": promo["code"],
        "discount_type": promo["discount_type"],
        "discount_value": promo["discount_value"],
        "applies_to_item_types": promo["applies_to_item_types"],
        "min_subtotal_cents": promo["min_subtotal_cents"],
        "max_discount_cents": promo["max_discount_cents"],
        "created_at": promo["created_at"],
    }
