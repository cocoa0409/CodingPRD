"""Pre-built role headers for every role named in PRD 2.1.

`GrowerRep` is entity-backed: its `X-User-ID` must be the `id` of the acting
Grower whenever a call is ownership-gated (transfer create/approve/reject/
cancel, abandonment reporting). For those calls use `make_grower_rep_headers`
with the real grower id; the shared constant is only a fallback for tests that
do not exercise ownership. All other roles carry opaque operator identifiers
that are never compared to any persisted entity's id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "contractor_admin_headers": build_user_headers("admin-op-1", "ContractorAdmin"),
    "program_reviewer_headers": build_user_headers("reviewer-op-1", "ProgramReviewer"),
    "housing_inspector_headers": build_user_headers("inspector-op-1", "HousingInspector"),
    "visa_officer_headers": build_user_headers("officer-op-1", "VisaOfficer"),
    "wage_auditor_headers": build_user_headers("auditor-op-1", "WageAuditor"),
    "system_admin_headers": build_user_headers("sysadmin-op-1", "SystemAdmin"),
    # Entity-backed identity — fallback for non-ownership tests only.
    "grower_rep_headers": build_user_headers("test-grower-rep-1", "GrowerRep"),
}


def make_grower_rep_headers(grower_id: str) -> Dict[str, str]:
    """For GrowerRep (entity-backed by Grower). Pass the acting Grower's id
    whenever the call is ownership-gated (transfers, abandonment reporting)."""
    return build_user_headers(grower_id, "GrowerRep")
