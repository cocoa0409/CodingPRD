"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks pinned to PRD prose. Each helper checks
the surface contract the PRD declares; computed-field presence is asserted
only when PRD §3 explicitly states the field is exposed on the listed
endpoint.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def _assert_common_fields_full(data: Dict[str, Any], entity_label: str) -> None:
    """For entities with the full common-fields quartet (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 with three fractional "
        f"digits, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 with three fractional "
        f"digits, got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{entity_label}.version must be a positive integer, got {version!r}"
    )


def _assert_common_fields_bare(data: Dict[str, Any], entity_label: str) -> None:
    """For append-only entities that carry only id + created_at (PRD §2.4).

    PRD §2.4: "Several auxiliary resources — ApprovalStep, ContractVersion,
    PaymentSchedule, and AuditLogEntry — carry only id and created_at;
    both updated_at and version are absent on these entities".
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, "
        f"got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# BudgetAccount (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_budget_account(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "BudgetAccount")
    assert isinstance(data["code"], str) and data["code"].startswith("BA-")
    assert isinstance(data["department"], str) and len(data["department"]) > 0
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] >= 0
    assert isinstance(data["committed_amount_cents"], int) and data["committed_amount_cents"] >= 0
    assert isinstance(data["spent_amount_cents"], int) and data["spent_amount_cents"] >= 0
    assert data["status"] in {"ACTIVE", "FROZEN", "CLOSED"}


# ---------------------------------------------------------------------------
# Supplier (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_supplier(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Supplier")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["tax_id"], str) and len(data["tax_id"]) > 0
    assert data["qualification_status"] in {"PROVISIONAL", "QUALIFIED", "BLACKLISTED"}
    assert isinstance(data["qualification_categories"], list)
    assert is_iso8601_timestamp(data["qualification_expires_at"])
    assert isinstance(data["bank_account_id"], str)
    rating = data["rating_avg"]
    assert isinstance(rating, (int, float))
    assert 0 <= float(rating) <= 100


# ---------------------------------------------------------------------------
# Requirement (PRD §3.2)
# ---------------------------------------------------------------------------
_REQUIREMENT_STATES = {
    "DRAFT", "SUBMITTED", "IN_SOURCING", "AWARDED", "IN_APPROVAL",
    "APPROVED", "REJECTED", "CANCELLED",
}
_REQUIREMENT_CATEGORIES = {
    "IT_HARDWARE", "IT_SOFTWARE", "OFFICE_SUPPLIES",
    "PROFESSIONAL_SERVICES", "MARKETING", "CAPEX_EQUIPMENT",
}


