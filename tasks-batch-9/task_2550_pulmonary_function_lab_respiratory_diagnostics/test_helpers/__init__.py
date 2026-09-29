"""Shared infrastructure for the pulmonary function laboratory test suite.

Importing this package registers the API's error-to-HTTP-status map with the
validation framework, so ``validate_error`` can cross-check the status of any
declared error without every test restating it.
"""

from . import api_errors  # noqa: F401  (registers the error status map on import)
from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient
from .test_users import (
    ALL_ROLES,
    COMPLIANCE_AUDITOR,
    LAB_MANAGER,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_INTERPRETING_PHYSICIAN,
    ROLE_LAB_MANAGER,
    ROLE_ORDERING_PHYSICIAN,
    ROLE_TECHNOLOGIST,
    make_headers,
    make_interpreting_physician_headers,
    make_ordering_physician_headers,
    make_technologist_headers,
)

__all__ = [
    "ApiClient",
    "ALL_ROLES",
    "COMPLIANCE_AUDITOR",
    "LAB_MANAGER",
    "ROLE_COMPLIANCE_AUDITOR",
    "ROLE_INTERPRETING_PHYSICIAN",
    "ROLE_LAB_MANAGER",
    "ROLE_ORDERING_PHYSICIAN",
    "ROLE_TECHNOLOGIST",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "make_headers",
    "make_interpreting_physician_headers",
    "make_ordering_physician_headers",
    "make_technologist_headers",
    "types",
]
