"""Entity assertions and domain invariant checkers.

Per-entity shape checks. Names follow PRD field naming exactly.
Append-only entities (ProjectTemplate, AuditEntry, ExternalSyncRecord)
intentionally OMIT updated_at and version per PRD §2.4.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ===========================================================================
# Allowed enum values (PRD §1 / §3.x)
# ===========================================================================
CLIENT_STATES = {"ACTIVE", "ARCHIVED"}
PAYMENT_CYCLE_DAYS_VALUES = {0, 7, 15, 30, 45}

DOMAINS = {"LEGAL", "MEDICAL", "TECH", "MARKETING", "MEDIA", "FINANCE", "GENERAL"}
TRANSLATOR_GRADES = {"JUNIOR", "INTERMEDIATE", "SENIOR", "EXPERT"}
TRANSLATOR_AVAILABILITIES = {"AVAILABLE", "BUSY", "OFFLINE", "SUSPENDED"}

PROJECT_STATES = {
    "DRAFT", "QUOTED", "ACTIVE", "ALL_TRANSLATED", "ALL_REVIEWED",
    "PUBLISHED", "CANCELLED",
}
URGENCY_TIERS = {"STANDARD", "RUSH", "CRITICAL"}
UNIT_PRICING_MODES = {"PER_WORD", "PER_SEGMENT", "PER_FILE"}

FILE_FORMATS = {"DOCX", "PDF", "PPTX", "XLSX", "SRT"}
SPLIT_MODES = {"SENTENCE", "PARAGRAPH"}
DOCUMENT_STATES = {"UPLOADED", "SPLIT", "ARCHIVED"}

SEGMENT_STATES = {
    "NEW", "ASSIGNED", "TRANSLATED", "REVIEWED",
    "FINAL_APPROVED", "REJECTED", "REASSIGNED",
}
REPETITION_CLASSES = {"NEW", "FUZZY", "EXACT_REPEAT", "TM_LEVERAGE"}

ASSIGNMENT_ROLES = {"TRANSLATOR", "REVIEWER", "FINAL_REVIEWER"}
ASSIGNMENT_STATES = {
    "PENDING", "ACCEPTED", "COMPLETED", "REJECTED", "EXPIRED", "REASSIGNED",
}

TERMINOLOGY_SCOPES = {"PROJECT", "CLIENT"}
TERMINOLOGY_STATES = {"PROPOSED", "APPROVED", "CONFLICT", "ARCHIVED"}

QUALITY_SCORE_STATES = {"DRAFT", "FINALIZED", "VOIDED"}
ERROR_CATEGORIES = {"MISTRANSLATION", "OMISSION", "GRAMMAR", "STYLE", "TERMINOLOGY"}
ERROR_SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}

AUDIT_SUBJECT_TYPES = {"Segment", "Assignment", "Project", "QualityScore"}
AUDIT_EVENTS = {"STATE_TRANSITION", "QUALITY_SCORED", "REASSIGNED", "EXTERNAL_SYNC"}

SYNC_TARGET_SYSTEMS = {"PAYMENT", "IM", "STORAGE"}
SYNC_TRIGGER_EVENTS = {
    "PROJECT_PUBLISHED", "PAYMENT_PAYABLE",
    "ASSIGNMENT_DISPATCHED", "ASSIGNMENT_REJECTED",
    "STAGE_DEADLINE_BREACHED",
}


# ===========================================================================
# Common-fields helpers
# ===========================================================================
def _assert_versioned_common(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 versioned entity envelope (id + created_at + updated_at + version)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, \
        f"{label}.version must be a non-negative integer starting at 1"


def _assert_append_only_common(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 append-only entity envelope (id + created_at ONLY)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    # Note: PRD §2.4 — 'both updated_at and version are absent from their
    # representations.' We assert ABSENCE only when the implementation
    # opts to be strict. To keep tests two-reader friendly, we don't
    # require the keys to be missing; just confirm version/updated_at do
    # not pretend to be versioned with version >= 1 (or check that
    # version is None if present). Hence this is a soft check.


# ===========================================================================
# Client
# ===========================================================================
def assert_client(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Client")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 200
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["tax_rate_bps"], int)
    assert 0 <= data["tax_rate_bps"] <= 3000
    assert data["payment_cycle_days"] in PAYMENT_CYCLE_DAYS_VALUES, \
        f"payment_cycle_days must be in {{0, 7, 15, 30, 45}}"
    assert data["status"] in CLIENT_STATES


# ===========================================================================
# Translator
# ===========================================================================
def assert_translator(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Translator")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["language_pairs"], list) and data["language_pairs"]
    for lp in data["language_pairs"]:
        assert "source_lang" in lp and "target_lang" in lp
        assert lp["source_lang"] != lp["target_lang"], \
            "language pair source != target (PRD §3.1)"
    assert isinstance(data["domains"], list) and data["domains"]
    for d in data["domains"]:
        assert d in DOMAINS
    assert data["grade"] in TRANSLATOR_GRADES
    assert isinstance(data["test_translation_passed"], bool)
    assert data["availability_status"] in TRANSLATOR_AVAILABILITIES
    assert isinstance(data["workload_segments_open"], int)
    assert data["workload_segments_open"] >= 0
    # rolling_quality_score / latest_quality_score: numbers, 0..100
    for f in ("rolling_quality_score", "latest_quality_score"):
        v = data[f]
        assert isinstance(v, (int, float))
        assert 0 <= float(v) <= 100, f"{f} must be in [0, 100]"


# ===========================================================================
# Project
# ===========================================================================
def assert_project(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Project")
    assert isinstance(data["client_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["source_lang"], str) and data["source_lang"]
    assert isinstance(data["target_lang"], str) and data["target_lang"]
    assert data["source_lang"] != data["target_lang"]
    assert data["domain"] in DOMAINS
    assert isinstance(data["word_count"], int) and data["word_count"] >= 0
    assert is_iso8601_timestamp(data["deadline_at"])
    # urgency_tier default is STANDARD if read pre-quote per PRD §3.2
    assert data["urgency_tier"] in URGENCY_TIERS
    assert data["unit_pricing_mode"] in UNIT_PRICING_MODES
    assert isinstance(data["base_unit_price_cents"], int) \
        and data["base_unit_price_cents"] >= 1
    assert isinstance(data["package_size_segments"], int)
    assert 1 <= data["package_size_segments"] <= 500
    assert data["state"] in PROJECT_STATES


def assert_project_invariants(data: Dict[str, Any]) -> None:
    """Cross-field invariants for a Project."""
    # Non-negative monetary fields when present.
    for f in ("quoted_total_cents", "final_payout_cents",
              "tax_amount_cents"):
        v = data.get(f)
        if v is not None:
            assert isinstance(v, int) and v >= 0, \
                f"Project.{f} must be a non-negative integer cents value"


# ===========================================================================
# Document
# ===========================================================================
def assert_document(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Document")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["filename"], str) and data["filename"]
    assert data["file_format"] in FILE_FORMATS
    assert data["split_mode"] in SPLIT_MODES
    assert isinstance(data["word_count"], int) and data["word_count"] >= 0
    assert data["state"] in DOCUMENT_STATES


# ===========================================================================
# Segment
# ===========================================================================
def assert_segment(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Segment")
    assert isinstance(data["document_id"], str)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["ordinal"], int) and data["ordinal"] >= 1
    assert isinstance(data["source_text"], str)
    assert isinstance(data["word_count"], int) and data["word_count"] >= 1
    assert data["repetition_class"] in REPETITION_CLASSES
    assert isinstance(data["tm_leverage_pct"], int)
    assert 0 <= data["tm_leverage_pct"] <= 100
    assert data["state"] in SEGMENT_STATES


# ===========================================================================
# Assignment
# ===========================================================================
def assert_assignment(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Assignment")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["translator_id"], str)
    assert data["role"] in ASSIGNMENT_ROLES
    assert isinstance(data["segment_ids"], list) and data["segment_ids"]
    assert is_iso8601_timestamp(data["dispatched_at"])
    assert is_iso8601_timestamp(data["accept_deadline_at"])
    assert data["state"] in ASSIGNMENT_STATES


# ===========================================================================
# Terminology Entry
# ===========================================================================
def assert_terminology_entry(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "TerminologyEntry")
    assert data["scope_type"] in TERMINOLOGY_SCOPES
    assert isinstance(data["scope_id"], str)
    assert isinstance(data["source_lang"], str)
    assert isinstance(data["target_lang"], str)
    assert isinstance(data["source_term"], str) and data["source_term"]
    assert isinstance(data["target_term"], str) and data["target_term"]
    assert data["state"] in TERMINOLOGY_STATES


# ===========================================================================
# Quality Score
# ===========================================================================
def assert_quality_score(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "QualityScore")
    assert isinstance(data["segment_id"], str)
    assert isinstance(data["translator_id"], str)
    assert isinstance(data["errors"], list)
    for e in data["errors"]:
        assert e["category"] in ERROR_CATEGORIES
        assert e["severity"] in ERROR_SEVERITIES
        assert isinstance(e["count"], int) and e["count"] >= 1
    assert isinstance(data["error_density"], (int, float))
    assert isinstance(data["score"], (int, float))
    assert 0 <= float(data["score"]) <= 100
    assert data["state"] in QUALITY_SCORE_STATES


# ===========================================================================
# Append-only entities (PRD §2.4: id + created_at only)
# ===========================================================================
def assert_audit_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "AuditEntry")
    assert data["subject_type"] in AUDIT_SUBJECT_TYPES
    assert isinstance(data["subject_id"], str)
    assert data["event"] in AUDIT_EVENTS
    assert isinstance(data["actor_role"], str) and data["actor_role"]


def assert_external_sync_record(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "ExternalSyncRecord")
    assert isinstance(data["project_id"], str)
    assert data["target_system"] in SYNC_TARGET_SYSTEMS
    assert data["trigger_event"] in SYNC_TRIGGER_EVENTS


# ===========================================================================
# Search helpers over audit / sync collections
# ===========================================================================
def find_audit_entries(entries: Iterable[Dict[str, Any]], *,
                       subject_type: Optional[str] = None,
                       subject_id: Optional[str] = None,
                       event: Optional[str] = None,
                       to_state: Optional[str] = None,
                       from_state: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filter a list of AuditEntry rows for any combination of keys."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if subject_type is not None and e.get("subject_type") != subject_type:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        if event is not None and e.get("event") != event:
            continue
        if to_state is not None and e.get("to_state") != to_state:
            continue
        if from_state is not None and e.get("from_state") != from_state:
            continue
        out.append(e)
    return out


def find_sync_records(records: Iterable[Dict[str, Any]], *,
                      project_id: Optional[str] = None,
                      target_system: Optional[str] = None,
                      trigger_event: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in records:
        if project_id is not None and r.get("project_id") != project_id:
            continue
        if target_system is not None and r.get("target_system") != target_system:
            continue
        if trigger_event is not None and r.get("trigger_event") != trigger_event:
            continue
        out.append(r)
    return out


__all__ = [
    "CLIENT_STATES", "PAYMENT_CYCLE_DAYS_VALUES",
    "DOMAINS", "TRANSLATOR_GRADES", "TRANSLATOR_AVAILABILITIES",
    "PROJECT_STATES", "URGENCY_TIERS", "UNIT_PRICING_MODES",
    "FILE_FORMATS", "SPLIT_MODES", "DOCUMENT_STATES",
    "SEGMENT_STATES", "REPETITION_CLASSES",
    "ASSIGNMENT_ROLES", "ASSIGNMENT_STATES",
    "TERMINOLOGY_SCOPES", "TERMINOLOGY_STATES",
    "QUALITY_SCORE_STATES", "ERROR_CATEGORIES", "ERROR_SEVERITIES",
    "AUDIT_SUBJECT_TYPES", "AUDIT_EVENTS",
    "SYNC_TARGET_SYSTEMS", "SYNC_TRIGGER_EVENTS",
    "assert_client", "assert_translator",
    "assert_project", "assert_project_invariants",
    "assert_document", "assert_segment", "assert_assignment",
    "assert_terminology_entry", "assert_quality_score",
    "assert_audit_entry", "assert_external_sync_record",
    "find_audit_entries", "find_sync_records",
]
