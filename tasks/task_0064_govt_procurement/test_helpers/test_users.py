"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1 identity rules:

- ProcurementOfficer, EvaluationExpert, Regulator are OPAQUE operator
  identifiers — "the server records it as the actor_id field on AuditLog
  entries it appends, but does not compare it to any entity's id."
  Shared constants are therefore safe for these roles.

- Supplier is ENTITY-BACKED — "When X-User-Role is Supplier, X-User-ID
  is the id of the acting Supplier; ownership checks on any resource
  that references a Supplier (a Bid, Query or Complaint) compare the
  resource's supplier_id / complainant_supplier_id foreign-key to
  X-User-ID. Operations that mutate a supplier-owned resource
  (withdrawing a bid, withdrawing a complaint) require this comparison
  to hold."

  Every ownership-gated Supplier-role call therefore MUST use
  make_supplier_headers(<supplier_id>) where <supplier_id> is the exact
  Supplier.id returned by POST /procurement/suppliers. Falling back to
  a shared constant guarantees the ownership comparison fails for any
  real supplier id, cascading "Setup failed" into every downstream
  test that depends on supplier ownership.

- EvaluationExpert is OPAQUE per PRD §2.1, BUT the server compares its
  X-User-ID against expert_id values inside EvaluationCommittee.members.
  Tests that need an expert to record evaluations must therefore read
  back the formed committee's members[].expert_id and use make_expert_headers
  with that exact id.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants for opaque roles, plus a non-binding fallback for the
# entity-backed Supplier role (use only for negative tests that don't
# exercise ownership traversal).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque operator identifiers (PRD §2.1).
    "officer_headers": build_user_headers(
        "officer-001", "ProcurementOfficer",
    ),
    "officer_headers_alt": build_user_headers(
        "officer-002", "ProcurementOfficer",
    ),
    "regulator_headers": build_user_headers(
        "regulator-001", "Regulator",
    ),
    "regulator_headers_alt": build_user_headers(
        "regulator-002", "Regulator",
    ),
    "expert_headers": build_user_headers(
        "expert-001", "EvaluationExpert",
    ),
    "expert_headers_alt": build_user_headers(
        "expert-002", "EvaluationExpert",
    ),
    "expert_headers_third": build_user_headers(
        "expert-003", "EvaluationExpert",
    ),
    # Entity-backed fallback — use ONLY for non-ownership negative tests
    # (e.g., "Supplier role calls Regulator endpoint → 403"). For every
    # ownership-gated supplier call (submit bid, withdraw bid, file
    # complaint, withdraw complaint, submit query) use the per-instance
    # builder below with the actual Supplier.id returned at registration.
    "supplier_fallback_headers": build_user_headers(
        "supplier-fallback", "Supplier",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. REQUIRED for the entity_backed Supplier role
# whenever the downstream call is ownership-gated.
# ---------------------------------------------------------------------------
def make_supplier_headers(supplier_id: str) -> Dict[str, str]:
    """PRD §2.1: "When X-User-Role is Supplier, X-User-ID is the id of
    the acting Supplier."

    Pass the Supplier.id returned by POST /procurement/suppliers for
    every ownership-gated supplier call (submit-bid, withdraw-bid,
    file-complaint, withdraw-complaint, submit-query). The server
    compares X-User-ID directly to the resource's supplier_id /
    complainant_supplier_id foreign keys, so a wrong id will cause every
    ownership-gated call to fail.
    """
    return build_user_headers(supplier_id, "Supplier")


def make_officer_headers(user_id: str = "officer-001") -> Dict[str, str]:
    """PRD §2.1: ProcurementOfficer identity is opaque."""
    return build_user_headers(user_id, "ProcurementOfficer")


def make_regulator_headers(user_id: str = "regulator-001") -> Dict[str, str]:
    """PRD §2.1: Regulator identity is opaque."""
    return build_user_headers(user_id, "Regulator")


def make_expert_headers(expert_id: str) -> Dict[str, str]:
    """PRD §2.1: EvaluationExpert identity is opaque, but the server
    "compares it against the expert_id values held inside
    EvaluationCommittee.members when authorising bid evaluations."
    Tests that record evaluations must pass an expert_id that the server
    selected into the committee (read from members[].expert_id after
    POST /procurement/projects/{id}/form-committee).
    """
    return build_user_headers(expert_id, "EvaluationExpert")


__all__ = [
    "TEST_USERS",
    "make_supplier_headers",
    "make_officer_headers",
    "make_regulator_headers",
    "make_expert_headers",
]
