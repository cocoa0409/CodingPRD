"""
Test helper package for the De Novo Bank Charter Application API.

Importing this package registers the error-identifier -> HTTP status map from the
PRD section 5 catalogue with the shared validators, so `validate_error` always
cross-checks the status code.
"""

from . import api_errors  # noqa: F401  (registers the status map on import)
from . import assertions, constants, factories, fixtures, types
from .api_client import DeNovoApiClient
from .test_users import (
    ALL_ROLES,
    CHARTERING_EXAMINER_HEADERS,
    CHARTERING_EXAMINER_USER_ID,
    COUNSEL_HEADERS,
    COUNSEL_USER_ID,
    ESCROW_AGENT_HEADERS,
    ESCROW_AGENT_USER_ID,
    INSURANCE_EXAMINER_HEADERS,
    INSURANCE_EXAMINER_USER_ID,
    PLATFORM_ADMIN_HEADERS,
    PLATFORM_ADMIN_USER_ID,
    ROLE_CHARTER_COUNSEL,
    ROLE_CHARTERING_EXAMINER,
    ROLE_ESCROW_AGENT,
    ROLE_INDEPENDENT_DIRECTOR,
    ROLE_INSURANCE_EXAMINER,
    ROLE_LEAD_ORGANIZER,
    ROLE_PLATFORM_ADMIN,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_independent_director_headers,
    make_lead_organizer_headers,
)

__all__ = [
    "DeNovoApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "ALL_ROLES",
    "COUNSEL_HEADERS",
    "COUNSEL_USER_ID",
    "CHARTERING_EXAMINER_HEADERS",
    "CHARTERING_EXAMINER_USER_ID",
    "INSURANCE_EXAMINER_HEADERS",
    "INSURANCE_EXAMINER_USER_ID",
    "ESCROW_AGENT_HEADERS",
    "ESCROW_AGENT_USER_ID",
    "PLATFORM_ADMIN_HEADERS",
    "PLATFORM_ADMIN_USER_ID",
    "ROLE_CHARTER_COUNSEL",
    "ROLE_LEAD_ORGANIZER",
    "ROLE_INDEPENDENT_DIRECTOR",
    "ROLE_CHARTERING_EXAMINER",
    "ROLE_INSURANCE_EXAMINER",
    "ROLE_ESCROW_AGENT",
    "ROLE_PLATFORM_ADMIN",
    "make_headers",
    "make_lead_organizer_headers",
    "make_independent_director_headers",
    "headers_without_role",
    "headers_without_user_id",
]
