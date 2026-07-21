"""Pre-built role headers for every role the PRD recognises.

`Organizer` and `Buyer` are backed by persisted entities: ownership checks compare
X-User-ID against the record's own id, so any ownership-gated call MUST use the
per-instance builder with the real entity id. The remaining roles are opaque
operator identifiers and the shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque-operator identifiers used consistently across setups.
ADMIN_USER_ID = "admin-1"
GATE_USER_ID = "gate-1"
GATE_USER_ID_2 = "gate-2"
FINANCE_USER_ID = "fin-1"
FINANCE_USER_ID_2 = "fin-2"

# Anonymous alone requires no X-User-ID.
ANONYMOUS_HEADERS = {
    "X-User-Role": "Anonymous",
    "Content-Type": "application/json",
}

TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "gate_staff_headers": build_user_headers(GATE_USER_ID, "GateStaff"),
    "gate_staff_headers_2": build_user_headers(GATE_USER_ID_2, "GateStaff"),
    "finance_officer_headers": build_user_headers(FINANCE_USER_ID, "FinanceOfficer"),
    "finance_officer_headers_2": build_user_headers(FINANCE_USER_ID_2, "FinanceOfficer"),
    "anonymous_headers": ANONYMOUS_HEADERS,
    # Fallbacks for tests that never exercise ownership (bad payload, missing
    # resource). Ownership-gated calls must use the builders below instead.
    "organizer_headers": build_user_headers("test-organizer-1", "Organizer"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_organizer_headers(organizer_id: str) -> dict:
    """Headers for an acting Organizer. Pass the real Organizer id: ownership
    checks compare it against the organizer reached from the target resource."""
    return build_user_headers(organizer_id, "Organizer")


def make_buyer_headers(buyer_id: str) -> dict:
    """Headers for an acting Buyer. Pass the real Buyer id: ownership checks
    compare it against the order's, waitlist entry's or admission's buyer."""
    return build_user_headers(buyer_id, "Buyer")


def make_gate_staff_headers(user_id: str) -> dict:
    """Headers for a gate operator; the id is recorded as scanned_by_user_id."""
    return build_user_headers(user_id, "GateStaff")


def make_finance_officer_headers(user_id: str) -> dict:
    """Headers for a finance operator; the id is recorded as approved_by_user_id
    or released_by_user_id and the two are compared for segregation of duties."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
