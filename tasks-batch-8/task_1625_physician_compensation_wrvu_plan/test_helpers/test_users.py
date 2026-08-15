"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (SystemAdmin, CompAnalyst, ComplianceOfficer, CompCommittee) carry an
X-User-ID that is not tied to any persisted entity; several pre-built ids exist so
segregation-of-duties scenarios can put different users on each side of a handoff
(PRD §2.8). The Physician role is entity-backed: its X-User-ID must be the id of an
existing Physician, so ownership-gated calls must build headers with
make_physician_headers(physician["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "system_admin_headers": build_user_headers("sa_1", "SystemAdmin"),
    "analyst_headers": build_user_headers("an_1", "CompAnalyst"),
    "analyst_2_headers": build_user_headers("an_2", "CompAnalyst"),
    "compliance_officer_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "committee_headers": build_user_headers("cc_1", "CompCommittee"),
    "committee_9_headers": build_user_headers("cc_9", "CompCommittee"),
    # Entity-backed role — shared fallback ONLY for tests that never exercise
    # ownership (the id matches no real Physician, so such a caller fails the
    # unauthenticated check of PRD §2.1 if it hits a Physician-only endpoint).
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
}


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_analyst_headers(user_id: str) -> dict:
    """CompAnalyst with a specific X-User-ID (needed for segregation-of-duties)."""
    return build_user_headers(user_id, "CompAnalyst")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific X-User-ID (segregation-of-duties)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_committee_headers(user_id: str) -> dict:
    """CompCommittee with a specific X-User-ID (segregation-of-duties)."""
    return build_user_headers(user_id, "CompCommittee")


def make_physician_headers(user_id: str) -> dict:
    """Physician is entity-backed: pass the actual Physician.id as user_id
    whenever the call is ownership-gated (own reads, disputes, acknowledgments)."""
    return build_user_headers(user_id, "Physician")
