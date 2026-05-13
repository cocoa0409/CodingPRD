"""Entity assertions and domain invariant checkers for the Travel
Reimburse API.

Each assert_{entity}() validates the response shape against PRD §2.4
(common resource properties) and the entity-specific field set described
in PRD §3. Three entities are write-once history rows per PRD §2.4 and
carry only id + created_at: ExpenseStandard, ApprovalRecord, AuditLog —
their assertions omit updated_at and version.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set

import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _assert_common_full(data: Dict[str, Any]) -> None:
    """Common fields for mutable resources (PRD §2.4).

    id, created_at, updated_at (ISO 8601), version (monotonically
    increasing integer starting at 1).
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a server-generated UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int, got {type(data.get('version')).__name__}"
    )
    assert data["version"] >= 1, "version must start at 1 and only increase"


def _assert_common_history_row(data: Dict[str, Any]) -> None:
    """Common fields for write-once history rows (PRD §2.4).

    'ExpenseStandard, ApprovalRecord, and AuditLog are write-once history
    rows — they carry only id and created_at, and they do not expose
    updated_at or version.'
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a server-generated UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_enum(value: Any, allowed: Set[str], field_name: str) -> None:
    assert value in allowed, (
        f"{field_name} must be one of {sorted(allowed)}, got {value!r}"
    )


def _assert_money(value: Any, field_name: str,
                  allow_negative: bool = False) -> None:
    assert isinstance(value, (int, float)), (
        f"{field_name} must be numeric, got {type(value).__name__}"
    )
    if not allow_negative:
        assert value >= 0, f"{field_name} must be >= 0, got {value}"
    assert_cost_precision(float(value))


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------
EMPLOYEE_LEVELS = {"STAFF", "MANAGER", "DIRECTOR", "EXECUTIVE"}
EMPLOYEE_STATUSES = {"ACTIVE", "INACTIVE"}


def assert_employee(data: Dict[str, Any]) -> None:
    """PRD §3.1: Employee carries full_name, employee_level,
    department_id, supervisor_id, status. Newly created employees default
    to ACTIVE."""
    _assert_common_full(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    _assert_enum(data.get("employee_level"), EMPLOYEE_LEVELS,
                 "employee_level")
    assert isinstance(data.get("department_id"), str)
    # supervisor_id may be null for top-level employees.
    sup = data.get("supervisor_id")
    assert sup is None or isinstance(sup, str)
    _assert_enum(data.get("status"), EMPLOYEE_STATUSES, "status")


# ---------------------------------------------------------------------------
# ExpenseStandard  (write-once history row per PRD §2.4)
# ---------------------------------------------------------------------------
CITY_TIERS = {"TIER_1", "TIER_2", "TIER_3", "OVERSEAS"}


def assert_expense_standard(data: Dict[str, Any]) -> None:
    """PRD §3.1: ExpenseStandard keyed by (version, city_tier,
    employee_level); carries the three caps and holiday_multiplier."""
    _assert_common_history_row(data)
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    et = data.get("effective_to")
    assert et is None or is_iso8601_timestamp(et)
    _assert_enum(data.get("city_tier"), CITY_TIERS, "city_tier")
    _assert_enum(data.get("employee_level"), EMPLOYEE_LEVELS,
                 "employee_level")
    _assert_money(data.get("lodging_daily_cap"), "lodging_daily_cap")
    _assert_money(data.get("per_diem_amount"), "per_diem_amount")
    _assert_money(data.get("transportation_daily_cap"),
                  "transportation_daily_cap")
    assert isinstance(data.get("holiday_multiplier"), (int, float))
    assert data["holiday_multiplier"] > 0

    # Per PRD §2.4: this entity has no updated_at and no version OCC.
    # (The integer 'version' here is the business-meaningful standard
    # generation number, not an OCC counter.) Implementations MAY omit
    # updated_at; assertions intentionally do not require its presence.


# ---------------------------------------------------------------------------
# TravelApplication
# ---------------------------------------------------------------------------
TRAVEL_SCOPES = {"DOMESTIC", "OVERSEAS"}
APPLICATION_STATUSES = {
    "DRAFT", "SUBMITTED", "SUPERVISOR_APPROVED",
    "DEPT_HEAD_APPROVED", "FINANCE_APPROVED", "GM_APPROVED",
    "APPROVED", "REJECTED", "BOOKING_LOCKED", "COMPLETED", "CANCELLED",
}
CHAIN_STEP_VALUES = {"SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM"}


def assert_travel_application(data: Dict[str, Any]) -> None:
    """PRD §3.2: TravelApplication shape."""
    _assert_common_full(data)
    assert isinstance(data.get("applicant_id"), str)
    assert isinstance(data.get("destination_city"), str)
    _assert_enum(data.get("destination_tier"), CITY_TIERS,
                 "destination_tier")
    _assert_enum(data.get("travel_scope"), TRAVEL_SCOPES, "travel_scope")
    assert isinstance(data.get("purpose"), str)
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    _assert_money(data.get("estimated_budget"), "estimated_budget")
    assert isinstance(data.get("urgent"), bool)
    _assert_enum(data.get("status"), APPLICATION_STATUSES, "status")
    # total_booked_cost defaults to 0 before any booking.
    if "total_booked_cost" in data and data["total_booked_cost"] is not None:
        _assert_money(data["total_booked_cost"], "total_booked_cost")


def assert_application_chain_after_submit(
    data: Dict[str, Any],
    expected_chain: Optional[List[str]] = None,
) -> None:
    """PRD §3.2: after submit, required_chain is materialised and
    standard_version_pinned is captured."""
    assert isinstance(data.get("required_chain"), list)
    assert len(data["required_chain"]) >= 2, (
        "PRD §3.2: chain always starts with [SUPERVISOR, ..., FINANCE]"
    )
    for step in data["required_chain"]:
        _assert_enum(step, CHAIN_STEP_VALUES, "required_chain step")
    assert data["required_chain"][0] == "SUPERVISOR", (
        "PRD §3.2: 'Start the chain with the single step SUPERVISOR.'"
    )
    assert "FINANCE" in data["required_chain"], (
        "PRD §3.2: 'Append FINANCE next.'"
    )
    if expected_chain is not None:
        assert data["required_chain"] == expected_chain, (
            f"Expected required_chain={expected_chain}, "
            f"got {data['required_chain']}"
        )
    assert isinstance(data.get("standard_version_pinned"), int)
    assert data["standard_version_pinned"] >= 1


# ---------------------------------------------------------------------------
# ItinerarySegment
# ---------------------------------------------------------------------------
SEGMENT_TYPES = {"FLIGHT", "TRAIN", "HOTEL", "CAR"}
SEGMENT_STATUSES = {"ACTIVE", "CHANGED", "CANCELLED"}


def assert_itinerary_segment(data: Dict[str, Any]) -> None:
    """PRD §3.3: ItinerarySegment shape."""
    _assert_common_full(data)
    assert isinstance(data.get("application_id"), str)
    _assert_enum(data.get("segment_type"), SEGMENT_TYPES, "segment_type")
    assert isinstance(data.get("option_code"), str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    _assert_money(data.get("cost"), "cost")
    _assert_enum(data.get("status"), SEGMENT_STATUSES, "status")
    prior = data.get("prior_segment_id")
    assert prior is None or isinstance(prior, str)


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
INVOICE_CATEGORIES = {"LODGING", "PER_DIEM", "TRANSPORTATION", "OTHER"}
INVOICE_OCR_STATUSES = {
    "PENDING_OCR", "OCR_RECOGNIZED", "TAX_VERIFIED",
    "REJECTED", "ATTACHED", "CONSUMED",
}


def assert_invoice(data: Dict[str, Any]) -> None:
    """PRD §3.6: Invoice shape."""
    _assert_common_full(data)
    assert isinstance(data.get("applicant_id"), str)
    assert isinstance(data.get("invoice_number"), str)
    assert isinstance(data.get("invoice_code"), str)
    # amount and invoice_date may be null on PENDING_OCR
    if data.get("amount") is not None:
        _assert_money(data["amount"], "amount")
    if data.get("invoice_date") is not None:
        assert is_iso8601_timestamp(data["invoice_date"])
    _assert_enum(data.get("category"), INVOICE_CATEGORIES, "category")
    _assert_enum(data.get("ocr_status"), INVOICE_OCR_STATUSES, "ocr_status")


# ---------------------------------------------------------------------------
# ReimbursementForm + Item
# ---------------------------------------------------------------------------
FORM_STATUSES = {
    "DRAFT", "SUBMITTED", "SUPERVISOR_APPROVED", "DEPT_APPROVED",
    "FINANCE_APPROVED", "GM_APPROVED", "APPROVED", "REJECTED",
    "PAID", "FAILED",
}


def assert_reimbursement_form(data: Dict[str, Any]) -> None:
    """PRD §3.7: ReimbursementForm shape."""
    _assert_common_full(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("applicant_id"), str)
    _assert_enum(data.get("status"), FORM_STATUSES, "status")
    _assert_money(data.get("total_claimed"), "total_claimed")
    _assert_money(data.get("total_reimbursable"), "total_reimbursable")
    _assert_money(data.get("total_self_paid"), "total_self_paid")
    assert isinstance(data.get("requires_special_approval"), bool)
    assert isinstance(data.get("special_approval_granted"), bool)
    assert isinstance(data.get("correction_round"), int)
    assert data["correction_round"] >= 0


def assert_reimbursement_item(data: Dict[str, Any]) -> None:
    """PRD §3.7: ReimbursementItem shape."""
    _assert_common_full(data)
    assert isinstance(data.get("form_id"), str)
    assert isinstance(data.get("invoice_id"), str)
    _assert_enum(data.get("category"), INVOICE_CATEGORIES, "category")
    assert isinstance(data.get("covered_days"), int)
    assert data["covered_days"] >= 1
    _assert_money(data.get("claimed_amount"), "claimed_amount")


# ---------------------------------------------------------------------------
# ApprovalRecord  (write-once history row per PRD §2.4)
# ---------------------------------------------------------------------------
APPROVAL_SUBJECT_TYPES = {"TRAVEL_APPLICATION", "REIMBURSEMENT_FORM"}
APPROVAL_ACTOR_ROLES = {"SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM"}
APPROVAL_ACTIONS = {"APPROVE", "REJECT"}


def assert_approval_record(data: Dict[str, Any]) -> None:
    """PRD §3.2/§3.7: ApprovalRecord captures every approve/reject."""
    _assert_common_history_row(data)
    _assert_enum(data.get("subject_type"), APPROVAL_SUBJECT_TYPES,
                 "subject_type")
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_id"), str)
    _assert_enum(data.get("actor_role"), APPROVAL_ACTOR_ROLES,
                 "actor_role")
    _assert_enum(data.get("action"), APPROVAL_ACTIONS, "action")
    assert isinstance(data.get("from_status"), str)
    assert isinstance(data.get("to_status"), str)
    # Per PRD §2.4: no updated_at, no version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "PRD §2.4: ApprovalRecord is a write-once history row and "
        "must not expose updated_at."
    )
    assert "version" not in data or data.get("version") is None, (
        "PRD §2.4: ApprovalRecord must not expose version."
    )


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
PAYMENT_STATUSES = {"PENDING", "EXECUTING", "SUCCESS", "FAILED", "RETRYING"}
PAYMENT_CHANNELS = {
    "BANK_TRANSFER", "CORPORATE_CARD_REFUND", "INTERNAL_WALLET",
}


def assert_payment(data: Dict[str, Any]) -> None:
    """PRD §3.9: Payment shape."""
    _assert_common_full(data)
    assert isinstance(data.get("form_id"), str)
    _assert_enum(data.get("channel"), PAYMENT_CHANNELS, "channel")
    _assert_money(data.get("amount"), "amount")
    assert isinstance(data.get("batch_id"), str) and data["batch_id"]
    _assert_enum(data.get("status"), PAYMENT_STATUSES, "status")
    assert isinstance(data.get("attempt_count"), int)
    assert 0 <= data["attempt_count"] <= 3


# ---------------------------------------------------------------------------
# AuditLog  (write-once history row per PRD §2.4)
# ---------------------------------------------------------------------------
AUDIT_EVENT_TYPES = {"APPROVAL_ACTION", "PAYMENT_EVENT", "EXTERNAL_SYNC"}
AUDIT_SUBJECT_TYPES = {
    "TRAVEL_APPLICATION", "REIMBURSEMENT_FORM", "PAYMENT", "INVOICE",
}


def assert_audit_log(data: Dict[str, Any]) -> None:
    """PRD §2.10/§3.10: AuditLog write-once row."""
    _assert_common_history_row(data)
    _assert_enum(data.get("event_type"), AUDIT_EVENT_TYPES, "event_type")
    _assert_enum(data.get("subject_type"), AUDIT_SUBJECT_TYPES,
                 "subject_type")
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_id"), str)
    # payload is free-form JSON per PRD §2.10
    assert isinstance(data.get("payload"), (dict, list)) or \
        data.get("payload") is None


# ---------------------------------------------------------------------------
# Cross-cutting invariants
# ---------------------------------------------------------------------------
def assert_form_totals_consistent(form: Dict[str, Any]) -> None:
    """PRD §3.8: total_reimbursable + total_self_paid == total_claimed
    (per-item rounded BEFORE summing).

    'reimbursable_amount is the lesser of claimed_amount and
    standard_cap_applied. self_paid_amount is the greater of zero and
    (claimed_amount minus standard_cap_applied); a non-negative quantity
    by construction.'
    """
    total_claimed = float(form["total_claimed"])
    total_reim = float(form["total_reimbursable"])
    total_self = float(form["total_self_paid"])
    assert total_self >= 0, "PRD §3.8: total_self_paid is non-negative"
    assert total_reim >= 0, "total_reimbursable must be non-negative"
    # Per-item rounding can introduce up to (count * 0.005) drift in
    # the equality; for safety, use a generous tolerance keyed on item
    # count if the caller passes items, else 1 cent.
    assert abs(total_reim + total_self - total_claimed) <= 0.01, (
        f"PRD §3.8: per-item reimbursable+self_paid sums must equal "
        f"claimed; got {total_reim} + {total_self} != {total_claimed}"
    )


def assert_chain_skipped_dept_head_when_urgent_domestic(
    chain: List[str],
) -> None:
    """PRD §3.2: 'if urgent is true and travel_scope is DOMESTIC, drop
    DEPT_HEAD from the chain if it is present.'"""
    assert "DEPT_HEAD" not in chain, (
        "PRD §3.2: urgent DOMESTIC chain must not contain DEPT_HEAD"
    )


def assert_chain_has_full_overseas_shape(chain: List[str]) -> None:
    """PRD §3.2: 'an urgent trip whose scope is OVERSEAS keeps the full
    chain.'"""
    assert chain == ["SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM"], (
        f"PRD §3.2: OVERSEAS application chain must be the full four-step "
        f"sequence; got {chain}"
    )


__all__ = [
    "assert_employee",
    "assert_expense_standard",
    "assert_travel_application",
    "assert_application_chain_after_submit",
    "assert_itinerary_segment",
    "assert_invoice",
    "assert_reimbursement_form",
    "assert_reimbursement_item",
    "assert_approval_record",
    "assert_payment",
    "assert_audit_log",
    "assert_form_totals_consistent",
    "assert_chain_skipped_dept_head_when_urgent_domestic",
    "assert_chain_has_full_overseas_shape",
]
