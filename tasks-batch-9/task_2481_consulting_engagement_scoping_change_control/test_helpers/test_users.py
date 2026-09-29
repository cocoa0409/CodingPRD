"""Header builders for the six roles of PRD 2.1.

Five of the six roles resolve ``X-User-ID`` to a persisted row, so their headers
can only be built once the row exists: an ``EngagementPartner``, an
``EngagementManager``, a ``QualityReviewer`` and ``FirmLeadership`` all carry the
id of the acting ``Consultant``, and a ``ClientContact`` carries the id of the
acting ``Client``. ``PracticeAdmin`` alone is an opaque back-office identifier
that is never compared to any entity's id, so a single constant serves it.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLIENT_CONTACT,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_ENGAGEMENT_PARTNER,
    ROLE_FIRM_LEADERSHIP,
    ROLE_PRACTICE_ADMIN,
    ROLE_QUALITY_REVIEWER,
)

Headers = Dict[str, str]

# PracticeAdmin is opaque: an operator identifier not tied to any entity.
PRACTICE_ADMIN_USER_ID = "practice-admin-001"


def make_partner_headers(consultant_id: str) -> Headers:
    return build_user_headers(consultant_id, ROLE_ENGAGEMENT_PARTNER)


def make_manager_headers(consultant_id: str) -> Headers:
    return build_user_headers(consultant_id, ROLE_ENGAGEMENT_MANAGER)


def make_reviewer_headers(consultant_id: str) -> Headers:
    return build_user_headers(consultant_id, ROLE_QUALITY_REVIEWER)


def make_leadership_headers(consultant_id: str) -> Headers:
    return build_user_headers(consultant_id, ROLE_FIRM_LEADERSHIP)


def make_client_headers(client_id: str) -> Headers:
    return build_user_headers(client_id, ROLE_CLIENT_CONTACT)


def make_practice_admin_headers(user_id: str = PRACTICE_ADMIN_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_PRACTICE_ADMIN)


PRACTICE_ADMIN_HEADERS = make_practice_admin_headers()


def make_headers(user_id: str, role: str) -> Headers:
    """Escape hatch for role/identity permutations driven by a table."""
    return build_user_headers(user_id, role)


def make_headers_without_user_id(role: str) -> Headers:
    """Headers whose ``X-User-ID`` is present but empty (PRD 2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
