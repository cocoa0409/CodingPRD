"""Identity headers for the five roles.

Two roles are entity backed: a ProviderAgent's X-User-ID is the Provider id and a
Subscriber's X-User-ID is the Subscriber id. Ownership scoped calls for those roles
must therefore use the make_*_headers builders with the real row id, never a
placeholder identity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque identities: the API records them verbatim in *_by_ref fields.
PROGRAM_ADMIN_ID = "PA-1"
PROGRAM_ADMIN_ID_ALT = "PA-2"
NATIONAL_VERIFIER_ID = "NV-1"
AUDITOR_DRAWER_ID = "AUD-1"
AUDITOR_ADJUDICATOR_ID = "AUD-2"
REVIEWER_1 = "REV-1"
REVIEWER_2 = "REV-2"
REVIEWER_3 = "REV-3"
REVIEWER_4 = "REV-4"


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PROGRAM_ADMINISTRATOR.value)


def make_provider_agent_headers(provider_id: str) -> Dict[str, str]:
    """ProviderAgent headers whose X-User-ID is the acting carrier's Provider id."""
    return build_user_headers(provider_id, Role.PROVIDER_AGENT.value)


def make_verifier_headers(user_id: str = NATIONAL_VERIFIER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.NATIONAL_VERIFIER.value)


def make_auditor_headers(user_id: str = AUDITOR_DRAWER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMPLIANCE_AUDITOR.value)


def make_subscriber_headers(subscriber_id: str) -> Dict[str, str]:
    """Subscriber headers whose X-User-ID is the acting Subscriber id."""
    return build_user_headers(subscriber_id, Role.SUBSCRIBER.value)


def make_headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role name, used by role-matrix tests."""
    return build_user_headers(user_id, role)


# Pre-built headers for the three opaque roles that never need row scoping.
PROGRAM_ADMIN = make_program_admin_headers()
PROGRAM_ADMIN_ALT = make_program_admin_headers(PROGRAM_ADMIN_ID_ALT)
NATIONAL_VERIFIER = make_verifier_headers()
AUDITOR_DRAWER = make_auditor_headers(AUDITOR_DRAWER_ID)
AUDITOR_ADJUDICATOR = make_auditor_headers(AUDITOR_ADJUDICATOR_ID)

NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
EMPTY_AUTH_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": "",
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers("WHO-1", "FieldTechnician")
