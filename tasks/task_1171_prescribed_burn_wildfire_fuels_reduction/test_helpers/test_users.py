"""Pre-built role headers for every role in the PRD (§2.1).

Identity rules (PRD §2.1): Landowner / BurnBoss / AgencyReviewer / Contractor are
entity-backed roles — X-User-ID must be the acting entity's id, so fixtures must
call the per-instance builders below. AssociationAdmin / AirQualityOfficer /
IncidentCommander carry opaque operator identifiers, so shared constants are fine.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (bad-payload 400s, 404s, role-denial probes by non-owning roles).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "AssociationAdmin"),
    "aqo_headers": build_user_headers("test-aqo-1", "AirQualityOfficer"),
    "commander_headers": build_user_headers("test-commander-1", "IncidentCommander"),
    # Fallbacks for entity-backed roles: use ONLY where no ownership-gated call
    # depends on the identity (e.g. a Landowner role-denied probe).
    "landowner_headers": build_user_headers("test-landowner-1", "Landowner"),
    "burn_boss_headers": build_user_headers("test-boss-1", "BurnBoss"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "AgencyReviewer"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}

# Any authenticated role may read (PRD §2.1); the admin header doubles as the
# canonical "Any" reader for GET calls.
ANY_READER_HEADERS = TEST_USERS["admin_headers"]


def make_landowner_headers(user_id: str) -> dict:
    """Landowner is entity-backed: pass the Landowner.id for ownership-gated calls."""
    return build_user_headers(user_id, "Landowner")


def make_burn_boss_headers(user_id: str) -> dict:
    """BurnBoss is entity-backed: pass the BurnBoss.id of the acting author."""
    return build_user_headers(user_id, "BurnBoss")


def make_reviewer_headers(user_id: str) -> dict:
    """AgencyReviewer is entity-backed by BurnBoss: pass the reviewer's BurnBoss.id."""
    return build_user_headers(user_id, "AgencyReviewer")


def make_contractor_headers(user_id: str) -> dict:
    """Contractor is entity-backed: pass the Contractor.id owning the assignment."""
    return build_user_headers(user_id, "Contractor")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """AssociationAdmin carries an opaque id; a custom id is needed only for the
    cost-share segregation-of-duties probe (approver must differ from applicant)."""
    return build_user_headers(user_id, "AssociationAdmin")
