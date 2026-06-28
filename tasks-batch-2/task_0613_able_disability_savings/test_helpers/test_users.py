"""Pre-built role headers for every role in the ABLE program API."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - ProgramAdministrator and MedicaidAgency are opaque identities: the shared
#     constant is the canonical form (X-User-ID is never compared to an entity id).
#   - Beneficiary / AuthorizedRepresentative are entity_backed: the shared
#     constant is a FALLBACK only for tests that do NOT exercise ownership
#     (e.g. ERR_FORBIDDEN before the ownership check, or non-existent-resource
#     paths). Ownership-gated calls MUST use the per-instance builders below.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdministrator"),
    "medicaid_agency_headers": build_user_headers("test-medicaid-1", "MedicaidAgency"),
    "beneficiary_headers": build_user_headers("test-beneficiary-1", "Beneficiary"),
    "representative_headers": build_user_headers("test-rep-1", "AuthorizedRepresentative"),
}


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ProgramAdministrator (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_medicaid_agency_headers(user_id: str = "test-medicaid-1") -> dict:
    """MedicaidAgency (opaque identity)."""
    return build_user_headers(user_id, "MedicaidAgency")


def make_beneficiary_headers(user_id: str) -> dict:
    """For Beneficiary (entity_backed:Beneficiary). Pass the actual Beneficiary.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Beneficiary")


def make_representative_headers(user_id: str) -> dict:
    """For AuthorizedRepresentative (entity_backed:AuthorizedRepresentative). Pass the
    actual AuthorizedRepresentative.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AuthorizedRepresentative")


def make_invalid_role_headers(user_id: str = "nobody") -> dict:
    """Headers carrying a role string that is not one of the four recognized roles."""
    return build_user_headers(user_id, "NoSuchRole")
