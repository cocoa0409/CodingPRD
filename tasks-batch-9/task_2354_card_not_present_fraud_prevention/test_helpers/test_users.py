"""Header builders for the five roles.

Three roles are opaque: their ``X-User-ID`` is a service, engineer or
administrator token that the server never resolves against stored data, so a
fixed token is fine. Two roles are entity-backed: ``RiskAnalyst`` and
``ReviewLead`` both carry the ``id`` of the acting ``Analyst`` row in
``X-User-ID``, so their builders take that id as a required argument.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

#: Opaque principals. These are tokens, not entity identifiers.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "checkout_service": {
        "user_id": "checkout-service-1",
        "role": Role.CHECKOUT_SERVICE,
    },
    "platform_admin": {
        "user_id": "admin-ops-1",
        "role": Role.PLATFORM_ADMIN,
    },
    "policy_engineer_author": {
        "user_id": "eng-author-1",
        "role": Role.POLICY_ENGINEER,
    },
    "policy_engineer_approver": {
        "user_id": "eng-approver-2",
        "role": Role.POLICY_ENGINEER,
    },
}

#: The engineer who drafts rule packs and models.
POLICY_ENGINEER_AUTHOR_ID = TEST_USERS["policy_engineer_author"]["user_id"]
#: A different engineer, so that activation clears the segregation check.
POLICY_ENGINEER_APPROVER_ID = TEST_USERS["policy_engineer_approver"]["user_id"]
CHECKOUT_SERVICE_ID = TEST_USERS["checkout_service"]["user_id"]
PLATFORM_ADMIN_ID = TEST_USERS["platform_admin"]["user_id"]


# ---------------------------------------------------------------------------
# Opaque roles
# ---------------------------------------------------------------------------


def make_checkout_service_headers(user_id: str = CHECKOUT_SERVICE_ID) -> Dict[str, str]:
    """Headers for the storefront integration."""
    return build_user_headers(user_id, Role.CHECKOUT_SERVICE)


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    """Headers for the platform administrator."""
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_policy_engineer_headers(
    user_id: str = POLICY_ENGINEER_AUTHOR_ID,
) -> Dict[str, str]:
    """Headers for a policy engineer; the id is recorded on authored packs."""
    return build_user_headers(user_id, Role.POLICY_ENGINEER)


def make_policy_engineer_author_headers() -> Dict[str, str]:
    """The engineer who drafts a pack, and is therefore barred from activating it."""
    return build_user_headers(POLICY_ENGINEER_AUTHOR_ID, Role.POLICY_ENGINEER)


def make_policy_engineer_approver_headers() -> Dict[str, str]:
    """A second engineer, eligible to activate a pack the author drafted."""
    return build_user_headers(POLICY_ENGINEER_APPROVER_ID, Role.POLICY_ENGINEER)


# ---------------------------------------------------------------------------
# Entity-backed roles: X-User-ID must name a real Analyst row
# ---------------------------------------------------------------------------


def make_risk_analyst_headers(analyst_id: str) -> Dict[str, str]:
    """Headers for a risk analyst acting as the ``Analyst`` row ``analyst_id``."""
    return build_user_headers(analyst_id, Role.RISK_ANALYST)


def make_review_lead_headers(analyst_id: str) -> Dict[str, str]:
    """Headers for a review lead acting as the ``Analyst`` row ``analyst_id``."""
    return build_user_headers(analyst_id, Role.REVIEW_LEAD)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for tests that need an arbitrary role/principal pairing."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str = CHECKOUT_SERVICE_ID) -> Dict[str, str]:
    """Headers that omit ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_with_empty_role(user_id: str = CHECKOUT_SERVICE_ID) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def make_headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
