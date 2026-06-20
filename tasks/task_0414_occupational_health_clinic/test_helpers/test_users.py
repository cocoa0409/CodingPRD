"""Pre-built role headers for every role in the PRD.

All four roles use an opaque identity model: X-User-ID is an opaque operator id that
is never matched against any entity's id. The server records the acting operator's id
only for the clinician-pinning, MRO-assignment, and segregation-of-duties comparisons.
Because identity is opaque (not entity_backed), the shared constants below are the
canonical form. Builders are provided for tests that must control the operator id
(e.g. MRO assignment must equal Employer.mro_user_id; the encounter clinician id is
pinned for segregation-of-duties).
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids used across fixtures.
DEFAULT_CLINICIAN_ID = "clin-1"
DEFAULT_MRO_ID = "mro-1"
DEFAULT_COLLECTOR_ID = "collector-1"
DEFAULT_ADMIN_ID = "admin-1"

TEST_USERS = {
    "clinic_admin_headers": build_user_headers(DEFAULT_ADMIN_ID, "ClinicAdmin"),
    "clinician_headers": build_user_headers(DEFAULT_CLINICIAN_ID, "Clinician"),
    "collector_headers": build_user_headers(DEFAULT_COLLECTOR_ID, "Collector"),
    "mro_headers": build_user_headers(DEFAULT_MRO_ID, "MRO"),
}


def make_clinic_admin_headers(user_id: str = DEFAULT_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "ClinicAdmin")


def make_clinician_headers(user_id: str = DEFAULT_CLINICIAN_ID) -> dict:
    """For Clinician (opaque). Pass a specific operator id when the encounter's
    pinned clinician_user_id matters (segregation-of-duties)."""
    return build_user_headers(user_id, "Clinician")


def make_collector_headers(user_id: str = DEFAULT_COLLECTOR_ID) -> dict:
    return build_user_headers(user_id, "Collector")


def make_mro_headers(user_id: str = DEFAULT_MRO_ID) -> dict:
    """For MRO (opaque). Pass the operator id that must equal Employer.mro_user_id
    for assignment checks, or a non-matching id to exercise ERR_MRO_NOT_ASSIGNED."""
    return build_user_headers(user_id, "MRO")
