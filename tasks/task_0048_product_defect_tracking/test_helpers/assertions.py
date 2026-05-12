"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) verifies the field set declared in PRD §1 /
§2.4: common_fields entities carry id/created_at/updated_at/version;
append-only logs carry only id + created_at + entity-specific fields.

Domain invariants (Module quota, defect status enum membership, etc.)
have dedicated helpers used wherever the test exercises the invariant.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp, is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helper
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    """Common id + created_at + updated_at + version validation per
    PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be valid UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601; got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601; got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"version must be int >=1; got {version!r}"
    )


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only rows carry only id + created_at — never updated_at,
    never version. PRD §2.4 explicitly lists DefectAttachment,
    DuplicateLink, FixRecord, VerificationRecord, SLAPause, AuditEntry."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be valid UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601; got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Project / Module / TeamMember
# ---------------------------------------------------------------------------
def assert_project(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["project_key"], str) and data["project_key"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["clock_minute"], int)
    assert data["clock_minute"] >= 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_module(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["module_key"], str) and data["module_key"]
    assert isinstance(data["owner_team_member_id"], str)
    assert data["owner_team_member_id"]
    assert isinstance(data["kloc"], (int, float))
    assert data["kloc"] > 0, "kloc must be > 0 per PRD §3.1"
    assert isinstance(data["initial_defect_quota"], int)
    assert data["initial_defect_quota"] >= 1
    assert isinstance(data["active_defect_count"], int)
    assert data["active_defect_count"] >= 0
    assert isinstance(data["quota_remaining"], int)
    assert data["quota_remaining"] >= 0
    assert_module_quota_invariant(data)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_module_quota_invariant(data: Dict[str, Any]) -> None:
    """PRD §3.1: 'initial_defect_quota equals the sum of quota_remaining
    and active_defect_count'."""
    total = int(data["quota_remaining"]) + int(data["active_defect_count"])
    assert total == int(data["initial_defect_quota"]), (
        f"Module quota invariant violated: "
        f"initial_defect_quota={data['initial_defect_quota']} but "
        f"quota_remaining({data['quota_remaining']}) + "
        f"active_defect_count({data['active_defect_count']}) = {total}"
    )


