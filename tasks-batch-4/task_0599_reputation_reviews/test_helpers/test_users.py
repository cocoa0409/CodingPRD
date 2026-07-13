"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - PlatformAdmin / ResponseAgent / ComplianceOfficer carry an opaque X-User-ID
#     that is never compared to a persisted entity, so the constant form is canonical.
#   - BusinessOwner / LocationManager bind X-User-ID to a Business.id / Location.id.
#     The constants below are ONLY safe for calls that are not ownership-gated;
#     ownership-gated calls MUST use the per-instance builders further down.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "admin2_headers": build_user_headers("admin-2", "PlatformAdmin"),
    "response_agent_headers": build_user_headers("agent-1", "ResponseAgent"),
    "response_agent2_headers": build_user_headers("agent-2", "ResponseAgent"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_officer2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "business_owner_headers": build_user_headers("owner-1", "BusinessOwner"),
    "location_manager_headers": build_user_headers("manager-1", "LocationManager"),
}


def make_admin_headers(user_id: str) -> dict:
    """PlatformAdmin with a specific opaque X-User-ID (segregation-of-duties tests)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_response_agent_headers(user_id: str) -> dict:
    """ResponseAgent with a specific opaque X-User-ID (drafted_by_user_id key)."""
    return build_user_headers(user_id, "ResponseAgent")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific opaque X-User-ID (approved_by_user_id key)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_business_owner_headers(business_id: str) -> dict:
    """BusinessOwner: X-User-ID is the id of the acting Business (PRD §2.1)."""
    return build_user_headers(business_id, "BusinessOwner")


def make_location_manager_headers(location_id: str) -> dict:
    """LocationManager: X-User-ID is the id of the acting Location (PRD §2.1)."""
    return build_user_headers(location_id, "LocationManager")


def anonymous_headers() -> dict:
    """Anonymous public visitor: X-User-Role only, no X-User-ID (PRD §2.1)."""
    return {"X-User-Role": "Anonymous", "Content-Type": "application/json"}
