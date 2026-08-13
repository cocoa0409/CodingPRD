"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): for `Requester`, X-User-ID is the id of the
acting StaffMember (entity-backed) — use make_requester_headers(staff_id)
whenever the call is ownership-gated. For the other ten roles, X-User-ID is an
opaque operator identifier; shared constants are safe for non-ownership calls,
and the make_* builders exist for segregation-of-duties scenarios that need
distinct operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "ingest_coordinator_headers": build_user_headers("ic-1", "IngestCoordinator"),
    "metadata_cataloger_headers": build_user_headers("cat-1", "MetadataCataloger"),
    "metadata_librarian_headers": build_user_headers("lib-1", "MetadataLibrarian"),
    "archivist_lead_headers": build_user_headers("arch-1", "ArchivistLead"),
    "rights_manager_headers": build_user_headers("rm-1", "RightsManager"),
    "legal_counsel_headers": build_user_headers("lc-1", "LegalCounsel"),
    "access_officer_headers": build_user_headers("ao-1", "AccessOfficer"),
    # Requester is entity-backed: this shared constant is a fallback only for
    # tests that do NOT exercise ownership (its X-User-ID is no StaffMember id).
    "requester_headers": build_user_headers("test-requester-1", "Requester"),
    "finance_officer_headers": build_user_headers("fin-1", "FinanceOfficer"),
    "lab_technician_headers": build_user_headers("lab-1", "LabTechnician"),
}


# Per-instance builders — required whenever the call is ownership- or
# segregation-gated (PRD §2.8).

def make_requester_headers(user_id: str) -> dict:
    """Requester is entity-backed: pass the actual StaffMember.id."""
    return build_user_headers(user_id, "Requester")


def make_metadata_cataloger_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MetadataCataloger")


def make_metadata_librarian_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MetadataLibrarian")


def make_archivist_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ArchivistLead")


def make_legal_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalCounsel")


def make_access_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccessOfficer")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
