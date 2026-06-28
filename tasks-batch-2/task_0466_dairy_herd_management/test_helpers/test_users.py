"""Pre-built role headers for every role in the PRD.

All five roles carry an opaque X-User-ID: the server never compares it to any
entity's id for ownership (PRD §2.1). Shared constants are therefore the
canonical form for every role; there are no entity-backed builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "herd_manager_headers": build_user_headers("test-herd-manager-1", "HerdManager"),
    "parlor_tech_headers": build_user_headers("test-parlor-tech-1", "ParlorTech"),
    "veterinarian_headers": build_user_headers("test-vet-1", "Veterinarian"),
    "coop_agent_headers": build_user_headers("test-coop-agent-1", "CoopSettlementAgent"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}
