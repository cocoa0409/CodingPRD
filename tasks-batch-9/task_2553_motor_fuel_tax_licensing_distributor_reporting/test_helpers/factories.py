"""Request-payload builders and unique-identifier generators."""

import itertools
from typing import Any, Dict, Optional

Json = Dict[str, Any]

_fein_seq = itertools.count(1)
_tcn_seq = itertools.count(1)
_bol_seq = itertools.count(1)
_doc_seq = itertools.count(1)
_name_seq = itertools.count(1)


def next_fein() -> str:
    """A unique `fein`: two digits, a hyphen and seven digits."""
    return "41-{:07d}".format(4000000 + next(_fein_seq))


def next_terminal_control_number() -> str:
    """A unique control number: `T`, two digits, two uppercase letters, four digits."""
    n = next(_tcn_seq)
    return "T{:02d}MN{:04d}".format(n % 100, n % 10000)


def next_bol() -> str:
    """A unique bill-of-lading number."""
    return "BOL-{:07d}".format(next(_bol_seq))


def next_document_number() -> str:
    """A unique certificate document number."""
    return "DOC-{:07d}".format(next(_doc_seq))


def next_legal_name(prefix: str = "Northland Fuel") -> str:
    return "{} {:04d} LLC".format(prefix, next(_name_seq))


def _with_optional(payload: Json, optionals: Json) -> Json:
    for key, value in optionals.items():
        if value is not None:
            payload[key] = value
    return payload


# --------------------------------------------------------------------------
# Licensing and bonding
# --------------------------------------------------------------------------


def licensee_payload(license_type: str = "DISTRIBUTOR", **overrides: Any) -> Json:
    payload: Json = {
        "legal_name": next_legal_name(),
        "fein": next_fein(),
        "license_type": license_type,
        "mailing_state": "MN",
    }
    payload.update(overrides)
    return payload


def bond_payload(
    amount_cents: int,
    expected_licensee_version: int,
    surety_name: str = "Great Lakes Surety Company",
    effective_date: str = "2026-07-01",
    **overrides: Any,
) -> Json:
    payload: Json = {
        "amount_cents": amount_cents,
        "surety_name": surety_name,
        "effective_date": effective_date,
        "expected_licensee_version": expected_licensee_version,
    }
    payload.update(overrides)
    return payload


def payment_payload(
    amount_cents: int, effective_date: str = "2026-08-01", memo: Optional[str] = None, **overrides
) -> Json:
    payload: Json = {"amount_cents": amount_cents, "effective_date": effective_date}
    _with_optional(payload, {"memo": memo})
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Terminals, certificates and rack removals
# --------------------------------------------------------------------------


def terminal_payload(
    name: str = "Twin Cities Terminal", state_code: str = "MN", **overrides: Any
) -> Json:
    payload: Json = {
        "terminal_control_number": next_terminal_control_number(),
        "name": name,
        "state_code": state_code,
    }
    payload.update(overrides)
    return payload


