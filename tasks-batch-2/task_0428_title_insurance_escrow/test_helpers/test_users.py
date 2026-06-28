"""Pre-built role headers for every role in the PRD.

Three roles (PRD §2.1): Agency (entity-backed — X-User-ID is the Agency.id),
TitleOfficer and Underwriter (both opaque — X-User-ID is an operator id never
matched against any stored entity id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#  - TitleOfficer / Underwriter are opaque: the shared constant is the canonical form.
#  - Agency is entity-backed: the shared constant is a FALLBACK only for tests that do
#    NOT exercise ownership (e.g. 401/unknown-role checks). Ownership-gated calls MUST
#    use make_agency_headers(agency_id) with the real Agency.id.
TEST_USERS = {
    "title_officer_headers": build_user_headers("test-title-officer-1", "TitleOfficer"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "agency_headers": build_user_headers("test-agency-fallback-1", "Agency"),
}


def make_agency_headers(agency_id: str) -> dict:
    """For the Agency role (entity_backed:Agency). Pass the actual Agency.id as the
    X-User-ID whenever the call is ownership-gated (opening/cancelling an order,
    depositing on an order the agency owns, etc.)."""
    return build_user_headers(agency_id, "Agency")


def make_title_officer_headers(user_id: str = "test-title-officer-1") -> dict:
    """For the TitleOfficer role (opaque identity)."""
    return build_user_headers(user_id, "TitleOfficer")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    """For the Underwriter role (opaque identity)."""
    return build_user_headers(user_id, "Underwriter")
