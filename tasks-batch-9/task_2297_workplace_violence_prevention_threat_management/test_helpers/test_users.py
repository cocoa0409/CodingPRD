"""Role headers.

The seven entity-backed roles must present an ``X-User-ID`` that resolves to an
ACTIVE employee row, so tests bind those headers to a concrete employee
identifier with the ``make_*_headers`` helpers. The three opaque roles carry an
operator identifier that is never compared to any row, so their headers are
constants; ``Anonymous`` additionally exercises the one case where ``X-User-ID``
may be omitted entirely.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --------------------------------------------------------------------------
# Entity-backed roles: headers must name a real ACTIVE employee.
# --------------------------------------------------------------------------


def make_safety_officer_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a SafetyOfficer acting as the given employee."""
    return build_user_headers(employee_id, "SafetyOfficer")


def make_site_manager_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a SiteManager acting as the given employee."""
    return build_user_headers(employee_id, "SiteManager")


def make_threat_team_lead_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a ThreatTeamLead acting as the given employee."""
    return build_user_headers(employee_id, "ThreatTeamLead")


def make_threat_team_member_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a ThreatTeamMember acting as the given employee."""
    return build_user_headers(employee_id, "ThreatTeamMember")


def make_security_coordinator_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a SecurityCoordinator acting as the given employee."""
    return build_user_headers(employee_id, "SecurityCoordinator")


def make_hr_partner_headers(employee_id: str) -> Dict[str, str]:
    """Headers for an HRPartner acting as the given employee."""
    return build_user_headers(employee_id, "HRPartner")


def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """Headers for an Employee acting as themselves."""
    return build_user_headers(employee_id, "Employee")


# --------------------------------------------------------------------------
# Opaque roles: the identifier is an operator handle, never a row id.
# --------------------------------------------------------------------------

PROGRAM_ADMIN_HEADERS = build_user_headers("ops-program-admin", "ProgramAdmin")
COMPLIANCE_AUDITOR_HEADERS = build_user_headers("ops-compliance-auditor", "ComplianceAuditor")
ANONYMOUS_HEADERS = build_user_headers("ops-anonymous-reporter", "Anonymous")

#: The anonymous reporting channel is the single case where X-User-ID may be omitted.
ANONYMOUS_HEADERS_WITHOUT_USER_ID = {
    "X-User-Role": "Anonymous",
    "Content-Type": "application/json",
}

#: Headers whose X-User-Role is not one of the ten recognised strings.
UNRECOGNISED_ROLE_HEADERS = build_user_headers("ops-program-admin", "FacilitiesManager")

#: Headers with no X-User-Role at all.
HEADERS_WITHOUT_ROLE = {
    "X-User-ID": "ops-program-admin",
    "Content-Type": "application/json",
}


TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": PROGRAM_ADMIN_HEADERS,
    "compliance_auditor": COMPLIANCE_AUDITOR_HEADERS,
    "anonymous": ANONYMOUS_HEADERS,
}

#: Role names whose headers can only be built once a concrete employee exists.
ENTITY_BACKED_ROLES = (
    "safety_officer",
    "site_manager",
    "threat_team_lead",
    "threat_team_member",
    "security_coordinator",
    "hr_partner",
    "employee",
)

_HEADER_BUILDERS = {
    "safety_officer": make_safety_officer_headers,
    "site_manager": make_site_manager_headers,
    "threat_team_lead": make_threat_team_lead_headers,
    "threat_team_member": make_threat_team_member_headers,
    "security_coordinator": make_security_coordinator_headers,
    "hr_partner": make_hr_partner_headers,
    "employee": make_employee_headers,
}


def headers_for(role: str, employee_id: str = "") -> Dict[str, str]:
    """Build headers for any role name, binding entity-backed roles to an employee."""
    if role in _HEADER_BUILDERS:
        if not employee_id:
            raise ValueError(f"role {role!r} is entity-backed and needs an employee id")
        return _HEADER_BUILDERS[role](employee_id)
    return TEST_USERS[role]
