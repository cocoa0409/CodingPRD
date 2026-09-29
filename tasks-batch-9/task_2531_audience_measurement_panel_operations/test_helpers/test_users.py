"""Header builders for the seven roles the PRD defines.

PRD 2.1 splits the roles two ways. For `PanelOperationsManager`,
`FieldTechnician`, `MethodologyStatistician`, `ClientServiceRep`,
`AccreditationAuditor` and `GovernanceDirector` the `X-User-ID` is "an opaque
operator identifier that is not tied to any persisted entity", so those builders
default to a stable per-role literal while still accepting an override -- three
segregation-of-duties gates (PRD 2.10) turn on whether two operator ids are the
same person, so several distinct literals per role are provided. For `ClientUser`
the `X-User-ID` "is the `id` of the acting `Client` row", so that builder takes a
mandatory client id.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from test_helpers.types import UserRole

# ---------------------------------------------------------------------------
# Stable opaque operator identifiers (PRD 2.1 identity semantics)
# ---------------------------------------------------------------------------
PANEL_OPS_USER_ID = "panel-ops-001"
PANEL_OPS_SECOND_USER_ID = "panel-ops-002"

FIELD_TECH_USER_ID = "field-tech-001"
FIELD_TECH_SECOND_USER_ID = "field-tech-002"

# Two statisticians: PRD 3.7 requires the publisher to differ from the opener.
STATISTICIAN_USER_ID = "statistician-opener"
STATISTICIAN_PUBLISHER_USER_ID = "statistician-publisher"
STATISTICIAN_THIRD_USER_ID = "statistician-third"

CLIENT_SERVICE_USER_ID = "client-service-001"
CLIENT_SERVICE_SECOND_USER_ID = "client-service-002"

# Two auditors: PRD 3.9 requires the finalizer to differ from the opener.
AUDITOR_USER_ID = "auditor-opener"
AUDITOR_FINALIZER_USER_ID = "auditor-finalizer"

# Two directors: PRD 3.9 requires the activator to differ from the drafter.
DIRECTOR_USER_ID = "director-drafter"
DIRECTOR_ACTIVATOR_USER_ID = "director-activator"

OPAQUE_ROLE_DEFAULT_USER_IDS = {
    UserRole.PANEL_OPERATIONS_MANAGER.value: PANEL_OPS_USER_ID,
    UserRole.FIELD_TECHNICIAN.value: FIELD_TECH_USER_ID,
    UserRole.METHODOLOGY_STATISTICIAN.value: STATISTICIAN_USER_ID,
    UserRole.CLIENT_SERVICE_REP.value: CLIENT_SERVICE_USER_ID,
    UserRole.ACCREDITATION_AUDITOR.value: AUDITOR_USER_ID,
    UserRole.GOVERNANCE_DIRECTOR.value: DIRECTOR_USER_ID,
}


def make_panel_ops_headers(user_id: str = PANEL_OPS_USER_ID) -> Dict[str, str]:
    """Headers for a `PanelOperationsManager`; `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.PANEL_OPERATIONS_MANAGER.value)


def make_field_tech_headers(user_id: str = FIELD_TECH_USER_ID) -> Dict[str, str]:
    """Headers for a `FieldTechnician`; `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.FIELD_TECHNICIAN.value)


def make_statistician_headers(user_id: str = STATISTICIAN_USER_ID) -> Dict[str, str]:
    """Headers for a `MethodologyStatistician`; `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.METHODOLOGY_STATISTICIAN.value)


def make_client_service_headers(user_id: str = CLIENT_SERVICE_USER_ID) -> Dict[str, str]:
    """Headers for a `ClientServiceRep`; `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.CLIENT_SERVICE_REP.value)


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> Dict[str, str]:
    """Headers for an `AccreditationAuditor`; `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.ACCREDITATION_AUDITOR.value)


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    """Headers for a `GovernanceDirector`; `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.GOVERNANCE_DIRECTOR.value)


def make_client_user_headers(client_id: str) -> Dict[str, str]:
    """Headers for a `ClientUser` acting as the `Client` row with this `id`."""
    return build_user_headers(client_id, UserRole.CLIENT_USER.value)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/id pair, including deliberately bad roles."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str = PANEL_OPS_USER_ID) -> Dict[str, str]:
    """`X-User-Role` absent entirely -- an `ERR_UNAUTHENTICATED` probe (PRD 2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_with_empty_role(user_id: str = PANEL_OPS_USER_ID) -> Dict[str, str]:
    """`X-User-Role` present but empty -- an `ERR_UNAUTHENTICATED` probe."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def make_headers_without_user_id(role: str = UserRole.PANEL_OPERATIONS_MANAGER.value) -> Dict[str, str]:
    """`X-User-ID` absent -- an `ERR_UNAUTHENTICATED` probe."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_empty_user_id(role: str = UserRole.PANEL_OPERATIONS_MANAGER.value) -> Dict[str, str]:
    """`X-User-ID` present but empty -- an `ERR_UNAUTHENTICATED` probe."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_for_role(role: str, client_id: Optional[str] = None) -> Dict[str, str]:
    """Dispatch to the right builder, supplying the client id where required."""
    if role == UserRole.CLIENT_USER.value:
        if client_id is None:
            raise ValueError("ClientUser is entity-backed and needs a client id")
        return build_user_headers(client_id, role)
    return build_user_headers(OPAQUE_ROLE_DEFAULT_USER_IDS.get(role, "operator-001"), role)
