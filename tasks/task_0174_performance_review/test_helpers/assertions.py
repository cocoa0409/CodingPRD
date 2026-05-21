"""Per-entity assertions and domain invariant checkers.

Each assert_<entity>() validates response payload shape per PRD §3
descriptions, including the common-fields branching rule:
* common_fields=true entities carry id, created_at, updated_at, version
  (PRD §2.4).
* FeedbackRequest and AuditEvent are append-only ledgers (PRD §2.4):
  they carry ONLY id + created_at — no updated_at, no version.

Domain invariant checkers (assert_cycle_budget_invariants, etc.) capture
PRD-stated cross-field constraints that should hold after every mutation.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CADENCES,
    PIP_DURATION_DAYS,
    RATINGS,
    RELATIONS,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 common-fields suite: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC with optional ms"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC with optional ms"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 0, (
        f"{label}.version must be a non-negative int; got {version!r}"
    )


def _assert_append_only_fields(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 append-only ledger: ONLY id + created_at (no updated_at,
    no version). Asserts presence of the required pair only; absence of
    updated_at / version is NOT asserted because PRD §2.4 says they are
    not carried — implementers may legitimately omit them.
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC with optional ms"
    )


# ---------------------------------------------------------------------------
# Employee — PRD §3.1
# ---------------------------------------------------------------------------
def assert_employee(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Employee")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("department"), str)
    assert isinstance(data.get("job_level"), int)
    assert 1 <= data["job_level"] <= 10
    assert isinstance(data.get("base_salary_cents"), int)
    assert data["base_salary_cents"] > 0
    assert isinstance(data.get("equity_units_outstanding"), int)
    assert data["equity_units_outstanding"] >= 0
    assert data.get("status") in {"ACTIVE", "ON_PIP", "TERMINATED"}
    assert is_iso8601_timestamp(data.get("hire_date", "")), (
        "Employee.hire_date must be ISO 8601"
    )
    # manager_employee_id may be None or a UUID
    mgr = data.get("manager_employee_id")
    assert mgr is None or is_valid_uuid(mgr)


# ---------------------------------------------------------------------------
# Cycle — PRD §3.2
# ---------------------------------------------------------------------------
def assert_cycle(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Cycle")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("cadence") in CADENCES
    assert data.get("status") in {"OPEN", "IN_CALIBRATION",
                                  "COMP_PLANNING", "CLOSED"}
    assert is_iso8601_timestamp(data.get("review_window_start", ""))
    assert is_iso8601_timestamp(data.get("review_window_end", ""))
    bct = data.get("bell_curve_target")
    assert isinstance(bct, dict)
    assert set(bct.keys()) == set(RATINGS), (
        f"bell_curve_target keys must equal the five rating buckets; "
        f"got {sorted(bct.keys())!r}"
    )
    assert sum(bct.values()) == 100
    for v in bct.values():
        assert isinstance(v, int) and 0 <= v <= 100
    assert isinstance(data.get("merit_budget_cents"), int)
    assert data["merit_budget_cents"] >= 0
    assert isinstance(data.get("equity_refresh_pool_units"), int)
    assert data["equity_refresh_pool_units"] >= 0
    assert isinstance(data.get("merit_budget_consumed_cents"), int)
    assert data["merit_budget_consumed_cents"] >= 0
    assert isinstance(data.get("equity_pool_consumed_units"), int)
    assert data["equity_pool_consumed_units"] >= 0
    assert_cycle_budget_invariants(data)


def assert_cycle_budget_invariants(data: Dict[str, Any]) -> None:
    """PRD §2.8: closure requires `merit_budget_consumed_cents <=
    merit_budget_cents` and `equity_pool_consumed_units <=
    equity_refresh_pool_units`. The fiscal gate at approval enforces the
    same ceiling, so the invariant must hold continuously."""
    assert (
        data["merit_budget_consumed_cents"] <= data["merit_budget_cents"]
    ), (
        f"Invariant violated: merit_budget_consumed_cents "
        f"{data['merit_budget_consumed_cents']} > merit_budget_cents "
        f"{data['merit_budget_cents']}"
    )
    assert (
        data["equity_pool_consumed_units"]
        <= data["equity_refresh_pool_units"]
    ), (
        f"Invariant violated: equity_pool_consumed_units "
        f"{data['equity_pool_consumed_units']} > "
        f"equity_refresh_pool_units {data['equity_refresh_pool_units']}"
    )


# ---------------------------------------------------------------------------
# ReviewCase — PRD §3.3
# ---------------------------------------------------------------------------
def assert_review_case(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ReviewCase")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("subject_employee_id", ""))
    assert is_valid_uuid(data.get("manager_employee_id", ""))
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "RETURNED", "LOCKED", "FINALIZED",
    }
    mr = data.get("manager_rating")
    assert mr is None or mr in RATINGS
    fr = data.get("final_rating")
    assert fr is None or fr in RATINGS
    assert isinstance(data.get("weighted_goal_score"), (int, float))
    assert data["weighted_goal_score"] >= 0
    assert isinstance(data.get("peer_feedback_count"), int)
    assert data["peer_feedback_count"] >= 0
    assert isinstance(data.get("revision_count"), int)
    assert data["revision_count"] >= 0


# ---------------------------------------------------------------------------
# Goal — PRD §3.3
# ---------------------------------------------------------------------------
def assert_goal(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Goal")
    assert is_valid_uuid(data.get("review_case_id", ""))
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("weight"), int)
    assert 1 <= data["weight"] <= 100
    ss = data.get("self_score")
    assert ss is None or (isinstance(ss, int) and 1 <= ss <= 5)
    ms = data.get("manager_score")
    assert ms is None or (isinstance(ms, int) and 1 <= ms <= 5)


# ---------------------------------------------------------------------------
# FeedbackRequest — PRD §3.4 (append-only)
# ---------------------------------------------------------------------------
def assert_feedback_request(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "FeedbackRequest")
    assert is_valid_uuid(data.get("review_case_id", ""))
    assert is_valid_uuid(data.get("reviewer_employee_id", ""))
    assert data.get("relation") in RELATIONS
    assert data.get("status") in {"PENDING", "SUBMITTED", "DECLINED"}
    sub_at = data.get("submitted_at")
    if data["status"] == "SUBMITTED":
        assert is_iso8601_timestamp(sub_at or ""), (
            "FeedbackRequest.submitted_at must be set on SUBMITTED "
            "(PRD §3.4)"
        )
    else:
        # PENDING and DECLINED: submitted_at is null (PRD §3.4)
        assert sub_at is None, (
            f"FeedbackRequest.submitted_at must be null while status="
            f"{data['status']} (PRD §3.4)"
        )


# ---------------------------------------------------------------------------
# CalibrationSession — PRD §3.5
# ---------------------------------------------------------------------------
def assert_calibration_session(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CalibrationSession")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert isinstance(data.get("department"), str) and data["department"]
    assert is_valid_uuid(data.get("facilitator_employee_id", ""))
    assert data.get("status") in {
        "SCHEDULED", "IN_SESSION", "COMMITTED", "ABANDONED",
    }
    proposed = data.get("proposed_ratings")
    assert isinstance(proposed, list)
    for pair in proposed:
        assert isinstance(pair, dict)
        assert is_valid_uuid(pair.get("review_case_id", ""))
        assert pair.get("proposed_rating") in RATINGS
    dist = data.get("bell_curve_distribution")
    assert isinstance(dist, dict)
    assert set(dist.keys()) == set(RATINGS)
    for v in dist.values():
        assert isinstance(v, int) and v >= 0
    if data["status"] == "COMMITTED":
        assert is_iso8601_timestamp(data.get("committed_at") or "")
    else:
        assert data.get("committed_at") is None


# ---------------------------------------------------------------------------
# PIPCase — PRD §3.6
# ---------------------------------------------------------------------------
def assert_pip_case(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "PIPCase")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("subject_employee_id", ""))
    assert is_valid_uuid(data.get("triggering_review_case_id", ""))
    assert data.get("status") in {"ACTIVE", "PASSED", "FAILED", "WITHDRAWN"}
    assert isinstance(data.get("duration_days"), int)
    assert data["duration_days"] in (PIP_DURATION_DAYS["NEEDS_IMPROVEMENT"],
                                     PIP_DURATION_DAYS["UNSATISFACTORY"])
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))


# ---------------------------------------------------------------------------
# CompPlan — PRD §3.7
# ---------------------------------------------------------------------------
def assert_comp_plan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CompPlan")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("subject_employee_id", ""))
    assert is_valid_uuid(data.get("pinned_review_case_id", ""))
    assert isinstance(data.get("pinned_review_case_version"), int)
    assert data["pinned_review_case_version"] >= 0
    assert isinstance(data.get("pinned_base_salary_cents"), int)
    assert data["pinned_base_salary_cents"] > 0
    assert isinstance(data.get("merit_increase_cents"), int)
    assert data["merit_increase_cents"] >= 0
    assert isinstance(data.get("equity_refresh_units"), int)
    assert data["equity_refresh_units"] >= 0
    ptl = data.get("promotion_to_level")
    assert ptl is None or (isinstance(ptl, int) and 1 <= ptl <= 10)
    assert data.get("status") in {"DRAFT", "PROPOSED", "APPROVED", "REJECTED"}
    if data["status"] == "APPROVED":
        assert is_iso8601_timestamp(data.get("approved_at") or "")


# ---------------------------------------------------------------------------
# AuditEvent — PRD §2.12 (append-only)
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "AuditEvent")
    assert isinstance(data.get("actor_role"), str) and data["actor_role"]
    assert isinstance(data.get("actor_user_id"), str)
    assert isinstance(data.get("entity_type"), str)
    assert isinstance(data.get("entity_id"), str)
    assert isinstance(data.get("action"), str) and data["action"]
    assert isinstance(data.get("payload_hash"), str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


__all__ = [
    "assert_employee",
    "assert_cycle",
    "assert_cycle_budget_invariants",
    "assert_review_case",
    "assert_goal",
    "assert_feedback_request",
    "assert_calibration_session",
    "assert_pip_case",
    "assert_comp_plan",
    "assert_audit_event",
    # Re-exported for tests that want monetary precision sanity checks
    "assert_cost_precision",
]
