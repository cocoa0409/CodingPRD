"""Pre-built role headers for every role in the PRD (§2.1).

ComplianceOfficer and Underwriter are opaque operator identities — any
X-User-ID string works, and segregation-of-duties compares the raw strings.
Policyholder is entity-backed: X-User-ID must equal the Policyholder.id of
the acting insured, so ownership-gated calls MUST use
make_policyholder_headers(policyholder["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not
# exercise Policyholder ownership checks.
TEST_USERS = {
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    # Fallback only for non-ownership tests (e.g. malformed-payload or
    # role-denial tests); never use for calls gated on policy ownership.
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
}


def make_policyholder_headers(user_id: str) -> dict:
    """Policyholder is entity-backed: pass the actual Policyholder.id."""
    return build_user_headers(user_id, "Policyholder")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque: arbitrary ids, used to vary SoD actors."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter is opaque: arbitrary ids, used to vary SoD actors."""
    return build_user_headers(user_id, "Underwriter")
