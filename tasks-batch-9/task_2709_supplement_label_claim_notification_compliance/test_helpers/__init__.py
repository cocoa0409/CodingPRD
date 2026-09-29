"""Shared test infrastructure for the Supplement Label Claim Compliance API.

Importing this package registers the error-id to HTTP-status map declared in
``api_errors``, so ``validate_error`` cross-checks both halves of every failure
response without each test restating the status.
"""

from . import api_errors, assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import SupplementComplianceClient  # noqa: F401
from .test_users import (  # noqa: F401
    AUDITOR_HEADERS,
    CAO_ALT_HEADERS,
    CAO_HEADERS,
    QAM_ALT_HEADERS,
    QAM_HEADERS,
    RAS_ALT_HEADERS,
    RAS_HEADERS,
    REVIEWER_ALT_HEADERS,
    REVIEWER_HEADERS,
    TEST_USERS,
    headers_for_role,
    make_supplier_representative_headers,
)

__all__ = [
    "SupplementComplianceClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "AUDITOR_HEADERS",
    "CAO_ALT_HEADERS",
    "CAO_HEADERS",
    "QAM_ALT_HEADERS",
    "QAM_HEADERS",
    "RAS_ALT_HEADERS",
    "RAS_HEADERS",
    "REVIEWER_ALT_HEADERS",
    "REVIEWER_HEADERS",
    "TEST_USERS",
    "headers_for_role",
    "make_supplier_representative_headers",
]
