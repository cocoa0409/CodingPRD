"""Header builders for the five roles the PRD defines.

Two of the roles are entity-backed: for `ParticipantAdmin` and
`PublicHealthOfficer` the `X-User-ID` header must be the `id` of the acting
`Participant`, and any mismatch against the participant that owns the addressed
resource is an `ERR_PARTICIPANT_SCOPE_VIOLATION`. Those two builders therefore
take a mandatory participant id. The other three roles carry an opaque operator
identifier that is never compared to an entity id, so their builders default to
a stable per-role literal while still accepting an override — several rules turn
on whether two operator ids are the same person (certifier versus signatory,
steward versus tuner, reviewer versus invoking clinician).
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from test_helpers.types import UserRole

# Stable opaque operator identifiers. Distinct literals so a test that needs two
# different operators of the same role can pick two of these without inventing
# strings inline.
HIE_ADMIN_USER_ID = "hie-admin-001"
HIE_ADMIN_SECOND_USER_ID = "hie-admin-002"
HIE_ADMIN_SIGNATORY_USER_ID = "hie-admin-signatory"
HIE_ADMIN_CERTIFIER_USER_ID = "hie-admin-certifier"

PRIVACY_OFFICER_USER_ID = "privacy-officer-001"
PRIVACY_OFFICER_SECOND_USER_ID = "privacy-officer-002"
PRIVACY_OFFICER_TUNER_USER_ID = "privacy-officer-tuner"
PRIVACY_OFFICER_STEWARD_USER_ID = "privacy-officer-steward"
PRIVACY_OFFICER_REVIEWER_USER_ID = "privacy-officer-reviewer"

CLINICIAN_USER_ID = "clinician-001"
CLINICIAN_SECOND_USER_ID = "clinician-002"


def make_hie_admin_headers(user_id: str = HIE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a `HieAdmin`; `X-User-ID` is an opaque operator identifier."""
    return build_user_headers(user_id, UserRole.HIE_ADMIN.value)


def make_privacy_officer_headers(user_id: str = PRIVACY_OFFICER_USER_ID) -> Dict[str, str]:
    """Headers for a `PrivacyOfficer`; `X-User-ID` is an opaque operator identifier."""
    return build_user_headers(user_id, UserRole.PRIVACY_OFFICER.value)


def make_clinician_headers(user_id: str = CLINICIAN_USER_ID) -> Dict[str, str]:
    """Headers for a `Clinician`; `X-User-ID` is an opaque operator identifier."""
    return build_user_headers(user_id, UserRole.CLINICIAN.value)


def make_participant_admin_headers(participant_id: str) -> Dict[str, str]:
    """Headers for a `ParticipantAdmin` acting as the participant with this `id`."""
    return build_user_headers(participant_id, UserRole.PARTICIPANT_ADMIN.value)


def make_public_health_officer_headers(participant_id: str) -> Dict[str, str]:
    """Headers for a `PublicHealthOfficer` acting as the participant with this `id`."""
    return build_user_headers(participant_id, UserRole.PUBLIC_HEALTH_OFFICER.value)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/id pair, including deliberately invalid roles."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str = HIE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers with `X-User-Role` absent entirely — an `ERR_UNAUTHENTICATED` probe."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_with_empty_role(user_id: str = HIE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers with `X-User-Role` present but empty — an `ERR_UNAUTHENTICATED` probe."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_for_role(role: str, participant_id: Optional[str] = None) -> Dict[str, str]:
    """Dispatch to the right builder, supplying the participant id where required."""
    if role in (UserRole.PARTICIPANT_ADMIN.value, UserRole.PUBLIC_HEALTH_OFFICER.value):
        if participant_id is None:
            raise ValueError(f"role {role} is entity-backed and needs a participant id")
        return build_user_headers(participant_id, role)
    defaults = {
        UserRole.HIE_ADMIN.value: HIE_ADMIN_USER_ID,
        UserRole.PRIVACY_OFFICER.value: PRIVACY_OFFICER_USER_ID,
        UserRole.CLINICIAN.value: CLINICIAN_USER_ID,
    }
    return build_user_headers(defaults.get(role, "operator-001"), role)
