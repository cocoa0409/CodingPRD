"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FIRM_NAME": "Main St M&A",
    "LICENSE_NUMBER": "BRK-1",
    "SELLER_NAME": "Sam Seller",
    "SELLER_EMAIL": "s@x.com",
    "BUYER_NAME": "Bea Buyer",
    "BUYER_EMAIL": "b@x.com",
    "PROOF_OF_FUNDS": 30_000_000,
    "NET_WORTH": 150_000_000,
    "BUSINESS_NAME": "Corner Diner",
    "INDUSTRY_CODE": "722511",
    "ANNUAL_SDE": 40_000_000,
    "ANNUAL_REVENUE": 150_000_000,
    "FFE_VALUE": 20_000_000,
    "INVENTORY_VALUE": 10_000_000,
    "INDUSTRY_MULTIPLE": 3.0,
    "ASKING_PRICE": 120_000_000,
    "EXCLUSIVE_START": "2026-01-01",
    "EXCLUSIVE_END": "2026-12-31",
    "OFFER_PRICE": 115_000_000,
    "EARNEST_DEPOSIT": 5_000_000,
}


def create_broker_payload(**overrides) -> dict:
    payload = {
        "firm_name": DEFAULTS["FIRM_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    payload.update(overrides)
    return payload


def create_seller_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["SELLER_NAME"],
        "email": DEFAULTS["SELLER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_buyer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["BUYER_NAME"],
        "email": DEFAULTS["BUYER_EMAIL"],
        "proof_of_funds_cents": DEFAULTS["PROOF_OF_FUNDS"],
        "net_worth_cents": DEFAULTS["NET_WORTH"],
    }
    payload.update(overrides)
    return payload


def create_listing_payload(seller_id, **overrides) -> dict:
    payload = {
        "seller_id": seller_id,
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "industry_code": DEFAULTS["INDUSTRY_CODE"],
        "annual_sde_cents": DEFAULTS["ANNUAL_SDE"],
        "annual_revenue_cents": DEFAULTS["ANNUAL_REVENUE"],
        "ffe_value_cents": DEFAULTS["FFE_VALUE"],
        "inventory_value_cents": DEFAULTS["INVENTORY_VALUE"],
        "industry_multiple": DEFAULTS["INDUSTRY_MULTIPLE"],
        "asking_price_cents": DEFAULTS["ASKING_PRICE"],
        "exclusive_start_date": DEFAULTS["EXCLUSIVE_START"],
        "exclusive_end_date": DEFAULTS["EXCLUSIVE_END"],
    }
    payload.update(overrides)
    return payload


def create_cim_payload(valuation_method="SDE_MULTIPLE", **overrides) -> dict:
    payload = {"valuation_method": valuation_method}
    payload.update(overrides)
    return payload


def create_document_payload(**overrides) -> dict:
    payload = {"title": "P&L 2025", "doc_type": "FINANCIALS"}
    payload.update(overrides)
    return payload


def create_meeting_payload(buyer_id, start_at, end_at, **overrides) -> dict:
    payload = {"buyer_id": buyer_id, "start_at": start_at, "end_at": end_at}
    payload.update(overrides)
    return payload


def create_deal_payload(listing_id, buyer_id, **overrides) -> dict:
    payload = {"listing_id": listing_id, "buyer_id": buyer_id}
    payload.update(overrides)
    return payload


def create_loi_payload(expected_deal_version, **overrides) -> dict:
    payload = {
        "offer_price_cents": DEFAULTS["OFFER_PRICE"],
        "earnest_deposit_cents": DEFAULTS["EARNEST_DEPOSIT"],
        "earnout_amount_cents": 0,
        "earnout_periods": 1,
        "financing_contingency": True,
        "expected_deal_version": expected_deal_version,
    }
    payload.update(overrides)
    return payload


def create_loan_payload(requested_amount_cents=99_000_000, **overrides) -> dict:
    payload = {"requested_amount_cents": requested_amount_cents}
    payload.update(overrides)
    return payload


def create_escrow_payload(closing_price_cents=110_000_000, required_deposit_cents=5_000_000, **overrides) -> dict:
    payload = {
        "closing_price_cents": closing_price_cents,
        "required_deposit_cents": required_deposit_cents,
    }
    payload.update(overrides)
    return payload
