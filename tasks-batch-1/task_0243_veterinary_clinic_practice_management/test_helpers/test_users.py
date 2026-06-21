"""Pre-built role headers for every role in the PRD.

All three roles (Receptionist, Veterinarian, PracticeManager) are opaque operator
identifiers per PRD 2.1: the X-User-ID is never compared to any resource id, and
authorization is purely role-based. So the shared-constant form is canonical for
every role; there are no entity_backed roles requiring per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "receptionist_headers": build_user_headers("test-receptionist-1", "Receptionist"),
    "veterinarian_headers": build_user_headers("test-veterinarian-1", "Veterinarian"),
    "practice_manager_headers": build_user_headers("test-practice-manager-1", "PracticeManager"),
}
