"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the structural shape PRD declares —
common fields per PRD §2.4 (id + created_at; updated_at + version
unless the entity is PerDiemRate or Receipt), plus the entity-specific
fields from PRD §3.

Domain invariants (e.g., VirtualCard.authorized_amount_cents ≤
credit_limit_cents, ExpenseReport totals ≥ 0) are encoded as
`assert_{entity}_invariants()` so cascade-affected entities can be
re-validated cheaply after every mutation.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status enumerations (string sets) — PRD §3 narratives.
# Defined here as plain lists so assertions stay self-contained and tests
# can import them when parametrizing.
# ---------------------------------------------------------------------------
TRIP_STATUSES = {
    "DRAFT", "SUBMITTED", "APPROVED", "REJECTED",
    "CHANGES_REQUESTED", "COMPLETED", "CANCELLED",
}
VIRTUAL_CARD_STATUSES = {
    "REQUESTED", "ISSUED", "ACTIVE", "LOCKED", "CLOSED",
}
EXPENSE_REPORT_STATUSES = {
    "DRAFT", "SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED",
    "REJECTED", "APPROVED", "REIMBURSED",
}
EXPENSE_CATEGORIES = {
    "FLIGHT", "LODGING", "RENTAL_CAR", "MEAL", "MILEAGE", "OTHER",
}
POLICY_STATUSES = {
    "PENDING_EVAL", "IN_POLICY", "OUT_OF_POLICY",
    "OOP_APPROVED", "OOP_DENIED",
}
OCR_STATUSES = {
    "NO_RECEIPT", "PENDING_OCR", "OCR_VERIFIED",
    "OCR_MISMATCH", "OCR_WAIVED",
}
LINE_STATUSES = {"ACTIVE", "REIMBURSED", "VOIDED"}
MEAL_TYPES = {"BREAKFAST", "LUNCH", "DINNER", "INCIDENTAL"}
PER_DIEM_METHODS = {"ACTUAL", "PER_DIEM"}
OOP_CHAIN_LEVELS = {
    "AWAITING_L1", "AWAITING_L2", "AWAITING_FINAL",
    "FINAL_APPROVED", "DENIED",
}
EMPLOYEE_ROLES = {
    "TRAVELER", "MANAGER", "FINANCE_REVIEWER",
    "OOP_APPROVER", "ADMIN",
}


# ---------------------------------------------------------------------------
# Generic structural assertions.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """Assert id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PerDiemRate and Receipt — PRD §2.4 says they carry ONLY id and
    created_at; updated_at and version are NOT present."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, \
        "append-only entities must not carry updated_at"
    assert "version" not in data, \
        "append-only entities must not carry version"


def assert_status(data: Dict[str, Any], allowed: set) -> None:
    """Assert data['status'] is in `allowed`."""
    assert data.get("status") in allowed, \
        f"status {data.get('status')!r} not in {sorted(allowed)}"


