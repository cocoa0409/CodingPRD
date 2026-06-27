"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Fixed ComplianceOfficer id used across setup chains (matches the design indices' "co-1").
COMPLIANCE_OFFICER_USER_ID = "co-1"

# Shared constants — safe for opaque roles (Anonymous, ComplianceOfficer) and for tests
# that do NOT exercise ownership (400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    # opaque roles: shared constants are the canonical form.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "issuer_headers": build_user_headers("test-issuer-1", "Issuer"),
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
}


# Per-instance builders — required for every entity_backed role.
def make_issuer_headers(user_id: str) -> dict:
    """For the Issuer role (entity_backed:Issuer). Pass the actual Issuer.id as user_id
    whenever the call is ownership-gated (offerings, updates of that issuer)."""
    return build_user_headers(user_id, "Issuer")


def make_investor_headers(user_id: str) -> dict:
    """For the Investor role (entity_backed:Investor). Pass the actual Investor.id as user_id
    whenever the call is ownership-gated (own investments, own accreditation requests)."""
    return build_user_headers(user_id, "Investor")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    """For the ComplianceOfficer role (opaque). The id is recorded but never ownership-compared,
    except for the segregation-of-duties rule on Form C qualify/reject where it must differ
    from the offering's issuer id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """For the Anonymous role (opaque public). Used for public registration and public reads."""
    return build_user_headers(user_id, "Anonymous")
