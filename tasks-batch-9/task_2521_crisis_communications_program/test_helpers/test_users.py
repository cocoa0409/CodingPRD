"""Identity headers for the seven declared roles (PRD §2.1).

``X-User-ID`` is an opaque operator identifier for ``ProgramAdmin`` only; for the
other six roles it must be the id of an existing TeamMember, so those headers
are always built from a member id with the ``make_*_headers`` builders.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque operator identity. ProgramAdmin ids are never resolved against the
# roster, so a fixed constant is safe here.
# ---------------------------------------------------------------------------

PROGRAM_ADMIN_USER_ID = "ops-admin-01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin_headers": build_user_headers(
        PROGRAM_ADMIN_USER_ID, UserRole.PROGRAM_ADMIN.value
    ),
}


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for the ProgramAdmin operator role."""
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_incident_lead_headers(member_id: str) -> Dict[str, str]:
    """Headers for an IncidentLead acting as the TeamMember ``member_id``."""
    return build_user_headers(member_id, UserRole.INCIDENT_LEAD.value)


def make_legal_counsel_headers(member_id: str) -> Dict[str, str]:
    """Headers for a LegalCounsel acting as the TeamMember ``member_id``."""
    return build_user_headers(member_id, UserRole.LEGAL_COUNSEL.value)


def make_comms_lead_headers(member_id: str) -> Dict[str, str]:
    """Headers for a CommsLead acting as the TeamMember ``member_id``."""
    return build_user_headers(member_id, UserRole.COMMS_LEAD.value)


def make_spokesperson_headers(member_id: str) -> Dict[str, str]:
    """Headers for a Spokesperson acting as the TeamMember ``member_id``."""
    return build_user_headers(member_id, UserRole.SPOKESPERSON.value)


def make_social_listener_headers(member_id: str) -> Dict[str, str]:
    """Headers for a SocialListener acting as the TeamMember ``member_id``."""
    return build_user_headers(member_id, UserRole.SOCIAL_LISTENER.value)


def make_exec_sponsor_headers(member_id: str) -> Dict[str, str]:
    """Headers for an ExecSponsor acting as the TeamMember ``member_id``."""
    return build_user_headers(member_id, UserRole.EXEC_SPONSOR.value)


def make_headers(role: str, member_id: str) -> Dict[str, str]:
    """Headers for any declared role, acting as ``member_id``."""
    return build_user_headers(member_id, role)


# Maps a crisis-team seat role onto the request role name that the seat holder
# uses when acting (PRD §2.1 / §3.4).
TEAM_ROLE_TO_USER_ROLE: Dict[str, str] = {
    "INCIDENT_LEAD": UserRole.INCIDENT_LEAD.value,
    "LEGAL_COUNSEL": UserRole.LEGAL_COUNSEL.value,
    "COMMS_LEAD": UserRole.COMMS_LEAD.value,
    "SPOKESPERSON": UserRole.SPOKESPERSON.value,
    "SOCIAL_LISTENER": UserRole.SOCIAL_LISTENER.value,
    "EXEC_SPONSOR": UserRole.EXEC_SPONSOR.value,
}
