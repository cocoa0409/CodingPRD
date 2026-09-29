"""Shared test infrastructure for the QDRO Processing API suite.

Importing this package registers the error-id to HTTP-status map with the
framework's validators, so `validate_error` cross-checks the status of every
error a test asserts.
"""

from . import api_errors, assertions, constants, factories, fixtures, types
from .api_client import QdroApiClient
from .test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    DETERMINER_USER_ID,
    REVIEWER_USER_ID,
    TEST_USERS,
    make_admin_headers,
    make_alternate_payee_headers,
    make_analyst_headers,
    make_attorney_headers,
    make_determiner_headers,
    make_headers,
    make_participant_headers,
    make_reviewer_headers,
)

__all__ = [
    "ADMIN_HEADERS",
    "ADMIN_USER_ID",
    "ANALYST_HEADERS",
    "ANALYST_USER_ID",
    "DETERMINER_USER_ID",
    "QdroApiClient",
    "REVIEWER_USER_ID",
    "TEST_USERS",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "make_admin_headers",
    "make_alternate_payee_headers",
    "make_analyst_headers",
    "make_attorney_headers",
    "make_determiner_headers",
    "make_headers",
    "make_participant_headers",
    "make_reviewer_headers",
    "types",
]