def assert_requirement(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Requirement")
    assert data["category"] in _REQUIREMENT_CATEGORIES
    assert isinstance(data["specification"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit"], str)
    assert is_iso8601_timestamp(data["expected_delivery_date"])
    assert isinstance(data["budget_account_id"], str)
    assert isinstance(data["estimated_unit_price_cents"], int) and data["estimated_unit_price_cents"] >= 0
    assert isinstance(data["estimated_total_cents"], int)
    # estimated_total_cents = quantity * estimated_unit_price_cents (PRD §3.2)
    assert data["estimated_total_cents"] == data["quantity"] * data["estimated_unit_price_cents"]
    assert data["status"] in _REQUIREMENT_STATES


# ---------------------------------------------------------------------------
# Quote (PRD §3.2)
# ---------------------------------------------------------------------------
_QUOTE_STATES = {"SUBMITTED", "SHORTLISTED", "AWARDED", "REJECTED", "EXPIRED"}


def assert_quote(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Quote")
    assert isinstance(data["requirement_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    tech = data["technical_score"]
    assert isinstance(tech, (int, float))
    assert 0 <= float(tech) <= 100
    com = data["commercial_score"]
    assert isinstance(com, (int, float))
    composite = data["composite_score"]
    assert isinstance(composite, (int, float))
    assert data["status"] in _QUOTE_STATES


# ---------------------------------------------------------------------------
# PurchaseOrder (PRD §3.3)
# ---------------------------------------------------------------------------
_PO_STATES = {
    "PENDING_APPROVAL", "APPROVED", "REJECTED", "CANCELLED",
    "CONTRACTED", "FULFILLED", "CLOSED",
}
_PO_TIERS = {"TIER_1", "TIER_2", "TIER_3", "TIER_4"}


def assert_purchase_order(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "PurchaseOrder")
    assert isinstance(data["requirement_id"], str)
    assert isinstance(data["awarded_quote_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["budget_account_id"], str)
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] >= 1
    assert data["tier"] in _PO_TIERS
    assert data["status"] in _PO_STATES
    if data.get("approved_at") is not None:
        assert is_iso8601_timestamp(data["approved_at"])


# ---------------------------------------------------------------------------
# ApprovalStep (PRD §3.3) — append-only
# ---------------------------------------------------------------------------
_STEP_STATES = {"PENDING", "APPROVED", "REJECTED", "ESCALATED", "SKIPPED"}
_STEP_STAGES = {"DEPARTMENT_HEAD", "FINANCE", "LEGAL", "GENERAL_MANAGER"}
_STEP_MODES = {"SERIAL", "PARALLEL"}
_STEP_ROLES = {"DepartmentHead", "FinanceApprover", "LegalApprover", "GeneralManager"}


def assert_approval_step(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "ApprovalStep")
    assert isinstance(data["purchase_order_id"], str)
    assert data["stage"] in _STEP_STAGES
    assert data["mode"] in _STEP_MODES
    assert data["assignee_role"] in _STEP_ROLES
    assert isinstance(data["assignee_user_id"], str)
    assert isinstance(data["original_assignee_user_id"], str)
    assert data["status"] in _STEP_STATES
    assert is_iso8601_timestamp(data["deadline_at"])
    if data.get("decided_at") is not None:
        assert is_iso8601_timestamp(data["decided_at"])
    # PRD §2.4 explicitly excludes updated_at and version from this entity.
    assert "updated_at" not in data, (
        "ApprovalStep is append-only (PRD §2.4) and must not carry updated_at"
    )
    assert "version" not in data, (
        "ApprovalStep is append-only (PRD §2.4) and must not carry version"
    )


# ---------------------------------------------------------------------------
# Contract (PRD §3.6)
# ---------------------------------------------------------------------------
_CONTRACT_STATES = {
    "DRAFTING", "IN_REVIEW", "AWAITING_SIGNATURE", "EXECUTED", "TERMINATED",
}
_PAYMENT_TERMS_TYPES = {"ADVANCE", "ON_DELIVERY", "NET_N_DAYS", "INSTALLMENT"}


def assert_contract(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Contract")
    assert isinstance(data["purchase_order_id"], str)
    assert isinstance(data["clause_template_ids"], list)
    assert data["payment_terms_type"] in _PAYMENT_TERMS_TYPES
    assert isinstance(data["payment_terms_params"], dict)
    assert isinstance(data["parties_required"], list)
    assert isinstance(data["signatures"], list)
    assert isinstance(data["current_version"], int) and data["current_version"] >= 1
    assert data["status"] in _CONTRACT_STATES


# ---------------------------------------------------------------------------
# ContractVersion (PRD §3.6) — append-only
# ---------------------------------------------------------------------------
def assert_contract_version(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "ContractVersion")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert isinstance(data["clause_template_ids_snapshot"], list)
    assert isinstance(data["payment_terms_snapshot"], dict)
    assert isinstance(data["change_reason"], str)
    assert "updated_at" not in data
    assert "version" not in data


# ---------------------------------------------------------------------------
# ClauseTemplate (PRD §3.6)
# ---------------------------------------------------------------------------
_CLAUSE_CATEGORIES = {
    "PAYMENT", "DELIVERY", "WARRANTY", "IP", "CONFIDENTIALITY", "TERMINATION",
}


def assert_clause_template(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "ClauseTemplate")
    assert isinstance(data["code"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["body"], str)
    assert data["category"] in _CLAUSE_CATEGORIES
    assert isinstance(data["is_active"], bool)


# ---------------------------------------------------------------------------
# Receipt (PRD §3.8)
# ---------------------------------------------------------------------------
_RECEIPT_STATES = {
    "DRAFT", "INSPECTING", "ACCEPTED", "PARTIALLY_ACCEPTED",
    "REJECTED", "RETURNED",
}


def assert_receipt(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Receipt")
    assert isinstance(data["purchase_order_id"], str)
    assert isinstance(data["delivery_note_no"], str)
    assert isinstance(data["received_quantity"], int) and data["received_quantity"] >= 1
    assert isinstance(data["accepted_quantity"], int) and data["accepted_quantity"] >= 0
    assert data["accepted_quantity"] <= data["received_quantity"]
    # PRD §3.8: rejected_quantity = received_quantity - accepted_quantity
    assert data["rejected_quantity"] == data["received_quantity"] - data["accepted_quantity"]
    qr = data["quality_rating"]
    assert isinstance(qr, (int, float))
    assert 0 <= float(qr) <= 100
    assert data["status"] in _RECEIPT_STATES


# ---------------------------------------------------------------------------
# PaymentSchedule (PRD §3.7) — append-only
# ---------------------------------------------------------------------------
_PAYMENT_SCHEDULE_STATES = {"PENDING", "APPLIED", "EXECUTED", "CANCELLED"}


def assert_payment_schedule(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "PaymentSchedule")
    assert isinstance(data["purchase_order_id"], str)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["installment_no"], int) and data["installment_no"] >= 1
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in _PAYMENT_SCHEDULE_STATES
    assert "updated_at" not in data
    assert "version" not in data


# ---------------------------------------------------------------------------
# Payment (PRD §3.10)
# ---------------------------------------------------------------------------
_PAYMENT_STATES = {"APPLIED", "APPROVED", "EXECUTED", "FAILED", "CANCELLED"}


def assert_payment(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Payment")
    assert isinstance(data["payment_schedule_id"], str)
    # invoice_id is required at apply per PRD §3.10
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in _PAYMENT_STATES


# ---------------------------------------------------------------------------
# Invoice (PRD §3.9)
# ---------------------------------------------------------------------------
_INVOICE_STATES = {
    "SUBMITTED", "MATCHED", "EXCEPTION", "REJECTED", "APPROVED", "PAID",
}


def assert_invoice(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Invoice")
    assert isinstance(data["purchase_order_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["invoice_no"], str)
    assert is_iso8601_timestamp(data["invoice_date"])
    assert isinstance(data["invoiced_quantity"], int) and data["invoiced_quantity"] >= 1
    assert isinstance(data["invoiced_amount_cents"], int) and data["invoiced_amount_cents"] >= 1
    assert isinstance(data["tax_amount_cents"], int) and data["tax_amount_cents"] >= 0
    assert isinstance(data["tax_rate_declared"], (int, float))
    assert 0 <= float(data["tax_rate_declared"]) <= 1
    assert data["status"] in _INVOICE_STATES


# ---------------------------------------------------------------------------
# AuditLogEntry (PRD §2.11) — append-only
# ---------------------------------------------------------------------------
_AUDIT_ACTIONS = {
    "APPROVAL_STEP_APPROVE",
    "APPROVAL_STEP_REJECT",
    "APPROVAL_STEP_DELEGATE",
    "APPROVAL_STEP_ESCALATE",
    "CONTRACT_VERSION_CREATED",
    "CONTRACT_SIGNED",
    "CONTRACT_AMENDED",
}


def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "AuditLogEntry")
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)
    assert data["action"] in _AUDIT_ACTIONS
    assert isinstance(data["entity_type"], str)
    assert isinstance(data["entity_id"], str)
    assert isinstance(data["payload"], dict)
    assert "updated_at" not in data
    assert "version" not in data


# ---------------------------------------------------------------------------
# Domain helpers — searching / counting
# ---------------------------------------------------------------------------
def find_steps_by_stage(
    steps: List[Dict[str, Any]], stage: str
) -> List[Dict[str, Any]]:
    return [s for s in steps if s.get("stage") == stage]


def find_step_by_stage(
    steps: List[Dict[str, Any]], stage: str
) -> Dict[str, Any]:
    matches = find_steps_by_stage(steps, stage)
    assert len(matches) == 1, (
        f"Expected exactly one step with stage={stage}, got {len(matches)}"
    )
    return matches[0]


def find_audit_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if action is not None and e.get("action") != action:
            continue
        if entity_type is not None and e.get("entity_type") != entity_type:
            continue
        if entity_id is not None and e.get("entity_id") != entity_id:
            continue
        out.append(e)
    return out


__all__ = [
    "assert_budget_account",
    "assert_supplier",
    "assert_requirement",
    "assert_quote",
    "assert_purchase_order",
    "assert_approval_step",
    "assert_contract",
    "assert_contract_version",
    "assert_clause_template",
    "assert_receipt",
    "assert_payment_schedule",
    "assert_payment",
    "assert_invoice",
    "assert_audit_log_entry",
    "find_steps_by_stage",
    "find_step_by_stage",
    "find_audit_entries",
]
