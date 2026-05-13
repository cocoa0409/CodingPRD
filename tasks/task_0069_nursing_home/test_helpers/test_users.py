"""Pre-built role headers for every role in the PRD.

PRD §2.1: 'None of the eight roles is backed by a persisted entity of its
own; for every role in this list, X-User-ID is an opaque operator identifier
not tied to any stored entity row.' All eight roles are therefore OPAQUE
and a shared-constant X-User-ID is the canonical form. Per-instance
builders (``make_<role>_headers``) are still exposed so that tests
exercising segregation-of-duties (e.g., assessor vs approver,
prescriber vs nurse, nurse vs witness) can mint distinct identifiers
on demand — these are NOT entity-id lookups, just unique strings.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers":        build_user_headers("admin-001",        "Admin"),
    "admin_headers_alt":    build_user_headers("admin-002",        "Admin"),
    "supervisor_headers":   build_user_headers("supervisor-001",   "Supervisor"),
    "supervisor_headers_alt": build_user_headers("supervisor-002", "Supervisor"),
    "physician_headers":    build_user_headers("physician-001",    "Physician"),
    "physician_headers_alt": build_user_headers("physician-002",   "Physician"),
    "nurse_headers":        build_user_headers("nurse-001",        "Nurse"),
    "nurse_headers_alt":    build_user_headers("nurse-002",        "Nurse"),
    "nurse_headers_third":  build_user_headers("nurse-003",        "Nurse"),
    "caregiver_headers":    build_user_headers("caregiver-001",    "Caregiver"),
    "family_headers":       build_user_headers("family-001",       "Family"),
    "finance_headers":      build_user_headers("finance-001",      "Finance"),
    "systemsync_headers":   build_user_headers("systemsync-001",   "SystemSync"),
}


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1 — Admin X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "Admin")


def make_supervisor_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1 — Supervisor X-User-ID is an opaque operator id.
    Used to construct supervisor ids distinct from a draft's
    ``assessor_id`` so segregation-of-duties tests pass (PRD §2.7 #6)."""
    return build_user_headers(user_id, "Supervisor")


def make_physician_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1 — Physician X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "Physician")


def make_nurse_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1 — Nurse X-User-ID is an opaque operator id.
    Used to construct nurse ids distinct from a prescription's
    ``prescriber_id`` so SoD on medication administration passes
    (PRD §2.7 #7)."""
    return build_user_headers(user_id, "Nurse")


def make_caregiver_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "Caregiver")


def make_family_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "Family")


def make_finance_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "Finance")


def make_systemsync_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "SystemSync")


__all__ = [
    "TEST_USERS",
    "make_admin_headers", "make_supervisor_headers",
    "make_physician_headers", "make_nurse_headers",
    "make_caregiver_headers", "make_family_headers",
    "make_finance_headers", "make_systemsync_headers",
]
