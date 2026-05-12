"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks are pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares -- never more,
never less.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: 'Resources whose history matters carry three additional
    system fields: created_at and updated_at, both ISO 8601 UTC timestamps
    with three fractional digits, and version, an integer that begins at 1
    on creation and is incremented by exactly 1 on every server-side
    mutation.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with three fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with three fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_append_only(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: 'ProjectTemplate ... and AuditEntry ... carry only id and
    created_at -- no updated_at, no version field appears on them.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# WeddingProject (PRD §3.1, §3.5, §3.8)
# ---------------------------------------------------------------------------
def assert_wedding_project(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "WeddingProject")
    assert isinstance(data["couple_name"], str) and data["couple_name"]
    assert isinstance(data["ceremony_date"], int)
    assert data["style"] in {"CLASSIC", "RUSTIC", "MODERN", "DESTINATION"}
    assert data["scale"] in {"INTIMATE", "MEDIUM", "GRAND"}
    assert isinstance(data["planner_user_id"], str) and data["planner_user_id"]
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert data["status"] in {
        "DRAFT", "PLANNING", "EXECUTION", "SETTLEMENT",
        "CLOSED", "CANCELLED",
    }
    assert isinstance(data["total_budget_cents"], int)
    assert data["total_budget_cents"] >= 0
    assert isinstance(data["provisional_committed_cents"], int)
    assert isinstance(data["finalized_settled_cents"], int)
    assert isinstance(data["budget_balance_cents"], int)
    assert isinstance(data["rehearsal_version"], int)
    assert data["rehearsal_version"] >= 0


def assert_project_ledger_invariant(data: Dict[str, Any]) -> None:
    """PRD §3.5: 'budget_balance_cents is then total_budget_cents minus
    provisional_committed_cents minus finalized_settled_cents.'"""
    expected = (
        data["total_budget_cents"]
        - data["provisional_committed_cents"]
        - data["finalized_settled_cents"]
    )
    assert data["budget_balance_cents"] == expected, (
        f"PRD §3.5 ledger invariant: total_budget_cents - "
        f"provisional_committed_cents - finalized_settled_cents = "
        f"{expected}, but budget_balance_cents = "
        f"{data['budget_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# ProjectTemplate (PRD §3.1) -- append-only
# ---------------------------------------------------------------------------
def assert_project_template(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "ProjectTemplate")
    assert "updated_at" not in data, (
        "ProjectTemplate must not expose updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "ProjectTemplate must not expose version (PRD §2.4)"
    )
    assert isinstance(data["name"], str) and data["name"]
    assert data["scale"] in {"INTIMATE", "MEDIUM", "GRAND"}
    assert isinstance(data["default_milestones"], list)


# ---------------------------------------------------------------------------
# Milestone (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_milestone(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Milestone")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["due_at"], int)
    assert isinstance(data["percent_of_budget"], (int, float))
    assert 0.0 <= float(data["percent_of_budget"]) <= 100.0
    assert data["status"] in {
        "PENDING", "IN_PROGRESS", "COMPLETED", "OVERDUE",
    }


# ---------------------------------------------------------------------------
# Vendor (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_vendor(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Vendor")
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in {
        "VENUE", "PHOTOGRAPHY", "FLORAL", "CATERING", "MC", "BAND",
    }
    assert data["qualification_status"] in {
        "PENDING_REVIEW", "APPROVED", "REJECTED", "SUSPENDED",
    }
    # avg_performance_rating is null when there are zero ratings; otherwise
    # it must be a number with at most 2 decimal places (PRD §2.6, §3.2).
    avg = data.get("avg_performance_rating")
    if avg is not None:
        assert isinstance(avg, (int, float))
        assert 1.0 <= float(avg) <= 5.0
    rating_count = data.get("rating_count", 0)
    assert isinstance(rating_count, int) and rating_count >= 0


# ---------------------------------------------------------------------------
# Quote (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_quote(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Quote")
    assert isinstance(data["vendor_id"], str)
    assert data["category"] in {
        "VENUE", "PHOTOGRAPHY", "FLORAL", "CATERING", "MC", "BAND",
    }
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["scope_description"], str)
    assert isinstance(data["valid_until"], int)
    assert data["status"] in {
        "DRAFT", "OFFERED", "BOUND", "EXPIRED", "WITHDRAWN",
    }


# ---------------------------------------------------------------------------
# Contract (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_contract(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Contract")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["quote_id"], str)
    assert data["contract_status"] in {
        "DRAFT", "NEGOTIATING", "SIGNED", "ACCEPTED", "TERMINATED",
    }
    assert data["payment_status"] in {
        "UNPAID", "PARTIAL", "FINALIZED", "REFUNDED",
    }
    assert isinstance(data["negotiation_round"], int)
    assert data["negotiation_round"] >= 0


# ---------------------------------------------------------------------------
# ChangeOrder (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_change_order(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ChangeOrder")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["delta_amount_cents"], int)
    assert isinstance(data["reason"], str)
    assert isinstance(data["requested_by_user_id"], str)
    assert data["status"] in {"PENDING", "APPROVED", "REJECTED"}


# ---------------------------------------------------------------------------
# Settlement (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_settlement(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Settlement")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["breach_deduction_cents"], int)
    assert data["breach_deduction_cents"] >= 0
    assert isinstance(data["refund_cents"], int)
    assert data["refund_cents"] >= 0
    assert isinstance(data["final_amount_cents"], int)
    assert data["status"] in {"DRAFT", "VENDOR_CONFIRMED", "FINALIZED"}
    assert isinstance(data["confirmed_by_user_id"], str)


# ---------------------------------------------------------------------------
# TimelineSlot (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_timeline_slot(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "TimelineSlot")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["start_at"], int)
    assert isinstance(data["end_at"], int)
    assert data["start_at"] < data["end_at"], (
        "PRD §3.6 half-open interval requires start_at < end_at"
    )
    assert isinstance(data["setup_buffer_seconds"], int)
    assert data["setup_buffer_seconds"] >= 0
    assert data["kind"] in {"PREPARATION", "CEREMONY", "RECEPTION"}
    assert isinstance(data["label"], str)


# ---------------------------------------------------------------------------
# Guest (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_guest(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Guest")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["party_size"], int)
    assert data["party_size"] >= 1, (
        "PRD §3.7: party_size MUST be at least 1"
    )
    assert data["rsvp_status"] in {
        "INVITED", "CONFIRMED", "DECLINED", "NO_RESPONSE",
    }
    assert isinstance(data["dietary_requirements"], list)
    assert isinstance(data["accessibility_requirements"], list)
    assert isinstance(data["gift_amount_cents"], int)
    assert data["gift_amount_cents"] >= 0


# ---------------------------------------------------------------------------
# AuditEntry (PRD §2.10, §3.8) -- append-only
# ---------------------------------------------------------------------------
def assert_audit_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditEntry")
    assert "updated_at" not in data, (
        "AuditEntry must not expose updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "AuditEntry must not expose version (PRD §2.4)"
    )
    assert data["subject_type"] in {
        "BUDGET", "CONTRACT", "SETTLEMENT", "CHANGE_ORDER",
    }
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_user_id"], str)
    assert data["actor_role"] in {
        "Planner", "VendorRep", "Couple", "Auditor",
    }
    assert data["event_kind"] in {
        "BUDGET_REALLOCATED", "CHANGE_ORDER_APPROVED",
        "CONTRACT_TERMINATED", "SETTLEMENT_FINALIZED",
        "OVERSPEND_WARNING_RAISED",
    }


# ---------------------------------------------------------------------------
# PerformanceRating (PRD §3.2) -- append-only / immutable
# ---------------------------------------------------------------------------
def assert_performance_rating(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "PerformanceRating")
    assert "updated_at" not in data, (
        "PerformanceRating must not expose updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "PerformanceRating must not expose version (PRD §2.4)"
    )
    assert isinstance(data["score"], int)
    assert 1 <= data["score"] <= 5, (
        "PRD §3.2: score must be an integer 1..5 inclusive"
    )


# ---------------------------------------------------------------------------
# Helpers for finding rows in lists returned by list endpoints
# ---------------------------------------------------------------------------
def find_audit_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    event_kind: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter audit entries by event_kind / subject_type / subject_id."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if event_kind is not None and e.get("event_kind") != event_kind:
            continue
        if subject_type is not None and e.get("subject_type") != subject_type:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        out.append(e)
    return out


__all__ = [
    "assert_wedding_project",
    "assert_project_ledger_invariant",
    "assert_project_template",
    "assert_milestone",
    "assert_vendor",
    "assert_quote",
    "assert_contract",
    "assert_change_order",
    "assert_settlement",
    "assert_timeline_slot",
    "assert_guest",
    "assert_audit_entry",
    "assert_performance_rating",
    "find_audit_entries",
]
