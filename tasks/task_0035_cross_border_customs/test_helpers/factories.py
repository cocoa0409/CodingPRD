"""Payload factories — one per entity, input fields only.

Each factory emits the exact field names the PRD requires for the
corresponding endpoint. Tests pass `**overrides` to mutate or inject
specific values; the factory handles the boilerplate.
"""
from __future__ import annotations
import itertools
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Counter helpers — keep generated codes/names unique within a test run.
# ---------------------------------------------------------------------------
_hs_code_counter = itertools.count(start=1)
_license_counter = itertools.count(start=1)
_agent_counter = itertools.count(start=1)
_external_order_counter = itertools.count(start=1)


def unique_hs_code() -> str:
    """Generate a unique 10-digit HS code."""
    n = next(_hs_code_counter)
    return f"{6109000000 + n:010d}"


def unique_license_number() -> str:
    return f"LIC-{next(_license_counter):08d}"


def unique_agent_code() -> str:
    return f"AGT-{next(_agent_counter):08d}"


def unique_external_order_ref() -> str:
    return f"EXT-{next(_external_order_counter):08d}"


# ---------------------------------------------------------------------------
# HsCode  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_hs_code_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "code": unique_hs_code(),
        "description": "test commodity",
        "keywords": ["widget", "test"],
        "country_code_map": {"US": "6109.10.0040", "EU": "61091000"},
        "tariff_rate_bps": 500,            # 5%
        "vat_rate_bps": 1300,              # 13%
        "consumption_tax_rate_bps": 0,
        "postal_tax_rate_bps": 1000,       # 10%
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# TariffRule  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_tariff_rule_payload(
    hs_code_id: str,
    *,
    origin_country: str = "US",
    destination_country: str = "CN",
    tariff_rate_bps: int = 500,
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: Optional[str] = "2026-12-31T23:59:59Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hs_code_id": hs_code_id,
        "origin_country": origin_country,
        "destination_country": destination_country,
        "tariff_rate_bps": tariff_rate_bps,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ExchangeRate  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_exchange_rate_payload(
    *,
    from_currency: str = "USD",
    to_currency: str = "CNY",
    rate_micros: int = 7_000_000,
    effective_date: str = "2026-01-01",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "rate_micros": rate_micros,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Importer / Declarant
# ---------------------------------------------------------------------------
def create_importer_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": "Test Importer Co., Ltd.",
        "license_number": unique_license_number(),
    }
    defaults.update(overrides)
    return defaults


