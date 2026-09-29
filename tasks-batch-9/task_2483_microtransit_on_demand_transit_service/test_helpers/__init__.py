"""Test helper package for the microtransit on-demand transit API.

Importing this package registers the error-to-HTTP-status map with the
framework's validators, so `validate_error` cross-checks statuses automatically.
"""

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .test_users import (
    AUDITOR_2_HEADERS,
    AUDITOR_HEADERS,
    AUDITOR_ID,
    AUDITOR_2_ID,
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_2_HEADERS,
    FINANCE_ANALYST_2_ID,
    FINANCE_ANALYST_HEADERS,
    FINANCE_ANALYST_ID,
    TEST_USERS,
    ZONE_ADMIN_HEADERS,
    headers_without_identity,
    make_auditor_headers,
    make_dispatcher_headers,
    make_driver_headers,
    make_finance_analyst_headers,
    make_rider_headers,
    make_zone_admin_headers,
)

__all__ = [
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "NOT_FOUND_ERROR_IDS",
    "TEST_USERS",
    "ZONE_ADMIN_HEADERS",
    "DISPATCHER_HEADERS",
    "FINANCE_ANALYST_HEADERS",
    "FINANCE_ANALYST_2_HEADERS",
    "AUDITOR_HEADERS",
    "AUDITOR_2_HEADERS",
    "FINANCE_ANALYST_ID",
    "FINANCE_ANALYST_2_ID",
    "AUDITOR_ID",
    "AUDITOR_2_ID",
    "make_rider_headers",
    "make_driver_headers",
    "make_zone_admin_headers",
    "make_dispatcher_headers",
    "make_finance_analyst_headers",
    "make_auditor_headers",
    "headers_without_identity",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
]
