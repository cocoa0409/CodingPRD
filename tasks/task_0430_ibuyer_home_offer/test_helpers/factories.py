"""Payload factories — one per entity, input fields only.

Only fields with source: input are included; computed and system fields
(avm_value, status, version, snapshots, etc.) are server-minted.
"""

DEFAULTS = {
    "SELLER_EMAIL": "seller@example.com",
    "SELLER_NAME": "Test Seller",
    "PROPERTY_ZIP": "90001",
    "PROPERTY_ADDRESS": "1 Test Lane",
    "BEDROOMS": 3,
    "LIVING_AREA_SQFT": 1800,
    "COMP_MEDIAN_VALUE": 500000,
    "MARKET_TREND_PCT": 0.02,
    "SERVICE_FEE_PCT": 0.05,
    "LIST_PRICE": 560000,
    "RESALE_COMMISSION_PCT": 0.03,
}


def create_seller_payload(**overrides) -> dict:
    """Seller input fields: email (required, unique), full_name (required),
    payout_method (optional, defaults to ACH)."""
    payload = {
        "email": DEFAULTS["SELLER_EMAIL"],
        "full_name": DEFAULTS["SELLER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(seller_id, **overrides) -> dict:
    """Property input fields. market_trend_pct is optional (defaults to 0.0)."""
    payload = {
        "seller_id": seller_id,
        "address_line": DEFAULTS["PROPERTY_ADDRESS"],
        "zip_code": DEFAULTS["PROPERTY_ZIP"],
        "bedrooms": DEFAULTS["BEDROOMS"],
        "living_area_sqft": DEFAULTS["LIVING_AREA_SQFT"],
        "comp_median_value": DEFAULTS["COMP_MEDIAN_VALUE"],
        "market_trend_pct": DEFAULTS["MARKET_TREND_PCT"],
    }
    payload.update(overrides)
    return payload


def issue_offer_payload(**overrides) -> dict:
    """Offer issuance input fields. service_fee_pct optional (defaults to 0.05);
    expected_property_version only required on re-issue."""
    payload = {"service_fee_pct": DEFAULTS["SERVICE_FEE_PCT"]}
    payload.update(overrides)
    return payload


def create_repair_line_item_payload(category, estimate_amount, **overrides) -> dict:
    """RepairLineItem input fields: category (enum), estimate_amount (>= 0)."""
    payload = {"category": category, "estimate_amount": estimate_amount}
    payload.update(overrides)
    return payload


def finalize_assessment_payload(
    roof_condition="GOOD",
    hvac_condition="GOOD",
    foundation_condition="GOOD",
    **overrides,
) -> dict:
    """Assessment finalize input fields: three component conditions (required),
    questionnaire_flags optional (defaults to [])."""
    payload = {
        "roof_condition": roof_condition,
        "hvac_condition": hvac_condition,
        "foundation_condition": foundation_condition,
    }
    payload.update(overrides)
    return payload


def schedule_close_payload(close_date, **overrides) -> dict:
    """schedule-close input fields: close_date (required), leaseback_days (optional,
    defaults 0), final_concession (optional, defaults 0.0)."""
    payload = {"close_date": close_date}
    payload.update(overrides)
    return payload


def retrade_payload(retrade_amount, **overrides) -> dict:
    """retrade input fields: retrade_amount (required), retrade_reason (optional)."""
    payload = {"retrade_amount": retrade_amount}
    payload.update(overrides)
    return payload


def create_resale_payload(transaction_id, list_price, **overrides) -> dict:
    """Resale input fields: transaction_id (required), list_price (>= 0),
    resale_commission_pct (optional, defaults 0.03)."""
    payload = {"transaction_id": transaction_id, "list_price": list_price}
    payload.update(overrides)
    return payload
