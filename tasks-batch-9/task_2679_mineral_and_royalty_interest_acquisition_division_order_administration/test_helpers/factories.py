"""Payload factories.

Each factory returns a valid request body built from the canonical fixture
literals; keyword overrides replace individual fields, and passing None for an
optional field removes it from the payload so defaults can be exercised.
"""

from typing import Any, Dict

_SENTINEL = object()


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if value is _SENTINEL:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


OMIT = _SENTINEL


# ------------------------------------------------------------------- tracts
def tract_payload(**overrides) -> dict:
    return _apply(
        {
            "county": "Reeves",
            "state_code": "TX",
            "gross_acres": 640.0000,
            "operator_activity_tier": "HIGH",
        },
        overrides,
    )


def patent_entry_payload(**overrides) -> dict:
    return _apply(
        {
            "instrument_type": "PATENT",
            "instrument_date": "1902-05-01",
            "conveyed_fraction": 1.0,
            "county_book_page": "100/1",
            "grantor_name": "United States",
            "grantee_name": "A Patentee",
        },
        overrides,
    )


def deed_entry_payload(**overrides) -> dict:
    return _apply(
        {
            "instrument_type": "DEED",
            "instrument_date": "1955-03-12",
            "conveyed_acres": 480.0000,
            "county_book_page": "220/45",
            "grantor_name": "A Patentee",
            "grantee_name": "B Grantee",
        },
        overrides,
    )


def probate_entry_payload(**overrides) -> dict:
    return _apply(
        {
            "instrument_type": "PROBATE",
            "instrument_date": "1988-07-20",
            "conveyed_fraction": 0.5,
            "county_book_page": "500/12",
            "grantor_name": "A Patentee Estate",
            "grantee_name": "C Heir",
        },
        overrides,
    )


def assignment_entry_payload(**overrides) -> dict:
    return _apply(
        {
            "instrument_type": "ASSIGNMENT",
            "instrument_date": "2011-01-05",
            "conveyed_fraction": 0.0625,
            "county_book_page": "780/301",
            "grantor_name": "C Heir",
            "grantee_name": "ORRI Holder",
        },
        overrides,
    )


# ----------------------------------------------------------- royalty owners
def royalty_owner_payload(**overrides) -> dict:
    return _apply(
        {
            "legal_name": "C Heir",
            "state_code": "TX",
            "mailing_address": "1 Pecos Rd, Pecos TX",
            "tax_id_on_file": True,
        },
        overrides,
    )


# -------------------------------------------------------- mineral interests
def mineral_interest_payload(tract_id: str, owner_id: str, **overrides) -> dict:
    return _apply(
        {
            "tract_id": tract_id,
            "seller_owner_id": owner_id,
            "seller_share_fraction": 0.5,
            "lease_royalty_rate": 0.1875,
            "undeveloped_net_acres": 20.0000,
        },
        overrides,
    )


def valuation_payload(**overrides) -> dict:
    return _apply(
        {
            "current_monthly_net_revenue": 1200.00,
            "annual_decline_rate": 0.18,
            "undeveloped_net_acres": 20.0000,
        },
        overrides,
    )


# ----------------------------------------------------------- offer letters
def offer_letter_payload(**overrides) -> dict:
    return _apply({"offer_amount": 48000.00, "expires_on": "2026-09-01"}, overrides)


def counter_payload(**overrides) -> dict:
    return _apply({"counter_amount": 52000.00}, overrides)


def revise_payload(**overrides) -> dict:
    return _apply({"revised_amount": 50000.00, "expires_on": "2026-09-15"}, overrides)


def reject_payload(**overrides) -> dict:
    return _apply({"rejection_reason": "Seller withdrew from the sale"}, overrides)


# --------------------------------------------------------------------- psas
def psa_payload(offer_letter_id: str, interest_version: int, **overrides) -> dict:
    return _apply(
        {
            "offer_letter_id": offer_letter_id,
            "effective_date": "2026-08-01",
            "curative_days": 45,
            "individual_defect_threshold": 2500.00,
            "aggregate_defect_basket": 16000.00,
            "expected_mineral_interest_version": interest_version,
        },
        overrides,
    )


def title_defect_payload(**overrides) -> dict:
    return _apply(
        {
            "defect_type": "MISSING_HEIR",
            "affected_nma": 10.0000,
            "description": "One unlocated heir of the 1988 estate",
        },
        overrides,
    )


def submit_cure_payload(**overrides) -> dict:
    return _apply({"cure_instrument_book_page": "900/15"}, overrides)


def cure_decision_payload(**overrides) -> dict:
    return _apply({"decision": "ACCEPTED"}, overrides)


def fund_payload(**overrides) -> dict:
    return _apply({"wire_amount": 48000.00, "wire_reference": "WIRE-1"}, overrides)


def record_deed_payload(**overrides) -> dict:
    return _apply(
        {
            "recording_county": "Reeves",
            "recorded_book_page": "915/210",
            "recording_date": "2026-08-10",
        },
        overrides,
    )


# -------------------------------------------------------------------- units
def unit_payload(**overrides) -> dict:
    return _apply(
        {
            "unit_name": "Reeves Unit 1H",
            "formation": "Wolfcamp",
            "state_code": "TX",
            "unit_gross_acres": 1280.0000,
            "royalty_rate_cap": 0.2500,
            "producing_depth_count": 2,
            "total_depth_count": 3,
        },
        overrides,
    )


def allocation_payload(unit_id: str, tract_id: str, **overrides) -> dict:
    return _apply(
        {
            "unit_id": unit_id,
            "tract_id": tract_id,
            "allocated_acres": 320.0000,
            "effective_from": "2026-01-01",
            "effective_to": "2028-01-01",
            "pooling_election": "POOLED",
        },
        overrides,
    )


def terminate_allocation_payload(**overrides) -> dict:
    return _apply(
        {"termination_reason": "Tract released from the unit by amended designation"},
        overrides,
    )


# ---------------------------------------------------------- division orders
def division_order_payload(interest_id: str, unit_id: str, unit_version: int, **overrides) -> dict:
    return _apply(
        {
            "mineral_interest_id": interest_id,
            "unit_id": unit_id,
            "expected_unit_version": unit_version,
        },
        overrides,
    )


def operator_response_payload(**overrides) -> dict:
    return _apply(
        {"operator_decimal": 0.00195313, "effective_production_month": "2026-06"},
        overrides,
    )


def correct_payload(**overrides) -> dict:
    return _apply({"corrected_decimal": 0.00195313}, overrides)


def revenue_check_detail_payload(**overrides) -> dict:
    return _apply(
        {
            "production_month": "2026-06",
            "product_code": "OIL",
            "gross_volume": 1000.0000,
            "gross_value": 62000.00,
            "operator_decimal_used": 0.00180000,
        },
        overrides,
    )


def escheat_payload(**overrides) -> dict:
    return _apply({"escheat_state_code": "TX"}, overrides)


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