def create_declarant_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": "Test Declarant Agency",
        "agent_code": unique_agent_code(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Order  (PRD §3.3)
# ---------------------------------------------------------------------------
def make_line_item(
    *,
    product_description: str = "test widget",
    quantity: int = 1,
    unit_price: int = 10_000,
    weight_kg: float = 1.0,
    hs_code_hint: Optional[str] = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "product_description": product_description,
        "quantity": quantity,
        "unit_price": unit_price,
        "weight_kg": weight_kg,
    }
    if hs_code_hint is not None:
        item["hs_code_hint"] = hs_code_hint
    return item


def create_order_payload(
    importer_id: str,
    declarant_id: str,
    *,
    external_order_ref: Optional[str] = None,
    trade_mode: str = "GENERAL_TRADE",
    origin_country: str = "US",
    destination_country: str = "CN",
    currency: str = "USD",
    line_items: Optional[List[Dict[str, Any]]] = None,
    total_value_minor: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    if line_items is None:
        line_items = [make_line_item()]
    if total_value_minor is None:
        total_value_minor = sum(
            li["quantity"] * li["unit_price"] for li in line_items
        )
    payload: Dict[str, Any] = {
        "external_order_ref": external_order_ref or unique_external_order_ref(),
        "importer_id": importer_id,
        "declarant_id": declarant_id,
        "trade_mode": trade_mode,
        "origin_country": origin_country,
        "destination_country": destination_country,
        "currency": currency,
        "line_items": line_items,
        "total_value_minor": total_value_minor,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Declaration  (PRD §3.3)
# Trade-mode template field is required at submit; we include it on draft
# creation by default so factories alone produce a submittable draft.
# ---------------------------------------------------------------------------
def create_declaration_payload(
    order_id: str,
    *,
    dutiable_value_method: str = "TRANSACTION_VALUE",
    trade_mode: str = "GENERAL_TRADE",
    importer_id_card_number: Optional[str] = None,
    bonded_zone_code: Optional[str] = None,
    contract_number: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "dutiable_value_method": dutiable_value_method,
    }

    # Auto-fill the appropriate template-completion field based on trade_mode
    # so a freshly-created draft is submittable without further input.
    # Callers that want to test ERR_DECLARATION_INCOMPLETE can override via
    # explicit `**overrides` (e.g., contract_number=None, ...).
    if trade_mode == "B2C_DIRECT_MAIL":
        payload["importer_id_card_number"] = (
            importer_id_card_number
            if importer_id_card_number is not None
            else "ID-1234567890"
        )
    elif trade_mode == "BONDED_WAREHOUSE":
        payload["bonded_zone_code"] = (
            bonded_zone_code if bonded_zone_code is not None else "BZ-001"
        )
    elif trade_mode == "GENERAL_TRADE":
        payload["contract_number"] = (
            contract_number if contract_number is not None else "CN-2026-001"
        )

    # Allow caller-supplied template fields regardless of trade_mode.
    if importer_id_card_number is not None and "importer_id_card_number" not in payload:
        payload["importer_id_card_number"] = importer_id_card_number
    if bonded_zone_code is not None and "bonded_zone_code" not in payload:
        payload["bonded_zone_code"] = bonded_zone_code
    if contract_number is not None and "contract_number" not in payload:
        payload["contract_number"] = contract_number

    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DeclarationLine  (PRD §3.4)
# ---------------------------------------------------------------------------
def create_declaration_line_payload(
    *,
    order_line_index: int = 0,
    hs_code_id: str,
    classification_source: str = "AUTO_SUGGESTED",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_line_index": order_line_index,
        "hs_code_id": hs_code_id,
        "classification_source": classification_source,
    }
    payload.update(overrides)
    return payload


def review_override_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Query  (PRD §3.7)
# ---------------------------------------------------------------------------
def open_query_payload(
    *,
    question: str = "Please provide additional documents.",
    required_documents: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "question": question,
        "required_documents": (
            required_documents if required_documents is not None else ["INVOICE"]
        ),
    }
    payload.update(overrides)
    return payload


def respond_query_payload(
    *,
    response_text: str = "See attached.",
    response_documents: Optional[List[Dict[str, str]]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "response_text": response_text,
        "response_documents": (
            response_documents
            if response_documents is not None
            else [{"doc_type": "INVOICE", "voucher_url": "https://x/invoice"}]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InspectionAppointment  (PRD §3.7)
# ---------------------------------------------------------------------------
def schedule_inspection_payload(
    *,
    scheduled_at: str = "2026-02-01T10:00:00Z",
    bay_code: str = "BAY-A1",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_at": scheduled_at,
        "bay_code": bay_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reject (declaration)
# ---------------------------------------------------------------------------
def reject_declaration_payload(
    rejection_reason: str = "documentation incomplete", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Amend (declaration)
# ---------------------------------------------------------------------------
def amend_declaration_payload(
    *,
    lines: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"lines": lines if lines is not None else []}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PaymentNotice — confirm / reverse  (PRD §3.8)
# ---------------------------------------------------------------------------
def confirm_payment_payload(
    *,
    payment_channel: str = "ELECTRONIC_PAYMENT",
    voucher_url: Optional[str] = None,
    idempotency_key: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "payment_channel": payment_channel,
        "idempotency_key": idempotency_key,
    }
    if voucher_url is not None:
        payload["voucher_url"] = voucher_url
    payload.update(overrides)
    return payload


def reverse_payment_payload(
    reverse_reason: str = "bank_dispute", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reverse_reason": reverse_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Refund  (PRD §3.10)
# ---------------------------------------------------------------------------
def create_refund_payload(
    declaration_id: str,
    *,
    refund_reason: str = "ERRONEOUS_DECLARATION",
    supporting_documents: Optional[List[Dict[str, str]]] = None,
    **overrides,
) -> Dict[str, Any]:
    if supporting_documents is None:
        # Default: include the document type the reason requires.
        doc_type_by_reason = {
            "RETURN": "SHIPMENT_RETURN_RECEIPT",
            "ORDER_CANCELLATION": "CANCELLATION_AGREEMENT",
            "ERRONEOUS_DECLARATION": "AMENDMENT_DECISION",
        }
        supporting_documents = [
            {
                "doc_type": doc_type_by_reason.get(refund_reason, "AMENDMENT_DECISION"),
                "voucher_url": "https://x/refund-doc",
            }
        ]
    payload: Dict[str, Any] = {
        "declaration_id": declaration_id,
        "refund_reason": refund_reason,
        "supporting_documents": supporting_documents,
    }
    payload.update(overrides)
    return payload


def reject_refund_payload(
    rejection_reason: str = "insufficient evidence", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Classification suggest
# ---------------------------------------------------------------------------
def suggest_payload(product_description: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"product_description": product_description}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# /_events/emit
# ---------------------------------------------------------------------------
def emit_event_payload(event_type: str, subject_id: str) -> Dict[str, Any]:
    return {"event_type": event_type, "subject_id": subject_id}


__all__ = [
    "unique_hs_code",
    "unique_license_number",
    "unique_agent_code",
    "unique_external_order_ref",
    "create_hs_code_payload",
    "create_tariff_rule_payload",
    "create_exchange_rate_payload",
    "create_importer_payload",
    "create_declarant_payload",
    "make_line_item",
    "create_order_payload",
    "create_declaration_payload",
    "create_declaration_line_payload",
    "review_override_payload",
    "open_query_payload",
    "respond_query_payload",
    "schedule_inspection_payload",
    "reject_declaration_payload",
    "amend_declaration_payload",
    "confirm_payment_payload",
    "reverse_payment_payload",
    "create_refund_payload",
    "reject_refund_payload",
    "suggest_payload",
    "emit_event_payload",
]
