"""Pre-built role headers for every role in the PRD.

All four roles carry an OPAQUE identity (PRD Section 2.1): X-User-ID is an
operator identifier never compared to any entity's id for ownership. Shared
constants are therefore the canonical form for every role here — no
entity-backed ownership threading is required.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_worker_headers": build_user_headers("intake-worker-1", "IntakeWorker"),
    "caseworker_headers": build_user_headers("caseworker-1", "Caseworker"),
    "supervisor_headers": build_user_headers("supervisor-1", "Supervisor"),
    "admin_headers": build_user_headers("admin-1", "Admin"),
}
