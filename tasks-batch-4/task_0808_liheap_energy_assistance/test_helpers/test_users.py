"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - Caseworker and ProgramAdmin are opaque identities (X-User-ID not tied to
#     any entity), so the shared constant is the canonical form for them.
#   - Applicant (entity_backed:Household) and VendorAgent (entity_backed:Vendor)
#     shared constants are a FALLBACK for non-ownership tests only (e.g. 401/404).
#     Ownership-gated calls MUST use the per-instance builders below.
TEST_USERS = {
    "caseworker_headers": build_user_headers("test-caseworker-1", "Caseworker"),
    "programadmin_headers": build_user_headers("test-programadmin-1", "ProgramAdmin"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "vendoragent_headers": build_user_headers("test-vendoragent-1", "VendorAgent"),
}


def make_applicant_headers(household_id: str) -> dict:
    """For Applicant (entity_backed:Household). Pass the acting Household.id as
    X-User-ID whenever the call is ownership-gated (submit, own-application ops)."""
    return build_user_headers(household_id, "Applicant")


def make_vendoragent_headers(vendor_id: str) -> dict:
    """For VendorAgent (entity_backed:Vendor). Pass the acting Vendor.id as
    X-User-ID whenever the call is ownership-gated (enroll, remit, return)."""
    return build_user_headers(vendor_id, "VendorAgent")


def make_caseworker_headers(user_id: str = "test-caseworker-1") -> dict:
    return build_user_headers(user_id, "Caseworker")


def make_programadmin_headers(user_id: str = "test-programadmin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
