"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator identities (PRD §2.1): the X-User-ID is an
opaque operator fingerprint, never compared to any entity id. The server records
X-User-ID only where a transition captures it (compiled_by_user_id on compile,
released_by_user_id on release). Because the segregation-of-duties control
compares those two recorded ids, tests need headers carrying *specific* user ids
for the compiler vs the releaser — make_headers(user_id, role) builds those.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles and for tests that do not depend
# on a specific operator fingerprint.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "compounding_headers": build_user_headers("test-compounding-1", "CompoundingPharmacist"),
    "qa_headers": build_user_headers("test-qa-1", "QualityAssurancePharmacist"),
    "dispensing_headers": build_user_headers("test-dispensing-1", "DispensingPharmacist"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers carrying a specific X-User-ID for a given role.

    Use when a test must control the operator fingerprint the server records —
    e.g. compiling as 'comp-user-1' and releasing as a different 'qa-user-2' to
    satisfy (or deliberately violate) segregation of duties.
    """
    return build_user_headers(user_id, role)


def make_compounding_headers(user_id: str) -> dict:
    """CompoundingPharmacist headers with a specific operator id."""
    return build_user_headers(user_id, "CompoundingPharmacist")


def make_qa_headers(user_id: str) -> dict:
    """QualityAssurancePharmacist headers with a specific operator id."""
    return build_user_headers(user_id, "QualityAssurancePharmacist")