def certificate_payload(
    purchaser_licensee_id: str,
    exemption_type: str = "AGRICULTURE",
    valid_from: str = "2026-01-01",
    valid_to: str = "2026-12-31",
    document_number: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "purchaser_licensee_id": purchaser_licensee_id,
        "exemption_type": exemption_type,
        "document_number": document_number or next_document_number(),
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    payload.update(overrides)
    return payload


def rack_removal_payload(
    terminal_id: str,
    position_holder_licensee_id: str,
    purchaser_licensee_id: str,
    product_code: str = "UNDYED_DIESEL",
    gross_gallons: float = 8000.00,
    net_gallons: float = 7960.00,
    removal_date: str = "2026-07-15",
    destination_state: str = "MN",
    bill_of_lading_number: Optional[str] = None,
    exemption_certificate_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "terminal_id": terminal_id,
        "position_holder_licensee_id": position_holder_licensee_id,
        "purchaser_licensee_id": purchaser_licensee_id,
        "product_code": product_code,
        "gross_gallons": gross_gallons,
        "net_gallons": net_gallons,
        "removal_date": removal_date,
        "destination_state": destination_state,
        "bill_of_lading_number": bill_of_lading_number or next_bol(),
    }
    _with_optional(payload, {"exemption_certificate_id": exemption_certificate_id})
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Returns, schedules and lines
# --------------------------------------------------------------------------


def return_payload(licensee_id: str, period_month: str = "2026-07", **overrides: Any) -> Json:
    payload: Json = {"licensee_id": licensee_id, "period_month": period_month}
    payload.update(overrides)
    return payload


def schedule_payload(
    schedule_code: str, product_code: str, total_gallons: float, **overrides: Any
) -> Json:
    payload: Json = {
        "schedule_code": schedule_code,
        "product_code": product_code,
        "total_gallons": total_gallons,
    }
    payload.update(overrides)
    return payload


def line_payload(
    counterparty_licensee_id: str,
    gallons: float,
    document_date: str = "2026-07-15",
    transaction_type: str = "PURCHASE",
    bill_of_lading_number: Optional[str] = None,
    exemption_certificate_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "counterparty_licensee_id": counterparty_licensee_id,
        "transaction_type": transaction_type,
        "gallons": gallons,
        "document_date": document_date,
        "bill_of_lading_number": bill_of_lading_number or next_bol(),
    }
    _with_optional(payload, {"exemption_certificate_id": exemption_certificate_id})
    payload.update(overrides)
    return payload


def amendment_payload(
    expected_return_version: int, reason: str = "Corrected receipts schedule", **overrides: Any
) -> Json:
    payload: Json = {
        "expected_return_version": expected_return_version,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Cross-matching
# --------------------------------------------------------------------------


def cross_match_run_payload(
    period_month: str, tolerance_gallons: Optional[float] = None, **overrides: Any
) -> Json:
    payload: Json = {"period_month": period_month}
    _with_optional(payload, {"tolerance_gallons": tolerance_gallons})
    payload.update(overrides)
    return payload


def inquiry_payload(
    question: str = "Explain the unreported gallons for this cell.",
    response_due_date: str = "2026-09-30",
    **overrides: Any,
) -> Json:
    payload: Json = {"question": question, "response_due_date": response_due_date}
    payload.update(overrides)
    return payload


def response_payload(
    explanation: str = "The load was received in the following period.",
    referenced_return_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {"explanation": explanation}
    _with_optional(payload, {"referenced_return_id": referenced_return_id})
    payload.update(overrides)
    return payload


def resolve_payload(
    resolution: str, write_off_reason: Optional[str] = None, **overrides: Any
) -> Json:
    payload: Json = {"resolution": resolution}
    _with_optional(payload, {"write_off_reason": write_off_reason})
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Refund claims
# --------------------------------------------------------------------------


def refund_claim_payload(
    licensee_id: str,
    period_month: str,
    claimed_gallons: float,
    claim_type: str = "OFF_ROAD",
    equipment_class: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "licensee_id": licensee_id,
        "claim_type": claim_type,
        "period_month": period_month,
        "claimed_gallons": claimed_gallons,
    }
    _with_optional(payload, {"equipment_class": equipment_class})
    payload.update(overrides)
    return payload


def review_payload(
    recommendation: str, recommended_gallons: Optional[float] = None, **overrides: Any
) -> Json:
    payload: Json = {"recommendation": recommendation}
    _with_optional(payload, {"recommended_gallons": recommended_gallons})
    payload.update(overrides)
    return payload


def decide_payload(decision: str, **overrides: Any) -> Json:
    payload: Json = {"decision": decision}
    payload.update(overrides)
    return payload


def pay_payload(payment_reference: str = "WARRANT-000123", **overrides: Any) -> Json:
    payload: Json = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Roadside enforcement and audits
# --------------------------------------------------------------------------


def inspection_payload(
    inspected_licensee_id: str,
    dye_test_result: str = "POSITIVE",
    gallons_in_tank: float = 150.00,
    inspection_date: str = "2026-07-20",
    vehicle_identifier: str = "MN-PLATE-4417",
    location_description: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "inspected_licensee_id": inspected_licensee_id,
        "inspection_date": inspection_date,
        "dye_test_result": dye_test_result,
        "gallons_in_tank": gallons_in_tank,
        "vehicle_identifier": vehicle_identifier,
    }
    _with_optional(payload, {"location_description": location_description})
    payload.update(overrides)
    return payload


def audit_case_payload(
    subject_licensee_id: str,
    period_start_month: str,
    period_end_month: str,
    selection_method: str = "ROADSIDE_REFERRAL",
    risk_score_variant: Optional[str] = None,
    source_discrepancy_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "subject_licensee_id": subject_licensee_id,
        "selection_method": selection_method,
        "period_start_month": period_start_month,
        "period_end_month": period_end_month,
    }
    _with_optional(
        payload,
        {
            "risk_score_variant": risk_score_variant,
            "source_discrepancy_id": source_discrepancy_id,
        },
    )
    payload.update(overrides)
    return payload


def assessment_payload(
    additional_tax_cents: int, evasion_indicator: bool = False, **overrides: Any
) -> Json:
    payload: Json = {
        "additional_tax_cents": additional_tax_cents,
        "evasion_indicator": evasion_indicator,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "next_fein",
    "next_terminal_control_number",
    "next_bol",
    "next_document_number",
    "next_legal_name",
    "licensee_payload",
    "bond_payload",
    "payment_payload",
    "terminal_payload",
    "certificate_payload",
    "rack_removal_payload",
    "return_payload",
    "schedule_payload",
    "line_payload",
    "amendment_payload",
    "cross_match_run_payload",
    "inquiry_payload",
    "response_payload",
    "resolve_payload",
    "refund_claim_payload",
    "review_payload",
    "decide_payload",
    "pay_payload",
    "inspection_payload",
    "audit_case_payload",
    "assessment_payload",
]
