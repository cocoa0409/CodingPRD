"""Per-role identity headers.

Every request carries ``X-User-ID`` and ``X-User-Role``.

Four of the five roles are opaque: their ``X-User-ID`` is never compared against
a stored row, so a module-level constant is safe. ``QualifiedIndividual`` is the
exception -- its ``X-User-ID`` is the id of the QualifiedIndividual row itself,
and designation-match plus segregation-of-duties checks compare against it. Use
:func:`make_qualified_individual_headers` with the real row id for every
QualifiedIndividual call; never reuse one QI's headers for another QI's action.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_QUALIFIED_INDIVIDUAL = "QualifiedIndividual"
ROLE_ENTRY_FILER = "EntryFiler"
ROLE_FDA_INSPECTOR = "FdaInspector"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

# --- Opaque-identity roles: a fixed user id is fine -------------------------
COMPLIANCE_OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    "co-11111111-1111-4111-8111-111111111111", ROLE_COMPLIANCE_OFFICER
)
ENTRY_FILER_HEADERS: Dict[str, str] = build_user_headers(
    "ef-22222222-2222-4222-8222-222222222222", ROLE_ENTRY_FILER
)
FDA_INSPECTOR_HEADERS: Dict[str, str] = build_user_headers(
    "fi-33333333-3333-4333-8333-333333333333", ROLE_FDA_INSPECTOR
)
PLATFORM_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    "pa-44444444-4444-4444-8444-444444444444", ROLE_PLATFORM_ADMIN
)

# A second ComplianceOfficer principal, for tests that need two distinct
# opaque compliance-office users.
SECOND_COMPLIANCE_OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    "co-55555555-5555-4555-8555-555555555555", ROLE_COMPLIANCE_OFFICER
)


def make_qualified_individual_headers(qualified_individual_id: str) -> Dict[str, str]:
    """Headers that act as the QualifiedIndividual row with this id."""
    return build_user_headers(qualified_individual_id, ROLE_QUALIFIED_INDIVIDUAL)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary (opaque) compliance-office principal."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_entry_filer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary (opaque) entry filer."""
    return build_user_headers(user_id, ROLE_ENTRY_FILER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for role-permission probes with an arbitrary role string."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
