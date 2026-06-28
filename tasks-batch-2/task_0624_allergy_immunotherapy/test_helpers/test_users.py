"""Pre-built role headers for every role in the PRD.

All five roles are opaque operator identities (PRD section 2.1): the X-User-ID
is never compared against any entity id, so a shared constant per role is the
canonical form and no per-instance entity-backed builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "allergist_headers": build_user_headers("test-allergist-1", "Allergist"),
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
    "biller_headers": build_user_headers("test-biller-1", "Biller"),
    "frontdesk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
}
