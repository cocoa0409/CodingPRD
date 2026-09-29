"""Pre-built caller headers for every role in the PRD.

Nine of the ten roles are opaque identities whose `X-User-ID` is never compared
to any entity's `id`, so a shared constant is the canonical form for them.
`CrewChief` is the one entity-backed identity: its `X-User-ID` must be the `id`
of the acting `Worker` row, so ownership-gated calls MUST go through
``make_crew_chief_headers(worker_id)``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the nine opaque roles.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("user-admin-1", "PlatformAdmin"),
    "route_manager_headers": build_user_headers("user-routemgr-1", "RouteManager"),
    "contract_negotiator_headers": build_user_headers(
        "user-negotiator-1", "ContractNegotiator"
    ),
    "general_manager_headers": build_user_headers("user-gm-1", "GeneralManager"),
    "lot_boss_headers": build_user_headers("user-lotboss-1", "LotBoss"),
    "safety_officer_headers": build_user_headers("user-safety-1", "SafetyOfficer"),
    "compliance_clerk_headers": build_user_headers("user-clerk-1", "ComplianceClerk"),
    "jurisdiction_officer_headers": build_user_headers(
        "user-officer-1", "JurisdictionOfficer"
    ),
    "ticketing_auditor_headers": build_user_headers("user-auditor-1", "TicketingAuditor"),
    # Fallback for CrewChief tests that do not exercise roster ownership at all.
    "crew_chief_headers": build_user_headers("user-crewchief-1", "CrewChief"),
}

# The negotiator identity that sends terms, and the two general-manager
# identities used to exercise the countersignature separation: one that differs
# from the sender and one that deliberately collides with it.
NEGOTIATOR_SENDER_USER_ID = "user-negotiator-1"
GENERAL_MANAGER_USER_ID = "user-gm-1"
COLLIDING_SENDER_USER_ID = "user-gm-9"

SENDING_GENERAL_MANAGER_HEADERS = build_user_headers(
    COLLIDING_SENDER_USER_ID, "ContractNegotiator"
)
COLLIDING_GENERAL_MANAGER_HEADERS = build_user_headers(
    COLLIDING_SENDER_USER_ID, "GeneralManager"
)


def make_crew_chief_headers(worker_id: str) -> dict:
    """Headers for a `CrewChief` acting as the `Worker` row with this `id`.

    Pass the actual worker's `id` whenever the call is ownership-gated, which is
    every read of a worker-scoped crew-assignment roster.
    """
    return build_user_headers(worker_id, "CrewChief")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_contract_negotiator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractNegotiator")


def make_general_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GeneralManager")
