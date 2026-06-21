"""Pre-built role headers for every role in the PRD (§2.1).

The system recognizes exactly five roles: Franchisor, ComplianceAuditor,
Franchisee, FinanceClerk, System.

Four roles are OPAQUE operator identities (§2.1): Franchisor, ComplianceAuditor,
FinanceClerk, System. Their X-User-ID is not tied to any persisted entity, so a
shared constant is the canonical form.

The Franchisee role is ENTITY-BACKED (§2.1): X-User-ID is matched against the
owner_user_id field of a Franchisee record. Ownership-gated franchisee calls
(unit open/close, sales-report creation, vendor-authorization creation) compare
the caller's X-User-ID to the owning franchisee's owner_user_id. Such calls MUST
use make_franchisee_headers(owner_user_id) with the SAME owner_user_id string the
franchisee was created with — NOT the franchisee entity id. Falling back to the
shared constant reproduces the canonical bug: X-User-ID equals no franchisee's
owner_user_id, so every ownership check rejects the request.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for the four opaque operator roles, and safe for
# tests that do NOT exercise franchisee ownership (401/403/404 paths, or
# Franchisor/FinanceClerk/ComplianceAuditor-driven setup and triggers).
TEST_USERS = {
    "franchisor_headers": build_user_headers("test-franchisor-1", "Franchisor"),
    "compliance_auditor_headers": build_user_headers(
        "test-auditor-1", "ComplianceAuditor"
    ),
    "finance_clerk_headers": build_user_headers("test-clerk-1", "FinanceClerk"),
    "system_headers": build_user_headers("test-system-1", "System"),
    # Entity_backed shared fallback — for non-ownership Franchisee tests only
    # (e.g. RBAC 403 where the role is forbidden before ownership is checked).
    "franchisee_headers": build_user_headers("test-franchisee-1", "Franchisee"),
}


def make_franchisor_headers(user_id: str = "test-franchisor-1") -> dict:
    """Headers for a Franchisor (opaque brand-HQ operator)."""
    return build_user_headers(user_id, "Franchisor")


def make_compliance_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    """Headers for a ComplianceAuditor (opaque audit/vendor-compliance operator)."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_finance_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    """Headers for a FinanceClerk (opaque royalty/rebate settlement operator)."""
    return build_user_headers(user_id, "FinanceClerk")


def make_system_headers(user_id: str = "test-system-1") -> dict:
    """Headers for the System role (opaque automated POS polling identity)."""
    return build_user_headers(user_id, "System")


def make_franchisee_headers(owner_user_id: str) -> dict:
    """For the Franchisee role (entity_backed). Pass the owner_user_id string the
    franchisee was created with whenever the call is ownership-gated (open/close a
    unit, ingest a sales report, authorize a vendor for an owned unit)."""
    return build_user_headers(owner_user_id, "Franchisee")
