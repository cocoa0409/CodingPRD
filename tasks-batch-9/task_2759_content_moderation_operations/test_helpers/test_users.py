"""Actor identities and their request headers.

Two shapes of identity exist in this API. Some roles are pure operator
identities whose ``X-User-ID`` is an opaque operator handle. Others are backed
by a persisted row, and for those the header must carry that row's own ``id``:
a reviewer acts under the id of their Reviewer record, and an account holder
acts under the id of their Account record. Ownership, duty-separation and
appellant-scoping checks all compare ``X-User-ID`` against a stored id, so a
fixture that substitutes a shared constant for the real row id makes every one
of those checks reject every request.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCOUNT_HOLDER,
    ROLE_LEGAL_COUNSEL,
    ROLE_POLICY_MANAGER,
    ROLE_QA_AUDITOR,
    ROLE_REVIEWER,
    ROLE_TRUST_SAFETY_ADMIN,
)

# ---------------------------------------------------------------------------
# Operator handles for the roles that are not backed by a persisted row
# ---------------------------------------------------------------------------

TRUST_SAFETY_ADMIN_ID = "ts-ops"
TRUST_SAFETY_ADMIN_ALT_ID = "ts-ops-2"

# Two policy managers exist because activating a policy version requires an
# activator whose id differs from the drafting manager's captured id.
POLICY_MANAGER_AUTHOR_ID = "pm-alice"
POLICY_MANAGER_ACTIVATOR_ID = "pm-bob"

LEGAL_COUNSEL_ID = "legal-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "trust_safety_admin": {"user_id": TRUST_SAFETY_ADMIN_ID, "role": ROLE_TRUST_SAFETY_ADMIN},
    "trust_safety_admin_alt": {"user_id": TRUST_SAFETY_ADMIN_ALT_ID, "role": ROLE_TRUST_SAFETY_ADMIN},
    "policy_manager_author": {"user_id": POLICY_MANAGER_AUTHOR_ID, "role": ROLE_POLICY_MANAGER},
    "policy_manager_activator": {"user_id": POLICY_MANAGER_ACTIVATOR_ID, "role": ROLE_POLICY_MANAGER},
    "legal_counsel": {"user_id": LEGAL_COUNSEL_ID, "role": ROLE_LEGAL_COUNSEL},
}


# ---------------------------------------------------------------------------
# Header builders for the operator identities
# ---------------------------------------------------------------------------

ADMIN_HEADERS = build_user_headers(TRUST_SAFETY_ADMIN_ID, ROLE_TRUST_SAFETY_ADMIN)
ADMIN_ALT_HEADERS = build_user_headers(TRUST_SAFETY_ADMIN_ALT_ID, ROLE_TRUST_SAFETY_ADMIN)
POLICY_AUTHOR_HEADERS = build_user_headers(POLICY_MANAGER_AUTHOR_ID, ROLE_POLICY_MANAGER)
POLICY_ACTIVATOR_HEADERS = build_user_headers(POLICY_MANAGER_ACTIVATOR_ID, ROLE_POLICY_MANAGER)
LEGAL_HEADERS = build_user_headers(LEGAL_COUNSEL_ID, ROLE_LEGAL_COUNSEL)


def make_admin_headers(user_id: str = TRUST_SAFETY_ADMIN_ID) -> Dict[str, str]:
    """Headers for a TrustSafetyAdmin."""
    return build_user_headers(user_id, ROLE_TRUST_SAFETY_ADMIN)


def make_policy_manager_headers(user_id: str = POLICY_MANAGER_AUTHOR_ID) -> Dict[str, str]:
    """Headers for a PolicyManager."""
    return build_user_headers(user_id, ROLE_POLICY_MANAGER)


def make_legal_counsel_headers(user_id: str = LEGAL_COUNSEL_ID) -> Dict[str, str]:
    """Headers for LegalCounsel."""
    return build_user_headers(user_id, ROLE_LEGAL_COUNSEL)


# ---------------------------------------------------------------------------
# Header builders for the entity-backed identities
# ---------------------------------------------------------------------------


def make_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """Headers for a Reviewer acting under their own Reviewer record id.

    Deciding, escalating and disputing all compare ``X-User-ID`` against a
    stored reviewer id, so this must be the real record id.
    """
    return build_user_headers(reviewer_id, ROLE_REVIEWER)


def make_qa_auditor_headers(reviewer_id: str) -> Dict[str, str]:
    """Headers for a QAAuditor acting under their own Reviewer record id.

    Drawing an audit sample reads the acting reviewer's ``role_class`` and
    compares the actor against the case's decider, so the header carries the
    id of the Reviewer record whose ``role_class`` is ``QA``.
    """
    return build_user_headers(reviewer_id, ROLE_QA_AUDITOR)


def make_account_holder_headers(account_id: str) -> Dict[str, str]:
    """Headers for an AccountHolder acting under their own Account record id.

    Appeal filing and both appeal read paths compare ``X-User-ID`` against an
    account id, so this must be the real Account record id.
    """
    return build_user_headers(account_id, ROLE_ACCOUNT_HOLDER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary role, used by the authorization tests."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = TRUST_SAFETY_ADMIN_ID) -> Dict[str, str]:
    """Headers that carry an identity but no role, for the authentication tests."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user(role: str = ROLE_TRUST_SAFETY_ADMIN) -> Dict[str, str]:
    """Headers that carry a role but no identity, for the authentication tests."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
