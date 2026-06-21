"""Common-field management for entities (PRD §2.4).

Entities carrying the full common set (id, created_at, updated_at, version):
  Term, Student, Course, Instructor, Section, EnrollmentAppointment,
  Enrollment, Hold, SwapRequest.

Immutable entities carrying only id + created_at (no updated_at, no version):
  Program, CourseRequirement, RefundTransaction.
"""
from __future__ import annotations

from typing import Any, Dict

import db

# Entities that carry updated_at + version.
VERSIONED = {
    "Term", "Student", "Course", "Instructor", "Section",
    "EnrollmentAppointment", "Enrollment", "Hold", "SwapRequest",
}


def new_common(kind: str) -> Dict[str, Any]:
    """Build the common system fields for a new entity of the given kind."""
    ts = db.now_iso()
    rec: Dict[str, Any] = {
        "id": db.new_uuid(),
        "created_at": ts,
        # internal monotonic sequence for deterministic tie-breaking; never
        # serialized to clients.
        "_seq": db.next_seq(),
    }
    if kind in VERSIONED:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec: Dict[str, Any]) -> None:
    """Record a mutation: refresh updated_at and bump version (PRD §2.4).

    A no-op for immutable entities (those without updated_at/version), which are
    never edited after creation.
    """
    if "updated_at" in rec:
        rec["updated_at"] = db.now_iso()
    if "version" in rec:
        rec["version"] = rec["version"] + 1
