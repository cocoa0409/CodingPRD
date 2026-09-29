"""Pre-built role headers for every role in the PRD.

`OperatorAdmin` and `ComplianceAuditor` are opaque principals: their
`X-User-ID` is never matched against an entity id, so the shared constants
below are the canonical form for them.

`SiteManager` and `FitnessStaff` resolve to a staff member id, `ClientSponsor`
to a client contract id and `Member` to a member id.  For any call that is
ownership-scoped, build the headers with the real entity id using the
`make_*_headers` builders — the shared constants are only safe for calls that
do not exercise ownership (bad payloads, missing resources, role gating).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque principals — shared constants are canonical.
    "operator_admin_headers": build_user_headers("op-admin-1", "OperatorAdmin"),
    "compliance_auditor_headers": build_user_headers("auditor-1", "ComplianceAuditor"),
    # Entity-backed principals — fallback for non-ownership tests only.
    "site_manager_headers": build_user_headers("staff-manager-1", "SiteManager"),
    "fitness_staff_headers": build_user_headers("staff-fitness-1", "FitnessStaff"),
    "client_sponsor_headers": build_user_headers("contract-sponsor-1", "ClientSponsor"),
    "member_headers": build_user_headers("member-1", "Member"),
}

# A second opaque operator identity, for segregation-of-duties scenarios where
# the acting principal must differ from a recorded one.
SECOND_OPERATOR_ADMIN_HEADERS = build_user_headers("op-admin-2", "OperatorAdmin")


def make_operator_admin_headers(user_id: str = "op-admin-1") -> dict:
    """OperatorAdmin is opaque; the id is recorded for audit only."""
    return build_user_headers(user_id, "OperatorAdmin")


def make_compliance_auditor_headers(user_id: str = "auditor-1") -> dict:
    """ComplianceAuditor is opaque; the id is recorded for audit only."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_site_manager_headers(staff_member_id: str) -> dict:
    """For SiteManager. Pass the acting staff member's id."""
    return build_user_headers(staff_member_id, "SiteManager")


def make_fitness_staff_headers(staff_member_id: str) -> dict:
    """For FitnessStaff. Pass the acting staff member's id."""
    return build_user_headers(staff_member_id, "FitnessStaff")


def make_client_sponsor_headers(contract_id: str) -> dict:
    """For ClientSponsor. Pass the acting client contract's id."""
    return build_user_headers(contract_id, "ClientSponsor")


def make_member_headers(member_id: str) -> dict:
    """For Member. Pass the acting member's id."""
    return build_user_headers(member_id, "Member")
