"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- CustomsOfficer, FinanceOfficer, Auditor:
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity. The shared TEST_USERS constants are canonical for these roles.

- Declarant: entity-backed on Declarant. PRD §2.1 (verbatim):
  "When X-User-Role is Declarant, X-User-ID is the id of the acting
  Declarant entity; ownership checks on any declaration, refund, or query
  that references a declarant compare the resource's declarant_id to
  X-User-ID."  Ownership-gated calls (create/submit/amend declaration,
  add line, respond to a query, create/submit refund) MUST use
  make_declarant_headers(declarant_id) with the actual Declarant.id.

- Importer: entity-backed on Importer. PRD §2.1 (verbatim):
  "When X-User-Role is Importer, X-User-ID is the id of the acting
  Importer entity; ownership checks on any order, declaration, or
  payment notice that references an importer compare the resource's
  importer_id (transitively, via the Order for declarations and notices)
  to X-User-ID."  Order cancellation/return MUST use
  make_importer_headers(importer_id).

The shared TEST_USERS["declarant_headers"] and ["importer_headers"]
fallbacks exist only for tests where the call does NOT reach an
ownership comparison — for example, ERR_FORBIDDEN_FOR_ROLE wrong-role
checks (which fail at priority 2, before any ownership check), or
ERR_NOT_FOUND on a missing path id. Any test whose success requires
the server to ACCEPT the request must use the per-instance builders
with a real entity id.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared canonical headers.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical shared constants.
    "customs_officer_headers": build_user_headers(
        "officer-001", "CustomsOfficer"
    ),
    "customs_officer_headers_alt": build_user_headers(
        "officer-002", "CustomsOfficer"
    ),
    "finance_officer_headers": build_user_headers(
        "finance-001", "FinanceOfficer"
    ),
    "finance_officer_headers_alt": build_user_headers(
        "finance-002", "FinanceOfficer"
    ),
    "auditor_headers": build_user_headers("auditor-001", "Auditor"),

    # Fallbacks for entity-backed roles. ONLY for tests that don't reach
    # an ownership check (wrong-role 403, NOT_FOUND on missing resource).
    # Ownership-gated tests must build per-instance headers via
    # make_declarant_headers / make_importer_headers with a real entity id.
    "declarant_headers": build_user_headers(
        "declarant-fallback-001", "Declarant"
    ),
    "importer_headers": build_user_headers(
        "importer-fallback-001", "Importer"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity-backed roles.
# ---------------------------------------------------------------------------
def make_declarant_headers(declarant_id: str) -> Dict[str, str]:
    """Declarant headers. PRD §2.1: 'When X-User-Role is Declarant, X-User-ID
    is the id of the acting Declarant entity; ownership checks on any
    declaration, refund, or query that references a declarant compare the
    resource's declarant_id to X-User-ID.'

    Pass the actual Declarant.id whenever the call is ownership-gated
    (create/submit/amend declaration, add line, respond to a query,
    create/submit refund, create order on behalf of importer).
    """
    return build_user_headers(declarant_id, "Declarant")


def make_importer_headers(importer_id: str) -> Dict[str, str]:
    """Importer headers. PRD §2.1: 'When X-User-Role is Importer,
    X-User-ID is the id of the acting Importer entity; ownership checks on
    any order, declaration, or payment notice that references an importer
    compare the resource's importer_id (transitively, via the Order for
    declarations and notices) to X-User-ID.'

    Pass the actual Importer.id whenever the call is ownership-gated
    (cancel order, return order).
    """
    return build_user_headers(importer_id, "Importer")


# ---------------------------------------------------------------------------
# Per-instance builders for opaque roles.
# ---------------------------------------------------------------------------
def make_customs_officer_headers(
    user_id: str = "officer-001",
) -> Dict[str, str]:
    return build_user_headers(user_id, "CustomsOfficer")


def make_finance_officer_headers(
    user_id: str = "finance-001",
) -> Dict[str, str]:
    return build_user_headers(user_id, "FinanceOfficer")


def make_auditor_headers(user_id: str = "auditor-001") -> Dict[str, str]:
    return build_user_headers(user_id, "Auditor")


__all__ = [
    "TEST_USERS",
    "make_declarant_headers",
    "make_importer_headers",
    "make_customs_officer_headers",
    "make_finance_officer_headers",
    "make_auditor_headers",
]
