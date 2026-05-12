"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks are pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares -- never more, never
less.
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
    """PRD §2.4: AnnotationProject, TaskPackage, AnnotatorProfile,
    QualityInspection, Appeal, PayrollPeriod each carry id + created_at +
    updated_at + version."""
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
    """PRD §2.4: GoldenSample, AnnotationSubmission, SalaryLedgerEntry,
    AuditLog, ExternalEvent each carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# AnnotationProject (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_annotation_project(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "AnnotationProject")
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert data["task_type"] in {
        "CLASSIFICATION", "BBOX", "SEGMENTATION", "KEYPOINT",
        "TEXT_NER", "AUDIO_TRANSCRIPTION",
    }
    assert data["difficulty"] in {"EASY", "MEDIUM", "HARD"}
    assert isinstance(data["guideline_doc_url"], str)
    assert isinstance(data["sample_preview_urls"], list)
    assert isinstance(data["package_size"], int)
    assert 10 <= data["package_size"] <= 500
    assert data["distribution_mode"] in {"GRAB", "DISPATCH", "HYBRID"}
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["pass_rate_target"], (int, float))
    assert 0.0 < float(data["pass_rate_target"]) <= 1.0
    assert isinstance(data["timeout_seconds"], int)
    assert data["timeout_seconds"] >= 60
    assert isinstance(data["golden_sample_count"], int)
    assert data["golden_sample_count"] >= 0
    assert data["status"] in {"DRAFT", "OPEN", "CLOSED", "ARCHIVED"}


# ---------------------------------------------------------------------------
# GoldenSample (PRD §3.1)  -- append-only
# ---------------------------------------------------------------------------
def assert_golden_sample(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "GoldenSample")
    assert "updated_at" not in data, (
        "GoldenSample must not expose updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "GoldenSample must not expose version (PRD §2.4)"
    )
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["payload_url"], str) and data["payload_url"]
    assert "expected_label" in data


# ---------------------------------------------------------------------------
# TaskPackage (PRD §3.1, §3.3, §3.4)
# ---------------------------------------------------------------------------
def assert_task_package(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "TaskPackage")
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["batch_no"], int) and data["batch_no"] >= 1
    assert isinstance(data["item_count"], int) and data["item_count"] >= 1
    assert isinstance(data["rework_round"], int) and data["rework_round"] >= 0
    assert data["status"] in {
        "POOL", "IN_PROGRESS", "SUBMITTED", "INSPECTING",
        "APPROVED", "REWORK_PENDING", "ARBITRATING", "REJECTED",
    }
    # tier_required is initialized at /open time per PRD §3.1.
    if data["status"] != "POOL" or "tier_required" in data:
        if data.get("tier_required") is not None:
            assert data["tier_required"] in {"JUNIOR", "SENIOR", "EXPERT"}
    # When in POOL, assigned_annotator_id / claimed_at / deadline_at are null.
    if data["status"] == "POOL":
        assert data.get("assigned_annotator_id") is None, (
            "POOL package must have assigned_annotator_id == null "
            "(PRD §3.1)"
        )
        assert data.get("claimed_at") is None, (
            "POOL package must have claimed_at == null (PRD §3.1)"
        )
        assert data.get("deadline_at") is None, (
            "POOL package must have deadline_at == null (PRD §3.1)"
        )


# ---------------------------------------------------------------------------
# AnnotatorProfile (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_annotator_profile(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "AnnotatorProfile")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["domain_tags"], list)
    assert isinstance(data["entry_test_score"], (int, float))
    assert 0 <= float(data["entry_test_score"]) <= 100
    assert data["tier"] in {"JUNIOR", "SENIOR", "EXPERT"}
    for fname in ("lifetime_pass_rate", "rolling_pass_rate", "golden_hit_rate"):
        v = data[fname]
        assert isinstance(v, (int, float))
        assert 0.0 <= float(v) <= 1.0, (
            f"{fname} must be in [0, 1], got {v!r}"
        )
    assert data["status"] in {"ACTIVE", "SUSPENDED"}
    if data.get("last_evaluated_at") is not None:
        assert is_iso8601_timestamp(data["last_evaluated_at"])


# ---------------------------------------------------------------------------
# AnnotationSubmission (PRD §3.4)  -- append-only
# ---------------------------------------------------------------------------
def assert_annotation_submission(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AnnotationSubmission")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["package_id"], str) and data["package_id"]
    assert isinstance(data["annotator_id"], str) and data["annotator_id"]
    assert isinstance(data["rework_round"], int) and data["rework_round"] >= 0
    assert isinstance(data["labels"], list)
    assert isinstance(data["golden_correct"], int)
    assert isinstance(data["golden_total"], int)
    assert 0 <= data["golden_correct"] <= data["golden_total"]


# ---------------------------------------------------------------------------
# QualityInspection (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_quality_inspection(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "QualityInspection")
    assert isinstance(data["package_id"], str) and data["package_id"]
    assert isinstance(data["submission_id"], str) and data["submission_id"]
    assert isinstance(data["inspector_id"], str) and data["inspector_id"]
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 1
    if "defects_found" in data and data["defects_found"] is not None:
        assert isinstance(data["defects_found"], int)
        assert 0 <= data["defects_found"] <= data["sample_size"]
    if "pass_rate" in data and data["pass_rate"] is not None:
        v = float(data["pass_rate"])
        assert 0.0 <= v <= 1.0
    outcome = data.get("outcome")
    if outcome is not None:
        assert outcome in {"PASS", "FAIL", "DISPUTED"}


# ---------------------------------------------------------------------------
# Appeal (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Appeal")
    assert isinstance(data["package_id"], str) and data["package_id"]
    assert isinstance(data["inspection_id"], str) and data["inspection_id"]
    assert isinstance(data["annotator_id"], str) and data["annotator_id"]
    assert isinstance(data["reason"], str)
    assert data["status"] in {
        "SUBMITTED", "UNDER_REVIEW", "UPHELD", "REJECTED",
    }
    if data.get("arbiter_id") is not None:
        assert isinstance(data["arbiter_id"], str) and data["arbiter_id"]
    if data.get("decision") is not None:
        assert data["decision"] in {"UPHELD", "REJECTED"}


# ---------------------------------------------------------------------------
# SalaryLedgerEntry (PRD §3.6, §3.10)  -- append-only
# ---------------------------------------------------------------------------
def assert_salary_ledger_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "SalaryLedgerEntry")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["annotator_id"], str) and data["annotator_id"]
    assert data["kind"] in {
        "PIECE_RATE", "BONUS", "PENALTY",
        "ADJUSTMENT_UPHELD", "ADJUSTMENT_REJECTED",
        "TAX", "WITHHOLD", "RELEASE",
    }
    assert isinstance(data["gross_amount_cents"], int)
    assert data["settlement_state"] in {"WITHHELD", "RELEASED"}


# ---------------------------------------------------------------------------
# PayrollPeriod (PRD §3.10)
# ---------------------------------------------------------------------------
def assert_payroll_period(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "PayrollPeriod")
    assert isinstance(data["cycle_label"], str) and data["cycle_label"]
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["closes_at"])
    assert isinstance(data["tax_rate"], (int, float))
    assert 0.0 <= float(data["tax_rate"]) <= 1.0
    assert data["status"] in {"OPEN", "LOCKED", "SETTLED"}


# ---------------------------------------------------------------------------
# AuditLog (PRD §3.11)  -- append-only
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditLog")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert data["subject_kind"] in {"TASK_PACKAGE", "SALARY"}
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert data["event_type"] in {"STATUS_CHANGE", "SALARY_ADJUSTMENT"}


# ---------------------------------------------------------------------------
# ExternalEvent (PRD §3.11)  -- append-only
# ---------------------------------------------------------------------------
def assert_external_event(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "ExternalEvent")
    assert "updated_at" not in data
    assert "version" not in data
    assert data["target_system"] in {"PAYMENT", "IM", "STORAGE"}
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["payload_ref_id"], str) and data["payload_ref_id"]
    assert data["dispatch_status"] in {"PENDING", "DISPATCHED"}


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def find_ledger_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    annotator_id: Optional[str] = None,
    package_id: Optional[str] = None,
    kind: Optional[str] = None,
    settlement_state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter ledger entries by annotator, package, kind, settlement state."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if annotator_id is not None and e.get("annotator_id") != annotator_id:
            continue
        if package_id is not None and e.get("package_id") != package_id:
            continue
        if kind is not None and e.get("kind") != kind:
            continue
        if (
            settlement_state is not None
            and e.get("settlement_state") != settlement_state
        ):
            continue
        out.append(e)
    return out


def find_audit_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if subject_kind is not None and e.get("subject_kind") != subject_kind:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        if event_type is not None and e.get("event_type") != event_type:
            continue
        out.append(e)
    return out


def find_external_events(
    entries: Iterable[Dict[str, Any]],
    *,
    target_system: Optional[str] = None,
    event_type: Optional[str] = None,
    payload_ref_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if (
            target_system is not None
            and e.get("target_system") != target_system
        ):
            continue
        if event_type is not None and e.get("event_type") != event_type:
            continue
        if (
            payload_ref_id is not None
            and e.get("payload_ref_id") != payload_ref_id
        ):
            continue
        out.append(e)
    return out


def assert_pass_rate_precision(value: float) -> None:
    """PRD §2.6: rates stored at four decimal places, round-half-up."""
    assert isinstance(value, (int, float))
    rounded4 = round(float(value) + 1e-12, 4)
    assert abs(float(value) - rounded4) < 1e-9, (
        f"value {value!r} not stored at four decimal places"
    )


__all__ = [
    "assert_annotation_project",
    "assert_golden_sample",
    "assert_task_package",
    "assert_annotator_profile",
    "assert_annotation_submission",
    "assert_quality_inspection",
    "assert_appeal",
    "assert_salary_ledger_entry",
    "assert_payroll_period",
    "assert_audit_log",
    "assert_external_event",
    "find_ledger_entries",
    "find_audit_entries",
    "find_external_events",
    "assert_pass_rate_precision",
]
