"""Payload factories — one per entity/action, input fields only."""

DEFAULTS = {
    "TAIL_NUMBER": "N1001GS",
    "MAKE": "Gulfstream",
    "MODEL": "G550",
    "YEAR": 2015,
    "TOTAL_TIME_HOURS": 2900,
    "ASKING_PRICE_USD": 12900000.00,
    "SELLER_NAME": "Apex Jet Holdings",
    "BUYER_NAME": "Dana Rios",
    "BUYER_EMAIL": "dana@rios.example",
    "QUALIFIED_BUDGET_USD": 3000000.00,
    "PROOF_OF_FUNDS_REF": "POF-8891",
    "OFFER_PRICE_USD": 2000000.00,
    "DEPOSIT_AMOUNT_USD": 100000.00,
    "FACILITY_NAME": "SkyMRO",
    "AIRPORT_CODE": "KTEB",
    "TURNAROUND_BUFFER_MINUTES": 120,
    "FUNDING_REFERENCE": "WIRE-1",
    "START_AT": "2026-09-01T10:00:00Z",
    "END_AT": "2026-09-01T14:00:00Z",
    "FINDING_DESCRIPTION": "Corrosion at MLG trunnion",
    "ESTIMATED_COST_USD": 185000.00,
    "TERMINATION_REASON": "buyer walked during inspection window",
}


def create_inspection_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "airport_code": DEFAULTS["AIRPORT_CODE"],
        "turnaround_buffer_minutes": DEFAULTS["TURNAROUND_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(**overrides) -> dict:
    defaults = {
        "tail_number": DEFAULTS["TAIL_NUMBER"],
        "make": DEFAULTS["MAKE"],
        "model": DEFAULTS["MODEL"],
        "year": DEFAULTS["YEAR"],
        "total_time_hours": DEFAULTS["TOTAL_TIME_HOURS"],
        "asking_price_usd": DEFAULTS["ASKING_PRICE_USD"],
        "seller_name": DEFAULTS["SELLER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def valuation_payload(variant="FINAL") -> dict:
    return {"variant": variant}


def create_buyer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["BUYER_NAME"],
        "email": DEFAULTS["BUYER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def qualify_buyer_payload(**overrides) -> dict:
    defaults = {
        "qualified_budget_usd": DEFAULTS["QUALIFIED_BUDGET_USD"],
        "proof_of_funds_ref": DEFAULTS["PROOF_OF_FUNDS_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_comparable_sale_payload(**overrides) -> dict:
    defaults = {
        "make": DEFAULTS["MAKE"],
        "model": DEFAULTS["MODEL"],
        "year": 2014,
        "sale_price_usd": 4123456.05,
        "sale_date": "2026-01-20",
        "total_time_hours": 3001,
    }
    defaults.update(overrides)
    return defaults


def create_loi_payload(listing_id, buyer_id, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "offer_price_usd": DEFAULTS["OFFER_PRICE_USD"],
        "deposit_amount_usd": DEFAULTS["DEPOSIT_AMOUNT_USD"],
    }
    defaults.update(overrides)
    return defaults


def counter_loi_payload(new_price_usd, expected_loi_version) -> dict:
    return {
        "new_price_usd": new_price_usd,
        "expected_loi_version": expected_loi_version,
    }


def disclosure_ack_payload(party) -> dict:
    return {"party": party}


def delivery_conditions_payload(expected_transaction_version, **overrides) -> dict:
    payload = {"expected_transaction_version": expected_transaction_version}
    payload.update(overrides)
    return payload


def terminate_transaction_payload(reason=None) -> dict:
    return {"reason": reason or DEFAULTS["TERMINATION_REASON"]}


def fund_escrow_payload(funding_reference=None) -> dict:
    return {"funding_reference": funding_reference or DEFAULTS["FUNDING_REFERENCE"]}


def create_inspection_booking_payload(transaction_id, facility_id, **overrides) -> dict:
    defaults = {
        "transaction_id": transaction_id,
        "facility_id": facility_id,
        "start_at": DEFAULTS["START_AT"],
        "end_at": DEFAULTS["END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_discrepancy_item_payload(inspection_booking_id, **overrides) -> dict:
    defaults = {
        "inspection_booking_id": inspection_booking_id,
        "description": DEFAULTS["FINDING_DESCRIPTION"],
        "severity": "NON_AIRWORTHINESS",
        "estimated_cost_usd": DEFAULTS["ESTIMATED_COST_USD"],
    }
    defaults.update(overrides)
    return defaults


def counter_discrepancy_payload(**overrides) -> dict:
    return dict(overrides)
