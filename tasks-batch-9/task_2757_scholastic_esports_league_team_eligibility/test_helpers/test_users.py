"""Header builders for the seven roles of PRD §2.1.

PRD §2.1 splits the seven roles into two families.

Opaque roles — ``LeagueAdmin``, ``EligibilityOfficer``, ``IntegrityOfficer``
and ``Recruiter`` — carry an ``X-User-ID`` that "is an opaque operator
identifier not tied to any persisted entity".  For those, a stable constant
identifier is enough, and distinct identifiers matter only where §2.1's two
segregation-of-duties rules compare recorded officer identifiers against
each other.

Entity-backed roles — ``DistrictAdmin`` (a ``District.id``),
``AthleticDirector`` (a ``School.id``) and ``Coach`` (a ``Coach.id``) — must
carry the identifier of the acting entity, because "ownership checks on any
resource that references a District compare the resource's district
foreign-key field to X-User-ID".  Never use a constant for those: use the
``make_*`` builders with the real entity id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque identifiers (PRD §2.1)
# --------------------------------------------------------------------------
LEAGUE_ADMIN_ID = "league-admin-001"
LEAGUE_ADMIN_ID_ALT = "league-admin-002"

ELIGIBILITY_OFFICER_ID = "elig-officer-001"
ELIGIBILITY_OFFICER_ID_2 = "elig-officer-002"
ELIGIBILITY_OFFICER_ID_3 = "elig-officer-003"

INTEGRITY_OFFICER_ID = "integrity-officer-001"
INTEGRITY_OFFICER_ID_2 = "integrity-officer-002"
INTEGRITY_OFFICER_ID_3 = "integrity-officer-003"

RECRUITER_ID = "recruiter-001"
RECRUITER_ID_2 = "recruiter-002"


# --------------------------------------------------------------------------
# Opaque-role header builders
# --------------------------------------------------------------------------
def league_admin_headers(user_id: str = LEAGUE_ADMIN_ID) -> Dict[str, str]:
    """Headers for a LeagueAdmin (opaque X-User-ID per PRD §2.1)."""
    return build_user_headers(user_id, UserRole.LEAGUE_ADMIN.value)


def eligibility_officer_headers(
    user_id: str = ELIGIBILITY_OFFICER_ID,
) -> Dict[str, str]:
    """Headers for an EligibilityOfficer (opaque X-User-ID per PRD §2.1)."""
    return build_user_headers(user_id, UserRole.ELIGIBILITY_OFFICER.value)


def integrity_officer_headers(
    user_id: str = INTEGRITY_OFFICER_ID,
) -> Dict[str, str]:
    """Headers for an IntegrityOfficer (opaque X-User-ID per PRD §2.1)."""
    return build_user_headers(user_id, UserRole.INTEGRITY_OFFICER.value)


def recruiter_headers(user_id: str = RECRUITER_ID) -> Dict[str, str]:
    """Headers for a Recruiter (opaque X-User-ID per PRD §2.1)."""
    return build_user_headers(user_id, UserRole.RECRUITER.value)


# --------------------------------------------------------------------------
# Entity-backed header builders (PRD §2.1) — the id argument is mandatory
# --------------------------------------------------------------------------
def make_district_admin_headers(district_id: str) -> Dict[str, str]:
    """Headers for the DistrictAdmin of ``district_id``.

    PRD §2.1: "When X-User-Role is DistrictAdmin, X-User-ID is the id of the
    acting District".
    """
    return build_user_headers(district_id, UserRole.DISTRICT_ADMIN.value)


def make_athletic_director_headers(school_id: str) -> Dict[str, str]:
    """Headers for the AthleticDirector of ``school_id``.

    PRD §2.1: "When X-User-Role is AthleticDirector, X-User-ID is the id of
    the acting School".
    """
    return build_user_headers(school_id, UserRole.ATHLETIC_DIRECTOR.value)


def make_coach_headers(coach_id: str) -> Dict[str, str]:
    """Headers for the Coach whose ``Coach.id`` is ``coach_id``.

    PRD §2.1: "When X-User-Role is Coach, X-User-ID is the id of the acting
    Coach".
    """
    return build_user_headers(coach_id, UserRole.COACH.value)


# Aliases used by the corner tests, which speak of "the acting officer".
make_league_admin_headers = league_admin_headers
make_eligibility_officer_headers = eligibility_officer_headers
make_integrity_officer_headers = integrity_officer_headers
make_recruiter_headers = recruiter_headers


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder used by the RBAC-shaped corner instances."""
    return build_user_headers(user_id, role)
