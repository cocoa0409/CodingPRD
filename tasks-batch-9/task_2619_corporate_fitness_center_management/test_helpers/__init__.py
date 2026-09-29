"""Shared test infrastructure for the corporate fitness centre operations API.

Import surface used by the suite:

    from test_helpers import api_client, ApiErrorId, TEST_USERS, fixtures
"""
from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .constants import (
    CLOCK_START_UTC,
    MALFORMED_ID,
    REQUIRED_CREDENTIALS_BY_ROLE,
    TEST_DEFAULTS,
    THRESHOLDS,
)
from .test_users import (
    SECOND_OPERATOR_ADMIN_HEADERS,
    TEST_USERS,
    make_client_sponsor_headers,
    make_compliance_auditor_headers,
    make_fitness_staff_headers,
    make_member_headers,
    make_operator_admin_headers,
    make_site_manager_headers,
)
from .types import UserRole

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "CLOCK_START_UTC",
    "HTTP_STATUS_CODES",
    "MALFORMED_ID",
    "REQUIRED_CREDENTIALS_BY_ROLE",
    "SECOND_OPERATOR_ADMIN_HEADERS",
    "TEST_DEFAULTS",
    "TEST_USERS",
    "THRESHOLDS",
    "UserRole",
    "api_client",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "make_client_sponsor_headers",
    "make_compliance_auditor_headers",
    "make_fitness_staff_headers",
    "make_member_headers",
    "make_operator_admin_headers",
    "make_site_manager_headers",
    "types",
]
