"""
Pre-built auth headers, one per acting operator.

PRD §2.1: every request must carry `X-User-ID` and `X-User-Role`. For the
four operator roles the `X-User-ID` is an opaque identifier; for a
`DealerServiceManager` the `X-User-ID` is the `id` of the acting `Dealer`,
so those headers must be built per dealer at call time.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ─── Opaque operator identifiers ──────────────────────

SAFETY_ENGINEER_1_ID = "u-eng-1"
SAFETY_ENGINEER_2_ID = "u-eng-2"
COMPLIANCE_OFFICER_1_ID = "u-comp-1"
COMPLIANCE_OFFICER_2_ID = "u-comp-2"
OPERATIONS_MANAGER_ID = "u-ops-1"
CLAIMS_AUDITOR_ID = "u-aud-1"

# ─── Header dicts for the four opaque-identity roles ──

SAFETY_ENGINEER_1 = build_user_headers(SAFETY_ENGINEER_1_ID, Role.SAFETY_ENGINEER)
SAFETY_ENGINEER_2 = build_user_headers(SAFETY_ENGINEER_2_ID, Role.SAFETY_ENGINEER)
COMPLIANCE_OFFICER_1 = build_user_headers(COMPLIANCE_OFFICER_1_ID, Role.COMPLIANCE_OFFICER)
COMPLIANCE_OFFICER_2 = build_user_headers(COMPLIANCE_OFFICER_2_ID, Role.COMPLIANCE_OFFICER)
OPERATIONS_MANAGER = build_user_headers(OPERATIONS_MANAGER_ID, Role.RECALL_OPERATIONS_MANAGER)
CLAIMS_AUDITOR = build_user_headers(CLAIMS_AUDITOR_ID, Role.CLAIMS_AUDITOR)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "safety_engineer_1": SAFETY_ENGINEER_1,
    "safety_engineer_2": SAFETY_ENGINEER_2,
    "compliance_officer_1": COMPLIANCE_OFFICER_1,
    "compliance_officer_2": COMPLIANCE_OFFICER_2,
    "operations_manager": OPERATIONS_MANAGER,
    "claims_auditor": CLAIMS_AUDITOR,
}


# ─── Identity-threaded builders ───────────────────────

def make_dealer_service_manager_headers(dealer_id: str) -> Dict[str, str]:
    """
    Headers for a `DealerServiceManager` acting as one specific dealership.

    PRD §2.1: "When `X-User-Role` is `DealerServiceManager`, `X-User-ID` is
    the `id` of the acting `Dealer`."
    """
    return build_user_headers(dealer_id, Role.DEALER_SERVICE_MANAGER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user/role pair (used for role-matrix probes)."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that declare a role but omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that carry a user id but omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
