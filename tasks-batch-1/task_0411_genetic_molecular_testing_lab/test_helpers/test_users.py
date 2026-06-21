"""Pre-built role headers for every role in the PRD.

Per PRD §2.1 every role's identity is *opaque*: X-User-ID is an operator
identifier never compared to any entity id. The only place X-User-ID is
behaviourally significant is the two-person-integrity rule (a variant's
classified_by_user_id vs the signing director's X-User-ID at sign-out).
For that reason the shared constants below are the canonical form, and
make_headers(role, user_id) lets a test pin a specific X-User-ID when it
must control the segregation-of-duties comparison.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for all opaque roles.
TEST_USERS = {
    "director_headers": build_user_headers("director-1", "LabDirector"),
    "intake_headers": build_user_headers("intake-1", "LabIntake"),
    "accessioning_headers": build_user_headers("accession-1", "AccessioningTech"),
    "molecular_headers": build_user_headers("tech-1", "MolecularTechnologist"),
    "billing_headers": build_user_headers("billing-1", "BillingSpecialist"),
    "counselor_headers": build_user_headers("counselor-1", "GeneticCounselor"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary (user_id, role) pair. Use when a test
    must control the acting X-User-ID for the segregation-of-duties check."""
    return build_user_headers(user_id, role)


def director_headers(user_id: str = "director-1") -> dict:
    return build_user_headers(user_id, "LabDirector")


def molecular_headers(user_id: str = "tech-1") -> dict:
    return build_user_headers(user_id, "MolecularTechnologist")
