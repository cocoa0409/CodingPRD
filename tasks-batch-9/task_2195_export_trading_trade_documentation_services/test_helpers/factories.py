"""Payload factories. Each carries only the input fields of its entity."""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

Json = Dict[str, Any]

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so uniqueness-constrained references never collide."""
    return f"{next(_counter):04d}"


def buyer_payload(**overrides: Any) -> Json:
    payload: Json = {
        "legal_name": "Hanwha Trading Co",
        "country_code": "KR",
        "credit_rating": "BBB",
        "sanctions_tier": "NONE",
        "restricted_party_flag": False,
    }
    payload.update(overrides)
    return payload


def order_payload(buyer_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "buyer_id": buyer_id,
        "incoterm": "FOB",
        "incoterm_named_place": "FOB Busan",
        "origin_country_code": "US",
        "destination_country_code": "KR",
        "destination_zone": "ZONE_2",
        "invoice_currency": "USD",
        "fx_rate_usd_to_invoice": 1.000000,
        "ship_by_date": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def shipment_line_payload(**overrides: Any) -> Json:
    payload: Json = {
        "line_no": 1,
        "goods_description": "Industrial valve assembly",
        "hs_code": "848180",
        "quantity": 100.000,
        "uom": "EA",
        "unit_price_usd": 250.0000,
        "line_discount_pct": 0.00,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 20,
    }
    payload.update(overrides)
    return payload


def credit_payload(order_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "export_order_id": order_id,
        "lc_number": f"LC-2026-{unique_suffix()}",
        "issuing_bank_swift": "HVBKKRSE",
        "amount_usd": 25000.00,
        "tolerance_pct": 10.00,
        "availability": "SIGHT",
        "usance_days": 0,
        "expiry_date": "2026-11-30T00:00:00Z",
        "latest_shipment_date": "2026-09-15T00:00:00Z",
        "presentation_period_days": 21,
        "partial_shipment_allowed": False,
        "transshipment_allowed": False,
        "required_document_types": ["COMMERCIAL_INVOICE"],
    }
    payload.update(overrides)
    return payload


def terms_finding_payload(**overrides: Any) -> Json:
    payload: Json = {
        "code": "DESCRIPTION_MISMATCH",
        "severity": "MINOR",
        "clause_ref": "DOCUMENTS",
        "detail": "goods description abbreviated against the credit wording",
    }
    payload.update(overrides)
    return payload


def examination_finding(**overrides: Any) -> Json:
    """One element of the ``findings`` collection on the examine endpoint."""
    payload: Json = {
        "code": "DESCRIPTION_MISMATCH",
        "severity": "CRITICAL",
        "clause_ref": "DOCUMENTS",
        "detail": "goods description on the invoice differs from the credit",
    }
    payload.update(overrides)
    return payload


def screening_decision_payload(**overrides: Any) -> Json:
    payload: Json = {
        "license_determination": "NLR",
        "eccn": "3A001",
        "denied_party_hits": 0,
    }
    payload.update(overrides)
    return payload


def license_payload(**overrides: Any) -> Json:
    payload: Json = {
        "license_number": f"BIS-2026-{unique_suffix()}",
        "authority": "BIS",
        "eccn": "3A001",
        "valid_from": "2026-07-01T00:00:00Z",
        "valid_to": "2026-12-31T00:00:00Z",
        "licensed_value_usd": 50000.00,
    }
    payload.update(overrides)
    return payload


def sailing_payload(**overrides: Any) -> Json:
    payload: Json = {
        "carrier_scac": "HLCU",
        "vessel_name": "MV Pacific Dawn",
        "voyage_no": f"V26{unique_suffix()}",
        "port_of_loading": "USLGB",
        "port_of_discharge": "KRPUS",
        "destination_zone": "ZONE_2",
        "cutoff_at": "2026-09-01T00:00:00Z",
        "etd": "2026-09-03T00:00:00Z",
        "eta": "2026-09-20T00:00:00Z",
        "capacity_weight_kg": 20000.000,
        "tariff_rate_per_1000kg_usd": 300.00,
    }
    payload.update(overrides)
    return payload


def booking_payload(
    order_id: str, sailing_id: str, sailing_version: int, **overrides: Any
) -> Json:
    payload: Json = {
        "export_order_id": order_id,
        "vessel_sailing_id": sailing_id,
        "booked_weight_kg": 1200.000,
        "container_type": "LCL",
        "expected_vessel_sailing_version": sailing_version,
    }
    payload.update(overrides)
    return payload


def bill_of_lading_payload(
    shipped_lines: List[Json], on_board_date: str = "2026-08-01T00:00:00Z", **overrides: Any
) -> Json:
    payload: Json = {
        "on_board_date": on_board_date,
        "shipped_lines": shipped_lines,
    }
    payload.update(overrides)
    return payload


def shipped_line(line_id: str, shipped_quantity: float) -> Json:
    return {"shipment_line_id": line_id, "shipped_quantity": shipped_quantity}


def presentation_payload(
    lc_id: str, order_id: str, document_ids: List[str], order_version: int, **overrides: Any
) -> Json:
    payload: Json = {
        "letter_of_credit_id": lc_id,
        "export_order_id": order_id,
        "trade_document_ids": document_ids,
        "expected_export_order_version": order_version,
    }
    payload.update(overrides)
    return payload


def policy_payload(buyer_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "buyer_id": buyer_id,
        "policy_number": f"POL-2026-{unique_suffix()}",
        "credit_limit_usd": 250000.00,
        "insured_pct": 90.00,
        "deductible_usd": 5000.00,
        "effective_from": "2026-07-01T00:00:00Z",
        "effective_to": "2027-06-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def dispute_payload(order_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "export_order_id": order_id,
        "dispute_type": "QUALITY",
        "claimed_amount_usd": 5000.00,
    }
    payload.update(overrides)
    return payload


def document_payload(order_id: str, doc_type: str = "COMMERCIAL_INVOICE") -> Json:
    return {"export_order_id": order_id, "doc_type": doc_type}


def settlement_payload(
    received_amount_usd: float, value_date: str = "2026-08-01T00:00:00Z"
) -> Json:
    return {"received_amount_usd": received_amount_usd, "value_date": value_date}


def claim_payload(dispute_id: str, policy_version: int) -> Json:
    return {
        "dispute_case_id": dispute_id,
        "expected_credit_insurance_policy_version": policy_version,
    }


def pagination(limit: Optional[int] = None, offset: Optional[int] = None) -> Json:
    params: Json = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return params