def assert_version_incremented_by(
    new_version: int, old_version: int, delta: int = 1,
) -> None:
    assert new_version == old_version + delta, (
        f"version expected {old_version + delta}, got {new_version}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions — PRD §3 narratives.
# ---------------------------------------------------------------------------
def assert_employee(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert data.get("role") in EMPLOYEE_ROLES, \
        f"role {data.get('role')!r} not recognized"
    assert isinstance(data.get("cost_center"), str)
    assert (
        isinstance(data.get("home_address_state"), str)
        and len(data["home_address_state"]) == 2
    ), "home_address_state must be a two-letter state code"
    # manager_id may be string (UUID) or None.
    mid = data.get("manager_id")
    assert mid is None or is_valid_uuid(mid), \
        f"manager_id must be UUID or null, got {mid!r}"


def assert_per_diem_rate(data: Dict[str, Any]) -> None:
    """PRD §3.12: PerDiemRate is append-only (no updated_at / version)."""
    assert_append_only_fields(data)
    assert isinstance(data.get("city"), str) and data["city"]
    assert (
        isinstance(data.get("state"), str) and len(data["state"]) == 2
    ), "state must be a two-letter code"
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert (
        isinstance(data.get("lodging_cap_cents"), int)
        and data["lodging_cap_cents"] >= 0
    )
    assert (
        isinstance(data.get("mie_cap_cents"), int)
        and data["mie_cap_cents"] >= 0
    )
    assert isinstance(data.get("is_high_cost_locality"), bool)


def assert_trip(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("traveler_id", ""))
    assert isinstance(data.get("purpose"), str)
    assert isinstance(data.get("origin_city"), str)
    assert (
        isinstance(data.get("origin_state"), str)
        and len(data["origin_state"]) == 2
    )
    assert isinstance(data.get("destination_city"), str)
    assert (
        isinstance(data.get("destination_state"), str)
        and len(data["destination_state"]) == 2
    )
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert_status(data, TRIP_STATUSES)
    assert isinstance(data.get("estimated_budget_cents"), int)
    assert data["estimated_budget_cents"] >= 0
    pinned = data.get("pinned_per_diem_rate_id")
    assert pinned is None or is_valid_uuid(pinned)
    approved_at = data.get("approved_at")
    assert approved_at is None or is_iso8601_timestamp(approved_at)


def assert_virtual_card(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("trip_id", ""))
    last4 = data.get("card_last4")
    # PRD §3.2: card_last4 is server-minted at /issue; null beforehand.
    assert last4 is None or (
        isinstance(last4, str) and len(last4) == 4 and last4.isdigit()
    ), f"card_last4 must be a 4-digit string or null, got {last4!r}"
    assert (
        isinstance(data.get("credit_limit_cents"), int)
        and data["credit_limit_cents"] >= 0
    )
    assert_status(data, VIRTUAL_CARD_STATUSES)
    assert (
        isinstance(data.get("authorized_amount_cents"), int)
        and data["authorized_amount_cents"] >= 0
    )
    locked_reason = data.get("locked_reason")
    assert locked_reason is None or isinstance(locked_reason, str)


def assert_virtual_card_invariants(data: Dict[str, Any]) -> None:
    """authorized_amount_cents must never exceed credit_limit_cents."""
    assert_virtual_card(data)
    assert data["authorized_amount_cents"] <= data["credit_limit_cents"], (
        f"authorized_amount_cents={data['authorized_amount_cents']} "
        f"exceeds credit_limit_cents={data['credit_limit_cents']}"
    )


def assert_expense_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("trip_id", ""))
    assert_status(data, EXPENSE_REPORT_STATUSES)
    assert isinstance(data.get("total_claimed_cents"), int)
    assert isinstance(data.get("total_reimbursable_cents"), int)
    assert (
        isinstance(data.get("policy_violation_count"), int)
        and data["policy_violation_count"] >= 0
    )
    reviewer_id = data.get("reviewer_id")
    assert reviewer_id is None or isinstance(reviewer_id, str)
    submitted_at = data.get("submitted_at")
    assert submitted_at is None or is_iso8601_timestamp(submitted_at)
    approved_at = data.get("approved_at")
    assert approved_at is None or is_iso8601_timestamp(approved_at)
    reimbursed_at = data.get("reimbursed_at")
    assert reimbursed_at is None or is_iso8601_timestamp(reimbursed_at)


def assert_expense_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("report_id", ""))
    assert data.get("category") in EXPENSE_CATEGORIES
    assert is_iso8601_timestamp(data.get("expense_date", ""))
    assert isinstance(data.get("amount_claimed_cents"), int)
    assert isinstance(data.get("amount_reimbursable_cents"), int)
    assert data.get("policy_status") in POLICY_STATUSES
    assert data.get("ocr_status") in OCR_STATUSES
    assert data.get("line_status") in LINE_STATUSES


def assert_receipt(data: Dict[str, Any]) -> None:
    """PRD §3.12: Receipt is append-only (no updated_at / version)."""
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("uploader_employee_id", ""))
    assert isinstance(data.get("merchant_name"), str)
    assert (
        isinstance(data.get("merchant_total_cents"), int)
        and data["merchant_total_cents"] >= 0
    )
    assert is_iso8601_timestamp(data.get("ocr_extracted_date", ""))
    conf = data.get("ocr_confidence")
    assert isinstance(conf, (int, float)) and 0.0 <= float(conf) <= 1.0, \
        f"ocr_confidence must be in [0,1], got {conf!r}"
    used_by = data.get("used_by_line_id")
    assert used_by is None or is_valid_uuid(used_by)


def assert_oop_approval(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("expense_line_id", ""))
    assert is_valid_uuid(data.get("requester_employee_id", ""))
    assert isinstance(data.get("justification"), str)
    assert data.get("chain_level") in OOP_CHAIN_LEVELS
    assert isinstance(data.get("requires_final_escalation"), bool)
    for fld in ("l1_approver_id", "l2_approver_id", "final_approver_id"):
        val = data.get(fld)
        assert val is None or isinstance(val, str), (
            f"{fld} must be string or null, got {val!r}"
        )


__all__ = [
    "TRIP_STATUSES",
    "VIRTUAL_CARD_STATUSES",
    "EXPENSE_REPORT_STATUSES",
    "EXPENSE_CATEGORIES",
    "POLICY_STATUSES",
    "OCR_STATUSES",
    "LINE_STATUSES",
    "MEAL_TYPES",
    "PER_DIEM_METHODS",
    "OOP_CHAIN_LEVELS",
    "EMPLOYEE_ROLES",
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    "assert_employee",
    "assert_per_diem_rate",
    "assert_trip",
    "assert_virtual_card",
    "assert_virtual_card_invariants",
    "assert_expense_report",
    "assert_expense_line",
    "assert_receipt",
    "assert_oop_approval",
]
