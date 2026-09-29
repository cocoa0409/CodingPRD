"""Test principals and their request headers (PRD §2.1).

Every request carries `X-User-ID` and `X-User-Role`. For `AccessibilityLead`,
`AccessibilityTester`, `ConformanceReviewer` and `CustomerLiaison` the user id is
an opaque operator identifier not tied to any persisted entity. For
`ProductOwner` the user id is the `id` of the acting `Product`, so those headers
must be built per product with make_product_owner_headers(product_id).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers (PRD §2.1).
LEAD_USER_ID = "lead-1"
TESTER_USER_ID = "tester-1"
SECOND_TESTER_USER_ID = "tester-2"
REVIEWER_USER_ID = "reviewer-1"
SECOND_REVIEWER_USER_ID = "reviewer-2"
LIAISON_USER_ID = "liaison-1"

# Placeholder identity for ProductOwner headers used only on calls that do not
# exercise product ownership. Ownership-gated calls must build headers from the
# product's own id with make_product_owner_headers(product["id"]).
PLACEHOLDER_PRODUCT_ID = "00000000-0000-4000-8000-000000000000"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "lead_headers": build_user_headers(LEAD_USER_ID, UserRole.ACCESSIBILITY_LEAD.value),
    "tester_headers": build_user_headers(TESTER_USER_ID, UserRole.ACCESSIBILITY_TESTER.value),
    "second_tester_headers": build_user_headers(
        SECOND_TESTER_USER_ID, UserRole.ACCESSIBILITY_TESTER.value
    ),
    "reviewer_headers": build_user_headers(REVIEWER_USER_ID, UserRole.CONFORMANCE_REVIEWER.value),
    "second_reviewer_headers": build_user_headers(
        SECOND_REVIEWER_USER_ID, UserRole.CONFORMANCE_REVIEWER.value
    ),
    "liaison_headers": build_user_headers(LIAISON_USER_ID, UserRole.CUSTOMER_LIAISON.value),
    "product_owner_headers": build_user_headers(
        PLACEHOLDER_PRODUCT_ID, UserRole.PRODUCT_OWNER.value
    ),
}


def make_lead_headers(user_id: str = LEAD_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.ACCESSIBILITY_LEAD.value)


def make_tester_headers(user_id: str = TESTER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.ACCESSIBILITY_TESTER.value)


def make_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CONFORMANCE_REVIEWER.value)


def make_liaison_headers(user_id: str = LIAISON_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CUSTOMER_LIAISON.value)


def make_product_owner_headers(product_id: str) -> Dict[str, str]:
    """ProductOwner headers whose `X-User-ID` is the acting product's id."""
    return build_user_headers(product_id, UserRole.PRODUCT_OWNER.value)


def make_role_headers(user_id: str, role: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers missing `X-User-ID` entirely (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = LEAD_USER_ID) -> Dict[str, str]:
    """Headers missing `X-User-Role` entirely (PRD §2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
