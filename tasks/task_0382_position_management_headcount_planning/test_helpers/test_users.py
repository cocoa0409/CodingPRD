"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use an OPAQUE identity model: X-User-ID is an operator
identifier not tied to any persisted entity and is never matched against an
entity's id. Ownership and authorization are governed entirely by role. There
are therefore no entity_backed roles and no per-instance header builders — the
shared constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "hrbp_headers": build_user_headers("test-hrbp-1", "HRBP"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceController"),
    "comp_headers": build_user_headers("test-comp-1", "CompensationAnalyst"),
    "director_headers": build_user_headers("test-director-1", "HRDirector"),
    # An unrecognised role for ERR_UNAUTHENTICATED (401) probes.
    "intruder_headers": build_user_headers("test-intruder-1", "Intruder"),
}
