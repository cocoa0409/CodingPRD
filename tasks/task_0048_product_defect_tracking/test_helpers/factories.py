"""Payload factories — one per endpoint that accepts a body. Only the
fields PRD §3 names as inputs are emitted; server-populated fields
(requested_by, paused_by, etc.) are NEVER included in the payload.

Every factory returns sensible defaults and accepts **overrides so tests
can pin a single field while leaving the rest at defaults.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def unique_suffix() -> str:
    """Short unique suffix for keys / titles to keep tests independent."""
    return uuid.uuid4().hex[:8]


def default_environment() -> Dict[str, str]:
    """PRD §3.2: 'environment object must contain all four sub-keys
    os, browser, app_version, and build_id, each non-empty'."""
    return {
        "os": "macOS 14.5",
        "browser": "Chrome 124",
        "app_version": "1.0.0",
        "build_id": "build-9001",
    }


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
def create_project_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_key": f"P{unique_suffix().upper()}",
        "name": f"Test Project {unique_suffix()}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------
def create_module_payload(
    owner_team_member_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "module_key": f"M{unique_suffix().upper()}",
        "owner_team_member_id": owner_team_member_id,
        "kloc": 2.0,
        "initial_defect_quota": 5,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TeamMember
# ---------------------------------------------------------------------------
def create_team_member_payload(
    role: str = "DEVELOPER",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "display_name": f"Member {unique_suffix()}",
        "role": role,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Defect
# ---------------------------------------------------------------------------
def create_defect_payload(
    project_id: str,
    module_id: str,
    reporter_id: str,
    *,
    title: Optional[str] = None,
    defect_source: str = "INTERNAL_TEST",
    severity: str = "MAJOR",
    business_impact: str = "INTERNAL",
    reproduction_steps: str = "1. Open app  2. Reproduce  3. Observe bug",
    environment: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: required body fields are project_id, module_id,
    reporter_id, title, defect_source, severity, business_impact,
    reproduction_steps, environment."""
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "module_id": module_id,
        "reporter_id": reporter_id,
        "title": title or f"Test defect {unique_suffix()}",
        "defect_source": defect_source,
        "severity": severity,
        "business_impact": business_impact,
        "reproduction_steps": reproduction_steps,
        "environment": environment if environment is not None
        else default_environment(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Assign / Reassign
# ---------------------------------------------------------------------------
def assign_payload(
    assignee_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if assignee_id is not None:
        payload["assignee_id"] = assignee_id
    payload.update(overrides)
    return payload


def reassign_payload(
    new_assignee_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_assignee_id": new_assignee_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Submit fix
# ---------------------------------------------------------------------------
def submit_fix_payload(
    *,
    fix_version: str = "1.0.1",
    fix_summary: str = "Patched root cause in submit-fix factory.",
    commit_sha: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: body carries fix_version, fix_summary, and commit_sha
    (7-64 hex chars)."""
    if commit_sha is None:
        # 40-char hex sha — within the 7-64 hex char range.
        commit_sha = uuid.uuid4().hex
    payload: Dict[str, Any] = {
        "fix_version": fix_version,
        "fix_summary": fix_summary,
        "commit_sha": commit_sha,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def verify_payload(
    outcome: str,
    fix_record_id: str,
    *,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: body carries outcome (PASSED or FAILED), fix_record_id,
    optional notes."""
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "fix_record_id": fix_record_id,
    }
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pause / Resume SLA
# ---------------------------------------------------------------------------
def pause_sla_payload(
    reason: str = "WAITING_ON_REPORTER",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: pause-sla body carries reason
    (WAITING_ON_REPORTER or WAITING_ON_THIRD_PARTY)."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
def attachment_payload(
    *,
    attachment_type: str = "SCREENSHOT",
    filename: str = "screenshot.png",
    size_bytes: int = 1_024,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "attachment_type": attachment_type,
        "filename": filename,
        "size_bytes": size_bytes,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Duplicate link
# ---------------------------------------------------------------------------
def duplicate_link_payload(
    duplicate_defect_id: str,
    canonical_defect_id: str,
    *,
    similarity_score: float = 0.85,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "duplicate_defect_id": duplicate_defect_id,
        "canonical_defect_id": canonical_defect_id,
        "similarity_score": similarity_score,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Severity override
# ---------------------------------------------------------------------------
def severity_override_payload(
    requested_severity: str,
    *,
    justification: str = "Business case for severity change.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requested_severity": requested_severity,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Regression run
# ---------------------------------------------------------------------------
def regression_run_payload(
    *,
    test_suite_key: str = "smoke",
    impact_scope: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10: regression-runs body carries test_suite_key and
    impact_scope (list of module_ids that must include defect.module_id)."""
    if impact_scope is None:
        impact_scope = []
    payload: Dict[str, Any] = {
        "test_suite_key": test_suite_key,
        "impact_scope": list(impact_scope),
    }
    payload.update(overrides)
    return payload


def regression_complete_payload(
    result: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": result}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Event emit
# ---------------------------------------------------------------------------
def emit_event_payload(
    defect_id: str,
    system: str,
    raw_payload: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.12: body carries defect_id, system (VCS/CI_CD/IM),
    raw_payload object."""
    payload: Dict[str, Any] = {
        "defect_id": defect_id,
        "system": system,
        "raw_payload": dict(raw_payload),
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix",
    "default_environment",
    "create_project_payload",
    "create_module_payload",
    "create_team_member_payload",
    "create_defect_payload",
    "assign_payload",
    "reassign_payload",
    "submit_fix_payload",
    "verify_payload",
    "pause_sla_payload",
    "attachment_payload",
    "duplicate_link_payload",
    "severity_override_payload",
    "regression_run_payload",
    "regression_complete_payload",
    "emit_event_payload",
]
