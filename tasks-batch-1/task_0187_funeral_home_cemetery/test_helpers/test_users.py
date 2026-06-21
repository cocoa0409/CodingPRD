"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use an OPAQUE identity model: X-User-ID is an opaque operator
identifier that is never compared to any entity's id for ownership (PRD §2.1).
The shared constants below are therefore safe everywhere.

The one place X-User-ID is semantically load-bearing is the segregation-of-duties
check (PRD §2.1, §3.6): acknowledging the FTC disclosure records the acting
Arranger's X-User-ID into the case's disclosure_officer_id, and marking the
contract funded compares the funding officer's X-User-ID against that recorded
value. Those tests need DISTINCT identities, sometimes the SAME identity acting
under two different roles. `make_headers(user_id, role)` builds those on demand.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("user-admin-1", "Admin"),
    "arranger_headers": build_user_headers("user-arranger-1", "Arranger"),
    "trust_officer_headers": build_user_headers("user-trust-1", "TrustOfficer"),
    "cemetery_clerk_headers": build_user_headers("user-clerk-1", "CemeteryClerk"),
    "registrar_headers": build_user_headers("user-registrar-1", "Registrar"),
    # Second distinct identities for the segregation-of-duties workflow.
    "arranger_headers_alt": build_user_headers("user-arranger-2", "Arranger"),
    "trust_officer_headers_alt": build_user_headers("user-trust-2", "TrustOfficer"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an explicit (user_id, role) pair.

    Used wherever the test must control the acting X-User-ID — chiefly the
    segregation-of-duties tests, where the disclosure-acknowledging Arranger
    and the contract-funding TrustOfficer must carry specific, distinct (or,
    for the violation case, identical) identifiers.
    """
    return build_user_headers(user_id, role)
