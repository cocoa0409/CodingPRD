"""Terminology library lifecycle + consistency check."""
from __future__ import annotations

from db import store
from services.common import touch


def _same_key(a: dict, b: dict) -> bool:
    return (
        a["scope_type"] == b["scope_type"]
        and a["scope_id"] == b["scope_id"]
        and a["source_lang"] == b["source_lang"]
        and a["target_lang"] == b["target_lang"]
        and a["source_term"] == b["source_term"]
    )


def detect_conflict_on_create(entry: dict) -> None:
    """When entry is created, find existing PROPOSED/APPROVED entries with the same
    key but different target_term: mark both as CONFLICT.

    TerminologyEntry isn't in the AuditEntry subject_type enum, so we do not emit an
    AuditEntry for terminology state transitions per the scaffold's enum constraints.
    """
    for other in list(store.terminology.values()):
        if other["id"] == entry["id"]:
            continue
        if other["state"] not in {"PROPOSED", "APPROVED"}:
            continue
        if _same_key(entry, other) and other["target_term"] != entry["target_term"]:
            other["state"] = "CONFLICT"
            touch(other)
            entry["state"] = "CONFLICT"
            touch(entry)


def project_has_open_terminology_conflict(project_id: str) -> bool:
    for t in store.terminology.values():
        if t["scope_type"] == "PROJECT" and t["scope_id"] == project_id and t["state"] == "CONFLICT":
            return True
    return False


def has_existing_approved(entry: dict) -> bool:
    """True if another APPROVED entry covers the same scope+term tuple."""
    for other in store.terminology.values():
        if other["id"] == entry["id"]:
            continue
        if other["state"] != "APPROVED":
            continue
        if _same_key(entry, other):
            return True
    return False
