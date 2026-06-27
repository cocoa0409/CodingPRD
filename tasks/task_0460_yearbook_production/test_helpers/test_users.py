"""Pre-built role headers for every role in the Yearbook Production PRD (§2.1).

All four roles (Adviser, Staff, Contributor, SalesRep) are opaque operator identities:
the X-User-ID value is not tied to any persisted entity's id, and the server decides
authorization purely from the declared X-User-Role (PRD §2.1). Shared constants are
therefore the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "adviser_headers": build_user_headers("adv-1", "Adviser"),
    "staff_headers": build_user_headers("staff-9", "Staff"),
    "contributor_headers": build_user_headers("c-1", "Contributor"),
    "salesrep_headers": build_user_headers("sr-1", "SalesRep"),
}