def assert_team_member(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["project_id"]
    assert data["display_name"]
    assert data["role"] in (
        "DEVELOPER", "QA_ENGINEER", "TRIAGE_MANAGER", "RELEASE_MANAGER",
    )
    assert isinstance(data["active_workload"], int)
    assert data["active_workload"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


# ---------------------------------------------------------------------------
# Defect
# ---------------------------------------------------------------------------
DEFECT_STATUSES = (
    "NEW", "ASSIGNED", "IN_PROGRESS", "FIXED", "VERIFIED", "REOPENED",
    "CLOSED",
)
NON_TERMINAL_DEFECT_STATUSES = (
    "NEW", "ASSIGNED", "IN_PROGRESS", "FIXED", "VERIFIED", "REOPENED",
)
DEFECT_SEVERITIES = ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "TRIVIAL")
BUSINESS_IMPACTS = (
    "REVENUE_BLOCKING", "CUSTOMER_FACING", "INTERNAL", "UNKNOWN",
)
DEFECT_SOURCES = ("INTERNAL_TEST", "USER_FEEDBACK", "ONLINE_MONITORING")


def assert_defect(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["project_id"]
    assert data["module_id"]
    assert data["reporter_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["defect_source"] in DEFECT_SOURCES
    assert data["severity"] in DEFECT_SEVERITIES
    assert data["effective_severity"] in DEFECT_SEVERITIES
    assert data["business_impact"] in BUSINESS_IMPACTS
    assert isinstance(data["reproduction_steps"], str)
    env = data["environment"]
    assert isinstance(env, dict)
    for key in ("os", "browser", "app_version", "build_id"):
        assert key in env and env[key], (
            f"environment.{key} must be non-empty per PRD §3.2"
        )
    assert isinstance(data["priority_score"], int)
    assert data["status"] in DEFECT_STATUSES
    assert data["sla_state"] in ("RUNNING", "PAUSED")
    assert isinstance(data["reopen_count"], int)
    assert data["reopen_count"] >= 0
    assert isinstance(data["total_paused_minutes"], int)
    assert data["total_paused_minutes"] >= 0
    assert isinstance(data["report_clock_minute"], int)
    assert data["report_clock_minute"] >= 0
    assert isinstance(data["response_due_minute"], int)
    assert isinstance(data["resolution_due_minute"], int)
    assert isinstance(data["escalation_level"], int)
    assert data["escalation_level"] in (0, 1, 2)
    # assignee_id may be null while NEW (PRD §3.2)
    if data["status"] == "NEW":
        assert data.get("assignee_id") in (None, ""), (
            "PRD §3.2: assignee_id is null until first assignment"
        )


# ---------------------------------------------------------------------------
# Severity Override
# ---------------------------------------------------------------------------
def assert_severity_override(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["defect_id"]
    assert data["requested_severity"] in DEFECT_SEVERITIES
    assert isinstance(data["justification"], str) and data["justification"]
    assert data["requested_by"]
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")
    if data["status"] == "APPROVED":
        assert data.get("approved_by"), (
            "PRD §3.3: approved_by populated on approve"
        )


# ---------------------------------------------------------------------------
# Append-only entities
# ---------------------------------------------------------------------------
def assert_fix_record(data: Dict[str, Any]) -> None:
    """PRD §2.4: FixRecord is append-only (no updated_at, no version)."""
    _assert_append_only_fields(data)
    assert data["defect_id"]
    assert data["fix_version"]
    assert data["developer_id"]
    assert data["fix_summary"]
    assert isinstance(data["commit_sha"], str)
    sha = data["commit_sha"]
    assert 7 <= len(sha) <= 64
    assert all(c in "0123456789abcdefABCDEF" for c in sha)
    # Append-only: must NOT carry updated_at / version
    assert "updated_at" not in data, (
        "FixRecord is append-only per PRD §2.4; updated_at must not appear"
    )
    assert "version" not in data, (
        "FixRecord is append-only per PRD §2.4; version must not appear"
    )


def assert_verification_record(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["defect_id"]
    assert data["fix_record_id"]
    assert data["verifier_id"]
    assert data["outcome"] in ("PASSED", "FAILED")
    assert "updated_at" not in data
    assert "version" not in data


def assert_sla_pause(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["defect_id"]
    assert isinstance(data["started_at_minute"], int)
    assert data["reason"] in ("WAITING_ON_REPORTER", "WAITING_ON_THIRD_PARTY")
    assert data["paused_by"]
    # ended_at_minute is null while open, integer when closed
    end = data.get("ended_at_minute")
    assert end is None or isinstance(end, int)
    assert "updated_at" not in data
    assert "version" not in data


def assert_attachment(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["defect_id"]
    assert data["attachment_type"] in ("SCREENSHOT", "LOG", "VIDEO")
    assert isinstance(data["filename"], str) and data["filename"]
    assert isinstance(data["size_bytes"], int) and data["size_bytes"] > 0
    assert data["uploaded_by"]
    assert "updated_at" not in data
    assert "version" not in data


def assert_duplicate_link(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["duplicate_defect_id"]
    assert data["canonical_defect_id"]
    assert data["duplicate_defect_id"] != data["canonical_defect_id"]
    assert data["linked_by"]
    assert isinstance(data["similarity_score"], (int, float))
    assert 0.0 <= data["similarity_score"] <= 1.0
    assert "updated_at" not in data
    assert "version" not in data


def assert_audit_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["event_type"] in (
        "STATUS_CHANGE",
        "SEVERITY_CHANGE",
        "ASSIGNMENT_CHANGE",
        "SLA_PAUSE",
        "SLA_RESUME",
        "ESCALATION",
        "EXTERNAL_EVENT_SYNC",
    )
    assert data["actor_id"]
    assert isinstance(data["at_minute"], int)
    assert "updated_at" not in data
    assert "version" not in data


# ---------------------------------------------------------------------------
# RegressionRun
# ---------------------------------------------------------------------------
def assert_regression_run(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["defect_id"]
    assert data["module_id"]
    assert data["test_suite_key"]
    assert isinstance(data["started_at_minute"], int)
    assert data["status"] in ("QUEUED", "RUNNING", "PASSED", "FAILED")
    assert isinstance(data["impact_scope"], list)


# ---------------------------------------------------------------------------
# Audit utilities
# ---------------------------------------------------------------------------
def find_audit_entries(
    entries: List[Dict[str, Any]],
    *,
    event_type: Optional[str] = None,
    from_value: Optional[str] = None,
    to_value: Optional[str] = None,
    defect_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter a list of AuditEntry rows by any combination of fields."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if event_type is not None and e.get("event_type") != event_type:
            continue
        if from_value is not None and str(e.get("from_value")) != str(
            from_value
        ):
            continue
        if to_value is not None and str(e.get("to_value")) != str(to_value):
            continue
        if defect_id is not None and e.get("defect_id") != defect_id:
            continue
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Compensating-invariant helpers
# ---------------------------------------------------------------------------
def assert_elapsed_time_invariant(
    defect: Dict[str, Any],
    project_clock_minute: int,
) -> None:
    """PRD §3.8 (paraphrasing the invariant captured in the resume side
    effect): 'compensating invariant: total_paused_minutes +
    active_running_minutes == project.clock_minute -
    defect.report_clock_minute'. Used in sla_pause_resume cycle tests."""
    elapsed = project_clock_minute - int(defect["report_clock_minute"])
    paused = int(defect["total_paused_minutes"])
    assert paused <= elapsed, (
        f"total_paused_minutes ({paused}) > elapsed ({elapsed})"
    )
    # active_running_minutes is implicit (= elapsed - paused), always
    # non-negative when paused <= elapsed.


__all__ = [
    "DEFECT_STATUSES",
    "NON_TERMINAL_DEFECT_STATUSES",
    "DEFECT_SEVERITIES",
    "BUSINESS_IMPACTS",
    "DEFECT_SOURCES",
    "assert_project",
    "assert_module",
    "assert_module_quota_invariant",
    "assert_team_member",
    "assert_defect",
    "assert_severity_override",
    "assert_fix_record",
    "assert_verification_record",
    "assert_sla_pause",
    "assert_attachment",
    "assert_duplicate_link",
    "assert_audit_entry",
    "assert_regression_run",
    "find_audit_entries",
    "assert_elapsed_time_invariant",
]
