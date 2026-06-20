"""Existence lookups (left-to-right path/FK validation, PRD §2.7)."""
import errors
from db import STORE


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


def policyholder_or_404(rid):
    return get_or_404(STORE.policyholders, rid)


def policy_or_404(rid):
    return get_or_404(STORE.policies, rid)


def provider_or_404(rid):
    return get_or_404(STORE.providers, rid)


def care_plan_or_404(rid):
    return get_or_404(STORE.care_plans, rid)


def claim_or_404(rid):
    return get_or_404(STORE.claims, rid)


def premium_invoice_or_404(rid):
    return get_or_404(STORE.premium_invoices, rid)


def rate_filing_or_404(rid):
    return get_or_404(STORE.rate_filings, rid)


def trigger_cert_or_404(rid):
    return get_or_404(STORE.trigger_certifications, rid)


def ledger_entry_or_404(rid):
    return get_or_404(STORE.ledger_entries, rid)


def sorted_by_created(records):
    """Default list order: created_at ASC (use _seq for a stable tiebreak)."""
    return sorted(records, key=lambda r: r["_seq"])
