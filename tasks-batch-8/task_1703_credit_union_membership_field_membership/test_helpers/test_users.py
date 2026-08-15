"""Pre-built role headers for every role in the PRD.

Only Member is entity-backed (X-User-ID is the acting Member's id); the six
staff roles are opaque operator identifiers. Ownership-gated Member calls MUST
use make_member_headers() with the real Member.id; the shared member constant
is a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
# Segregation-of-duties tests need distinct operator ids, so the filing and
# deciding variants of MembershipOfficer / ComplianceOfficer are both provided.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # opaque roles
    "membership_officer_headers": build_user_headers("officer-1", "MembershipOfficer"),
    "membership_officer_2_headers": build_user_headers("officer-2", "MembershipOfficer"),
    "membership_officer_9_headers": build_user_headers("officer-9", "MembershipOfficer"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "compliance_officer_3_headers": build_user_headers("co-3", "ComplianceOfficer"),
    "regulator_headers": build_user_headers("reg-1", "Regulator"),
    "regulator_2_headers": build_user_headers("reg-2", "Regulator"),
    "board_director_headers": build_user_headers("bd-1", "BoardDirector"),
    "operations_officer_headers": build_user_headers("ops-1", "OperationsOfficer"),
    "system_admin_headers": build_user_headers("sysadmin-1", "SystemAdmin"),
}

# A request carrying no auth headers at all (authentication-tier rejection).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the acting Member.id whenever
    the call is ownership-gated (own record, accounts, transactions, ballots)."""
    return build_user_headers(member_id, "Member")


def make_membership_officer_headers(user_id: str = "officer-1") -> dict:
    return build_user_headers(user_id, "MembershipOfficer")


def make_compliance_officer_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_regulator_headers(user_id: str = "reg-1") -> dict:
    return build_user_headers(user_id, "Regulator")


def make_board_director_headers(user_id: str = "bd-1") -> dict:
    return build_user_headers(user_id, "BoardDirector")


def make_operations_officer_headers(user_id: str = "ops-1") -> dict:
    return build_user_headers(user_id, "OperationsOfficer")


def make_system_admin_headers(user_id: str = "sysadmin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")
