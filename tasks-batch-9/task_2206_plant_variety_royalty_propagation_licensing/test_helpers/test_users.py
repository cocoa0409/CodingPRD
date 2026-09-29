"""Pre-built role headers for every role in the PRD.

Four of the five roles carry an opaque operator identifier in X-User-ID.  The
`Propagator` role is different: X-User-ID is the id of the acting Propagator
row, so ownership-gated calls MUST use make_propagator_headers(propagator_id).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across tests.
BREEDER_USER_ID = "breeder-1"
OFFICER_USER_ID = "officer-1"
OFFICER_TWO_USER_ID = "officer-2"
OFFICER_THREE_USER_ID = "officer-3"
COORDINATOR_USER_ID = "coord-1"
AUDITOR_USER_ID = "auditor-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "breeder_admin_headers": build_user_headers(BREEDER_USER_ID, "BreederAdmin"),
    "licensing_officer_headers": build_user_headers(OFFICER_USER_ID, "LicensingOfficer"),
    "licensing_officer_two_headers": build_user_headers(OFFICER_TWO_USER_ID, "LicensingOfficer"),
    "licensing_officer_three_headers": build_user_headers(OFFICER_THREE_USER_ID, "LicensingOfficer"),
    "trial_coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "TrialCoordinator"),
    "compliance_auditor_headers": build_user_headers(AUDITOR_USER_ID, "ComplianceAuditor"),
    # Fallback only: never use for an ownership-gated Propagator call.
    "propagator_headers": build_user_headers("test-propagator-1", "Propagator"),
}


def make_propagator_headers(propagator_id: str) -> Dict[str, str]:
    """Headers for the Propagator role.  X-User-ID must be the acting
    Propagator row's own id, because ownership checks compare the propagator
    reached from the resource against it."""
    return build_user_headers(propagator_id, "Propagator")


def make_breeder_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "BreederAdmin")


def make_licensing_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "LicensingOfficer")


def make_trial_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "TrialCoordinator")


def make_compliance_auditor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceAuditor")
