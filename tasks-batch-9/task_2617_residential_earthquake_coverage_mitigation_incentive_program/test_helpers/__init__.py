"""Test helpers for the Residential Earthquake Coverage & Mitigation Incentive
Program API.

Importing this package registers the error-to-status pairing with the shared
response validators, so any test that imports a helper gets that cross-check for
free.
"""
from . import assertions, constants, factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    FIELD_INSPECTOR_ALT_HEADERS,
    FIELD_INSPECTOR_HEADERS,
    GRANT_REVIEWER_ALT_HEADERS,
    GRANT_REVIEWER_HEADERS,
    PROGRAM_ADMIN_ALT_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    TEST_USERS,
    make_contractor_headers,
    make_headers_with_empty_user_id,
    make_headers_with_unknown_role,
    make_headers_without_role,
    make_headers_without_user_id,
    make_insurer_headers,
    make_policyholder_headers,
)
from .types import UserRole

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "UserRole",
    "api_client",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "CLAIM_ADJUSTER_ALT_HEADERS",
    "CLAIM_ADJUSTER_HEADERS",
    "FIELD_INSPECTOR_ALT_HEADERS",
    "FIELD_INSPECTOR_HEADERS",
    "GRANT_REVIEWER_ALT_HEADERS",
    "GRANT_REVIEWER_HEADERS",
    "PROGRAM_ADMIN_ALT_HEADERS",
    "PROGRAM_ADMIN_HEADERS",
    "make_contractor_headers",
    "make_headers_with_empty_user_id",
    "make_headers_with_unknown_role",
    "make_headers_without_role",
    "make_headers_without_user_id",
    "make_insurer_headers",
    "make_policyholder_headers",
]
