"""Payload factories — one per endpoint that takes a body.

Factories emit input fields only (PRD-exact field names). Every factory
accepts **overrides so tests can pin the precise value under assertion
(boundary, threshold, exact total) while keeping defaults sensible for
unrelated fields.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional


# ===========================================================================
# Uniqueness helpers — keep payloads collision-free across tests
# ===========================================================================
def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def unique_email() -> str:
    return f"contact+{unique_suffix()}@example.com"


def unique_name(prefix: str) -> str:
    return f"{prefix}-{unique_suffix()}"


# ===========================================================================
# ISO 8601 datetime helpers (PRD §2.4)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _server_now() -> datetime:
    """Best-effort query of the platform clock.

    PRD §2.10: 'the platform clock advances only via the test-driving
    /_clock/advance endpoint.' Tests in earlier modules may have advanced
    the clock; subsequent fixtures that compute deadlines from wall-clock
    time would otherwise be in the server clock's past.

    We anchor against the server's most recent api_request_timestamp,
    obtained by making a cheap GET (audit-entries list with limit=1).
    Falls back to wall clock if anything goes wrong.
    """
    try:
        from .api_client import api_client
        from .test_users import TEST_USERS
        resp = api_client.list_audit_entries(
            TEST_USERS["project_manager_headers"],
            params={"limit": 1, "offset": 0},
        )
        ts = resp.json().get("meta", {}).get("api_request_timestamp")
        if ts:
            s = ts
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    return datetime.now(timezone.utc)


def future_iso(days: int = 30) -> str:
    """Return an ISO 8601 timestamp `days` ahead of the platform clock."""
    return iso_z(_server_now() + timedelta(days=days))


def future_iso_hours(hours: int) -> str:
    """Return an ISO 8601 timestamp `hours` ahead of the platform clock."""
    return iso_z(_server_now() + timedelta(hours=hours))


# ===========================================================================
# Client (PRD §3.1)
# ===========================================================================
def create_client_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": unique_name("Client"),
        "contact_email": unique_email(),
        "tax_rate_bps": 0,
        "payment_cycle_days": 0,
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Translator (PRD §3.1)
# ===========================================================================
def create_translator_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "display_name": unique_name("Translator"),
        "language_pairs": [
            {"source_lang": "en", "target_lang": "fr"},
        ],
        "domains": ["GENERAL"],
        "grade": "JUNIOR",
    }
    defaults.update(overrides)
    return defaults


def language_pair(source: str = "en", target: str = "fr") -> Dict[str, str]:
    return {"source_lang": source, "target_lang": target}


# ===========================================================================
# Project (PRD §3.2)
# ===========================================================================
def create_project_payload(client_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "client_id": client_id,
        "name": unique_name("Project"),
        "source_lang": "en",
        "target_lang": "fr",
        "domain": "GENERAL",
        "deadline_at": future_iso(days=30),
        "unit_pricing_mode": "PER_WORD",
        "base_unit_price_cents": 100,
        "package_size_segments": 50,
    }
    defaults.update(overrides)
    return defaults


def update_project_payload(**overrides: Any) -> Dict[str, Any]:
    # No defaults — caller supplies only the fields to update.
    return dict(overrides)


# ===========================================================================
# Project Template (PRD §3.2)
# ===========================================================================
def create_project_template_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": unique_name("Template"),
        "default_domain": "GENERAL",
        "default_unit_pricing_mode": "PER_WORD",
        "default_base_unit_price_cents": 100,
        "default_package_size_segments": 50,
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Document & Split (PRD §3.2)
# ===========================================================================
def upload_document_payload(raw_text: str = "Hello world.",
                            **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "filename": unique_name("doc") + ".docx",
        "file_format": "DOCX",
        "split_mode": "SENTENCE",
        "raw_text": raw_text,
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Segment workflow (PRD §3.4)
# ===========================================================================
def submit_translation_payload(translated_text: str = "Bonjour le monde.",
                               **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"translated_text": translated_text}
    defaults.update(overrides)
    return defaults


def submit_review_payload(reviewed_text: str = "Bonjour le monde.",
                          **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"reviewed_text": reviewed_text}
    defaults.update(overrides)
    return defaults


def reject_segment_payload(reason: str = "rework",
                           errors: Optional[List[Dict[str, Any]]] = None,
                           **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"reason": reason}
    if errors is not None:
        defaults["errors"] = errors
    defaults.update(overrides)
    return defaults


def make_error_item(category: str = "MISTRANSLATION",
                    severity: str = "MAJOR",
                    count: int = 1) -> Dict[str, Any]:
    return {"category": category, "severity": severity, "count": count}


# ===========================================================================
# Assignment (PRD §3.3)
# ===========================================================================
def dispatch_assignment_payload(translator_id: str,
                                role: str,
                                segment_ids: List[str],
                                **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "translator_id": translator_id,
        "role": role,
        "segment_ids": list(segment_ids),
    }
    defaults.update(overrides)
    return defaults


def reject_assignment_payload(reason: str = "unavailable",
                              **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"reason": reason}
    defaults.update(overrides)
    return defaults


def reassign_assignment_payload(reason: str = "STALE",
                                **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Terminology (PRD §3.5)
# ===========================================================================
def create_terminology_payload(scope_type: str,
                               scope_id: str,
                               source_term: str,
                               target_term: str,
                               source_lang: str = "en",
                               target_lang: str = "fr",
                               **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_term": source_term,
        "target_term": target_term,
    }
    defaults.update(overrides)
    return defaults


def resolve_terminology_payload(loser_id: str,
                                **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"loser_id": loser_id}
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Quality Score (PRD §3.6)
# ===========================================================================
def create_quality_score_payload(segment_id: str,
                                 errors: Optional[List[Dict[str, Any]]] = None,
                                 **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "segment_id": segment_id,
        "errors": errors if errors is not None else [],
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Test-driving clock (PRD §2.10, §4)
# ===========================================================================
def clock_payload(seconds: int) -> Dict[str, Any]:
    return {"seconds": int(seconds)}


__all__ = [
    "unique_suffix", "unique_email", "unique_name",
    "iso_z", "future_iso", "future_iso_hours",
    "create_client_payload",
    "create_translator_payload", "language_pair",
    "create_project_payload", "update_project_payload",
    "create_project_template_payload",
    "upload_document_payload",
    "submit_translation_payload", "submit_review_payload",
    "reject_segment_payload", "make_error_item",
    "dispatch_assignment_payload",
    "reject_assignment_payload", "reassign_assignment_payload",
    "create_terminology_payload", "resolve_terminology_payload",
    "create_quality_score_payload",
    "clock_payload",
]
