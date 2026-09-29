"""
Test infrastructure for the brick and masonry unit manufacturing API.

Importing this package registers the error-identifier to HTTP-status mapping with
the framework's response validators, so `validate_error` cross-checks statuses
without every test restating them.
"""

from . import api_errors  # noqa: F401  (registers the error status mapping)
from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient

__all__ = [
    "ApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
