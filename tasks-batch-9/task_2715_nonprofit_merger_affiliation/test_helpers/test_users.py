"""Auth header builders for the seven roles declared by the PRD.

Two roles carry an entity-backed identity: StrategyOfficer and BoardSecretary
act for a party Organization, so their X-User-ID must be the actual
Organization id created by the test. Every other role is an opaque operator
handle.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_STRATEGY_OFFICER = "StrategyOfficer"
ROLE_BOARD_SECRETARY = "BoardSecretary"
ROLE_DILIGENCE_LEAD = "DiligenceLead"
ROLE_CHARITABLE_TRUST_COUNSEL = "CharitableTrustCounsel"
ROLE_STATE_CHARITIES_REGULATOR = "StateCharitiesRegulator"
ROLE_INTEGRATION_MANAGER = "IntegrationManager"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_STRATEGY_OFFICER,
    ROLE_BOARD_SECRETARY,
    ROLE_DILIGENCE_LEAD,
    ROLE_CHARITABLE_TRUST_COUNSEL,
    ROLE_STATE_CHARITIES_REGULATOR,
    ROLE_INTEGRATION_MANAGER,
]

# --- opaque operator handles ---
PLATFORM_ADMIN = build_user_headers("admin-001", ROLE_PLATFORM_ADMIN)
PLATFORM_ADMIN_2 = build_user_headers("admin-002", ROLE_PLATFORM_ADMIN)
DILIGENCE_LEAD = build_user_headers("dl-001", ROLE_DILIGENCE_LEAD)
DILIGENCE_LEAD_2 = build_user_headers("dl-002", ROLE_DILIGENCE_LEAD)
DILIGENCE_LEAD_3 = build_user_headers("dl-003", ROLE_DILIGENCE_LEAD)
TRUST_COUNSEL = build_user_headers("ctc-001", ROLE_CHARITABLE_TRUST_COUNSEL)
TRUST_COUNSEL_2 = build_user_headers("ctc-002", ROLE_CHARITABLE_TRUST_COUNSEL)
CHARITIES_REGULATOR = build_user_headers("scr-001", ROLE_STATE_CHARITIES_REGULATOR)
INTEGRATION_MANAGER = build_user_headers("im-001", ROLE_INTEGRATION_MANAGER)
INTEGRATION_MANAGER_2 = build_user_headers("im-002", ROLE_INTEGRATION_MANAGER)

# --- unauthenticated / malformed identities ---
NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
UNKNOWN_ROLE = build_user_headers("who-001", "NotARealRole")


def make_strategy_officer_headers(org_id: str) -> Dict[str, str]:
    """StrategyOfficer acting for the Organization whose id is org_id."""
    return build_user_headers(org_id, ROLE_STRATEGY_OFFICER)


def make_board_secretary_headers(org_id: str) -> Dict[str, str]:
    """BoardSecretary acting for the Organization whose id is org_id."""
    return build_user_headers(org_id, ROLE_BOARD_SECRETARY)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, for role-permission probes."""
    return build_user_headers(user_id, role)
