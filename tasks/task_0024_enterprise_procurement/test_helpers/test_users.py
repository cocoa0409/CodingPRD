"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- Requester, Buyer, DepartmentHead, FinanceApprover, LegalApprover,
  GeneralManager, Inspector, PlatformAdmin: opaque — X-User-ID is not
  compared to any persisted entity row.
- Supplier: entity-backed on Supplier — when X-User-Role is `Supplier`,
  X-User-ID is the id of the acting Supplier entity. PRD §2.1: "ownership
  checks on any resource that references a Supplier (notably an invoice
  referencing supplier_id, or a contract whose purchase_order_id resolves
  to a PO with a particular supplier_id) compare the resource's
  foreign-key field to X-User-ID."

For Supplier ownership-gated calls, tests MUST use
make_supplier_headers(supplier["id"]). The shared TEST_USERS Supplier
fallback exists only for tests whose success does NOT depend on the
caller owning a specific supplier (e.g., 401 / 403 / 404 paths).

In addition, PRD §2.8 priority 7 segregation-of-duties applies to opaque
approver roles based on their X-User-ID across ApprovalSteps on the same
PO. Tests of segregation-of-duties violations therefore need DISTINCT
operator_ids per role; the *_alt builders provide a second persona.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles; for the Supplier role, use only
# when the test does NOT exercise an ownership comparison.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "requester_headers": build_user_headers("requester-001", "Requester"),
    "requester_headers_alt": build_user_headers("requester-002", "Requester"),
    "buyer_headers": build_user_headers("buyer-001", "Buyer"),
    "buyer_headers_alt": build_user_headers("buyer-002", "Buyer"),
    "dept_head_headers": build_user_headers("dept-head-001", "DepartmentHead"),
    "dept_head_headers_alt": build_user_headers("dept-head-002", "DepartmentHead"),
    "finance_headers": build_user_headers("finance-001", "FinanceApprover"),
    "finance_headers_alt": build_user_headers("finance-002", "FinanceApprover"),
    "finance_headers_third": build_user_headers("finance-003", "FinanceApprover"),
    "legal_headers": build_user_headers("legal-001", "LegalApprover"),
    "legal_headers_alt": build_user_headers("legal-002", "LegalApprover"),
    "gm_headers": build_user_headers("gm-001", "GeneralManager"),
    "gm_headers_alt": build_user_headers("gm-002", "GeneralManager"),
    "inspector_headers": build_user_headers("inspector-001", "Inspector"),
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),

    # Entity-backed Supplier role — fallback for non-ownership tests only.
    "supplier_headers": build_user_headers("supplier-fallback-001", "Supplier"),
}


# --- Per-instance builders for opaque roles (allow distinct operators) ---
def make_requester_headers(operator_id: str = "requester-001") -> Dict[str, str]:
    """Requester headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "Requester")


def make_buyer_headers(operator_id: str = "buyer-001") -> Dict[str, str]:
    """Buyer headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "Buyer")


def make_dept_head_headers(operator_id: str = "dept-head-001") -> Dict[str, str]:
    """DepartmentHead headers; identity is opaque, but PRD §2.8 priority 7
    segregation-of-duties compares X-User-ID across ApprovalSteps on a PO.
    Tests of that rule must hand distinct operator_id values to each
    DepartmentHead acting on the same PO.
    """
    return build_user_headers(operator_id, "DepartmentHead")


def make_finance_headers(operator_id: str = "finance-001") -> Dict[str, str]:
    """FinanceApprover headers; identity is opaque, but PRD §2.8 priorities
    7 and 8 segregation-of-duties apply across ApprovalSteps and Payment
    approvals. Tests of those rules must use distinct operator_ids per
    FinanceApprover persona.
    """
    return build_user_headers(operator_id, "FinanceApprover")


def make_legal_headers(operator_id: str = "legal-001") -> Dict[str, str]:
    """LegalApprover headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "LegalApprover")


def make_gm_headers(operator_id: str = "gm-001") -> Dict[str, str]:
    """GeneralManager headers; identity is opaque, but PRD §3.4 names this
    role as the escalation target and as the deciding role on ESCALATED
    steps; tests routinely pass a specific gm operator_id to control which
    actor appears in audit entries.
    """
    return build_user_headers(operator_id, "GeneralManager")


def make_inspector_headers(operator_id: str = "inspector-001") -> Dict[str, str]:
    """Inspector headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "Inspector")


def make_platform_admin_headers(
    operator_id: str = "admin-001",
) -> Dict[str, str]:
    """PlatformAdmin headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "PlatformAdmin")


def make_supplier_headers(supplier_id: str) -> Dict[str, str]:
    """Supplier headers. PRD §2.1: "When X-User-Role is Supplier, X-User-ID
    is the id of the acting Supplier entity; ownership checks on any
    resource that references a Supplier (notably an invoice referencing
    supplier_id, or a contract whose purchase_order_id resolves to a PO
    with a particular supplier_id) compare the resource's foreign-key
    field to X-User-ID."

    Pass the actual Supplier.id whenever the request is ownership-gated
    (POST /invoices, POST /contracts/{id}/sign with role=Supplier).
    """
    return build_user_headers(supplier_id, "Supplier")


__all__ = [
    "TEST_USERS",
    "make_requester_headers",
    "make_buyer_headers",
    "make_dept_head_headers",
    "make_finance_headers",
    "make_legal_headers",
    "make_gm_headers",
    "make_inspector_headers",
    "make_platform_admin_headers",
    "make_supplier_headers",
]
