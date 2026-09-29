"""
Request identities for the seven roles of the practice.

Six of the seven roles are entity-backed: the acting user is a real ``Provider``
row and the role claimed in the header must agree with that row's
``role_type``, so the header builders for those six take the id of the Provider
that was registered for the test. Only ``PracticeAdmin`` is an opaque operator
identifier that is never resolved to a Provider row, which is why it — and only
it — has a fixed constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_PATHOLOGY_LIAISON,
    ROLE_PELVIC_HEALTH_COORDINATOR,
    ROLE_PRACTICE_ADMIN,
    ROLE_PROCEDURE_NURSE,
    ROLE_SCHEDULER,
    ROLE_STERILE_PROCESSING_TECH,
    ROLE_UROLOGIST,
)

# The practice administrator's identifier is opaque: it is not tied to any
# persisted entity, which is what lets it bootstrap the first Provider onto an
# empty roster and drive the logical clock.
PRACTICE_ADMIN_USER_ID = "admin-operator-0001"

# A second opaque administrator identifier, for tests that need two distinct
# administrators.
PRACTICE_ADMIN_USER_ID_ALT = "admin-operator-0002"


def make_practice_admin_headers(user_id: str = PRACTICE_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRACTICE_ADMIN)


def make_scheduler_headers(provider_id: str) -> Dict[str, str]:
    return build_user_headers(provider_id, ROLE_SCHEDULER)


def make_urologist_headers(provider_id: str) -> Dict[str, str]:
    return build_user_headers(provider_id, ROLE_UROLOGIST)


def make_procedure_nurse_headers(provider_id: str) -> Dict[str, str]:
    return build_user_headers(provider_id, ROLE_PROCEDURE_NURSE)


def make_sterile_processing_tech_headers(provider_id: str) -> Dict[str, str]:
    return build_user_headers(provider_id, ROLE_STERILE_PROCESSING_TECH)


def make_pathology_liaison_headers(provider_id: str) -> Dict[str, str]:
    return build_user_headers(provider_id, ROLE_PATHOLOGY_LIAISON)


def make_pelvic_health_coordinator_headers(provider_id: str) -> Dict[str, str]:
    return build_user_headers(provider_id, ROLE_PELVIC_HEALTH_COORDINATOR)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary (identifier, role) pair."""
    return build_user_headers(user_id, role)


def make_headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers that declare a role but carry no acting user identifier."""
    return {"X-User-Role": role}


def make_headers_missing_role(user_id: str) -> Dict[str, str]:
    """Headers that carry an acting user identifier but declare no role."""
    return {"X-User-ID": user_id}


def make_headers_blank_user_id(role: str) -> Dict[str, str]:
    """Headers whose acting user identifier is present but blank."""
    return {"X-User-ID": "", "X-User-Role": role}
