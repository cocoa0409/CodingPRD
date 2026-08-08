"""Pre-built role headers for every role in the PRD.

Applicant and Driller are entity-backed: for ownership-gated calls the
X-User-ID MUST be the acting entity's own id, so per-instance builders are
used. LabAnalyst and HealthOfficer are opaque operator identities; a shared
constant is fine except where segregation-of-duties needs a specific officer
id, for which make_health_officer_headers(id) is provided.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise
# entity ownership (e.g. 404-on-missing-resource, 401/403 auth checks).
TEST_USERS = {
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "driller_headers": build_user_headers("test-driller-1", "Driller"),
    "lab_analyst_headers": build_user_headers("test-lab-1", "LabAnalyst"),
    "health_officer_headers": build_user_headers("test-officer-1", "HealthOfficer"),
}


# Per-instance builders — required for the entity-backed roles.
def make_applicant_headers(applicant_id: str) -> dict:
    """For Applicant (entity_backed:Applicant). Pass the acting Applicant.id."""
    return build_user_headers(applicant_id, "Applicant")


def make_driller_headers(driller_id: str) -> dict:
    """For Driller (entity_backed:Driller). Pass the acting Driller.id."""
    return build_user_headers(driller_id, "Driller")


def make_lab_analyst_headers(operator_id: str = "test-lab-1") -> dict:
    """For LabAnalyst (opaque operator id)."""
    return build_user_headers(operator_id, "LabAnalyst")


def make_health_officer_headers(officer_id: str = "test-officer-1") -> dict:
    """For HealthOfficer (opaque operator id). Pass a specific officer id when
    segregation-of-duties on contamination-case close must be controlled."""
    return build_user_headers(officer_id, "HealthOfficer")
