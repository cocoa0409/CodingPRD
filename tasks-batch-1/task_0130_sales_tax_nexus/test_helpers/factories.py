"""Payload factories — one per entity, input fields only.

Only fields the PRD marks as client-supplied input appear here; computed and
system fields (combined_rate, tax_collected, status, version, ...) are never sent.
"""
from .constants import CA_JURISDICTION


def create_tax_jurisdiction_payload(**overrides) -> dict:
    """POST /tax-jurisdictions. Defaults to the canonical CA jurisdiction."""
    defaults = dict(CA_JURISDICTION)
    defaults.update(overrides)
    return defaults


def create_product_category_payload(jurisdiction_id: str, category_code: str = "TANGIBLE",
                                    taxability: str = "FULL", **overrides) -> dict:
    """POST /product-categories."""
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "category_code": category_code,
        "taxability": taxability,
    }
    defaults.update(overrides)
    return defaults


def create_seller_payload(legal_name: str = "Test Seller",
                          origin_state_code: str = "CA", **overrides) -> dict:
    """POST /sellers."""
    defaults = {
        "legal_name": legal_name,
        "origin_state_code": origin_state_code,
    }
    defaults.update(overrides)
    return defaults


def create_marketplace_facilitator_payload(name: str = "Test Marketplace",
                                           collecting_state_codes=None, **overrides) -> dict:
    """POST /marketplace-facilitators."""
    defaults = {
        "name": name,
        "collecting_state_codes": collecting_state_codes if collecting_state_codes is not None else ["CA"],
    }
    defaults.update(overrides)
    return defaults


def create_nexus_profile_payload(seller_id: str, jurisdiction_id: str, **overrides) -> dict:
    """POST /nexus-profiles."""
    defaults = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
    }
    defaults.update(overrides)
    return defaults


def create_exemption_certificate_payload(seller_id: str, jurisdiction_id: str,
                                         customer_ref: str = "b1",
                                         exempt_category_code: str = "TANGIBLE",
                                         valid_from: str = "2026-01-01T00:00:00Z",
                                         valid_to: str = "2027-01-01T00:00:00Z",
                                         **overrides) -> dict:
    """POST /exemption-certificates."""
    defaults = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "customer_ref": customer_ref,
        "exempt_category_code": exempt_category_code,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(seller_id: str, jurisdiction_id: str,
                               customer_ref: str = "b1", **overrides) -> dict:
    """POST /transactions. facilitator_id and customer_exempt_requested are optional."""
    defaults = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "customer_ref": customer_ref,
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(transaction_id: str, category_code: str = "TANGIBLE",
                             quantity: int = 1, unit_price: float = 10.00, **overrides) -> dict:
    """POST /line-items."""
    defaults = {
        "transaction_id": transaction_id,
        "category_code": category_code,
        "quantity": quantity,
        "unit_price": unit_price,
    }
    defaults.update(overrides)
    return defaults


def create_use_tax_accrual_payload(seller_id: str, jurisdiction_id: str,
                                   purchase_amount: float = 1200.00, **overrides) -> dict:
    """POST /use-tax-accruals."""
    defaults = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "purchase_amount": purchase_amount,
    }
    defaults.update(overrides)
    return defaults


def create_tax_return_payload(seller_id: str, jurisdiction_id: str,
                              period_start: str = "2026-02-01T00:00:00Z",
                              period_end: str = "2026-03-01T00:00:00Z", **overrides) -> dict:
    """POST /tax-returns."""
    defaults = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payment_payload(tax_return_id: str, amount: float,
                                      expected_tax_return_version: int, **overrides) -> dict:
    """POST /remittance-payments."""
    defaults = {
        "tax_return_id": tax_return_id,
        "amount": amount,
        "expected_tax_return_version": expected_tax_return_version,
    }
    defaults.update(overrides)
    return defaults
