"""Pre-built role headers for every role in the PRD (§2.1).

The meaning of X-User-ID depends on the role (PRD §2.1): for MemberRep it is
the id of the acting Member, for SupplierRep the id of the acting Supplier,
and for CoopAdmin / FinanceOfficer / ProgramAuditor it is an opaque operator
identifier not tied to any persisted entity.

Shared constants are provided for every role; for the entity-backed roles
(MemberRep, SupplierRep) the per-instance builders MUST be used with the
actual entity id whenever the call touches an ownership-checked or
supplier-scoped resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "coop_admin_headers": build_user_headers("test-coop-admin-1", "CoopAdmin"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "program_auditor_headers": build_user_headers("test-auditor-1", "ProgramAuditor"),
    # Entity-backed roles — fallback only for tests that do not exercise
    # ownership (e.g. role-denied calls where the role check fires first).
    "member_rep_headers": build_user_headers("test-member-rep-1", "MemberRep"),
    "supplier_rep_headers": build_user_headers("test-supplier-rep-1", "SupplierRep"),
}


def make_member_rep_headers(member_id: str) -> dict:
    """MemberRep is entity-backed by Member: X-User-ID must be the acting
    Member's id whenever the call is member-scoped (PRD §2.1)."""
    return build_user_headers(member_id, "MemberRep")


def make_supplier_rep_headers(supplier_id: str) -> dict:
    """SupplierRep is entity-backed by Supplier: X-User-ID must be the acting
    Supplier's id whenever the call touches a supplier-referencing resource
    (PRD §2.1)."""
    return build_user_headers(supplier_id, "SupplierRep")
