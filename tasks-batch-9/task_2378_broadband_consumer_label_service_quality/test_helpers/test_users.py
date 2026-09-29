"""Header builders for each acting principal (PRD §2.1).

For the six operator roles `X-User-ID` is an opaque operator identifier that is
not tied to any persisted entity, so the module exposes stable pre-built header
dictionaries plus distinct second identities for the two maker-checker controls.

For the `Subscriber` role `X-User-ID` is the `id` of the acting
`SubscriberAccount`, so subscriber headers must be built per account with
:func:`make_subscriber_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque operator identities
# ---------------------------------------------------------------------------

COMPLIANCE_OFFICER_USER_ID = "co-1"
COMPLIANCE_OFFICER_2_USER_ID = "co-2"
NETWORK_ENGINEER_USER_ID = "ne-1"
NETWORK_ENGINEER_2_USER_ID = "ne-2"
LOCALIZATION_SPECIALIST_USER_ID = "loc-1"
LOCALIZATION_SPECIALIST_2_USER_ID = "loc-2"
COMPLAINT_ANALYST_USER_ID = "an-1"
COMPLAINT_ANALYST_2_USER_ID = "an-2"
REGULATORY_LIAISON_USER_ID = "liaison-1"
RETAIL_AGENT_USER_ID = "agent-1"


COMPLIANCE_OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    COMPLIANCE_OFFICER_USER_ID, UserRole.COMPLIANCE_OFFICER.value
)
#: A second officer, required wherever a label may not be published by the
#: officer who drafted it.
COMPLIANCE_OFFICER_2_HEADERS: Dict[str, str] = build_user_headers(
    COMPLIANCE_OFFICER_2_USER_ID, UserRole.COMPLIANCE_OFFICER.value
)
NETWORK_ENGINEER_HEADERS: Dict[str, str] = build_user_headers(
    NETWORK_ENGINEER_USER_ID, UserRole.NETWORK_ENGINEER.value
)
NETWORK_ENGINEER_2_HEADERS: Dict[str, str] = build_user_headers(
    NETWORK_ENGINEER_2_USER_ID, UserRole.NETWORK_ENGINEER.value
)
LOCALIZATION_SPECIALIST_HEADERS: Dict[str, str] = build_user_headers(
    LOCALIZATION_SPECIALIST_USER_ID, UserRole.LOCALIZATION_SPECIALIST.value
)
#: A second specialist, required wherever a translation may not be verified by
#: the specialist who authored it.
LOCALIZATION_SPECIALIST_2_HEADERS: Dict[str, str] = build_user_headers(
    LOCALIZATION_SPECIALIST_2_USER_ID, UserRole.LOCALIZATION_SPECIALIST.value
)
COMPLAINT_ANALYST_HEADERS: Dict[str, str] = build_user_headers(
    COMPLAINT_ANALYST_USER_ID, UserRole.COMPLAINT_ANALYST.value
)
COMPLAINT_ANALYST_2_HEADERS: Dict[str, str] = build_user_headers(
    COMPLAINT_ANALYST_2_USER_ID, UserRole.COMPLAINT_ANALYST.value
)
REGULATORY_LIAISON_HEADERS: Dict[str, str] = build_user_headers(
    REGULATORY_LIAISON_USER_ID, UserRole.REGULATORY_LIAISON.value
)
RETAIL_AGENT_HEADERS: Dict[str, str] = build_user_headers(
    RETAIL_AGENT_USER_ID, UserRole.RETAIL_AGENT.value
)


# ---------------------------------------------------------------------------
# Entity-backed subscriber identity
# ---------------------------------------------------------------------------


def make_subscriber_headers(account_id: str) -> Dict[str, str]:
    """Headers for the `Subscriber` who owns `account_id`.

    When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting
    `SubscriberAccount`, so the real account id must be threaded through.
    """
    return build_user_headers(account_id, UserRole.SUBSCRIBER.value)


def make_operator_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary operator id acting in `role`."""
    return build_user_headers(user_id, role)


#: Every role that can legally be presented, for authorisation probing.
ALL_ROLE_VALUES = tuple(role.value for role in UserRole)
