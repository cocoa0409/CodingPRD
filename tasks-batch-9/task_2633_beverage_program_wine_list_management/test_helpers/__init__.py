"""Shared test infrastructure for the beverage program / wine list API.

Importing this package registers the error_id -> HTTP status mapping with the
framework validators, so ``validate_error`` cross-checks status codes without
each test having to pass one.
"""

from . import api_errors  # noqa: F401  (registers the error/status map on import)
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401

__all__ = [
    "ApiClient",
    "api_client",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
