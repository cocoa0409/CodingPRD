"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "network_manager_headers": build_user_headers("test-nm-1", "NetworkManager"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "regulator_headers": build_user_headers("test-reg-1", "Regulator"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only.
    "provider_rep_headers": build_user_headers("test-rep-1", "ProviderRep"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_provider_rep_headers(user_id: str) -> dict:
    """For ProviderRep (identity = the acting Provider's id, PRD §2.1). Pass the actual
    Provider.id whenever the call is ownership-gated (attestation respond)."""
    return build_user_headers(user_id, "ProviderRep")


def make_member_headers(user_id: str) -> dict:
    """For Member (identity = the acting Member's id, PRD §2.1). Pass the actual
    Member.id whenever the call is ownership-gated (complaint filing)."""
    return build_user_headers(user_id, "Member")


def make_network_manager_headers(user_id: str) -> dict:
    """Opaque role, but the id is recorded as submitted_by_user_id on manual corrections."""
    return build_user_headers(user_id, "NetworkManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Opaque role, but the id is recorded as verified_by_user_id on corrections."""
    return build_user_headers(user_id, "ComplianceOfficer")
