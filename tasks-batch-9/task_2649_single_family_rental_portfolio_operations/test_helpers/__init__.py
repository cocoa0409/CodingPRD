"""Test infrastructure for the Single-Family Rental Portfolio Operations API.

Importing this package registers the PRD SS5 error-identifier to HTTP-status mapping with
the shared response validators, so ``validate_error`` cross-checks statuses everywhere.
"""

from . import api_errors  # noqa: F401  (import registers the error status map)
from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient
from .test_users import (  # noqa: F401
    TEST_USERS,
    headers_without_user_id,
    make_headers,
    make_prospect_headers,
    make_vendor_headers,
)

__all__ = [
    "ApiClient",
    "TEST_USERS",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "headers_without_user_id",
    "make_headers",
    "make_prospect_headers",
    "make_vendor_headers",
    "types",
]
