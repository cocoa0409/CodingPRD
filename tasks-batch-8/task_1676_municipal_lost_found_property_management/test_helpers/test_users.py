"""Pre-built role headers for every role in the PRD (§2.1, §4).

Only Claimant is entity-backed: when X-User-Role is Claimant, X-User-ID is the
id of the acting Claimant entity (PRD §2.1), so ownership-gated calls MUST use
make_claimant_headers() with the real Claimant.id. All other roles are opaque
operator identifiers; the per-role builders exist so tests can pick distinct
operator ids (needed for the segregation-of-duties rules of §3.4/§3.5/§3.8).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (bad-payload 400s, missing-resource 404s, wrong-role denials).
TEST_USERS = {
    "public_user_headers": build_user_headers("test-public-1", "PublicUser"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "claimant_headers": build_user_headers("test-claimant-1", "Claimant"),
    "intake_officer_headers": build_user_headers("officer-intake-1", "IntakeOfficer"),
    "property_custodian_headers": build_user_headers("custodian-1", "PropertyCustodian"),
    "claims_examiner_headers": build_user_headers("examiner-1", "ClaimsExaminer"),
    "release_officer_headers": build_user_headers("officer-release-1", "ReleaseOfficer"),
    "police_liaison_headers": build_user_headers("liaison-1", "PoliceLiaison"),
    "auction_coordinator_headers": build_user_headers("coord-1", "AuctionCoordinator"),
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
}


def make_claimant_headers(claimant_id: str) -> dict:
    """For Claimant (entity-backed by the Claimant resource). Pass the actual
    Claimant.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(claimant_id, "Claimant")


def make_public_user_headers(user_id: str = "test-public-1") -> dict:
    return build_user_headers(user_id, "PublicUser")


def make_intake_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeOfficer")


def make_property_custodian_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertyCustodian")


def make_claims_examiner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsExaminer")


def make_release_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReleaseOfficer")


def make_police_liaison_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PoliceLiaison")


def make_auction_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AuctionCoordinator")


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
