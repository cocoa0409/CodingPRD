"""Entity assertions and domain invariant checkers."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common-fields assertion (PRD §2.4).
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_full_common_fields(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int, got {type(data.get('version')).__name__}"
    )
    assert data["version"] >= 1, (
        f"version must start at 1 and only increase, got {data['version']}"
    )


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def assert_hs_code(data: Dict[str, Any]) -> None:
    """common_fields=false → only id + created_at."""
    _assert_common_fields(data)
    assert "updated_at" not in data, (
        "PRD §2.4: HsCode does not carry updated_at"
    )
    assert "version" not in data, (
        "PRD §2.4: HsCode does not carry version"
    )
    assert isinstance(data["code"], str) and len(data["code"]) == 10
    assert data["code"].isdigit()
    assert isinstance(data["description"], str)
    assert isinstance(data["keywords"], list)
    assert isinstance(data["country_code_map"], dict)
    assert isinstance(data["tariff_rate_bps"], int) and data["tariff_rate_bps"] >= 0
    assert isinstance(data["vat_rate_bps"], int) and data["vat_rate_bps"] >= 0
    assert isinstance(data["consumption_tax_rate_bps"], int)
    assert data["consumption_tax_rate_bps"] >= 0
    assert isinstance(data["postal_tax_rate_bps"], int)
    assert data["postal_tax_rate_bps"] >= 0
    assert data["status"] in ("ACTIVE", "DEPRECATED")


def assert_tariff_rule(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["hs_code_id"], str)
    assert isinstance(data["origin_country"], str)
    assert isinstance(data["destination_country"], str)
    assert isinstance(data["tariff_rate_bps"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"])


def assert_exchange_rate(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["from_currency"], str) and len(data["from_currency"]) == 3
    assert isinstance(data["to_currency"], str) and len(data["to_currency"]) == 3
    assert isinstance(data["rate_micros"], int) and data["rate_micros"] > 0
    assert isinstance(data["effective_date"], str)


# ---------------------------------------------------------------------------
# Counterparties
# ---------------------------------------------------------------------------
def assert_importer(data: Dict[str, Any]) -> None:
    _assert_full_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["license_number"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_declarant(data: Dict[str, Any]) -> None:
    _assert_full_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["agent_code"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------
def assert_order(data: Dict[str, Any]) -> None:
    _assert_full_common_fields(data)
    assert isinstance(data["external_order_ref"], str)
    assert isinstance(data["importer_id"], str)
    assert isinstance(data["declarant_id"], str)
    assert data["trade_mode"] in (
        "B2C_DIRECT_MAIL", "BONDED_WAREHOUSE", "GENERAL_TRADE"
    )
    assert isinstance(data["currency"], str)
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    assert isinstance(data["total_value_minor"], int)
    assert data["status"] in (
        "PENDING_DECLARATION", "DECLARED", "RELEASED", "CANCELLED", "RETURNED"
    )


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------
DECLARATION_VALID_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "QUERIED", "REVISED",
    "APPROVED", "CONDITIONALLY_RELEASED", "RELEASED", "REJECTED", "AMENDED",
}


def assert_declaration(data: Dict[str, Any]) -> None:
    _assert_full_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["declarant_id"], str)
    assert data["trade_mode"] in (
        "B2C_DIRECT_MAIL", "BONDED_WAREHOUSE", "GENERAL_TRADE"
    )
    assert data["dutiable_value_method"] in (
        "TRANSACTION_VALUE", "DEDUCTIVE_VALUE", "COMPUTED_VALUE"
    )
    assert data["status"] in DECLARATION_VALID_STATUSES
    assert isinstance(data["submission_count"], int)
    assert data["submission_count"] >= 0


def assert_declaration_taxes_present(data: Dict[str, Any]) -> None:
    """Once submitted, all tax fields are integers >= 0."""
    for f in (
        "dutiable_value_cny_minor",
        "tariff_amount_cny_minor",
        "vat_amount_cny_minor",
        "consumption_tax_cny_minor",
        "total_tax_cny_minor",
    ):
        assert isinstance(data.get(f), int), (
            f"{f} must be integer, got {type(data.get(f)).__name__}"
        )
        assert data[f] >= 0, f"{f} must be non-negative, got {data[f]}"
    # Composition (PRD §3.6)
    assert (
        data["total_tax_cny_minor"]
        == data["tariff_amount_cny_minor"]
        + data["vat_amount_cny_minor"]
        + data["consumption_tax_cny_minor"]
    ), (
        "total_tax_cny_minor must equal "
        "tariff_amount_cny_minor + vat_amount_cny_minor + consumption_tax_cny_minor"
    )
    assert data.get("tax_mode") in ("STANDARD", "PERSONAL_POSTAL")


# ---------------------------------------------------------------------------
# DeclarationLine
# ---------------------------------------------------------------------------
def assert_declaration_line(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["declaration_id"], str)
    assert isinstance(data["order_line_index"], int)
    assert data["order_line_index"] >= 0
    assert isinstance(data["hs_code_id"], str)
    assert data["classification_source"] in (
        "AUTO_SUGGESTED", "MANUAL_OVERRIDE", "RULE_ENGINE"
    )
    assert data["override_review_status"] in (
        "NOT_APPLICABLE", "PENDING", "APPROVED", "REJECTED"
    )


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
def assert_query(data: Dict[str, Any]) -> None:
    _assert_full_common_fields(data)
    assert isinstance(data["declaration_id"], str)
    assert isinstance(data["question"], str)
    assert isinstance(data["required_documents"], list)
    assert data["status"] in ("OPEN", "RESPONDED", "RESOLVED")


# ---------------------------------------------------------------------------
# InspectionAppointment
# ---------------------------------------------------------------------------
def assert_inspection_appointment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["declaration_id"], str)
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["bay_code"], str) and len(data["bay_code"]) > 0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


# ---------------------------------------------------------------------------
# PaymentNotice
# ---------------------------------------------------------------------------
def assert_payment_notice(data: Dict[str, Any]) -> None:
    _assert_full_common_fields(data)
    assert isinstance(data["declaration_id"], str)
    assert isinstance(data["amount_cny_minor"], int)
    assert data["amount_cny_minor"] >= 0
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("PENDING", "PAID", "EXPIRED", "REVERSED")
    if data.get("payment_channel") is not None:
        assert data["payment_channel"] in (
            "BANK_TRANSFER", "ELECTRONIC_PAYMENT", "GUARANTEE_DEDUCTION"
        )


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------
def assert_refund(data: Dict[str, Any]) -> None:
    _assert_full_common_fields(data)
    assert isinstance(data["declaration_id"], str)
    assert data["refund_reason"] in (
        "RETURN", "ORDER_CANCELLATION", "ERRONEOUS_DECLARATION"
    )
    assert isinstance(data["supporting_documents"], list)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EXECUTED"
    )
    if data.get("refundable_amount_cny_minor") is not None:
        assert isinstance(data["refundable_amount_cny_minor"], int)
        assert data["refundable_amount_cny_minor"] >= 0
    if data.get("executed_amount_cny_minor") is not None:
        assert isinstance(data["executed_amount_cny_minor"], int)
        assert data["executed_amount_cny_minor"] >= 0


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------
VALID_AUDIT_EVENT_TYPES = {
    "DECLARATION_FIELD_CHANGE",
    "DECLARATION_STATUS_CHANGE",
    "TAX_RECOMPUTED",
    "PAYMENT_CONFIRMED",
    "REFUND_DECISION",
    "EXTERNAL_SYNC",
}


def assert_audit_event(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert "updated_at" not in data
    assert "version" not in data
    assert data["subject_type"] in ("DECLARATION", "PAYMENT_NOTICE", "REFUND")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert data["event_type"] in VALID_AUDIT_EVENT_TYPES


# ---------------------------------------------------------------------------
# Search helpers — used to verify side-effects in tests.
# ---------------------------------------------------------------------------
def find_audit_events(
    events: List[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return events matching all given filters (None = unconstrained)."""
    out = []
    for ev in events:
        if subject_type is not None and ev.get("subject_type") != subject_type:
            continue
        if subject_id is not None and ev.get("subject_id") != subject_id:
            continue
        if event_type is not None and ev.get("event_type") != event_type:
            continue
        out.append(ev)
    return out


__all__ = [
    "assert_hs_code",
    "assert_tariff_rule",
    "assert_exchange_rate",
    "assert_importer",
    "assert_declarant",
    "assert_order",
    "assert_declaration",
    "assert_declaration_taxes_present",
    "assert_declaration_line",
    "assert_query",
    "assert_inspection_appointment",
    "assert_payment_notice",
    "assert_refund",
    "assert_audit_event",
    "find_audit_events",
    "DECLARATION_VALID_STATUSES",
    "VALID_AUDIT_EVENT_TYPES",
]
