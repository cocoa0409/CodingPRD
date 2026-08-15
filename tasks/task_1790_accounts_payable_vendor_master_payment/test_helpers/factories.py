"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def unique_tax_id() -> str:
    return f"99-{next(_counter):07d}"


def unique_invoice_number() -> str:
    return f"INV-{next(_counter):06d}"


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Fixture Vendor",
        "tax_id": unique_tax_id(),
        "remit_email": "ap@fixture-vendor.example",
        "phone": "+1-555-3000",
        "address_line1": "100 Fixture Ave",
        "city": "Springfield",
        "country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_bank_account_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "account_number": f"000{n:09d}",
        "routing_number": "021000021",
        "account_holder_name": "Fixture Vendor",
        "is_primary": True,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "W9",
        "valid_from": "2026-01-01",
        "valid_until": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_watchlist_entry_payload(**overrides) -> dict:
    defaults = {
        "name_pattern": "Fixture Watch Name",
        "severity": "REVIEW",
        "list_source": "OFAC_SDN",
    }
    defaults.update(overrides)
    return defaults


def create_matrix_rule_payload(**overrides) -> dict:
    defaults = {
        "cost_center": "GLOBAL",
        "min_amount_cents": 0,
        "max_amount_cents": 500000,
        "tier": 1,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "vendor_id": None,
        "invoice_number": unique_invoice_number(),
        "amount_cents": 100000,
        "cost_center": "CC-100",
    }
    defaults.update(overrides)
    return defaults


def create_payment_run_payload(**overrides) -> dict:
    defaults = {
        "scheduled_date": "2026-08-05",
        "payment_method": "CHECK",
    }
    defaults.update(overrides)
    return defaults
