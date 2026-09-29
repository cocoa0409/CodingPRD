"""Pre-built identity headers for the five roles of PRD §2.1.

`ProgramAdministrator`, `DisclosureOfficer` and `ComplianceAuditor` carry an
opaque operator identifier, so a shared constant is safe for them. The two
entity-backed roles do not: PRD §2.1 states that for `Representative` and
`Taxpayer` the `X-User-ID` is the `id` of the acting row, and an id that does
not resolve is rejected with `ERR_IDENTITY_NOT_RECOGNIZED`. Ownership-gated
calls must therefore always be built with `make_taxpayer_headers(...)` /
`make_representative_headers(...)` against a real created entity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_DISCLOSURE_OFFICER,
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_REPRESENTATIVE,
    ROLE_TAXPAYER,
)

# --- Opaque operator identifiers -------------------------------------------

ADMIN_USER_ID = "admin-one"
OFFICER_ALPHA_USER_ID = "officer-alpha"
OFFICER_BETA_USER_ID = "officer-beta"
OFFICER_GAMMA_USER_ID = "officer-gamma"
AUDITOR_ONE_USER_ID = "auditor-one"
AUDITOR_TWO_USER_ID = "auditor-two"

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMINISTRATOR)
OFFICER_ALPHA_HEADERS = build_user_headers(
    OFFICER_ALPHA_USER_ID, ROLE_DISCLOSURE_OFFICER
)
OFFICER_BETA_HEADERS = build_user_headers(
    OFFICER_BETA_USER_ID, ROLE_DISCLOSURE_OFFICER
)
OFFICER_GAMMA_HEADERS = build_user_headers(
    OFFICER_GAMMA_USER_ID, ROLE_DISCLOSURE_OFFICER
)
AUDITOR_ONE_HEADERS = build_user_headers(AUDITOR_ONE_USER_ID, ROLE_COMPLIANCE_AUDITOR)
AUDITOR_TWO_HEADERS = build_user_headers(AUDITOR_TWO_USER_ID, ROLE_COMPLIANCE_AUDITOR)


# --- Entity-backed roles: always per-instance ------------------------------


def make_taxpayer_headers(taxpayer_id: str) -> Dict[str, str]:
    """Headers for the `Taxpayer` role bound to a real `Taxpayer.id`."""
    return build_user_headers(taxpayer_id, ROLE_TAXPAYER)


def make_representative_headers(representative_id: str) -> Dict[str, str]:
    """Headers for the `Representative` role bound to a real `Representative.id`."""
    return build_user_headers(representative_id, ROLE_REPRESENTATIVE)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for role/identity combinations a test constructs itself."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers carrying `X-User-ID` but no `X-User-Role` (PRD §2.1 / §2.6 rule 1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PROGRAM_ADMINISTRATOR) -> Dict[str, str]:
    """Headers carrying `X-User-Role` but no `X-User-ID` (PRD §2.1 / §2.6 rule 1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


TEST_USERS = {
    "program_administrator_headers": ADMIN_HEADERS,
    "disclosure_officer_headers": OFFICER_ALPHA_HEADERS,
    "second_disclosure_officer_headers": OFFICER_BETA_HEADERS,
    "third_disclosure_officer_headers": OFFICER_GAMMA_HEADERS,
    "compliance_auditor_headers": AUDITOR_ONE_HEADERS,
    "second_compliance_auditor_headers": AUDITOR_TWO_HEADERS,
}
