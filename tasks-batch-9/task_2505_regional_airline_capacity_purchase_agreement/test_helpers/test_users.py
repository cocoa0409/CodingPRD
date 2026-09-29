"""Acting principals for the five declared roles.

Four of the roles are opaque: their ``X-User-ID`` is a free-form principal label
that the service never resolves against stored data. ``BaseChiefPilot`` is the
one entity-backed role, so its header must carry the identifier of the crew base
being commanded and never a constant label; use
:func:`make_base_chief_pilot_headers` for those calls.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BASE_CHIEF_PILOT,
    ROLE_BRAND_AUDITOR,
    ROLE_CPA_ADMINISTRATOR,
    ROLE_MAINLINE_SCHEDULER,
    ROLE_REGIONAL_OPS_CONTROLLER,
)

# Opaque principal labels. Distinct labels exist per role so that a segregation
# check can tell two acting parties apart.
ADMIN_USER_ID = "admin-1"
SECOND_ADMIN_USER_ID = "admin-2"
SCHEDULER_USER_ID = "scheduler-1"
SECOND_SCHEDULER_USER_ID = "scheduler-2"
OPS_USER_ID = "ops-1"
SECOND_OPS_USER_ID = "ops-2"
AUDITOR_USER_ID = "auditor-1"
SECOND_AUDITOR_USER_ID = "auditor-2"


ADMIN_HEADERS: Dict[str, str] = build_user_headers(ADMIN_USER_ID, ROLE_CPA_ADMINISTRATOR)
SECOND_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_ADMIN_USER_ID, ROLE_CPA_ADMINISTRATOR
)
SCHEDULER_HEADERS: Dict[str, str] = build_user_headers(
    SCHEDULER_USER_ID, ROLE_MAINLINE_SCHEDULER
)
SECOND_SCHEDULER_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_SCHEDULER_USER_ID, ROLE_MAINLINE_SCHEDULER
)
OPS_HEADERS: Dict[str, str] = build_user_headers(OPS_USER_ID, ROLE_REGIONAL_OPS_CONTROLLER)
SECOND_OPS_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_OPS_USER_ID, ROLE_REGIONAL_OPS_CONTROLLER
)
AUDITOR_HEADERS: Dict[str, str] = build_user_headers(AUDITOR_USER_ID, ROLE_BRAND_AUDITOR)
SECOND_AUDITOR_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_AUDITOR_USER_ID, ROLE_BRAND_AUDITOR
)


def make_base_chief_pilot_headers(crew_base_id: str) -> Dict[str, str]:
    """Headers for the chief pilot who commands ``crew_base_id``.

    Ownership is decided by comparing the target pilot's base against this
    identifier, so the caller must pass the crew base the pilot belongs to.
    """
    return build_user_headers(crew_base_id, ROLE_BASE_CHIEF_PILOT)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary principal label and role."""
    return build_user_headers(user_id, role)


def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """A request envelope that declares a principal but no capacity."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user(role: str = ROLE_CPA_ADMINISTRATOR) -> Dict[str, str]:
    """A request envelope that declares a capacity but no principal."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_no_credentials() -> Dict[str, str]:
    """A request envelope carrying neither of the two mandatory headers."""
    return {"Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """A request envelope whose declared capacity is not one of the five roles."""
    return build_user_headers(user_id, "FleetPlanner")


# Headers for every role, keyed by role name, for read-surface sweeps. The chief
# pilot entry is a placeholder principal because read endpoints are open to all
# five roles and perform no base-ownership comparison.
READ_HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_CPA_ADMINISTRATOR: ADMIN_HEADERS,
    ROLE_MAINLINE_SCHEDULER: SCHEDULER_HEADERS,
    ROLE_REGIONAL_OPS_CONTROLLER: OPS_HEADERS,
    ROLE_BASE_CHIEF_PILOT: build_user_headers("chief-pilot-1", ROLE_BASE_CHIEF_PILOT),
    ROLE_BRAND_AUDITOR: AUDITOR_HEADERS,
}


__all__ = [
    "ADMIN_USER_ID",
    "SECOND_ADMIN_USER_ID",
    "SCHEDULER_USER_ID",
    "SECOND_SCHEDULER_USER_ID",
    "OPS_USER_ID",
    "SECOND_OPS_USER_ID",
    "AUDITOR_USER_ID",
    "SECOND_AUDITOR_USER_ID",
    "ADMIN_HEADERS",
    "SECOND_ADMIN_HEADERS",
    "SCHEDULER_HEADERS",
    "SECOND_SCHEDULER_HEADERS",
    "OPS_HEADERS",
    "SECOND_OPS_HEADERS",
    "AUDITOR_HEADERS",
    "SECOND_AUDITOR_HEADERS",
    "READ_HEADERS_BY_ROLE",
    "make_base_chief_pilot_headers",
    "make_headers",
    "headers_missing_role",
    "headers_missing_user",
    "headers_with_no_credentials",
    "headers_with_unknown_role",
]
