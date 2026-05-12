"""Payload factories — one per entity, input fields only.

Field names match PRD §3 verbatim. Each factory accepts **overrides so
individual tests can pin specific values (boundary, threshold, edge case).
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-id helpers
# ---------------------------------------------------------------------------
def unique_id(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_project_name(prefix: str = "Project") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_display_name(prefix: str = "Annotator") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def unique_cycle_label(prefix: str = "Cycle") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_url(prefix: str = "https://example.test") -> str:
    return f"{prefix}/{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# AnnotationProject (PRD §3.1)
# ---------------------------------------------------------------------------
def create_project_payload(
    *,
    project_name: Optional[str] = None,
    task_type: str = "CLASSIFICATION",
    difficulty: str = "EASY",
    guideline_doc_url: Optional[str] = None,
    sample_preview_urls: Optional[List[str]] = None,
    package_size: int = 10,
    distribution_mode: str = "GRAB",
    unit_price_cents: int = 100,
    pass_rate_target: float = 0.80,
    timeout_seconds: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_name": project_name or unique_project_name(),
        "task_type": task_type,
        "difficulty": difficulty,
        "guideline_doc_url": guideline_doc_url or unique_url(
            "https://example.test/guideline"
        ),
        "sample_preview_urls": (
            sample_preview_urls
            if sample_preview_urls is not None
            else [unique_url("https://example.test/preview")]
        ),
        "package_size": package_size,
        "distribution_mode": distribution_mode,
        "unit_price_cents": unit_price_cents,
        "pass_rate_target": pass_rate_target,
    }
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    payload.update(overrides)
    return payload


def patch_project_payload(*, version: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.5: PATCH may include version for optimistic concurrency."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# GoldenSample (PRD §3.1)
# ---------------------------------------------------------------------------
def create_golden_sample_payload(
    *,
    payload_url: Optional[str] = None,
    expected_label: Any = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "payload_url": payload_url or unique_url(
            "https://example.test/golden"
        ),
        "expected_label": (
            expected_label
            if expected_label is not None
            else {"class": "cat"}
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TaskPackage split (PRD §3.1)
# ---------------------------------------------------------------------------
def split_packages_payload(
    *,
    total_item_count: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"total_item_count": total_item_count}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TaskPackage actions (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
def dispatch_package_payload(
    *,
    annotator_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"annotator_id": annotator_id}
    payload.update(overrides)
    return payload


def submit_package_payload(
    *,
    labels: List[Any],
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'the length of labels must equal package.item_count'."""
    payload: Dict[str, Any] = {"labels": labels}
    payload.update(overrides)
    return payload


def labels_for_count(item_count: int, label: Any = "A") -> List[Any]:
    """Build a uniform label array of the given length."""
    return [label for _ in range(item_count)]


def finalize_inspection_payload(
    *,
    outcome: str,
    defects_found: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: outcome in {PASS, FAIL}; defects_found in [0, sample_size]."""
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "defects_found": defects_found,
    }
    payload.update(overrides)
    return payload


def arbitrate_payload(
    *,
    decision: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: decision in {APPROVE, REJECT}."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appeal (PRD §3.8)
# ---------------------------------------------------------------------------
def create_appeal_payload(
    *,
    inspection_id: str,
    reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inspection_id": inspection_id,
        "reason": reason or "Disputed defects.",
    }
    payload.update(overrides)
    return payload


def decide_appeal_payload(
    *,
    decision: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: decision in {UPHOLD, REJECT}."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AnnotatorProfile (PRD §3.2)
# ---------------------------------------------------------------------------
def create_annotator_payload(
    *,
    display_name: Optional[str] = None,
    domain_tags: Optional[List[str]] = None,
    entry_test_score: float = 70.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "display_name": display_name or unique_display_name(),
        "domain_tags": (
            domain_tags if domain_tags is not None else ["general"]
        ),
        "entry_test_score": entry_test_score,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PayrollPeriod (PRD §3.10)
# ---------------------------------------------------------------------------
def create_payroll_period_payload(
    *,
    cycle_label: Optional[str] = None,
    opens_at: str,
    closes_at: str,
    tax_rate: float = 0.10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_label": cycle_label or unique_cycle_label(),
        "opens_at": opens_at,
        "closes_at": closes_at,
        "tax_rate": tax_rate,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance (PRD §3.5)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to_iso: str) -> Dict[str, Any]:
    return {"to": to_iso}


__all__ = [
    "unique_id",
    "unique_project_name",
    "unique_display_name",
    "unique_cycle_label",
    "unique_url",
    "create_project_payload",
    "patch_project_payload",
    "create_golden_sample_payload",
    "split_packages_payload",
    "dispatch_package_payload",
    "submit_package_payload",
    "labels_for_count",
    "finalize_inspection_payload",
    "arbitrate_payload",
    "create_appeal_payload",
    "decide_appeal_payload",
    "create_annotator_payload",
    "create_payroll_period_payload",
    "clock_advance_payload",
]
