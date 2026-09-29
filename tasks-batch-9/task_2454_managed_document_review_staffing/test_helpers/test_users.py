"""Role headers for the five acting capacities.

Two roles are identity-bound to a stored row: a ``Reviewer`` caller must
present the reviewer row's own ``id`` as ``X-User-ID`` and a ``ClientCounsel``
caller must present the client row's own ``id``. For those two roles always
use the per-entity builders below rather than the fixed placeholders in
``TEST_USERS``, otherwise ownership-gated calls will be refused.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_ENGAGEMENT_MANAGER = "EngagementManager"
ROLE_STAFFING_COORDINATOR = "StaffingCoordinator"
ROLE_QC_LEAD = "QCLead"
ROLE_REVIEWER = "Reviewer"
ROLE_CLIENT_COUNSEL = "ClientCounsel"

ALL_ROLES = [
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_STAFFING_COORDINATOR,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_CLIENT_COUNSEL,
]

# Opaque principals: the identifier is not matched against any stored row.
ENGAGEMENT_MANAGER_ID = "em-0001"
STAFFING_COORDINATOR_ID = "sc-0001"
QC_LEAD_ID = "qc-0001"

TEST_USERS = {
    ROLE_ENGAGEMENT_MANAGER: build_user_headers(
        ENGAGEMENT_MANAGER_ID, ROLE_ENGAGEMENT_MANAGER
    ),
    ROLE_STAFFING_COORDINATOR: build_user_headers(
        STAFFING_COORDINATOR_ID, ROLE_STAFFING_COORDINATOR
    ),
    ROLE_QC_LEAD: build_user_headers(QC_LEAD_ID, ROLE_QC_LEAD),
}

ENGAGEMENT_MANAGER = TEST_USERS[ROLE_ENGAGEMENT_MANAGER]
STAFFING_COORDINATOR = TEST_USERS[ROLE_STAFFING_COORDINATOR]
QC_LEAD = TEST_USERS[ROLE_QC_LEAD]


def make_engagement_manager_headers(user_id: str = ENGAGEMENT_MANAGER_ID) -> dict:
    """Headers for an engagement manager; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_ENGAGEMENT_MANAGER)


def make_staffing_coordinator_headers(
    user_id: str = STAFFING_COORDINATOR_ID,
) -> dict:
    """Headers for a staffing coordinator; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_STAFFING_COORDINATOR)


def make_qc_lead_headers(user_id: str = QC_LEAD_ID) -> dict:
    """Headers for a quality-control lead; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_QC_LEAD)


def make_reviewer_headers(reviewer_id: str) -> dict:
    """Headers for a reviewer acting on their own row.

    ``reviewer_id`` must be the ``id`` returned when the reviewer was sourced.
    """
    return build_user_headers(reviewer_id, ROLE_REVIEWER)


def make_client_counsel_headers(client_id: str) -> dict:
    """Headers for client counsel acting for their own client.

    ``client_id`` must be the ``id`` returned when the client was registered.
    """
    return build_user_headers(client_id, ROLE_CLIENT_COUNSEL)


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for parametrized role-permission sweeps."""
    return build_user_headers(user_id, role)


def raw_headers(user_id: str | None = None, role: str | None = None) -> dict:
    """Build a header dict with either header deliberately omitted.

    Used by the tests that probe a missing identity header, a missing role
    header, or an unrecognised role name.
    """
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers
