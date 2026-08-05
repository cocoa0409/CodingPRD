"""Pre-built role headers for every role named in PRD §2.1.

Eight roles carry an opaque identity: their `X-User-ID` is an operator identifier that is
never compared against any row's `id`. The ninth role, `Inmate`, is entity backed — its
`X-User-ID` must be the acting inmate's own `id`, so ownership-gated calls MUST use
`make_inmate_headers(inmate["id"])` rather than any shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared operator identifiers for the eight opaque roles.
INTAKE_OFFICER_ID = "u-intake-1"
NURSE_ID = "u-nurse-1"
PROVIDER_ID = "u-prov-1"
UTILIZATION_REVIEWER_ID = "u-ur-1"
PEER_REVIEWER_ID = "u-peer-1"
CUSTODY_OFFICER_ID = "u-co-1"
HEALTH_SERVICES_ADMIN_ID = "u-hsa-1"
GRIEVANCE_COORDINATOR_ID = "u-gc-1"

TEST_USERS = {
    "intake_officer_headers": build_user_headers(INTAKE_OFFICER_ID, "IntakeOfficer"),
    "nurse_headers": build_user_headers(NURSE_ID, "Nurse"),
    "provider_headers": build_user_headers(PROVIDER_ID, "Provider"),
    "utilization_reviewer_headers": build_user_headers(
        UTILIZATION_REVIEWER_ID, "UtilizationReviewer"
    ),
    "peer_reviewer_headers": build_user_headers(PEER_REVIEWER_ID, "PeerReviewer"),
    "custody_officer_headers": build_user_headers(CUSTODY_OFFICER_ID, "CustodyOfficer"),
    "health_services_admin_headers": build_user_headers(
        HEALTH_SERVICES_ADMIN_ID, "HealthServicesAdmin"
    ),
    "grievance_coordinator_headers": build_user_headers(
        GRIEVANCE_COORDINATOR_ID, "GrievanceCoordinator"
    ),
    # Placeholder only. Never use for an ownership-gated call — build per inmate instead.
    "inmate_headers": build_user_headers("u-inmate-placeholder", "Inmate"),
}


# ─── Per-instance builders ────────────────────────────

def make_inmate_headers(inmate_id: str) -> dict:
    """For the entity-backed `Inmate` role: X-User-ID is the acting inmate's own id."""
    return build_user_headers(inmate_id, "Inmate")


def make_nurse_headers(user_id: str) -> dict:
    """Nurse acting under a specific operator identifier (segregation-of-duties tests)."""
    return build_user_headers(user_id, "Nurse")


def make_provider_headers(user_id: str) -> dict:
    """Provider acting under a specific operator identifier (prescriber_user_id target)."""
    return build_user_headers(user_id, "Provider")


def make_utilization_reviewer_headers(user_id: str) -> dict:
    """UtilizationReviewer acting under a specific operator identifier."""
    return build_user_headers(user_id, "UtilizationReviewer")


def make_peer_reviewer_headers(user_id: str) -> dict:
    """PeerReviewer acting under a specific operator identifier."""
    return build_user_headers(user_id, "PeerReviewer")


def make_custody_officer_headers(user_id: str) -> dict:
    """CustodyOfficer acting under a specific operator identifier."""
    return build_user_headers(user_id, "CustodyOfficer")


def make_health_services_admin_headers(user_id: str) -> dict:
    """HealthServicesAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "HealthServicesAdmin")


def make_grievance_coordinator_headers(user_id: str) -> dict:
    """GrievanceCoordinator acting under a specific operator identifier."""
    return build_user_headers(user_id, "GrievanceCoordinator")


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
