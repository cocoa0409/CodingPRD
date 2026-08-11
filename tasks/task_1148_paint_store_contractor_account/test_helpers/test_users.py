"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the four opaque roles — the PRD does not compare their
# X-User-ID against any persisted entity, so a fixed operator id is canonical.
# The Contractor constant is a fallback for non-ownership-gated calls only;
# ownership-gated calls MUST use make_contractor_headers(account["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CorporateAdmin"),
    "manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    "spec_writer_headers": build_user_headers("test-specwriter-1", "SpecWriter"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity-backed by ContractorAccount). Pass the actual
    ContractorAccount.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Contractor")
