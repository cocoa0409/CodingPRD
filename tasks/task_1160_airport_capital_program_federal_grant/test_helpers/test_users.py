"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (FAAManager, SponsorStaff, ComplianceOfficer, FinanceOfficer, Auditor)
use stable operator identifiers — the server records them (e.g. as
created_by_user_id / prepared_by_user_id / certified_by_user_id) but never compares
them to an entity id for ownership.

The Contractor role is entity-backed: X-User-ID must equal the acting Contractor
entity's id on ownership-gated calls (invoice filing, DBE report filing). Use
make_contractor_headers(contractor["id"]) for those calls; the shared
contractor_headers constant is a fallback for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable operator identifiers (segregation-of-duties anchors, PRD §2.10).
FAA_USER_ID = "user-faa-1"
SPONSOR_USER_ID = "user-sponsor-1"
COMPLIANCE_USER_ID = "user-compl-1"
COMPLIANCE_USER_ID_2 = "user-compl-2"
FINANCE_USER_ID = "user-fin-1"
AUDITOR_USER_ID = "user-aud-1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "faa_manager_headers": build_user_headers(FAA_USER_ID, "FAAManager"),
    "sponsor_staff_headers": build_user_headers(SPONSOR_USER_ID, "SponsorStaff"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers(COMPLIANCE_USER_ID_2, "ComplianceOfficer"),
    "finance_officer_headers": build_user_headers(FINANCE_USER_ID, "FinanceOfficer"),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity_backed: Contractor). Pass the actual Contractor.id
    as user_id whenever the call is ownership-gated (invoice / DBE report filing)."""
    return build_user_headers(user_id, "Contractor")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific operator id (used to exercise the
    segregation-of-duties comparison against an application's creator)."""
    return build_user_headers(user_id, "ComplianceOfficer")
