"""Pre-built role headers for every PRD §2.1 role.

PRD §2.1 identity rules (paraphrased here only):

- ``CoreEnterpriseUser`` is ENTITY-BACKED to ``CoreEnterprise``:
  "X-User-ID is the id of the acting CoreEnterprise; any resource that
  references that core enterprise ... is owned by the user whose
  X-User-ID matches the resource's core_enterprise_id."

- ``SupplierUser`` is ENTITY-BACKED to ``Supplier``:
  "X-User-ID is the id of the acting Supplier; ownership checks on a
  Receivable or FinancingApplication compare the resource's supplier_id
  to X-User-ID."

- The remaining seven roles — ``CreditOfficer``, ``ComplianceOfficer``,
  ``RiskReviewer``, ``CreditApprover``, ``Funder``, ``CollectionManager``,
  ``PlatformAdmin`` — are OPAQUE operator identities; the server records
  the ``X-User-ID`` on audit log entries and segregation-of-duties
  checks, but never compares it to any persisted entity's ``id``.

Per the SKILL contract: every entity_backed role exposes BOTH a
shared-constant fallback (for tests that do not exercise ownership) AND
a per-instance builder ``make_<role>_headers(entity_id)`` that fixtures
MUST use whenever the downstream call is ownership-gated. Falling back
to the shared constant for an entity_backed role guarantees ownership
checks reject every request and cascades "Setup failed" into dozens of
unrelated tests.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
# Opaque roles — these are canonical (PRD §2.1 says the server records the
# X-User-ID for audit but does not compare it to any entity's id).
#
# Entity-backed roles also have entries here, but they are FALLBACKS used
# only for tests that don't exercise ownership: missing-auth probes,
# wrong-role probes, and missing-resource probes (PRD §2.4 path-existence
# check fires BEFORE ownership per §2.10's validation priority order).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # ---- Opaque roles (canonical) ----
    "credit_officer_headers": build_user_headers(
        "credit-officer-001", "CreditOfficer",
    ),
    "compliance_officer_headers": build_user_headers(
        "compliance-officer-001", "ComplianceOfficer",
    ),
    "risk_reviewer_headers": build_user_headers(
        "risk-reviewer-001", "RiskReviewer",
    ),
    "risk_reviewer_headers_alt": build_user_headers(
        "risk-reviewer-002", "RiskReviewer",
    ),
    "credit_approver_headers": build_user_headers(
        "credit-approver-001", "CreditApprover",
    ),
    "credit_approver_headers_alt": build_user_headers(
        "credit-approver-002", "CreditApprover",
    ),
    "funder_headers": build_user_headers(
        "funder-001", "Funder",
    ),
    "collection_manager_headers": build_user_headers(
        "collection-manager-001", "CollectionManager",
    ),
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),

    # ---- Entity-backed fallbacks (NOT for ownership-gated calls) ----
    "core_enterprise_user_headers": build_user_headers(
        "core-enterprise-user-fallback", "CoreEnterpriseUser",
    ),
    "supplier_user_headers": build_user_headers(
        "supplier-user-fallback", "SupplierUser",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for every entity-backed role per
# PRD §2.1. Fixtures pass the actual entity id (CoreEnterprise.id or
# Supplier.id) returned by POST /scf/core-enterprises or
# POST /scf/suppliers so ownership checks see a matching X-User-ID.
# ---------------------------------------------------------------------------
def make_core_enterprise_headers(core_enterprise_id: str) -> Dict[str, str]:
    """PRD §2.1: "When X-User-Role is CoreEnterpriseUser, X-User-ID is the
    id of the acting CoreEnterprise; any resource that references that
    core enterprise ... is owned by the user whose X-User-ID matches the
    resource's core_enterprise_id." Pass the CoreEnterprise.id from
    POST /scf/core-enterprises for every payable-confirmation upload,
    confirm, revoke, and on-due-date repayment call.
    """
    return build_user_headers(core_enterprise_id, "CoreEnterpriseUser")


def make_supplier_headers(supplier_id: str) -> Dict[str, str]:
    """PRD §2.1: "When X-User-Role is SupplierUser, X-User-ID is the id of
    the acting Supplier; ownership checks on a Receivable or
    FinancingApplication compare the resource's supplier_id to
    X-User-ID." Pass the Supplier.id from POST /scf/suppliers for every
    receivable registration, pledge/transfer, financing-application
    draft/submit, and supplier-side early-settle / partial-prepay call.
    """
    return build_user_headers(supplier_id, "SupplierUser")


# ---------------------------------------------------------------------------
# Opaque-role builders — provided for symmetry; tests use these when they
# need a SPECIFIC X-User-ID distinct from the shared constant (e.g.,
# segregation-of-duties tests where the approver and the reviewer must
# share or differ in X-User-ID, even though both roles are opaque).
# ---------------------------------------------------------------------------
def make_credit_officer_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: CreditOfficer is opaque; X-User-ID is recorded on audit
    log entries but not compared to any entity. Use this builder when a
    test needs to distinguish two CreditOfficer actors (e.g., chain-of-
    custody audit trail)."""
    return build_user_headers(user_id, "CreditOfficer")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: ComplianceOfficer is opaque. Use this builder when a
    test needs a specific opaque actor id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_risk_reviewer_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: RiskReviewer is opaque; PRD §2.1 segregation-of-duties
    rule pivots on the reviewer's X-User-ID being recorded at
    start-review and later compared to the approver's X-User-ID, so
    tests that exercise SoD MUST use distinct opaque ids per actor."""
    return build_user_headers(user_id, "RiskReviewer")


def make_credit_approver_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: CreditApprover is opaque; the segregation-of-duties rule
    requires the approver's X-User-ID to differ from the X-User-ID
    recorded for the start-review actor on the same application."""
    return build_user_headers(user_id, "CreditApprover")


def make_funder_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: Funder is opaque."""
    return build_user_headers(user_id, "Funder")


def make_collection_manager_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: CollectionManager is opaque."""
    return build_user_headers(user_id, "CollectionManager")


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin is opaque."""
    return build_user_headers(user_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_core_enterprise_headers",
    "make_supplier_headers",
    "make_credit_officer_headers",
    "make_compliance_officer_headers",
    "make_risk_reviewer_headers",
    "make_credit_approver_headers",
    "make_funder_headers",
    "make_collection_manager_headers",
    "make_platform_admin_headers",
]
