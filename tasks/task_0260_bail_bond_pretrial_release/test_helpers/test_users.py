"""Pre-built role headers for every role in the Bail Bond & Pretrial Release API.

All five roles (BondsAgent, Court, ComplianceOfficer, RecoveryAgent, SystemAdmin)
carry an OPAQUE identity (PRD §2.1): X-User-ID is an operator identifier that is
never compared to any resource's id. The shared constants below are therefore the
canonical form for every role.

The one place X-User-ID matters across operations is segregation of duties on
exoneration (PRD §3.7): the ComplianceOfficer who exonerates a bond must not be
the same X-User-ID who activated it as a BondsAgent. Because BondsAgent and
ComplianceOfficer use different default user-ids here, an exoneration by the
shared ComplianceOfficer constant after an activation by the shared BondsAgent
constant cleanly passes the SoD check. The make_*_headers builders let a test
control X-User-ID explicitly when it needs to force same-user / distinct-user.
"""
from prd_bench_local_runner.testing import build_user_headers

# Default operator ids per role (opaque; never an entity id).
BONDS_AGENT_ID = "agent-1"
COURT_ID = "court-1"
COMPLIANCE_OFFICER_ID = "officer-1"
RECOVERY_AGENT_ID = "recovery-1"
SYSTEM_ADMIN_ID = "admin-1"

TEST_USERS = {
    "bonds_agent_headers": build_user_headers(BONDS_AGENT_ID, "BondsAgent"),
    "court_headers": build_user_headers(COURT_ID, "Court"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_ID, "ComplianceOfficer"),
    "recovery_agent_headers": build_user_headers(RECOVERY_AGENT_ID, "RecoveryAgent"),
    "system_admin_headers": build_user_headers(SYSTEM_ADMIN_ID, "SystemAdmin"),
}


def make_bonds_agent_headers(user_id: str = BONDS_AGENT_ID) -> dict:
    """BondsAgent is opaque; user_id is an arbitrary operator identifier. Pass an
    explicit user_id to control the X-User-ID retained at activation for the
    segregation-of-duties comparison on exoneration."""
    return build_user_headers(user_id, "BondsAgent")


def make_court_headers(user_id: str = COURT_ID) -> dict:
    return build_user_headers(user_id, "Court")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_ID) -> dict:
    """ComplianceOfficer is opaque. Pass an explicit user_id to force a same-user
    self-approval (== the activating agent's id) when exercising
    ERR_SEGREGATION_OF_DUTIES."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_recovery_agent_headers(user_id: str = RECOVERY_AGENT_ID) -> dict:
    return build_user_headers(user_id, "RecoveryAgent")


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
