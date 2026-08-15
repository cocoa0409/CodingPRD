"""Pre-built role headers for every role in the PRD (§2.1).

Identity model:
- ProgramAdmin / PIAReviewer / CommitmentOfficer / InvoiceProcessor /
  AppealOfficer / Auditor are opaque: X-User-ID is never compared to any
  persisted entity id (but is recorded, e.g. pia_reviewer_user_ids,
  decided_by_user_id — the segregation-of-duties hooks in PRD §2.8).
- ApplicantCoordinator / ApplicantCertifier are entity_backed by ApplicantUser:
  X-User-ID MUST be the created ApplicantUser's id or every ownership check
  rejects the call. Use make_coordinator_headers(user["id"]) /
  make_certifier_headers(user["id"]) after creating the user.
- VendorRepresentative is entity_backed by ServiceProvider: X-User-ID MUST be
  the provider's id. Use make_vendor_headers(provider["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that never exercise
# entity-backed ownership (bad-payload 400s, missing-resource 404s, reads).
TEST_USERS = {
    "program_admin_headers": build_user_headers("usac-admin-1", "ProgramAdmin"),
    "pia_reviewer_headers": build_user_headers("usac-emp-9", "PIAReviewer"),
    "commitment_officer_headers": build_user_headers("usac-emp-7", "CommitmentOfficer"),
    "invoice_processor_headers": build_user_headers("usac-inv-1", "InvoiceProcessor"),
    "appeal_officer_headers": build_user_headers("usac-app-3", "AppealOfficer"),
    "auditor_headers": build_user_headers("usac-aud-1", "Auditor"),
    # Fallbacks for entity-backed roles — NON-ownership contexts only.
    "coordinator_headers": build_user_headers("test-coordinator-1", "ApplicantCoordinator"),
    "certifier_headers": build_user_headers("test-certifier-1", "ApplicantCertifier"),
    "vendor_headers": build_user_headers("test-vendor-1", "VendorRepresentative"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — mandatory for entity-backed roles whenever the call
# is ownership-gated; also used to give opaque operators deliberate identities
# (segregation-of-duties scenarios).
# ---------------------------------------------------------------------------

def make_coordinator_headers(user_id: str) -> dict:
    """ApplicantCoordinator headers; pass the acting ApplicantUser.id."""
    return build_user_headers(user_id, "ApplicantCoordinator")


def make_certifier_headers(user_id: str) -> dict:
    """ApplicantCertifier headers; pass the acting ApplicantUser.id."""
    return build_user_headers(user_id, "ApplicantCertifier")


def make_vendor_headers(provider_id: str) -> dict:
    """VendorRepresentative headers; pass the acting ServiceProvider.id."""
    return build_user_headers(provider_id, "VendorRepresentative")


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_pia_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PIAReviewer")


def make_commitment_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommitmentOfficer")


def make_invoice_processor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InvoiceProcessor")


def make_appeal_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AppealOfficer")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
