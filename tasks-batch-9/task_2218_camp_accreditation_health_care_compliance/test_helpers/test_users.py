"""Identity headers for the five roles the accreditation API recognises.

Two of the roles are opaque operator identities, so their user ids are shared
constants. Three roles are entity-backed: a ``CampDirector`` and
``HealthCareStaff`` act as a specific ``Camp`` id and a ``Visitor`` acts as a
specific ``Visitor`` id, so those identities can only be built once the entity
exists — hence the per-instance builders below.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identities. Two distinct officers are kept because the officer
# who confirmed a visit is barred from issuing that cycle's decision.
OFFICER_ONE_ID = "officer-1"
OFFICER_TWO_ID = "officer-2"
STATE_AGENT_ID = "state-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "officer_one": {"user_id": OFFICER_ONE_ID, "role": Role.ACCREDITATION_OFFICER},
    "officer_two": {"user_id": OFFICER_TWO_ID, "role": Role.ACCREDITATION_OFFICER},
    "state_agent": {"user_id": STATE_AGENT_ID, "role": Role.STATE_LICENSING_AGENT},
}

OFFICER_ONE_HEADERS = build_user_headers(OFFICER_ONE_ID, Role.ACCREDITATION_OFFICER)
OFFICER_TWO_HEADERS = build_user_headers(OFFICER_TWO_ID, Role.ACCREDITATION_OFFICER)
STATE_AGENT_HEADERS = build_user_headers(STATE_AGENT_ID, Role.STATE_LICENSING_AGENT)


def make_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary opaque accreditation officer identity."""
    return build_user_headers(user_id, Role.ACCREDITATION_OFFICER)


def make_state_agent_headers(user_id: str = STATE_AGENT_ID) -> Dict[str, str]:
    """Headers for an arbitrary opaque state licensing agent identity."""
    return build_user_headers(user_id, Role.STATE_LICENSING_AGENT)


def make_camp_director_headers(camp_id: str) -> Dict[str, str]:
    """Headers for the director of the camp whose id is ``camp_id``."""
    return build_user_headers(camp_id, Role.CAMP_DIRECTOR)


def make_health_care_staff_headers(camp_id: str) -> Dict[str, str]:
    """Headers for the health centre staff of the camp whose id is ``camp_id``."""
    return build_user_headers(camp_id, Role.HEALTH_CARE_STAFF)


def make_visitor_headers(visitor_id: str) -> Dict[str, str]:
    """Headers for the visitor whose roster id is ``visitor_id``."""
    return build_user_headers(visitor_id, Role.VISITOR)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Well-formed headers missing ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is not one of the five recognised roles."""
    return build_user_headers(user_id, "CampAccountant")
