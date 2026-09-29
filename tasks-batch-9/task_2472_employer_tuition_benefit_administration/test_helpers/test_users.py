"""
Identity header builders for the five roles of PRD §2.1.

Three roles are entity-backed, so their builders take the `id` of the backing
resource: a `BenefitAdministrator` acts as an `Employer`, an `Employee` acts as
itself and a `SchoolPartner` acts as a `School`. The two opaque roles take an
operator identifier the server never compares to any entity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers for the two roles that are not entity-backed.
PLATFORM_ADMIN_USER_ID = "ops-platform-admin-001"
COACH_USER_ID = "ops-coach-001"


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    """Guild-side operator; X-User-ID is opaque and tied to no entity."""
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_benefit_administrator_headers(employer_id: str) -> Dict[str, str]:
    """Employer-side benefits owner; X-User-ID is the acting Employer's id."""
    return build_user_headers(employer_id, Role.BENEFIT_ADMINISTRATOR)


def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """The learner; X-User-ID is the acting Employee's id."""
    return build_user_headers(employee_id, Role.EMPLOYEE)


def make_school_partner_headers(school_id: str) -> Dict[str, str]:
    """School-side registrar; X-User-ID is the acting School's id."""
    return build_user_headers(school_id, Role.SCHOOL_PARTNER)


def make_coach_headers(user_id: str = COACH_USER_ID) -> Dict[str, str]:
    """Advising coach; X-User-ID is recorded as coach_user_id on each session."""
    return build_user_headers(user_id, Role.COACH)


def make_headers_without_role(user_id: str) -> Dict[str, str]:
    """A request missing X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str) -> Dict[str, str]:
    """A request missing X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_unknown_role(user_id: str, role: str) -> Dict[str, str]:
    """A request whose X-User-Role is not one of the five declared roles."""
    return build_user_headers(user_id, role)
