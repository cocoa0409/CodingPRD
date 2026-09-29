"""Payload factories: one per write endpoint body the PRD declares.

Each factory returns a fresh dict of the PRD-required fields with sane values and
lets the caller override any of them with keyword arguments.  Optional fields are
left out unless supplied, so a factory call also documents which fields the PRD
treats as optional.
"""
from typing import Any, Dict

from .constants import (
    CLOCK_PROGRAMME_START,
    GUIDE_EFFECTIVE_FROM,
    REQ_SHP_04,
)

_COUNTER = {"n": 0}


def _next() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def clock_payload(to_iso8601: str = CLOCK_PROGRAMME_START) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def vendor_payload(**overrides) -> Dict[str, Any]:
    payload = {
        # A supplier code is drawn from uppercase letters and digits only.
        "vendor_code": f"V{9000 + _next()}",
        "legal_name": "Northwind Supply Company",
        "payment_terms_days": 60,
    }
    payload.update(overrides)
    return payload


def routing_guide_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "guide_code": f"RG-2026-{_next()}",
        "title": "Domestic Routing Guide 2026-A",
        "scope_code": "ALL",
        "effective_from": GUIDE_EFFECTIVE_FROM,
    }
    payload.update(overrides)
    return payload


def requirement_payload(**overrides) -> Dict[str, Any]:
    payload = dict(REQ_SHP_04)
    payload.update(overrides)
    return payload


def purchase_order_payload(vendor_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "vendor_id": vendor_id,
        "po_number": f"PO-{_next()}",
        "ordered_units": 1000,
        "unit_cost_cents": 500,
        "ship_window_start": "2026-08-06T00:00:00Z",
        "ship_window_end": "2026-08-09T00:00:00Z",
        "must_arrive_by": "2026-08-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def shipment_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "asn_number": f"ASN-{_next()}",
        "shipped_units": 1000,
        "carton_count": 40,
    }
    payload.update(overrides)
    return payload


def receipt_payload(received_units: int = 1000, **overrides) -> Dict[str, Any]:
    payload = {"received_units": received_units}
    payload.update(overrides)
    return payload


def violation_payload(requirement_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "requirement_id": requirement_id,
        "affected_units": 400,
        "affected_cartons": 16,
        "narrative": "ASN transmitted after trailer arrival.",
    }
    payload.update(overrides)
    return payload


def evidence_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "kind": "DOCUMENT",
        "reference_uri": f"s3://evidence/item-{_next()}.pdf",
    }
    payload.update(overrides)
    return payload


def assess_payload(**overrides) -> Dict[str, Any]:
    payload = {"assessment_note": "Late ASN."}
    payload.update(overrides)
    return payload


def void_payload(**overrides) -> Dict[str, Any]:
    payload = {"void_reason": "Detection was in error; overlabels were present."}
    payload.update(overrides)
    return payload


def dispute_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "reason_code": "CARRIER_CAUSED",
        "claimed_reversal_cents": 200_000,
        "narrative": "Carrier detained the trailer at the yard.",
    }
    payload.update(overrides)
    return payload


def request_info_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "information_request_note": "Supply the carrier's signed detention log.",
    }
    payload.update(overrides)
    return payload


def resubmit_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "claimed_reversal_cents": 220_000,
        "narrative": "Detention log attached; the carrier accepts responsibility.",
    }
    payload.update(overrides)
    return payload


def dispute_decision_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload = {
        "decision": decision,
        "review_note": "Reviewed against the routing guide and the evidence set.",
    }
    payload.update(overrides)
    return payload


def scorecard_payload(vendor_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "vendor_id": vendor_id,
        "period_code": "2026-M08",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-31T23:59:59Z",
    }
    payload.update(overrides)
    return payload


def measure_payload(measurement_variant: str = "ORDER_WEIGHTED", **overrides):
    payload = {"measurement_variant": measurement_variant}
    payload.update(overrides)
    return payload


def cap_submit_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "milestone_text": "Install an ASN gateway with automated pre-arrival transmission.",
        "committed_completion_at": "2026-09-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def cap_decision_payload(decision: str = "ACCEPT", **overrides) -> Dict[str, Any]:
    payload = {
        "decision": decision,
        "review_note": "Milestone reviewed against the programme's remediation bar.",
    }
    payload.update(overrides)
    return payload


def cap_escalation_payload(
    buying_decision: str = "SOURCING_HOLD", **overrides
) -> Dict[str, Any]:
    payload = {
        "buying_decision": buying_decision,
        "escalation_note": "Category buyer escalates the unremediated plan.",
    }
    payload.update(overrides)
    return payload


def cap_close_payload(outcome: str = "SUCCESS", **overrides) -> Dict[str, Any]:
    payload = {
        "outcome": outcome,
        "closure_note": "Remediation verified at the distribution centre.",
    }
    payload.update(overrides)
    return payload


def deduction_payload(
    vendor_id: str, expected_vendor_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "vendor_id": vendor_id,
        "invoice_reference": f"INV-{_next()}",
        "expected_vendor_version": expected_vendor_version,
    }
    payload.update(overrides)
    return payload


def allocation_payload(chargeback_id: str, allocated_cents: int, **overrides):
    payload = {
        "chargeback_id": chargeback_id,
        "allocated_cents": allocated_cents,
    }
    payload.update(overrides)
    return payload


def reversal_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "reversal_reason": "AP applied the netting to the wrong remittance advice.",
    }
    payload.update(overrides)
    return payload


def cash_application_payload(
    amount_cents: int, expected_chargeback_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "remittance_reference": f"RA-{_next()}",
        "amount_cents": amount_cents,
        "expected_chargeback_version": expected_chargeback_version,
    }
    payload.update(overrides)
    return payload
